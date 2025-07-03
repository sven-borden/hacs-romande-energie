"""Config flow for Romande Énergie integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import jwt
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .const import (
    DOMAIN,
    LOGIN_ENDPOINT,
    CONTRACTS_ENDPOINT,
    CONF_CONTRACT_ID,
    CONF_ACCOUNT_ID,
)

_LOGGER = logging.getLogger(__name__)


class RomandeEnergieConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            session = aiohttp_client.async_get_clientsession(self.hass)

            try:
                # 1. Login
                async with session.post(LOGIN_ENDPOINT, json=user_input, timeout=20) as resp:
                    if resp.status != 200:
                        raise ValueError("invalid_auth")
                    login_payload = await resp.json()

                access_token: str = login_payload["access_token"]
                decoded = jwt.decode(access_token, options={"verify_signature": False})
                account_id: str = decoded.get("user_account_id")  # JWT field is user_account_id

                # 2. Contracts
                url = CONTRACTS_ENDPOINT.format(account_id=account_id)
                headers = {"Authorization": f"Bearer {access_token}"}
                async with session.get(url, headers=headers, timeout=20) as resp:
                    if resp.status != 200:
                        raise ValueError("cannot_connect")
                    contracts = await resp.json()

                if not contracts:
                    raise ValueError("no_contract")

                contract_id = contracts[0]["id"]  # Pick the first contract

            except ValueError as exc:
                errors["base"] = str(exc)
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            else:
                # Everything looks good → create entry.
                data = {
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_ACCOUNT_ID: account_id,
                    CONF_CONTRACT_ID: contract_id,
                }
                return self.async_create_entry(title=f"Romande Énergie ({account_id})", data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=self._get_schema(),
            errors=errors,
        )

    # -------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------
    @staticmethod
    def _get_schema():
        from homeassistant.helpers import config_validation as cv
        import voluptuous as vol

        return vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }
        )