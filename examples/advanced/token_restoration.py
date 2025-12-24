#!/usr/bin/env python3
"""Example demonstrating token restoration/persistence.

This example shows how to save and restore authentication tokens to avoid
re-authenticating on every application restart. This is especially useful
for applications like Home Assistant that restart frequently.

Usage:
    # First run - authenticate and save tokens
    python3 token_restoration_example.py --save

    # Subsequent runs - restore from saved tokens
    python3 token_restoration_example.py --restore
"""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from nwp500 import NavienAuthClient

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Token storage file
TOKEN_FILE = Path.home() / ".navien_tokens.json"


async def save_tokens_example():
    """Authenticate and save tokens for future use."""
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        raise ValueError(
            "Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables"
        )

    logger.info("Authenticating with Navien API...")

    # Authenticate normally
    async with NavienAuthClient(email, password) as auth_client:
        tokens = auth_client.current_tokens
        if not tokens:
            raise RuntimeError("Failed to obtain tokens")

        logger.info("[OK] Authentication successful")
        logger.info(f"Token expires at: {tokens.expires_at}")

        # Serialize tokens to dictionary
        token_data = tokens.to_dict()

        # Save to file
        with open(TOKEN_FILE, "w") as f:
            json.dump(token_data, f, indent=2)

        logger.info(f"[OK] Tokens saved to {TOKEN_FILE}")
        logger.info("You can now use --restore to skip authentication on future runs")


async def restore_tokens_example():
    """Restore authentication from saved tokens."""
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(
            f"Token file not found: {TOKEN_FILE}\n"
            "Please run with --save first to authenticate and save tokens"
        )

    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")

    if not email or not password:
        raise ValueError(
            "Please set NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables"
        )

    # Load saved tokens
    with open(TOKEN_FILE) as f:
        token_data = json.load(f)

    logger.info(f"Loading tokens from {TOKEN_FILE}...")

    # Import after getting token_data to avoid circular import issues
    from nwp500.auth import AuthTokens

    stored_tokens = AuthTokens.from_dict(token_data)

    logger.info(f"Stored tokens issued at: {stored_tokens.issued_at}")
    logger.info(f"Stored tokens expire at: {stored_tokens.expires_at}")

    if stored_tokens.is_expired:
        logger.warning("⚠ Stored tokens are expired, will refresh...")
    elif stored_tokens.are_aws_credentials_expired:
        logger.warning("⚠ AWS credentials expired, will re-authenticate...")
    else:
        logger.info("[OK] Stored tokens are still valid")

    # Use stored tokens to initialize client
    async with NavienAuthClient(
        email, password, stored_tokens=stored_tokens
    ) as auth_client:
        tokens = auth_client.current_tokens
        if not tokens:
            raise RuntimeError("Failed to restore authentication")

        logger.info("[OK] Successfully authenticated using stored tokens")
        logger.info(f"Current token expires at: {tokens.expires_at}")

        # If tokens were refreshed, save them
        if tokens.issued_at != stored_tokens.issued_at:
            logger.info("Tokens were refreshed, updating stored copy...")
            token_data = tokens.to_dict()
            with open(TOKEN_FILE, "w") as f:
                json.dump(token_data, f, indent=2)
            logger.info(f"[OK] Updated tokens saved to {TOKEN_FILE}")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Token restoration example for nwp500-python"
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--save",
        action="store_true",
        help="Authenticate and save tokens for future use (default)",
    )
    group.add_argument(
        "--restore",
        action="store_true",
        help="Restore authentication from saved tokens",
    )

    args = parser.parse_args()

    try:
        if args.restore:
            await restore_tokens_example()
        else:
            # Default to save mode if --save is specified or no args provided
            await save_tokens_example()
    except Exception as e:
        logger.error(f"Error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
