"""Tests for the multi-step OTP config + reauth flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.romande_energie.api import AuthError, OtpError
from custom_components.romande_energie.const import (
    CONF_ACCOUNT_ID,
    CONF_CONTRACT_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

from .conftest import (
    FAKE_PASSWORD,
    FAKE_USERNAME,
    build_config_entry,
    make_jwt,
)

_CLIENT_PATH = "custom_components.romande_energie.config_flow.RomandeEnergieApiClient"
_SETUP_PATH = "custom_components.romande_energie.async_setup_entry"

# Finishing a flow loads the entry, and the integration depends on the recorder.
pytestmark = pytest.mark.recorder


def _client_mock(
    *,
    login_exc: Exception | None = None,
    validate_exc: Exception | None = None,
    validate_result: dict | None = None,
    contracts: list | None = None,
    account_id: str = "ACCT_TEST",
) -> AsyncMock:
    """Build an API-client mock covering every step of the flow."""
    client = AsyncMock()
    if login_exc is not None:
        client.login.side_effect = login_exc
    else:
        client.login.return_value = {
            "access_token": make_jwt(account_id),
            "mobile_number": "+41 79 *** ** 00",
        }
    client.send_otp.return_value = {"otp_id": "OTP_TEST"}
    if validate_exc is not None:
        client.validate_otp.side_effect = validate_exc
    else:
        client.validate_otp.return_value = validate_result or {
            "access_token": make_jwt(account_id),
            "refresh_token": "REFRESH_TEST",
        }
    client.get_contracts.return_value = (
        contracts if contracts is not None else [{"id": "CONTRACT_TEST"}]
    )
    return client


def _patch_setup():
    return patch(_SETUP_PATH, new_callable=AsyncMock, return_value=True)


@pytest.fixture(autouse=True)
def no_real_client_session():
    """Hand the flow a dummy aiohttp session.

    The API client is mocked in every test here, so a real session is never
    used — and building one spins up a DNS resolver whose background thread
    outlives the test and trips the plugin's cleanup checks.
    """
    with patch(
        "custom_components.romande_energie.config_flow.aiohttp_client"
        ".async_get_clientsession",
        return_value=MagicMock(),
    ):
        yield


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
async def test_full_flow_creates_entry(hass: HomeAssistant) -> None:
    client = _client_mock()

    with patch(_CLIENT_PATH, return_value=client), _patch_setup():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: FAKE_USERNAME, CONF_PASSWORD: FAKE_PASSWORD},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "otp"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp_code": "123456"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "ACCT_TEST"
    assert result["data"] == {
        CONF_USERNAME: FAKE_USERNAME,
        CONF_PASSWORD: FAKE_PASSWORD,
        CONF_ACCOUNT_ID: "ACCT_TEST",
        CONF_CONTRACT_ID: "CONTRACT_TEST",
        CONF_REFRESH_TOKEN: "REFRESH_TEST",
    }
    client.send_otp.assert_awaited_once()


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------
async def test_invalid_credentials_on_user_step(hass: HomeAssistant) -> None:
    client = _client_mock(login_exc=AuthError("bad creds"))

    with patch(_CLIENT_PATH, return_value=client):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: FAKE_USERNAME, CONF_PASSWORD: FAKE_PASSWORD},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}
    client.send_otp.assert_not_called()


async def test_invalid_otp(hass: HomeAssistant) -> None:
    client = _client_mock(validate_exc=OtpError("wrong code"))

    with patch(_CLIENT_PATH, return_value=client):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: FAKE_USERNAME, CONF_PASSWORD: FAKE_PASSWORD},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp_code": "000000"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "otp"
    assert result["errors"] == {"base": "invalid_otp"}


async def test_no_contract(hass: HomeAssistant) -> None:
    client = _client_mock(contracts=[])

    with patch(_CLIENT_PATH, return_value=client):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: FAKE_USERNAME, CONF_PASSWORD: FAKE_PASSWORD},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp_code": "123456"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "otp"
    assert result["errors"] == {"base": "no_contract"}


# ---------------------------------------------------------------------------
# Reauth
# ---------------------------------------------------------------------------
def _start_reauth(hass: HomeAssistant, entry):
    return hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=entry.data,
    )


async def test_reauth_success_updates_entry(hass: HomeAssistant) -> None:
    entry = build_config_entry()  # unique_id ACCT_TEST
    entry.add_to_hass(hass)
    client = _client_mock(
        validate_result={
            "access_token": make_jwt("ACCT_TEST"),
            "refresh_token": "REFRESH_ROTATED",
        }
    )

    with patch(_CLIENT_PATH, return_value=client), _patch_setup():
        result = await _start_reauth(hass, entry)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: FAKE_USERNAME, CONF_PASSWORD: "new-password"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "otp"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp_code": "123456"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "REFRESH_ROTATED"


async def test_reauth_unique_id_mismatch_aborts(hass: HomeAssistant) -> None:
    # The stored entry belongs to a different account than the one that logs in.
    entry = build_config_entry(data={CONF_ACCOUNT_ID: "ACCT_OTHER"})
    entry.add_to_hass(hass)
    client = _client_mock(account_id="ACCT_TEST")

    with patch(_CLIENT_PATH, return_value=client):
        result = await _start_reauth(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: FAKE_USERNAME, CONF_PASSWORD: "new-password"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp_code": "123456"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
