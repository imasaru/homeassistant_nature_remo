import logging
import voluptuous as vol
from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .coordinator import NatureRemoCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1  # one cloud command at a time per platform

CONF_TOKEN = "token"
CONF_NAME = "name"
CONF_DEVICE_ID = "device_id"
CONF_APPLIANCE_ID = "appliance_id"

PLATFORM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOKEN): cv.string,
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required(CONF_APPLIANCE_ID): cv.string,
    }
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """
    UI設定からライトエンティティを追加.
    Add light entity from UI configuration.
    """
    _LOGGER.info("Nature Remo Light: async_setup_entry called!")

    coordinator: NatureRemoCoordinator = entry.runtime_data.coordinator
    api = entry.runtime_data.api

    entities = []
    for appliance in coordinator.lights.values():
        entity = NatureRemoLight(
            coordinator=coordinator,
            appliance=appliance,
            device=appliance["device"],
            api=api,
        )
        entities.append(entity)

    if not entities:
        _LOGGER.warning("No light appliances matched selected IDs.")

    async_add_entities(entities, True)


class NatureRemoLight(LightEntity):
    """
    Nature Remo のライトデバイスを表すエンティティ.
    Representation of a Nature Remo light device.
    """

    def __init__(self, coordinator, appliance, device, api) -> None:
        """ライトエンティティの初期設定を行う. / Initialize the light entity."""
        self._attr_unique_id = f"nature_remo_light_{appliance['appliance_id']}"
        self._attr_name = f"Nature Remo {appliance['name']}"
        self._coordinator = coordinator  # コーディネーターを使う
        self._appliance = appliance
        self._device = device
        self._appliance_id = appliance["appliance_id"]
        self._attr_supported_color_modes = ColorMode.ONOFF
        self._is_on = False  # 照明のON/OFF状態
        self._last_mode = "on"  # 最後に指定した照明状態
        self._supported_effects = ["on", "off", "night"]

        self._api = api

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device["device_id"])},
            "name": self._device["name"],
            "manufacturer": "Nature",
            "model": self._device.get("firmware_version", "Nature Remo"),
        }

    @property
    def supported_color_modes(self):
        """ライトの種類を定義する. / Define the type or category of the light."""
        return self._attr_supported_color_modes

    @property
    def color_mode(self):
        return ColorMode.ONOFF

    @property
    def is_on(self):
        """ライトがONかOFFかを返す. / Return whether the light is ON or OFF."""
        return self._is_on

    @property
    def extra_state_attributes(self):
        """
        現在の照明モードを表すカスタム属性を返す.
        Returns a dictionary of custom attributes related to the current state.
        """
        return {"mode": self._last_mode}

    async def async_added_to_hass(self):
        """
        エンティティがHome Assistantに追加されたら更新をトリガー.
        Trigger update when the entity is added to Home Assistant.
        """
        _LOGGER.info(
            f"[{self._attr_name}] async_added_to_hass: Light entity complete setup"
        )
        self.async_on_remove(self._coordinator.async_add_listener(self.update_status))
        self.update_status()
        self.async_write_ha_state()  # 状態をHome Assistantに通知
        self._coordinator.entity_map[self.entity_id] = self
        entity_id = self.entity_id
        # Forget this light when it is removed, so the action cannot reach a
        # stale entity after an unload or rename.
        self.async_on_remove(
            lambda: self._coordinator.entity_map.pop(entity_id, None)
        )

    def update_status(self) -> None:
        """
        コーディネーターで取得した値に状態を更新する.
        Update the light state based on coordinator data.
        """
        _LOGGER.debug(f"[{self._attr_name}] Start update_status.")
        appliance = self._coordinator.data.get(self._appliance_id, {})

        if appliance and "light" in appliance:
            _LOGGER.info("Nature Remo Settings: %s", appliance["light"])

            # 現在の状態（ON/OFF）を取得
            state = appliance["light"]["state"]
            self._is_on = state["power"] == "on"
            # 最後に指定した照明状態を取得
            self._last_mode = state.get("last_button", "on")

            # 有効な効果を取得
            effect_buttons = appliance["light"].get("buttons", [])
            self._supported_effects = [btn["name"] for btn in effect_buttons]
            _LOGGER.debug(f"[{self._attr_name}]有効ボタン: {self._supported_effects}")

        # HomeAssistantへ状態を通知
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        """
        ライトをremo_light_modeで指定した状態でONにする.
        Turn on the light with a specified remo_light_mode.
        """
        _LOGGER.debug(f"kwargs: {kwargs}")
        mode = kwargs.get("remo_light_mode", "on")

        # サポートされていないlight_modeの場合はエラー
        if mode not in self._supported_effects:
            raise HomeAssistantError(f"Effect '{mode}' is not supported by this light")

        # NatureRemo APIへリクエスト送信
        response = await self._api.send_light_command(self._appliance_id, mode)
        _LOGGER.debug(f"[{self._attr_name}]send_light_command response: {response}")

        # 状態を更新
        self._is_on = mode != "off"
        self._last_mode = mode
        # HomeAssistantへ状態通知
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """ライトをOFFにする. / Turn off the light."""
        await self._api.send_light_command(self._appliance_id, "off")
        # 状態を更新
        self._is_on = False
        self._last_mode = "off"

        # HomeAssistantへ状態通知
        self.async_write_ha_state()
