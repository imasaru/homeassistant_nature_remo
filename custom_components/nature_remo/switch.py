"""Oshirase (お知らせ) toggle for locally controlled Fujitsu AR-RFF2J air conditioners.

One restored switch per climate appliance whose local protocol is AR-RFF2J. The
switch only stores the preference; the climate entity reads it when it builds the
next local IR frame (footer bit 0x40). Cloud sends are unaffected (Nature's
prebuilt signals always have oshirase OFF). Default: OFF.
"""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, LOCAL_PROTOCOL_FUJITSU_ARRFF2J, LOCAL_PROTOCOL_NONE, OPT_LOCAL_PROTOCOL

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0  # local toggle, no device I/O


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    store = entry.runtime_data.oshirase
    entities = []
    for appliance in coordinator.aircons.values():
        proto = entry.options.get(
            OPT_LOCAL_PROTOCOL.format(appliance_id=appliance["appliance_id"]), LOCAL_PROTOCOL_NONE
        )
        if proto == LOCAL_PROTOCOL_FUJITSU_ARRFF2J:
            entities.append(OshiraseSwitch(store, appliance))
    async_add_entities(entities)


class OshiraseSwitch(SwitchEntity, RestoreEntity):
    _attr_icon = "mdi:bell-ring-outline"
    _attr_should_poll = False

    def __init__(self, store: dict, appliance: dict) -> None:
        self._store = store
        self._appliance_id = appliance["appliance_id"]
        self._attr_unique_id = f"nature_remo_oshirase_{self._appliance_id}"
        # -> switch.<appliance>_oshirase, e.g. switch.living_room_fujitsu_oshirase
        self._attr_name = f"{appliance['name']} Oshirase"
        self._store.setdefault(self._appliance_id, False)
        device = appliance.get("device") or {}
        self._device_id = device.get("device_id")

    @property
    def device_info(self):
        if not self._device_id:
            return None
        return {"identifiers": {(DOMAIN, self._device_id)}}  # same device as the climate

    @property
    def is_on(self) -> bool:
        return bool(self._store.get(self._appliance_id, False))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._store[self._appliance_id] = last is not None and last.state == STATE_ON
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        self._store[self._appliance_id] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._store[self._appliance_id] = False
        self.async_write_ha_state()
