"""Config flow for the Nature Remo integration.

Setup asks only for the cloud access token (from https://home.nature.global).
The token is checked against the Nature Remo cloud before an entry is created,
and the Nature account id is used as the entry's unique id so the same account
cannot be added twice.  Re-authentication and reconfiguration let the user
replace the token without removing the integration.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import NatureRemoAuthError, NatureRemoConnectionError, async_get_user
from .const import DEFAULT_NAME, DOMAIN
from .options_flow import NatureRemoOptionsFlowHandler

_LOGGER = logging.getLogger(__name__)

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

USER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_API_KEY): TOKEN_SELECTOR,
    }
)
TOKEN_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): TOKEN_SELECTOR})


class NatureRemoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nature Remo."""

    VERSION = 1

    async def _async_validate(
        self, token: str
    ) -> tuple[dict[str, str], dict[str, Any] | None]:
        """Check the token with the cloud. Return (errors, user)."""
        errors: dict[str, str] = {}
        try:
            user = await async_get_user(async_get_clientsession(self.hass), token)
        except NatureRemoAuthError:
            errors["base"] = "invalid_auth"
        except NatureRemoConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error while checking the Nature Remo token")
            errors["base"] = "unknown"
        else:
            return errors, user
        return errors, None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the access token and create the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_API_KEY].strip()
            # Older entries have no unique id yet: match them by token too.
            self._async_abort_entries_match({CONF_API_KEY: token})
            errors, user = await self._async_validate(token)
            if user is not None:
                if user_id := user.get("id"):
                    await self.async_set_unique_id(str(user_id))
                    self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME) or user.get("nickname") or DEFAULT_NAME,
                    data={CONF_API_KEY: token},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the cloud rejected the token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token."""
        return await self._async_step_replace_token(
            "reauth_confirm", self._get_reauth_entry(), user_input
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change the token without removing the integration."""
        return await self._async_step_replace_token(
            "reconfigure", self._get_reconfigure_entry(), user_input
        )

    async def _async_step_replace_token(
        self,
        step_id: str,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_API_KEY].strip()
            errors, user = await self._async_validate(token)
            if user is not None:
                user_id = str(user.get("id") or "")
                if entry.unique_id and user_id and user_id != entry.unique_id:
                    return self.async_abort(reason="wrong_account")
                updates: dict[str, Any] = {}
                if entry.unique_id is None and user_id:
                    updates["unique_id"] = user_id
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: token}, **updates
                )
        return self.async_show_form(
            step_id=step_id,
            data_schema=TOKEN_SCHEMA,
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NatureRemoOptionsFlowHandler:
        """Return the options flow (update interval, Remo IPs, local IR)."""
        return NatureRemoOptionsFlowHandler()
