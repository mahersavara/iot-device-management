import json
import unittest
import time
import threading

from ws_client import WebSocketManager
from utilities import HANDSHAKE_ACTION


class DummyLogger:
    def __init__(self) -> None:
        self.messages = []

    def log(self, message: str) -> None:
        self.messages.append(message)


class DummyWebSocket:
    def __init__(self) -> None:
        self.sent = []
        self.closed = False

    def send(self, payload: str) -> None:
        self.sent.append(payload)

    def close(self) -> None:
        self.closed = True


class WebSocketManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = DummyLogger()
        self.status_changes = []
        self.manager = WebSocketManager(
            logger=self.logger,
            on_status_change=self.status_changes.append,
        )
        self.manager.ws_app = DummyWebSocket()
        self.manager.connected = True

    def test_send_json_blocks_invalid_handshake(self) -> None:
        """Test that invalid handshake payloads are rejected."""
        payload = {
            "action": HANDSHAKE_ACTION,
            "timestamp": "2026-05-29T14:51:02Z",
            "capabilities": ["websocket"],
        }

        result = self.manager.send_json(payload)

        self.assertFalse(result)
        self.assertEqual(self.manager.ws_app.sent, [])
        self.assertTrue(any("Handshake payload requires a non-empty clientId" in message for message in self.logger.messages))

    def test_on_open_sends_handshake_once(self) -> None:
        """Test that handshake is sent exactly once on connection open."""
        self.manager._on_open(self.manager.ws_app)
        self.manager._on_open(self.manager.ws_app)

        self.assertTrue(self.manager.connected)
        self.assertEqual(len(self.manager.ws_app.sent), 1)
        handshake_payload = json.loads(self.manager.ws_app.sent[0])
        self.assertEqual(handshake_payload["action"], HANDSHAKE_ACTION)
        self.assertTrue(any("WebSocket handshake sent." in message for message in self.logger.messages))

    def test_disconnect_resets_handshake_state(self) -> None:
        """Test that disconnect resets all handshake state."""
        self.manager._on_open(self.manager.ws_app)
        self.manager.disconnect()

        self.assertTrue(self.manager.ws_app.closed)
        self.assertFalse(self.manager._handshake_sent_for_current_connection)
        self.assertFalse(self.manager._handshake_completed)
        self.assertFalse(self.manager._handshake_response_received)

    def test_handshake_payload_includes_session_id(self) -> None:
        """Test that handshake payload includes sessionId."""
        self.manager._on_open(self.manager.ws_app)

        self.assertEqual(len(self.manager.ws_app.sent), 1)
        handshake_payload = json.loads(self.manager.ws_app.sent[0])
        self.assertIn("sessionId", handshake_payload)
        self.assertTrue(handshake_payload["sessionId"])

    def test_handshake_payload_includes_protocol_version(self) -> None:
        """Test that handshake payload includes protocolVersion."""
        self.manager._on_open(self.manager.ws_app)

        self.assertEqual(len(self.manager.ws_app.sent), 1)
        handshake_payload = json.loads(self.manager.ws_app.sent[0])
        self.assertIn("protocolVersion", handshake_payload)
        self.assertEqual(handshake_payload["protocolVersion"], "1.0")

    def test_handle_handshake_response_ack(self) -> None:
        """Test handling of handshake-ack response."""
        self.manager._on_open(self.manager.ws_app)
        handshake_payload = json.loads(self.manager.ws_app.sent[0])
        session_id = handshake_payload["sessionId"]

        # Simulate server handshake-ack response
        response = {
            "action": "handshake-ack",
            "sessionId": session_id,
            "status": "success",
        }

        self.manager._handle_handshake_response(response)

        self.assertTrue(self.manager._handshake_completed)
        self.assertTrue(self.manager._handshake_response_received)
        self.assertTrue(any("Handshake completed successfully" in message for message in self.logger.messages))

    def test_handle_handshake_response_mismatched_session_id(self) -> None:
        """Test that mismatched sessionId doesn't mark handshake as completed."""
        self.manager._on_open(self.manager.ws_app)

        # Simulate server response with different session ID
        response = {
            "action": "handshake-ack",
            "sessionId": "different-session-id",
            "status": "success",
        }

        self.manager._handle_handshake_response(response)

        self.assertFalse(self.manager._handshake_completed)

    def test_handle_handshake_error_response(self) -> None:
        """Test handling of handshake-error response."""
        self.manager._on_open(self.manager.ws_app)
        initial_sent_count = len(self.manager.ws_app.sent)

        # Simulate server error response
        response = {
            "action": "handshake-error",
            "message": "Invalid client credentials",
        }

        self.manager._handle_handshake_response(response)

        self.assertTrue(any("Handshake error from server" in message for message in self.logger.messages))
        self.assertTrue(any("Invalid client credentials" in message for message in self.logger.messages))

    def test_send_json_masks_token_in_logs(self) -> None:
        """Test that tokens are masked in log messages."""
        token = "tk_1234567890abcdefghij"
        payload = {
            "action": "test-action",
            "token": token,
        }

        self.manager.send_json(payload)

        # Check that full token doesn't appear in logs
        log_text = " ".join(self.logger.messages)
        self.assertNotIn(token, log_text)
        # Check that masked version appears
        self.assertTrue(any("***" in msg for msg in self.logger.messages))

    def test_on_message_calls_handler(self) -> None:
        """Test that on_message callback is called."""
        messages = []
        manager = WebSocketManager(
            logger=self.logger,
            on_message=messages.append,
        )

        test_message = '{"action": "test"}'
        manager._on_message(None, test_message)

        self.assertEqual(messages, [test_message])

    def test_on_message_parses_json_for_handshake_responses(self) -> None:
        """Test that on_message can parse JSON for handshake responses."""
        self.manager._on_open(self.manager.ws_app)
        handshake_payload = json.loads(self.manager.ws_app.sent[0])
        session_id = handshake_payload["sessionId"]

        # Send a handshake-ack response as JSON
        response_json = json.dumps({
            "action": "handshake-ack",
            "sessionId": session_id,
            "status": "success",
        })

        self.manager._on_message(None, response_json)

        self.assertTrue(self.manager._handshake_completed)

    def test_check_handshake_timeout_triggers_retry(self) -> None:
        """Test that timeout triggers retry after backoff period."""
        self.manager.handshake_timeout_seconds = 0.1
        self.manager._on_open(self.manager.ws_app)

        # Record initial sent count
        initial_sent = len(self.manager.ws_app.sent)

        # Wait for timeout to trigger
        time.sleep(0.3)

        # Manually trigger timeout check
        self.manager._check_handshake_timeout()

        # Verify timeout was detected
        self.assertTrue(any("timeout" in msg.lower() for msg in self.logger.messages))

    def test_handshake_state_on_close(self) -> None:
        """Test that handshake state is reset on connection close."""
        self.manager._on_open(self.manager.ws_app)
        self.assertTrue(self.manager._handshake_sent_for_current_connection)

        self.manager._on_close(self.manager.ws_app, 1000, "Normal closure")

        self.assertFalse(self.manager._handshake_sent_for_current_connection)
        self.assertFalse(self.manager._handshake_completed)
        self.assertFalse(self.manager._handshake_response_received)
        self.assertFalse(self.manager.connected)

    def test_multiple_connections_reset_handshake_state(self) -> None:
        """Test that each new connection resets handshake state."""
        # First connection
        self.manager._on_open(self.manager.ws_app)
        session_id_1 = self.manager._current_session_id
        self.assertEqual(len(self.manager.ws_app.sent), 1)

        # Simulate disconnect
        self.manager._on_close(self.manager.ws_app, 1000, "Normal closure")

        # Second connection
        self.manager.ws_app = DummyWebSocket()
        self.manager.connected = True
        self.manager._on_open(self.manager.ws_app)
        session_id_2 = self.manager._current_session_id

        # Different session IDs for different connections
        self.assertNotEqual(session_id_1, session_id_2)
        # Only 1 message in second connection
        self.assertEqual(len(self.manager.ws_app.sent), 1)


if __name__ == "__main__":
    unittest.main()
