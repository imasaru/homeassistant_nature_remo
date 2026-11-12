"""The Nature Remo integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    NatureRemoAPI,
    NatureRemoAuthError,
    NatureRemoConnectionError,
    async_get_user,
)
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN
from .coordinator import NatureRemoCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["climate", "light", "sensor", "remote", "lock"]


@dataclass
class NatureRemoRuntimeData:
    """Objects shared by the platforms of one config entry."""

    api: NatureRemoAPI
    coordinator: NatureRemoCoordinator


type NatureRemoConfigEntry = ConfigEntry[NatureRemoRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: NatureRemoConfigEntry) -> bool:
    """Set up Nature Remo from a config entry.

    The token is checked first so a revoked token starts re-authentication
    and an unreachable cloud makes Home Assistant retry later.
    """
    token: str = entry.data[CONF_API_KEY]
    try:
        user = await async_get_user(async_get_clientsession(hass), token)
    except NatureRemoAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="invalid_auth"
        ) from err
    except NatureRemoConnectionError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="cannot_connect"
        ) from err

    # Migration: entries created before 0.4.0 have no unique id. Adopt the
    # Nature account id so the account cannot be added twice. Entity unique
    # ids are not touched.
    user_id = str(user.get("id") or "")
    if entry.unique_id is None and user_id:
        taken = any(
            other.unique_id == user_id
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.entry_id != entry.entry_id
        )
        if not taken:
            hass.config_entries.async_update_entry(entry, unique_id=user_id)

    api = NatureRemoAPI(token)
    update_interval = entry.options.get("update_interval", DEFAULT_UPDATE_INTERVAL)
    coordinator = NatureRemoCoordinator(hass, api, update_interval)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = NatureRemoRuntimeData(api=api, coordinator=coordinator)
    # Platforms and the options flow still read hass.data; kept for now.
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
    }

    async def handle_send_light_mode(call: ServiceCall) -> dict[str, str]:
        """Send a light mode (on, off, night, ...) to a Nature Remo light."""
        entity_id = call.data.get("entity_id")
        mode = call.data.get("mode", "on")

        light_entity = coordinator.entity_map.get(entity_id)
        if light_entity is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entity_not_found",
                translation_placeholders={"entity_id": str(entity_id)},
            )
        if mode not in light_entity._supported_effects:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_mode",
                translation_placeholders={"mode": str(mode)},
            )

        await api.send_light_command(light_entity._appliance_id, mode)

        light_entity._last_mode = mode
        light_entity._is_on = mode != "off"
        light_entity.async_write_ha_state()

        return {"status": "success", "appliance_id": light_entity._appliance_id}

    hass.services.async_register(
        DOMAIN, "send_light_mode", handle_send_light_mode, supports_response=True
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NatureRemoConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
