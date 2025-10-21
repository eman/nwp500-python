"""Token storage and management for CLI authentication."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from nwp500.auth import AuthTokens

_logger = logging.getLogger(__name__)

TOKEN_FILE = Path.home() / ".nwp500_tokens.json"


def save_tokens(tokens: AuthTokens, email: str) -> None:
    """
    Save authentication tokens and user email to a file.

    Args:
        tokens: AuthTokens object containing credentials
        email: User email address
    """
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(
                {
                    "email": email,
                    "id_token": tokens.id_token,
                    "access_token": tokens.access_token,
                    "refresh_token": tokens.refresh_token,
                    "authentication_expires_in": (
                        tokens.authentication_expires_in
                    ),
                    "issued_at": tokens.issued_at.isoformat(),
                    # AWS Credentials
                    "access_key_id": tokens.access_key_id,
                    "secret_key": tokens.secret_key,
                    "session_token": tokens.session_token,
                    "authorization_expires_in": tokens.authorization_expires_in,
                },
                f,
            )
        _logger.info(f"Tokens saved to {TOKEN_FILE}")
    except OSError as e:
        _logger.error(f"Failed to save tokens: {e}")


def load_tokens() -> tuple[Optional[AuthTokens], Optional[str]]:
    """
    Load authentication tokens and user email from a file.

    Returns:
        Tuple of (AuthTokens, email) or (None, None) if tokens cannot be loaded
    """
    if not TOKEN_FILE.exists():
        return None, None
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
            email = data["email"]
            # Reconstruct the AuthTokens object
            tokens = AuthTokens(
                id_token=data["id_token"],
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                authentication_expires_in=data["authentication_expires_in"],
                # AWS Credentials (use .get for backward compatibility)
                access_key_id=data.get("access_key_id"),
                secret_key=data.get("secret_key"),
                session_token=data.get("session_token"),
                authorization_expires_in=data.get("authorization_expires_in"),
            )
            # Manually set the issued_at from the stored ISO format string
            tokens.issued_at = datetime.fromisoformat(data["issued_at"])
            _logger.info(f"Tokens loaded from {TOKEN_FILE} for user {email}")
            return tokens, email
    except (OSError, json.JSONDecodeError, KeyError) as e:
        _logger.error(
            f"Failed to load or parse tokens, will re-authenticate: {e}"
        )
        return None, None
