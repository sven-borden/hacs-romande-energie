"""Shared fixtures for the Romande Énergie test suite.

No real credentials, tokens or personal data live here: every value is an
obvious placeholder and the JWTs are built on the fly from a tiny helper so
there are no opaque token blobs to trust.
"""
from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.romande_energie.const import (
    CONF_ACCOUNT_ID,
    CONF_CONTRACT_ID,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    DOMAIN,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Obviously-fake identifiers reused across the suite.
FAKE_USERNAME = "user@example.com"
FAKE_PASSWORD = "fake-password"
FAKE_ACCOUNT_ID = "ACCT_TEST"
FAKE_CONTRACT_ID = "CONTRACT_TEST"
FAKE_REFRESH_TOKEN = "REFRESH_TEST"


@pytest.fixture
def recorder_before_hass(request):
    """Set up the recorder for tests marked ``recorder``, before ``hass`` exists.

    The integration declares ``recorder`` as a dependency, so any test that
    actually loads a config entry needs it. ``recorder_mock`` refuses to run
    once ``hass`` exists, hence the ordering: the autouse fixture below takes
    this one as its first argument so it always resolves first.
    """
    if "recorder" in request.keywords:
        request.getfixturevalue("recorder_mock")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_before_hass, enable_custom_integrations):
    """Enable loading of the custom integration for every test."""
    yield


# ---------------------------------------------------------------------------
# JWT helper
# ---------------------------------------------------------------------------
def _b64url(payload: dict[str, Any]) -> str:
    """base64url-encode a dict as a JWT segment (padding stripped)."""
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_jwt(
    account_id: str | None = FAKE_ACCOUNT_ID, exp: int | None = None
) -> str:
    """Build a fake, unsigned ``header.payload.sig`` JWT.

    The signature segment is a placeholder string: the integration only reads
    claims and never verifies signatures. ``account_id``/``exp`` are omitted
    from the payload when passed as ``None`` so callers can exercise the
    "missing claim" branches.
    """
    header = _b64url({"alg": "none", "typ": "JWT"})
    payload: dict[str, Any] = {}
    if account_id is not None:
        payload["user_account_id"] = account_id
    if exp is not None:
        payload["exp"] = int(exp)
    return f"{header}.{_b64url(payload)}.sig"


@pytest.fixture
def make_token() -> Callable[..., str]:
    """Expose :func:`make_jwt` to tests."""
    return make_jwt


@pytest.fixture
def valid_access_token() -> str:
    """A fake access token whose exp is comfortably in the future."""
    return make_jwt(FAKE_ACCOUNT_ID, exp=int(time.time()) + 3600)


# ---------------------------------------------------------------------------
# Curve payload fixture
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_curves() -> list[dict[str, Any]]:
    """The realistic curves payload loaded from the fixture file."""
    with (FIXTURES_DIR / "curves_sample.json").open(encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Config entry builder
# ---------------------------------------------------------------------------
def build_config_entry(
    *, data: dict[str, Any] | None = None, **overrides: Any
) -> MockConfigEntry:
    """Build a :class:`MockConfigEntry` with sensible fake defaults."""
    entry_data = {
        CONF_USERNAME: FAKE_USERNAME,
        CONF_PASSWORD: FAKE_PASSWORD,
        CONF_ACCOUNT_ID: FAKE_ACCOUNT_ID,
        CONF_CONTRACT_ID: FAKE_CONTRACT_ID,
        CONF_REFRESH_TOKEN: FAKE_REFRESH_TOKEN,
    }
    if data:
        entry_data.update(data)
    kwargs: dict[str, Any] = {
        "domain": DOMAIN,
        "data": entry_data,
        "unique_id": entry_data[CONF_ACCOUNT_ID],
        "title": f"Romande Énergie ({entry_data[CONF_CONTRACT_ID]})",
    }
    kwargs.update(overrides)
    return MockConfigEntry(**kwargs)


@pytest.fixture
def config_entry_factory() -> Callable[..., MockConfigEntry]:
    """Return the :func:`build_config_entry` builder."""
    return build_config_entry


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A ready-to-use config entry with fake defaults."""
    return build_config_entry()
