"""Config flow for Romande Energie integration."""
import logging
import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import RomandeEnergieApiClient
from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
})


async def validate_input(hass: core.HomeAssistant, data):
    """Validate the user input allows us to connect."""
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    
    session = async_get_clientsession(hass)
    client = RomandeEnergieApiClient(username, password, session)
    
    if not await client.login():
        raise InvalidAuth
    
    # Return info to be stored in the config entry
    return {"title": f"Romande Energie ({username})"}


class RomandeEnergieConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Romande Energie."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )
    
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return RomandeEnergieOptionsFlowHandler(config_entry)


class RomandeEnergieOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Romande Energie."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        super().__init__(config_entry)

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = {
            vol.Optional(
                "scan_interval",
                default=self.config_entry.options.get(
                    "scan_interval", DEFAULT_SCAN_INTERVAL.total_seconds()
                ),
            ): vol.All(cv.positive_int, vol.Clamp(min=1800, max=86400))
        }

        return self.async_show_form(step_id="init", data_schema=vol.Schema(options))


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""