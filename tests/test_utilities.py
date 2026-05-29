import unittest
import json
import time
import threading

from utilities import (
    DEFAULT_COMMANDS,
    HANDSHAKE_ACTION,
    HANDSHAKE_COMMAND_NAME,
    HANDSHAKE_PROTOCOL_VERSION,
    build_handshake_payload,
    validate_handshake_payload,
    mask_token,
)


class UtilitiesTests(unittest.TestCase):
    def test_default_commands_include_handshake(self) -> None:
        self.assertEqual(DEFAULT_COMMANDS[0]["name"], HANDSHAKE_COMMAND_NAME)
        self.assertGreaterEqual(len(DEFAULT_COMMANDS), 6)

    def test_build_handshake_payload_contains_expected_fields(self) -> None:
        payload = build_handshake_payload(client_id="client-123", capabilities=["websocket"])

        self.assertEqual(payload["action"], HANDSHAKE_ACTION)
        self.assertEqual(payload["clientId"], "client-123")
        self.assertEqual(payload["capabilities"], ["websocket"])
        self.assertIsInstance(payload["timestamp"], str)
        self.assertTrue(payload["timestamp"])

    def test_build_handshake_payload_includes_protocol_version(self) -> None:
        """Test that protocol version is included in handshake payload."""
        payload = build_handshake_payload()
        self.assertEqual(payload["protocolVersion"], HANDSHAKE_PROTOCOL_VERSION)

    def test_build_handshake_payload_includes_session_id(self) -> None:
        """Test that session ID is auto-generated and included."""
        payload = build_handshake_payload()
        self.assertIn("sessionId", payload)
        self.assertIsInstance(payload["sessionId"], str)
        self.assertTrue(payload["sessionId"])

    def test_build_handshake_payload_uses_provided_session_id(self) -> None:
        """Test that provided session ID is used instead of auto-generated."""
        custom_session_id = "custom-session-123"
        payload = build_handshake_payload(session_id=custom_session_id)
        self.assertEqual(payload["sessionId"], custom_session_id)

    def test_build_handshake_payload_generates_unique_session_ids(self) -> None:
        """Test that different payloads get different session IDs."""
        payload1 = build_handshake_payload()
        payload2 = build_handshake_payload()
        self.assertNotEqual(payload1["sessionId"], payload2["sessionId"])

    def test_validate_handshake_payload_rejects_missing_client_id(self) -> None:
        payload = {
            "action": HANDSHAKE_ACTION,
            "timestamp": "2026-05-29T14:51:02Z",
            "capabilities": ["websocket"],
        }

        is_valid, error_message = validate_handshake_payload(payload)

        self.assertFalse(is_valid)
        self.assertIn("clientId", error_message)

    def test_validate_handshake_payload_accepts_optional_fields(self) -> None:
        """Test that payload with optional protocolVersion and sessionId is valid."""
        payload = {
            "action": HANDSHAKE_ACTION,
            "clientId": "client-123",
            "timestamp": "2026-05-29T14:51:02Z",
            "capabilities": ["websocket"],
            "protocolVersion": "1.0",
            "sessionId": "session-123",
        }

        is_valid, error_message = validate_handshake_payload(payload)

        self.assertTrue(is_valid)
        self.assertIsNone(error_message)

    def test_validate_handshake_payload_rejects_invalid_protocol_version(self) -> None:
        """Test validation rejects non-string protocolVersion."""
        payload = {
            "action": HANDSHAKE_ACTION,
            "clientId": "client-123",
            "timestamp": "2026-05-29T14:51:02Z",
            "capabilities": ["websocket"],
            "protocolVersion": 1.0,
        }

        is_valid, error_message = validate_handshake_payload(payload)

        self.assertFalse(is_valid)
        self.assertIn("protocolVersion", error_message)

    def test_validate_handshake_payload_rejects_invalid_session_id(self) -> None:
        """Test validation rejects non-string sessionId."""
        payload = {
            "action": HANDSHAKE_ACTION,
            "clientId": "client-123",
            "timestamp": "2026-05-29T14:51:02Z",
            "capabilities": ["websocket"],
            "sessionId": 12345,
        }

        is_valid, error_message = validate_handshake_payload(payload)

        self.assertFalse(is_valid)
        self.assertIn("sessionId", error_message)

    def test_mask_token_short_token(self) -> None:
        """Test token masking for short tokens."""
        masked = mask_token("abc")
        self.assertEqual(masked, "***")

    def test_mask_token_none(self) -> None:
        """Test token masking for None."""
        masked = mask_token(None)
        self.assertEqual(masked, "***")

    def test_mask_token_long_token(self) -> None:
        """Test token masking for long tokens."""
        long_token = "tk_1234567890abcdef"
        masked = mask_token(long_token)
        # Should show first 3 and last 6
        self.assertTrue(masked.startswith("tk_"))
        self.assertTrue(masked.endswith("cdef"))
        self.assertIn("***", masked)
        self.assertNotIn(long_token, masked)


if __name__ == "__main__":
    unittest.main()
