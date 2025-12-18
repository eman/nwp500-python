"""Basic tests for CLI entry point."""

import sys
from unittest.mock import patch

import pytest

from nwp500.cli.__main__ import run


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
