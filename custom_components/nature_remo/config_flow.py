"""Config flow for the Nature Remo integration.

Setup asks only for the cloud access token (from https://home.nature.global).
The token is checked against the Nature Remo cloud before an entry is created,
and the Nature account id is used as the entry's unique id so the same account
cannot be added twice.  Re-authentication and reconfiguration let the user
replace the token without removing the integration.

Zeroconf (_remo._tcp) discovery updates the stored local IP of a known Remo,
or starts a confirm step that asks for the token to add a new account.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import NatureRemoAuthError, NatureRemoConnectionError, async_get_user
from .const import DEFAULT_NAME, DOMAIN
from .options_flow import NatureRemoOptionsFlowHandler

if TYPE_CHECKING:
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

_LOGGER = logging.getLogger(__name__)

# TXT keys seen in docs or reserved for future firmware. None were observed
# on the LAN (no Remo advertised during the 2026-11-13 browse).
_PROPERTY_ID_KEYS = frozenset(
    {"id", "serial", "serial_number", "mac", "mac_address", "bt_mac_address"}
)
_HEX_ONLY = re.compile(r"[^0-9a-f]")

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

USER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_API_KEY): TOKEN_SELECTOR,
    }
)
TOKEN_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): TOKEN_SELECTOR})


def _norm(value: str) -> str:
    return value.strip().rstrip(".").lower()


def _mac_forms(value: str) -> set[str]:
    """Return common string forms of a MAC or serial suffix."""
    raw = _norm(value).replace("-", ":")
    hex_only = _HEX_ONLY.sub("", raw)
    forms = {raw, hex_only}
    if len(hex_only) == 12:
        forms.add(":".join(hex_only[i : i + 2] for i in range(0, 12, 2)))
    if len(hex_only) >= 6:
        forms.add(hex_only[-6:])
    return {item for item in forms if item}


def _property_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode()
        except UnicodeDecodeError:
            return None
    text = str(value).strip()
    return text or None


def _zeroconf_host(discovery_info: ZeroconfServiceInfo) -> str:
    host = getattr(discovery_info, "host", None)
    if host:
        return str(host)
    return str(discovery_info.ip_address)


def _zeroconf_instance_name(discovery_info: ZeroconfServiceInfo) -> str:
    name = discovery_info.name or ""
    instance = name.split(".")[0] if name else ""
    if instance:
        return instance
    hostname = (discovery_info.hostname or "").rstrip(".")
    if hostname.lower().endswith(".local"):
        hostname = hostname[: -len(".local")].rstrip(".")
    return hostname


def _discovery_identifiers(
    discovery_info: ZeroconfServiceInfo, host: str
) -> set[str]:
    """Serial, MAC, hostname and IP forms that can match a stored Remo."""
    identifiers: set[str] = set()
    if host:
        identifiers.add(_norm(host))
    hostname = _norm(discovery_info.hostname or "")
    if hostname:
        identifiers.add(hostname)
        if hostname.endswith(".local"):
            identifiers.add(hostname[: -len(".local")].rstrip("."))
    instance = _zeroconf_instance_name(discovery_info)
    if instance:
        identifiers.add(_norm(instance))
        if "-" in instance:
            identifiers.update(_mac_forms(instance.split("-", 1)[1]))
    for key, value in (discovery_info.properties or {}).items():
        if key.lower() not in _PROPERTY_ID_KEYS:
            continue
        text = _property_text(value)
        if text is None:
            continue
        identifiers.add(_norm(text))
        identifiers.update(_mac_forms(text))
    return {item for item in identifiers if item}


def _device_identifiers(device: Any) -> set[str]:
    identifiers: set[str] = set()
    for raw in (device.serial_number, device.name, device.name_by_user):
        if raw:
            identifiers.add(_norm(str(raw)))
            identifiers.update(_mac_forms(str(raw)))
    for _conn_type, conn_id in device.connections:
        identifiers.add(_norm(str(conn_id)))
        identifiers.update(_mac_forms(str(conn_id)))
    for _ident_domain, ident_id in device.identifiers:
        if ident_id:
            identifiers.add(_norm(str(ident_id)))
    return identifiers


def _find_configured_remo(
    hass: HomeAssistant, identifiers: set[str]
) -> tuple[ConfigEntry, str] | None:
    """Match an existing entry by stored local host, serial, MAC or name.

    The entry unique id is the Nature account id, so a Remo is identified
    by the local-API IP option (keyed by the HA device registry id) and by
    serial/MAC/name on the device registry entry.
    """
    registry = async_get_device_registry(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        for key, value in entry.options.items():
            if isinstance(value, str) and _norm(value) in identifiers:
                return entry, str(key)
        for device in registry.devices.values():
            if entry.entry_id not in device.config_entries:
                continue
            if _device_identifiers(device) & identifiers:
                return entry, device.id
    return None


class NatureRemoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nature Remo."""

    VERSION = 1

    _discovery_host: str
    _discovery_name: str

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

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a Remo advertised over mDNS (_remo._tcp)."""
        host = _zeroconf_host(discovery_info)
        name = _zeroconf_instance_name(discovery_info) or host
        self._discovery_host = host
        self._discovery_name = name
        self.context["title_placeholders"] = {"name": name, "host": host}

        identifiers = _discovery_identifiers(discovery_info, host)
        if match := _find_configured_remo(self.hass, identifiers):
            entry, option_key = match
            current = str(entry.options.get(option_key, "")).strip()
            if current != host:
                self.hass.config_entries.async_update_entry(
                    entry, options={**entry.options, option_key: host}
                )
                if entry.state in (
                    ConfigEntryState.LOADED,
                    ConfigEntryState.SETUP_RETRY,
                ):
                    self.hass.async_create_task(
                        self.hass.config_entries.async_reload(entry.entry_id)
                    )
            return self.async_abort(reason="already_configured")

        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the cloud token after a new Remo is discovered."""
        errors: dict[str, str] = {}
        host = getattr(self, "_discovery_host", "") or ""
        name = getattr(self, "_discovery_name", "") or host
        if user_input is not None:
            token = user_input[CONF_API_KEY].strip()
            self._async_abort_entries_match({CONF_API_KEY: token})
            errors, user = await self._async_validate(token)
            if user is not None:
                if user_id := user.get("id"):
                    await self.async_set_unique_id(str(user_id), raise_on_progress=False)
                    self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user.get("nickname") or name or DEFAULT_NAME,
                    data={CONF_API_KEY: token},
                )
        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=TOKEN_SCHEMA,
            errors=errors,
            description_placeholders={"name": name, "host": host},
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
