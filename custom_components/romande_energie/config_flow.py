"""Config flow for Romande Énergie integration."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

class RomandeEnergieConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Romande Énergie."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Here you can validate the user_input, e.g., try logging in
            # If successful, create the entry
            return self.async_create_entry(title="Romande Énergie", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return an options flow if needed."""
        return RomandeEnergieOptionsFlowHandler(config_entry)


class RomandeEnergieOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for Romande Énergie."""

    def __init__(self, config_entry):
        """Initialize the options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_USERNAME,
                    default=self.config_entry.data.get(CONF_USERNAME, ""),
                ): str,
                vol.Optional(
                    CONF_PASSWORD,
                    default=self.config_entry.data.get(CONF_PASSWORD, ""),
                ): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)