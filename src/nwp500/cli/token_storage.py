"""Token storage and management for CLI authentication."""

import json
import logging
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
            # Use the built-in to_dict() method for serialization
            token_data = tokens.to_dict()
            token_data["email"] = email
            json.dump(token_data, f)
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
            email = data.get("email")
            if not email:
                _logger.error("No email found in token file")
                return None, None

            # Use the built-in from_dict() method for deserialization
            tokens = AuthTokens.from_dict(data)
            _logger.info(f"Tokens loaded from {TOKEN_FILE} for user {email}")
            return tokens, email
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        _logger.error(
            f"Failed to load or parse tokens, will re-authenticate: {e}"
        )
        return None, None
