from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import NatureRemoAPI
from .const import DOMAIN
from .coordinator import NatureRemoCoordinator

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1  # one cloud command at a time per platform

ON_COMMANDS = ["on", "オン"]
OFF_COMMANDS = ["off", "オフ"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nature Remoのリモートエンティティを初期化する. / Set up remote entities for Nature Remo (IR Remotes)."""
    coordinator: NatureRemoCoordinator = entry.runtime_data.coordinator
    api: NatureRemoAPI = entry.runtime_data.api

    entities = [
        NatureRemoRemoteEntity(
            coordinator=coordinator, api=api, remote_info=remote_info
        )
        for remote_info in coordinator.ir_remotes.values()
    ]

    async_add_entities(entities)


class NatureRemoRemoteEntity(CoordinatorEntity[NatureRemoCoordinator], RemoteEntity):
    """
    Nature Remo の赤外線リモコンを表すRemoteEntityクラス.
    Representation of a Nature Remo IR Remote as a RemoteEntity.
    """

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        api: NatureRemoAPI,
        remote_info: dict[str, Any],
    ) -> None:
        """リモートエンティティを初期化. / Initialize the remote entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"nature_remo_remote_{remote_info['appliance_id']}"
        self._attr_name = f"Nature Remo {remote_info["name"]}"
        self._coordinator = coordinator
        self._api = api
        self._device = remote_info["device"]
        self._appliance_id = remote_info["appliance_id"]
        self._remote_info = remote_info
        self._commands = {s["name"].lower(): s["id"] for s in remote_info["signals"]}

        self._attr_state = "off"
        # コマンド候補を保存
        self._power_on_id = next(
            (self._commands[c] for c in ON_COMMANDS if c in self._commands), None
        )
        self._power_off_id = next(
            (self._commands[c] for c in OFF_COMMANDS if c in self._commands), None
        )

    @property
    def device_info(self):
        """
        Home Assistantのデバイス一覧に表示するための基本情報を返す.
        Returns basic device info for display in Home Assistant's device registry.
        """
        return {
            "identifiers": {(DOMAIN, self._device["device_id"])},
            "name": self._device["name"],
            "manufacturer": "Nature",
            "model": self._device.get("firmware_version", "Nature Remo"),
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """このエンティティの追加属性を返却する. / Return extra attributes for this entity."""
        return {
            "available_commands": list(self._commands.keys()),
            "command": self._attr_state,
        }

    @property
    def available(self) -> bool:
        """このエンティティが利用可能かどうかを返却する. / Return whether this entity is available."""
        return super().available and bool(self._commands)

    @property
    def state(self) -> str | None:
        """現在の状態（最後に送信されたコマンド）を返却する. / Return the current state (last command sent)."""
        return self._attr_state

    async def async_send_command(self, command: str | list[str], **kwargs: Any) -> None:
        """指定されたコマンドをリモコンに送信します。 / Send a command to the remote."""
        if isinstance(command, str):
            command = [command]

        for cmd in command:
            normalized_cmd = cmd.lower()
            signal_id = self._commands.get(normalized_cmd)
            if not signal_id:
                _LOGGER.warning("Unknown command: %s", cmd)
                continue

            await self.coordinator.api.send_command_signal(signal_id)

            if normalized_cmd in ON_COMMANDS:
                self._attr_state = "on"
            elif normalized_cmd in OFF_COMMANDS:
                self._attr_state = "off"
            else:
                self._attr_state = cmd
            self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """turn_on サービス呼び出し時の処理 / Handle the turn_on service call."""
        if self._power_on_id:
            await self.coordinator.api.send_command_signal(self._power_on_id)
            self._attr_state = "on"
            self.async_write_ha_state()
        else:
            _LOGGER.debug(f"Power ON command not available for {self.name}")
            raise HomeAssistantError(f"Power ON command not available for {self.name}")

    async def async_turn_off(self) -> None:
        """turn_off サービス呼び出し時の処理. / Handle the turn_off service call."""
        if self._power_off_id:
            await self.coordinator.api.send_command_signal(self._power_off_id)
            self._attr_state = "off"
            self.async_write_ha_state()
        else:
            _LOGGER.debug(f"Power OFF command not available for {self.name}")
            raise HomeAssistantError(f"Power OFF command not available for {self.name}")
