"""Tests for the JWT claim helpers in ``api.py``."""
from __future__ import annotations

import base64
import json

import pytest

from custom_components.romande_energie.api import (
    AuthError,
    _decode_jwt_payload,
    account_id_from_token,
    token_expiry,
)


def _b64url(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# _decode_jwt_payload
# ---------------------------------------------------------------------------
def test_decode_valid_payload(make_token):
    token = make_token("ACCT_TEST", exp=1893456000)
    payload = _decode_jwt_payload(token)
    assert payload["user_account_id"] == "ACCT_TEST"
    assert payload["exp"] == 1893456000


def test_decode_handles_unpadded_base64():
    # A single-key payload whose base64 length is not a multiple of 4 forces
    # the padding logic to kick in.
    segment = _b64url({"user_account_id": "A"})
    assert len(segment) % 4 != 0  # would fail without padding restoration
    token = f"header.{segment}.sig"
    assert _decode_jwt_payload(token) == {"user_account_id": "A"}


def test_decode_no_dot_raises_auth_error():
    with pytest.raises(AuthError):
        _decode_jwt_payload("no-dots-here")


def test_decode_non_json_payload_raises_auth_error():
    # Valid base64 that does not decode to JSON.
    bogus = base64.urlsafe_b64encode(b"not-json{{{").rstrip(b"=").decode("ascii")
    with pytest.raises(AuthError):
        _decode_jwt_payload(f"header.{bogus}.sig")


# ---------------------------------------------------------------------------
# account_id_from_token
# ---------------------------------------------------------------------------
def test_account_id_present(make_token):
    assert account_id_from_token(make_token("ACCT_TEST")) == "ACCT_TEST"


def test_account_id_missing_raises(make_token):
    with pytest.raises(AuthError):
        account_id_from_token(make_token(account_id=None))


def test_account_id_empty_raises(make_token):
    with pytest.raises(AuthError):
        account_id_from_token(make_token(""))


# ---------------------------------------------------------------------------
# token_expiry
# ---------------------------------------------------------------------------
def test_token_expiry_present(make_token):
    assert token_expiry(make_token("ACCT_TEST", exp=1893456000)) == 1893456000


def test_token_expiry_absent_returns_zero(make_token):
    assert token_expiry(make_token("ACCT_TEST")) == 0
