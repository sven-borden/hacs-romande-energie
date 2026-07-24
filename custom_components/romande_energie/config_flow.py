"""Config flow for the Romande Énergie integration (OTP + reauth)."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import aiohttp_client
import homeassistant.helpers.config_validation as cv

from .api import (
    ApiError,
    AuthError,
    CannotConnect,
    OtpError,
    RomandeEnergieApiClient,
    account_id_from_token,
)
from .const import CONF_ACCOUNT_ID, CONF_CONTRACT_ID, CONF_REFRESH_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)


class RomandeEnergieConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Credentials -> SMS OTP -> contract, with reauth reusing the same steps."""

    VERSION = 1

    def __init__(self) -> None:
        # Reauth flag + carried state between the multi-step forms.
        self._reauth_entry: config_entries.ConfigEntry | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._account_id: str | None = None
        self._otp_token: str | None = None  # scope otp_pending
        self._otp_id: str | None = None
        self._mobile: str | None = None  # masked, for the OTP step description

    # ---- Step 1: credentials --------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect credentials, then login + trigger the SMS OTP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_start_otp(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if not errors:
                return await self.async_step_otp()
        return self.async_show_form(
            step_id="user", data_schema=self._user_schema(), errors=errors
        )

    # ---- Step 2: OTP code ------------------------------------------------
    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the SMS code, resolve the contract, create/update the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = RomandeEnergieApiClient(
                aiohttp_client.async_get_clientsession(self.hass)
            )
            try:
                tokens = await client.validate_otp(
                    self._otp_token, self._otp_id, user_input["otp_code"]
                )
                refresh_token = tokens["refresh_token"]
                access = tokens["access_token"]
                contracts = await client.get_contracts(access, self._account_id)
            except OtpError:
                errors["base"] = "invalid_otp"
            except AuthError as err:
                # Not bad credentials here: the OTP passed but the token was
                # rejected fetching contracts. Don't blame the password.
                _LOGGER.error("Authorization failed after OTP: %s", err)
                errors["base"] = "unknown"
            except CannotConnect as err:
                _LOGGER.debug("Cannot connect during OTP step: %s", err)
                errors["base"] = "cannot_connect"
            except ApiError as err:
                _LOGGER.error("Unexpected API error during OTP step: %s", err)
                errors["base"] = "unknown"
            else:
                contract_id = contracts[0].get("id") if contracts else None
                if not contract_id:
                    if contracts:
                        _LOGGER.error(
                            "Contract has no 'id'; keys=%s", list(contracts[0])
                        )
                    errors["base"] = "no_contract"
                else:
                    await self.async_set_unique_id(self._account_id)
                    if self._reauth_entry:
                        # Guard without _abort_if_unique_id_mismatch (HA >= 2024.11 only).
                        if self._account_id != self._reauth_entry.unique_id:
                            return self.async_abort(reason="unique_id_mismatch")
                    else:
                        self._abort_if_unique_id_configured()
                    data = {
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_ACCOUNT_ID: self._account_id,
                        CONF_CONTRACT_ID: contract_id,
                        CONF_REFRESH_TOKEN: refresh_token,
                    }
                    if self._reauth_entry:
                        return self.async_update_reload_and_abort(
                            self._reauth_entry, data=data
                        )
                    return self.async_create_entry(
                        title=f"Romande Énergie ({contract_id})", data=data
                    )
        return self.async_show_form(
            step_id="otp",
            data_schema=self._otp_schema(),
            errors=errors,
            description_placeholders={"mobile": self._mobile or ""},
        )

    # ---- Reauth ---------------------------------------------------------
    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start a reauth: remember the entry and prefill the known username."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._username = entry_data[CONF_USERNAME]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-run login + send-otp; async_step_otp then updates the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input.get(CONF_USERNAME, self._username)
            errors = await self._async_start_otp(username, user_input[CONF_PASSWORD])
            if not errors:
                return await self.async_step_otp()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self._reauth_schema(self._username),
            errors=errors,
        )

    # ---- Shared login + send-otp ---------------------------------------
    async def _async_start_otp(self, username: str, password: str) -> dict[str, str]:
        """Login, stash state, trigger the SMS. Return errors ({} on success)."""
        client = RomandeEnergieApiClient(
            aiohttp_client.async_get_clientsession(self.hass)
        )
        try:
            login = await client.login(username, password)
            self._username = username
            self._password = password
            self._otp_token = login["access_token"]
            self._mobile = login.get("mobile_number")
            self._account_id = account_id_from_token(self._otp_token)
            res = await client.send_otp(self._otp_token)
            self._otp_id = res["otp_id"]
        except AuthError:
            return {"base": "invalid_auth"}
        except OtpError:
            return {"base": "invalid_otp"}
        except CannotConnect as err:
            _LOGGER.debug("Cannot connect during login/send-otp: %s", err)
            return {"base": "cannot_connect"}
        except ApiError as err:
            _LOGGER.error("Unexpected API error during login/send-otp: %s", err)
            return {"base": "unknown"}
        _LOGGER.debug("OTP sent for account %s", self._account_id)
        return {}

    # ---- Schema helpers -------------------------------------------------
    @staticmethod
    def _user_schema() -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }
        )

    @staticmethod
    def _reauth_schema(username: str | None) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=username or ""): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }
        )

    @staticmethod
    def _otp_schema() -> vol.Schema:
        return vol.Schema({vol.Required("otp_code"): cv.string})
