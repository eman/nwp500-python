"""Token storage and management for CLI authentication."""

import json
import logging
import os
from pathlib import Path

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
        # Tokens grant account access; keep the file owner-readable only.
        # O_CREAT mode only applies to new files, so chmod existing ones.
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            TOKEN_FILE.chmod(0o600)
            # Use the built-in to_dict() method for serialization
            token_data = tokens.to_dict()
            token_data["email"] = email
            json.dump(token_data, f)
        _logger.info(f"Tokens saved to {TOKEN_FILE}")
    except OSError as e:
        _logger.error(f"Failed to save tokens: {e}")


def load_tokens() -> tuple[AuthTokens | None, str | None]:
    """
    Load authentication tokens and user email from a file.

    Returns:
        Tuple of (AuthTokens, email) or (None, None) if tokens cannot be loaded
    """
    if not TOKEN_FILE.exists():
        return None, None
    try:
        with TOKEN_FILE.open() as f:
            data = json.load(f)
            email = data.get("email")
            if not email:
                _logger.error("No email found in token file")
                return None, None

            # Use the built-in model_validate() method for deserialization
            tokens = AuthTokens.model_validate(data)
            _logger.info(f"Tokens loaded from {TOKEN_FILE} for user {email}")
            return tokens, email
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        _logger.error(
            f"Failed to load or parse tokens, will re-authenticate: {e}"
        )
        return None, None
