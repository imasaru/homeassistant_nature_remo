import logging

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NatureRemoCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """
    UI設定からロックエンティティを追加.
    Add lock entities from UI configuration.
    """
    _LOGGER.info("Nature Remo Lock: async_setup_entry called!")

    coordinator: NatureRemoCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    entities = []
    for lock_data in coordinator.locks.values():
        entity = NatureRemoQrioLock(
            coordinator=coordinator,
            lock_data=lock_data,
            device=lock_data["device"],
        )
        entities.append(entity)

    if not entities:
        _LOGGER.debug("No Qrio Lock appliances found.")

    async_add_entities(entities, True)


class NatureRemoQrioLock(LockEntity):
    """
    Nature Remo 経由の Qrio Lock を表すエンティティ.
    Representation of a Qrio Lock controlled via Nature Remo.
    """

    def __init__(self, coordinator, lock_data, device) -> None:
        """ロックエンティティの初期設定. / Initialize the lock entity."""
        self._coordinator = coordinator
        self._lock_data = lock_data
        self._device = device
        self._appliance_id = lock_data["appliance_id"]
        self._attr_unique_id = f"nature_remo_lock_{self._appliance_id}"
        self._attr_name = f"Nature Remo {lock_data['name']}"
        qrio_lock = lock_data.get("qrio_lock", {})
        self._is_available = qrio_lock.get("is_available", False)
        self._bd_address = lock_data.get("bd_address", "")
        self._lock_device = lock_data.get("lock_device", {})

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device["device_id"])},
            "name": self._lock_device.get("name", self._device["name"]),
            "manufacturer": "Qrio",
            "model": self._lock_device.get("name", "Qrio Lock"),
        }

    @property
    def available(self) -> bool:
        """Return True if the lock is available."""
        return self._is_available

    @property
    def is_locked(self):
        """Return None because lock state is not exposed by the public API."""
        return None

    @property
    def extra_state_attributes(self):
        """
        追加の状態属性を返す.
        Return extra state attributes.
        """
        return {
            "appliance_type": "QRIO_LOCK",
            "bd_address": self._bd_address,
            "qrio_lock_device_id": self._lock_device.get("id"),
            "qrio_lock_device_name": self._lock_device.get("name"),
        }

    async def async_added_to_hass(self):
        """
        エンティティがHome Assistantに追加されたら更新をトリガー.
        Trigger update when the entity is added to Home Assistant.
        """
        _LOGGER.info(
            f"[{self._attr_name}] async_added_to_hass: Lock entity complete setup"
        )
        self.async_on_remove(
            self._coordinator.async_add_listener(self._update_status)
        )
        self._update_status()
        self.async_write_ha_state()

    def _update_status(self) -> None:
        """
        コーディネーターで取得した値に状態を更新する.
        Update the lock state based on coordinator data.
        """
        _LOGGER.debug(f"[{self._attr_name}] Start _update_status.")
        lock_data = self._coordinator.locks.get(self._appliance_id)
        if lock_data:
            qrio_lock = lock_data.get("qrio_lock", {})
            self._is_available = qrio_lock.get("is_available", False)
            self._bd_address = lock_data.get("bd_address", "")
            self._lock_device = lock_data.get("lock_device", {})
        self.async_write_ha_state()

    async def async_lock(self, **kwargs) -> None:
        """Lock the device."""
        raise HomeAssistantError(
            "Lock control is not available via the public Nature API for this setup."
        )

    async def async_unlock(self, **kwargs) -> None:
        """Unlock the device."""
        raise HomeAssistantError(
            "Unlock control is not available via the public Nature API for this setup."
        )
