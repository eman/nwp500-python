"""Basic tests for CLI entry point."""

import logging
import sys
from unittest.mock import patch

import pytest

try:
    from nwp500.cli.__main__ import run
except ImportError:
    pytest.skip("CLI dependencies not installed", allow_module_level=True)


@pytest.fixture(autouse=True)
def _restore_log_levels():
    """The CLI group callback mutates global logger levels; undo it."""
    names = (None, "nwp500", "nwp500.cli.__main__", "aiohttp")
    saved = {name: logging.getLogger(name).level for name in names}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def test_cli_help():
    """Test that CLI help command works."""
    with patch.object(sys, "argv", ["nwp-cli", "--help"]):
        with pytest.raises(SystemExit) as excinfo:
            run()
        assert excinfo.value.code == 0


def test_cli_no_args():
    """Test that CLI without args shows help."""
    with patch.object(sys, "argv", ["nwp-cli"]):
        with pytest.raises(SystemExit) as excinfo:
            run()
        assert excinfo.value.code != 0


def test_cli_mode_rejects_vacation():
    """Vacation is not a valid mode argument (use the vacation command)."""
    with patch.object(sys, "argv", ["nwp-cli", "mode", "vacation"]):
        with pytest.raises(SystemExit) as excinfo:
            run()
        assert excinfo.value.code == 2  # click usage error


def test_cli_mode_rejects_standby():
    """Standby (0) is not a writable operation mode."""
    with patch.object(sys, "argv", ["nwp-cli", "mode", "standby"]):
        with pytest.raises(SystemExit) as excinfo:
            run()
        assert excinfo.value.code == 2  # click usage error


def test_cli_exits_nonzero_on_missing_credentials():
    """Command failures must produce a non-zero exit code."""
    import os

    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("NAVIEN_EMAIL", "NAVIEN_PASSWORD")
    }
    with (
        patch.dict(os.environ, env, clear=True),
        patch("nwp500.cli.__main__.load_tokens", return_value=(None, None)),
        patch.object(sys, "argv", ["nwp-cli", "mode", "heat-pump"]),
    ):
        with pytest.raises(SystemExit) as excinfo:
            run()
        assert excinfo.value.code == 1


def test_cli_discards_cached_tokens_for_different_email():
    """Cached tokens for account A must not be reused for account B."""
    from unittest.mock import MagicMock

    from nwp500.exceptions import AuthenticationError

    cached_tokens = MagicMock()
    mock_auth_cls = MagicMock(
        side_effect=AuthenticationError("stop before network")
    )
    with (
        patch(
            "nwp500.cli.__main__.load_tokens",
            return_value=(cached_tokens, "usera@example.com"),
        ),
        patch("nwp500.cli.__main__.NavienAuthClient", mock_auth_cls),
        patch.object(
            sys,
            "argv",
            [
                "nwp-cli",
                "--email",
                "userb@example.com",
                "--password",
                "pw",
                "mode",
                "heat-pump",
            ],
        ),
    ):
        with pytest.raises(SystemExit) as excinfo:
            run()
        assert excinfo.value.code == 1
    mock_auth_cls.assert_called_once_with(
        "userb@example.com", "pw", stored_tokens=None
    )
