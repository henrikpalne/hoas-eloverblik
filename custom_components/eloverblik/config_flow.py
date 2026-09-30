"""Config flow for Eloverblik integration."""
import logging
from requests import HTTPError, RequestException

import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from pyeloverblik.eloverblik import Eloverblik

from .const import DOMAIN  # pylint:disable=unused-import

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required("refresh_token"): str,
        vol.Required("metering_point",): str
    })

TOKEN_SCHEMA = vol.Schema({vol.Required("refresh_token"): str})

async def validate_input(hass: core.HomeAssistant, data):
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    token = data["refresh_token"]
    metering_point = data["metering_point"]

    service = Eloverblik(token)

    try:
        result = await hass.async_add_executor_job(service.get_tariffs, metering_point)
    except HTTPError as error:
        if error.response is not None and error.response.status_code in (401, 403):
            raise InvalidAuth() from error
        raise CannotConnect() from error
    except RequestException as error:
        raise CannotConnect() from error

    if result.status in (401, 403):
        raise InvalidAuth()
    if result.status != 200:
        raise CannotConnect()

    return {"title": f"Eloverblik {metering_point}"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Eloverblik."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    @staticmethod
    @core.callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""

        errors = {}
        if user_input is not None:
            metering_point = user_input["metering_point"]
            await self.async_set_unique_id(metering_point)
            self._abort_if_unique_id_configured()
            try:
                info = await validate_input(self.hass, user_input)

                return self.async_create_entry(title=info["title"], data=user_input)

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def _async_validate_token(self, entry, user_input):
        """Validate a new token against the entry's metering point."""
        try:
            await validate_input(self.hass, {
                "refresh_token": user_input["refresh_token"].strip(),
                "metering_point": entry.data["metering_point"],
            })
        except CannotConnect:
            return "cannot_connect"
        except InvalidAuth:
            return "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            return "unknown"
        return None

    async def async_step_reconfigure(self, user_input=None):
        """Replace the refresh token without removing the integration."""
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            error = await self._async_validate_token(entry, user_input)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={"refresh_token": user_input["refresh_token"].strip()}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=TOKEN_SCHEMA,
            errors=errors,
            description_placeholders={"metering_point": entry.data["metering_point"]},
        )

    async def async_step_reauth(self, entry_data):
        """Start re-authentication when the token has expired."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Ask for a new refresh token."""
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            error = await self._async_validate_token(entry, user_input)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={"refresh_token": user_input["refresh_token"].strip()}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=TOKEN_SCHEMA,
            errors=errors,
            description_placeholders={"metering_point": entry.data["metering_point"]},
        )

class OptionsFlow(config_entries.OptionsFlow):
    """Opt in to net spot estimates; existing entries remain consumption-only."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            if user_input.get("spot_price_area") in ("disabled", "DK1", "DK2"):
                return self.async_create_entry(title="", data={
                    **self.config_entry.options, "spot_price_area": user_input["spot_price_area"]
                })
            errors["base"] = "invalid_price_area"
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required(
                "spot_price_area", default=self.config_entry.options.get("spot_price_area", "disabled")
            ): vol.In({"disabled": "Disabled", "DK1": "DK1", "DK2": "DK2"})}),
            errors=errors,
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
