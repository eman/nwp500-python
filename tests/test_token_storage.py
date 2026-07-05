"""Tests for CLI token storage."""

import json

import pytest

try:
    from nwp500.cli import token_storage
except ImportError:
    pytest.skip("CLI dependencies not installed", allow_module_level=True)

from nwp500.auth import AuthTokens


@pytest.fixture
def tokens():
    return AuthTokens(
        id_token="test_id",
        access_token="test_access",
        refresh_token="test_refresh",
        authentication_expires_in=3600,
    )


def test_save_tokens_owner_only_permissions(tmp_path, monkeypatch, tokens):
    """Token file must not be readable by group/others."""
    token_file = tmp_path / "tokens.json"
    monkeypatch.setattr(token_storage, "TOKEN_FILE", token_file)

    token_storage.save_tokens(tokens, "user@example.com")

    assert token_file.exists()
    assert token_file.stat().st_mode & 0o777 == 0o600


def test_save_tokens_tightens_existing_permissions(
    tmp_path, monkeypatch, tokens
):
    """Saving over a pre-existing world-readable file fixes its mode."""
    token_file = tmp_path / "tokens.json"
    token_file.write_text("{}")
    token_file.chmod(0o644)
    monkeypatch.setattr(token_storage, "TOKEN_FILE", token_file)

    token_storage.save_tokens(tokens, "user@example.com")

    assert token_file.stat().st_mode & 0o777 == 0o600


def test_save_and_load_roundtrip(tmp_path, monkeypatch, tokens):
    token_file = tmp_path / "tokens.json"
    monkeypatch.setattr(token_storage, "TOKEN_FILE", token_file)

    token_storage.save_tokens(tokens, "user@example.com")
    loaded, email = token_storage.load_tokens()

    assert email == "user@example.com"
    assert loaded is not None
    assert loaded.refresh_token == "test_refresh"
    # File content is valid JSON including the email
    assert json.loads(token_file.read_text())["email"] == "user@example.com"
