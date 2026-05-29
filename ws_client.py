import json
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from websocket import WebSocketApp

from utilities import build_handshake_payload, validate_handshake_payload, HANDSHAKE_ACTION, mask_token


class WebSocketManager:
    """
    Manages WebSocket connections with handshake support, including timeout and retry logic.
    
    Features:
    - Automatic handshake on connection
    - Timeout mechanism for handshake (default 5 seconds)
    - Exponential backoff retry strategy (max 3 retries)
    - Response handling for handshake-specific messages
    - Token masking in logs for security
    """

    def __init__(
        self,
        logger,
        on_message: Optional[Callable[[str], None]] = None,
        on_status_change: Optional[Callable[[bool], None]] = None,
        handshake_timeout_seconds: float = 5.0,
        max_handshake_retries: int = 3,
    ) -> None:
        self.logger = logger
        self.on_message = on_message
        self.on_status_change = on_status_change
        self.ws_app = None
        self.ws_thread = None
        self.connected = False
        self.last_connected_time: Optional[str] = None
        self._handshake_sent_for_current_connection = False
        self._handshake_completed = False
        self._handshake_response_received = False
        self._current_session_id: Optional[str] = None
        self._handshake_start_time: Optional[float] = None
        self.handshake_timeout_seconds = handshake_timeout_seconds
        self.max_handshake_retries = max_handshake_retries
        self._handshake_attempt_count = 0
        self._handshake_lock = threading.Lock()

    def connect(self, ws_url: str) -> None:
        """
        Establish WebSocket connection.
        
        Args:
            ws_url: WebSocket URL to connect to
        """
        if self.connected:
            self.logger.log("WebSocket is already connected.")
            return

        if not ws_url:
            self.logger.log("WebSocket URL is empty.")
            return

        self._handshake_sent_for_current_connection = False
        self._handshake_completed = False
        self._handshake_response_received = False
        self._handshake_attempt_count = 0
        self.logger.log(f"Connecting to WebSocket: {ws_url}")

        def run_ws() -> None:
            self.ws_app = WebSocketApp(
                ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            try:
                self.ws_app.run_forever()
            except Exception as exc:
                self.logger.log(f"WebSocket run_forever exception: {exc}")

        self.ws_thread = threading.Thread(target=run_ws, daemon=True)
        self.ws_thread.start()

    def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        if self.ws_app is None:
            self.logger.log("No active WebSocket connection.")
            return

        self.logger.log("Disconnecting WebSocket...")
        self._handshake_sent_for_current_connection = False
        self._handshake_completed = False
        self._handshake_response_received = False
        try:
            self.ws_app.close()
        except Exception as exc:
            self.logger.log(f"Disconnect error: {exc}")

    def send_json(self, payload: dict) -> bool:
        """
        Send JSON payload via WebSocket with validation and logging.
        Masks sensitive tokens in logs.
        
        Args:
            payload: Dictionary payload to send
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.connected or self.ws_app is None:
            self.logger.log("Cannot send via WebSocket: not connected.")
            return False

        if not isinstance(payload, dict):
            self.logger.log("WebSocket send blocked: payload must be a JSON object.")
            return False

        if payload.get("action") == HANDSHAKE_ACTION:
            is_valid, error_message = validate_handshake_payload(payload)
            if not is_valid:
                self.logger.log(f"WebSocket send blocked: {error_message}")
                return False

        try:
            raw_payload = json.dumps(payload)
            # Log with masked tokens for security
            log_payload = self._mask_payload_for_logging(payload)
            self.ws_app.send(raw_payload)
            self.logger.log(f"Sent WebSocket message: {json.dumps(log_payload)}")
            return True
        except Exception as exc:
            self.logger.log(f"WebSocket send error: {exc}")
            return False

    def _set_connected(self, value: bool) -> None:
        self.connected = value
        if self.on_status_change:
            self.on_status_change(value)

    def _mask_payload_for_logging(self, payload: dict) -> dict:
        """
        Create a copy of payload with sensitive tokens masked.
        
        Args:
            payload: The original payload
            
        Returns:
            A copy of payload with tokens masked
        """
        masked = payload.copy()
        if "token" in masked and masked["token"]:
            masked["token"] = mask_token(masked["token"])
        return masked

    def _check_handshake_timeout(self) -> None:
        """
        Check if handshake has timed out and retry if needed.
        Uses exponential backoff: 1s, 2s, 4s for retries.
        """
        if not self._handshake_sent_for_current_connection or self._handshake_completed:
            return

        if self._handshake_start_time is None:
            return

        elapsed = time.time() - self._handshake_start_time
        if elapsed > self.handshake_timeout_seconds:
            with self._handshake_lock:
                # Double-check under lock
                if self._handshake_completed or self._handshake_response_received:
                    return

                if self._handshake_attempt_count < self.max_handshake_retries:
                    self._handshake_attempt_count += 1
                    backoff_delay = 2 ** (self._handshake_attempt_count - 1)
                    self.logger.log(
                        f"Handshake timeout (attempt {self._handshake_attempt_count}). "
                        f"Retrying in {backoff_delay}s..."
                    )
                    self._handshake_sent_for_current_connection = False
                    # Schedule retry after backoff
                    threading.Timer(
                        backoff_delay,
                        self._send_handshake_with_retry,
                    ).start()
                else:
                    self.logger.log(
                        f"Handshake failed after {self.max_handshake_retries} retries. "
                        "Check server connectivity and authentication."
                    )
                    self._handshake_completed = True

    def _send_handshake_with_retry(self) -> None:
        """Send handshake if not already sent, checking timeout periodically."""
        if not self.connected or self.ws_app is None:
            return

        self._send_handshake()

        # Schedule timeout check
        if not self._handshake_completed:
            threading.Timer(
                0.5,
                self._check_handshake_timeout,
            ).start()

    def _send_handshake(self) -> None:
        """
        Send handshake payload with timeout tracking.
        Only sends once per connection attempt.
        """
        if self._handshake_sent_for_current_connection:
            return

        handshake_payload = build_handshake_payload()
        self._current_session_id = handshake_payload.get("sessionId")

        log_payload = self._mask_payload_for_logging(handshake_payload)
        self.logger.log(f"Sending WebSocket handshake (sessionId: {self._current_session_id[:8]}...).")

        if self.send_json(handshake_payload):
            with self._handshake_lock:
                self._handshake_sent_for_current_connection = True
                self._handshake_start_time = time.time()
                self._handshake_attempt_count = 1

            self.logger.log("WebSocket handshake sent.")

            # Schedule timeout check
            threading.Timer(
                self.handshake_timeout_seconds + 0.1,
                self._check_handshake_timeout,
            ).start()

    def _on_open(self, _ws) -> None:
        """Handle WebSocket open event and initiate handshake."""
        self.last_connected_time = datetime.now().isoformat()
        self._set_connected(True)
        self.logger.log("WebSocket connected.")
        self._send_handshake()

    def _on_message(self, _ws, message: str) -> None:
        """
        Handle incoming WebSocket message.
        Processes handshake-specific responses separately.
        
        Args:
            _ws: WebSocket instance
            message: Incoming message string
        """
        # Try to parse as JSON for handshake response handling
        try:
            parsed_msg = json.loads(message)
            if isinstance(parsed_msg, dict):
                self._handle_handshake_response(parsed_msg)
        except (json.JSONDecodeError, ValueError):
            # Not JSON, pass to regular message handler
            pass

        # Call regular message handler
        if self.on_message:
            self.on_message(message)
        else:
            self.logger.log(f"WebSocket received: {message}")

    def _handle_handshake_response(self, response: dict) -> None:
        """
        Handle handshake-specific server responses.
        
        Recognizes responses that confirm handshake completion or indicate errors.
        
        Args:
            response: Parsed JSON response from server
        """
        action = response.get("action")
        
        # Check for handshake acknowledgment responses
        if action == "handshake-ack" or (action == "handshake" and response.get("status") == "success"):
            with self._handshake_lock:
                session_id = response.get("sessionId")
                if session_id and session_id == self._current_session_id:
                    self._handshake_completed = True
                    self._handshake_response_received = True
                    self.logger.log(f"Handshake completed successfully (sessionId: {session_id[:8]}...).")
                elif not self._handshake_completed:
                    self._handshake_response_received = True
                    self.logger.log("Handshake response received from server.")
        
        # Check for handshake error responses
        elif action == "handshake-error" or (action == "handshake" and response.get("status") == "error"):
            with self._handshake_lock:
                error_msg = response.get("message", "Unknown handshake error")
                self.logger.log(f"Handshake error from server: {error_msg}")
                if self._handshake_attempt_count < self.max_handshake_retries:
                    self._handshake_sent_for_current_connection = False
                    backoff_delay = 2 ** (self._handshake_attempt_count)
                    self.logger.log(f"Scheduling handshake retry in {backoff_delay}s...")
                    threading.Timer(
                        backoff_delay,
                        self._send_handshake_with_retry,
                    ).start()

    def _on_error(self, _ws, error) -> None:
        """Handle WebSocket error event."""
        self.logger.log(f"WebSocket error: {error}")

    def _on_close(self, _ws, close_status_code, close_msg) -> None:
        """Handle WebSocket close event and reset handshake state."""
        self._handshake_sent_for_current_connection = False
        self._handshake_completed = False
        self._handshake_response_received = False
        self._set_connected(False)
        self.logger.log(f"WebSocket closed. code={close_status_code}, message={close_msg}")
