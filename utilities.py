from datetime import datetime, timezone
import os
import uuid
from typing import Optional, List, Tuple

HANDSHAKE_ACTION = "handshake"
HANDSHAKE_COMMAND_NAME = "Handshake"
HANDSHAKE_PROTOCOL_VERSION = "1.0"
DEFAULT_CLIENT_ID = os.getenv("TK_CLIENT_ID", "tkinter-client")
DEFAULT_CAPABILITIES = ["websocket", "http", "tkinter-ui"]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _generate_session_id() -> str:
    """Generate a unique session ID for handshake tracking."""
    return str(uuid.uuid4())


def mask_token(token: Optional[str]) -> str:
    """
    Mask sensitive token for logging purposes.
    
    Args:
        token: The token to mask
        
    Returns:
        Masked token string (e.g., 'tk_***...***abc123')
    """
    if not token or not isinstance(token, str):
        return "***"
    
    if len(token) <= 6:
        return "***"
    
    # Show first 3 chars and last 6 chars
    return f"{token[:3]}***...***{token[-6:]}"


def build_handshake_payload(
    client_id: Optional[str] = None,
    token: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    session_id: Optional[str] = None,
) -> dict:
    """
    Build a handshake payload with all required and optional fields.
    
    Args:
        client_id: Optional client identifier (defaults to TK_CLIENT_ID env var or hardcoded default)
        token: Optional authentication token (defaults to TK_CLIENT_TOKEN env var)
        capabilities: Optional list of supported capabilities
        session_id: Optional session ID for tracking handshake (auto-generated if not provided)
        
    Returns:
        A valid handshake payload dictionary
    """
    payload = {
        "action": HANDSHAKE_ACTION,
        "clientId": (client_id or DEFAULT_CLIENT_ID).strip(),
        "timestamp": _utc_timestamp(),
        "capabilities": capabilities or DEFAULT_CAPABILITIES,
        "protocolVersion": HANDSHAKE_PROTOCOL_VERSION,
        "sessionId": session_id or _generate_session_id(),
    }

    resolved_token = token if token is not None else os.getenv("TK_CLIENT_TOKEN")
    if resolved_token:
        payload["token"] = resolved_token

    return payload


def validate_handshake_payload(payload) -> Tuple[bool, Optional[str]]:
    """
    Validate a handshake payload for required and optional fields.
    
    Args:
        payload: The payload dictionary to validate
        
    Returns:
        A tuple of (is_valid, error_message). error_message is None if valid.
    """
    if not isinstance(payload, dict):
        return False, "Handshake payload must be a JSON object."

    if payload.get("action") != HANDSHAKE_ACTION:
        return False, f"Handshake payload must set action to '{HANDSHAKE_ACTION}'."

    client_id = payload.get("clientId")
    if not isinstance(client_id, str) or not client_id.strip():
        return False, "Handshake payload requires a non-empty clientId."

    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.strip():
        return False, "Handshake payload requires a non-empty timestamp."

    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        return False, "Handshake payload requires a non-empty capabilities list."

    for capability in capabilities:
        if not isinstance(capability, str) or not capability.strip():
            return False, "Handshake payload capabilities must be non-empty strings."

    token = payload.get("token")
    if token is not None and not isinstance(token, str):
        return False, "Handshake payload token must be a string when provided."

    # Validate optional protocol version and session ID if present
    protocol_version = payload.get("protocolVersion")
    if protocol_version is not None and not isinstance(protocol_version, str):
        return False, "Handshake payload protocolVersion must be a string when provided."

    session_id = payload.get("sessionId")
    if session_id is not None and not isinstance(session_id, str):
        return False, "Handshake payload sessionId must be a string when provided."

    return True, None


DEFAULT_COMMANDS = [
    {
        "name": HANDSHAKE_COMMAND_NAME,
        "payload": build_handshake_payload(),
    },
    {
        "name": "Ping",
        "payload": {
            "action": "ping",
            "timestamp": "2026-03-27T12:00:00Z",
        },
    },
    {
        "name": "Login",
        "payload": {
            "action": "login",
            "username": "demo_user",
            "token": "replace-me",
        },
    },
    {
        "name": "Subscribe",
        "payload": {
            "action": "subscribe",
            "channel": "events",
        },
    },
    {
        "name": "Echo",
        "payload": {
            "action": "echo",
            "message": "hello from tkinter client",
        },
    },
    {
        "name": "HTTP POST sample",
        "payload": {
            "method": "POST",
            "path": "/api/commands",
            "headers": {
                "Content-Type": "application/json",
            },
            "body": {
                "action": "status",
            },
            "timeout": 10,
        },
    },
]


class AppLogger:
    def __init__(self, callback) -> None:
        self.callback = callback

    def log(self, message: str) -> None:
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.callback(f"[{timestamp}] {message}\n")
