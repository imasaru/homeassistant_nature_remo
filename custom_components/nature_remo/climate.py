import logging
import time
import voluptuous as vol
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.restore_state import RestoreEntity
from datetime import timedelta
from .coordinator import NatureRemoCoordinator
from .const import (
    DOMAIN,
    LOCAL_POLL_INTERVAL,
    LOCAL_PROTOCOL_FUJITSU_ARRFF2J,
    LOCAL_PROTOCOL_NONE,
    OPT_LOCAL_POLL,
    OPT_LOCAL_PROTOCOL,
)
from .local_api import NatureRemoLocalAPI, NatureRemoLocalError
from .ir import fujitsu_arrff2j as fujitsu

_LOGGER = logging.getLogger(__name__)

CONF_TOKEN = "token"
CONF_NAME = "name"
CONF_DEVICE_ID = "device_id"
CONF_APPLIANCE_ID = "appliance_id"

MODE_MAP = {
    HVACMode.COOL: "cool",
    HVACMode.HEAT: "warm",
    HVACMode.DRY: "dry",
    HVACMode.FAN_ONLY: "blow",
    HVACMode.AUTO: "auto",
}

# [local-api] modes the AR-RFF2J encoder can express (fan_only is not encodable)
LOCAL_HVAC_MODES = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.DRY, HVACMode.AUTO]
HVAC_TO_FUJITSU = {
    HVACMode.COOL: fujitsu.MODE_COOL,
    HVACMode.HEAT: fujitsu.MODE_HEAT,
    HVACMode.DRY: fujitsu.MODE_DRY,
    HVACMode.AUTO: fujitsu.MODE_AUTO,
}
FUJITSU_TO_HVAC = {v: k for k, v in HVAC_TO_FUJITSU.items()}
# fan levels (lowest -> highest) by number of non-auto fan names
FAN_LEVELS = {
    1: ["medium"],
    2: ["low", "high"],
    3: ["low", "medium", "high"],
    4: ["low", "med_low", "medium", "high"],
}
DEFAULT_LOCAL_FAN_NAMES = ["1", "2", "3", "4", "auto"]
DEFAULT_LOCAL_SWING_NAMES = ["still", "swing"]
# ignore cloud AC settings for this long after a local send
LOCAL_CLOUD_HOLD_SECONDS = 60

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
    UI設定からエアコンエンティティを追加.
    Add air conditioner entity from UI configuration.
    """
    _LOGGER.info("Nature Remo Climate: async_setup_entry called!")
    _LOGGER.debug(f"★[Climate]{hass.data[DOMAIN][entry.entry_id]}")
    _LOGGER.debug(f"config_entry.options: {entry.options}")

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: NatureRemoCoordinator = data["coordinator"]
    api = data["api"]

    entities = []
    session = async_get_clientsession(hass)
    device_registry = dr.async_get(hass)

    for appliance in coordinator.aircons.values():
        remo_device_id = appliance["device"]["device_id"]
        local_protocol = entry.options.get(
            OPT_LOCAL_PROTOCOL.format(appliance_id=appliance["appliance_id"]),
            LOCAL_PROTOCOL_NONE,
        )
        local_api = None
        if local_protocol != LOCAL_PROTOCOL_NONE:
            host = _local_host_for_device(device_registry, entry, remo_device_id)
            if host:
                local_api = NatureRemoLocalAPI(session, host)
            else:
                _LOGGER.warning(
                    "[%s] local protocol %s selected but no IP address configured for its Remo"
                    " device; using the cloud API",
                    appliance["name"],
                    local_protocol,
                )
                local_protocol = LOCAL_PROTOCOL_NONE

        entity = NatureRemoClimate(
            coordinator=coordinator,
            appliance=appliance,
            device=appliance["device"],
            api=api,
            entry_id=entry.entry_id,  # [Issue#4] entry_idのみ保持してoptionsにアクセスする
            local_protocol=local_protocol,
            local_api=local_api,
        )
        entities.append(entity)

    if not entities:
        _LOGGER.warning("No climate appliances matched selected IDs.")

    async_add_entities(entities, True)

    # [local-api] optional poller: GET /messages and apply decoded remote presses
    by_device: dict[str, list[NatureRemoClimate]] = {}
    for entity in entities:
        if entity.local_api is not None:
            by_device.setdefault(entity.remo_device_id, []).append(entity)
    for remo_device_id, dev_entities in by_device.items():
        if not entry.options.get(OPT_LOCAL_POLL.format(device_id=remo_device_id), False):
            continue
        poller = LocalMessagePoller(hass, dev_entities[0].local_api, dev_entities)
        entry.async_on_unload(
            async_track_time_interval(
                hass, poller.async_poll, timedelta(seconds=LOCAL_POLL_INTERVAL)
            )
        )
        _LOGGER.info(
            "Local /messages polling enabled for Remo %s (%s)",
            remo_device_id,
            dev_entities[0].local_api.host,
        )


def _local_host_for_device(device_registry, entry: ConfigEntry, remo_device_id: str) -> str | None:
    """The existing per-device "IP Address" option is keyed by the HA device registry id."""
    device = device_registry.async_get_device(identifiers={(DOMAIN, remo_device_id)})
    if device is None:
        return None
    host = (entry.options.get(device.id) or "").strip()
    return host or None


class LocalMessagePoller:
    """Polls GET /messages and forwards newly received Fujitsu frames.

    The Remo keeps only the LAST received IR signal, with no timestamp; a new
    press is detected when the returned signal differs from the previous poll.
    The first read is only a baseline (it may be an old signal).
    """

    def __init__(self, hass, local_api: NatureRemoLocalAPI, entities) -> None:
        self._hass = hass
        self._api = local_api
        self._entities = entities
        self._last_raw = None
        self._baseline_done = False
        self._busy = False
        self._error_logged = False

    async def async_poll(self, _now=None) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            try:
                signal = await self._api.get_last_signal()
            except NatureRemoLocalError as err:
                if not self._error_logged:
                    _LOGGER.warning("Local /messages poll failed (%s): %s", self._api.host, err)
                    self._error_logged = True
                return
            self._error_logged = False
            raw = tuple(signal.get("data", [])) if isinstance(signal, dict) else None
            if not self._baseline_done:
                self._baseline_done = True
                self._last_raw = raw
                return
            if raw == self._last_raw or not raw:
                return
            self._last_raw = raw
            fujitsu_entities = [
                e for e in self._entities if e.local_protocol == LOCAL_PROTOCOL_FUJITSU_ARRFF2J
            ]
            if not fujitsu_entities:
                return
            state = fujitsu.decode_remo_signal(signal)
            if state is None:
                _LOGGER.debug("Local IR signal received but not a valid AR-RFF2J frame")
                return
            if len(fujitsu_entities) > 1:
                _LOGGER.warning(
                    "AR-RFF2J frame received but %d ACs on this Remo use that protocol;"
                    " cannot tell which one it was for. Ignoring.",
                    len(fujitsu_entities),
                )
                return
            fujitsu_entities[0].apply_remote_ir_state(state)
        finally:
            self._busy = False


class NatureRemoClimate(ClimateEntity, RestoreEntity):
    """
    Nature Remoでエアコンを操作するエンティティ.
    Entity to control an air conditioner via Nature Remo.
    """

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance,
        device,
        api,
        entry_id: str = None,  # [Issue#4] entry_idのみ受け取る（hassはself.hassで参照）
        local_protocol: str = LOCAL_PROTOCOL_NONE,
        local_api: NatureRemoLocalAPI | None = None,
    ) -> None:
        """エアコンの初期設定. / Initialize air conditioner settings."""
        _LOGGER.debug(f'[{appliance["name"]}]Start __init__')
        try:
            self._attr_unique_id = f"nature_remo_climate_{appliance['appliance_id']}"
            self._attr_name = f"Nature Remo {appliance['name']}"
            self._coordinator = coordinator
            self._appliance = appliance
            self._device = device
            self._appliance_id = appliance["appliance_id"]
            self._temperature = None
            self._humidity = None
            self._hvac_modes = [HVACMode.OFF]
            self._hvac_mode = HVACMode.OFF
            self._button = "power-off"
            self._api = api
            self._target_temperature = 25
            self._fan_mode = "auto"
            self._swing_mode = "auto"
            self._aircon_range_modes = {}

            # [Issue#4] entry_idを保持（optionsはself.hassから都度取得する）
            # self.hassはasync_added_to_hass()以降にHAフレームワークが自動セットする
            self._entry_id = entry_id

            # [local-api] ローカルIR送信の設定と楽観的状態管理
            self.local_protocol = local_protocol
            self.local_api = local_api
            self.remo_device_id = device.get("device_id", "")
            self._last_command_path: str | None = None
            self._last_local_error: str | None = None
            self._last_local_send: float | None = None  # monotonic
            self._last_remote_ir: str | None = None
            self._cloud_settings_seen: str | None = None
            self._has_local_state = False

        except Exception as e:
            _LOGGER.error(f"Error initializing NatureRemoClimate: {e}")

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device["device_id"])},
            "name": self._device["name"],
            "manufacturer": "Nature",
            "model": self._device.get("firmware_version", "Nature Remo"),
        }

    @property
    def supported_features(self) -> int:
        """対応している機能を定義. / Define the features supported by this entity."""
        _LOGGER.debug(f"[{self._attr_name}] Start supported_features")
        support_feature = ClimateEntityFeature(0)
        if self.is_local:
            support_feature = (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.FAN_MODE
                | ClimateEntityFeature.SWING_MODE
                | ClimateEntityFeature.TURN_ON
                | ClimateEntityFeature.TURN_OFF
            )
            return support_feature
        if self.min_temp != 0.0 and self.max_temp != 0.0:
            support_feature = support_feature | ClimateEntityFeature.TARGET_TEMPERATURE
        if self.fan_modes:
            support_feature = support_feature | ClimateEntityFeature.FAN_MODE
        if self.swing_modes:
            support_feature = support_feature | ClimateEntityFeature.SWING_MODE

        _LOGGER.info(f"Nature Remo Climate support_feature: {support_feature}")
        return support_feature

    @property
    def target_temperature_step(self) -> float:
        """温度変更の刻み幅を設定. / Set the step size for temperature adjustment."""
        _LOGGER.debug(f"[{self._attr_name}] Start target_temperature_step")
        if self.is_local:
            return fujitsu.TEMP_STEP
        remo_mode = MODE_MAP.get(self._hvac_mode)
        temp_list = self._aircon_range_modes.get(remo_mode, {}).get("temp", [])
        temp_list = list(map(float, filter(None, temp_list)))

        if not temp_list:
            return 0.0

        differences = [
            temp_list[i + 1] - temp_list[i] for i in range(len(temp_list) - 1)
        ]

        step = 1.0
        if len(set(differences)) == 1:
            step = differences[0]
        _LOGGER.debug(f"target_temperature_step: {step}")
        return step

    @property
    def min_temp(self):
        """設定可能な最低温度. / Return the minimum temperature that can be set."""
        _LOGGER.debug(f"[{self._attr_name}] Start min_temp")
        if self.is_local:
            return fujitsu.COOL_MIN if self._hvac_mode == HVACMode.COOL else fujitsu.TEMP_MIN
        remo_mode = MODE_MAP.get(self._hvac_mode)
        temp_list = self._aircon_range_modes.get(remo_mode, {}).get("temp", [])
        temp_list = list(map(float, filter(None, temp_list)))
        if not temp_list:
            return 0.0

        _LOGGER.debug(f"min_temp: {min(temp_list)}")
        return min(temp_list)

    @property
    def max_temp(self):
        """設定可能な最高温度. / Return the maximum temperature that can be set."""
        if self.is_local:
            return fujitsu.TEMP_MAX
        remo_mode = MODE_MAP.get(self._hvac_mode)
        temp_list = self._aircon_range_modes.get(remo_mode, {}).get("temp", [])
        temp_list = list(map(float, filter(None, temp_list)))
        if not temp_list:
            return 0.0

        _LOGGER.debug(f"max_temp: {max(temp_list)}")
        return max(temp_list)

    @property
    def current_temperature(self) -> float | None:
        """現在の室温を返す / Return the current room temperature."""
        return self._temperature

    @property
    def current_humidity(self) -> int | None:
        """現在の湿度を返す / Return the current room humidity."""
        return self._humidity

    @property
    def name(self):
        """エアコンの表示名を返す. / Return the display name of the air conditioner."""
        return self._attr_name

    @property
    def temperature_unit(self) -> str:
        """温度の単位を取得. / Get the temperature unit used by the device."""
        return UnitOfTemperature.CELSIUS

    @property
    def hvac_mode(self):
        """現在の動作モード. / Current operation mode of the air conditioner."""
        if self._button == "power-off":
            return HVACMode.OFF
        return self._hvac_mode

    @property
    def hvac_modes(self):
        """サポートするモード. / List of supported HVAC modes."""
        if self.is_local:
            return LOCAL_HVAC_MODES
        return self._hvac_modes

    @property
    def fan_modes(self) -> list[str] | None:
        """設定可能な風量のリスト. / List of available fan modes."""
        if self.is_local:
            return self._local_fan_names()
        remo_mode = MODE_MAP.get(self._hvac_mode)
        return self._aircon_range_modes.get(remo_mode, {}).get("vol", [])

    @property
    def swing_modes(self) -> list[str] | None:
        """設定可能な風向きのリスト. / List of available swing modes."""
        if self.is_local:
            return self._local_swing_names()
        remo_mode = MODE_MAP.get(self._hvac_mode)
        return self._aircon_range_modes.get(remo_mode, {}).get("dir", [])

    @property
    def target_temperature(self) -> float | None:
        """現在の目標温度を取得. / Get the current target temperature."""
        return self._target_temperature

    @property
    def fan_mode(self) -> str | None:
        """現在の風量を返す. / Return the current fan mode."""
        return self._fan_mode

    @property
    def swing_mode(self) -> str | None:
        """現在の風向きを返す. / Return the current swing mode."""
        return self._swing_mode

    def _get_external_sensor_value(self, sensor_type: str) -> float | None:
        """
        [Issue#4] 外部センサーエンティティから値を取得する.
        Get value from external sensor entity if configured.

        Args:
            sensor_type: "temperature" または "humidity"
        Returns:
            外部センサーの値（未設定またはエラー時はNone）

        Note:
            self.hassはHAフレームワークがasync_added_to_hass()以降に自動セットする。
            __init__時点ではNoneのため、このメソッドはasync_added_to_hass()以降に呼ぶこと。
        """
        # [Issue#4] self.hassはHAフレームワークが自動セットするプロパティを使用
        if self.hass is None or self._entry_id is None:
            _LOGGER.debug(
                f"[{self._attr_name}] [{sensor_type}] self.hass={self.hass}, "
                f"self._entry_id={self._entry_id} → スキップ / skipped"
            )
            return None

        # [Issue#4] config_entriesからoptionsを都度取得（最新の設定を参照できる）
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            _LOGGER.warning(
                f"[{self._attr_name}] entry_id '{self._entry_id}' のConfigEntryが見つかりません。"
                f" / ConfigEntry not found for entry_id '{self._entry_id}'."
            )
            return None

        device_id = self._device["device_id"]
        option_key = f"external_{sensor_type}_{device_id}"
        entity_id = entry.options.get(option_key)

        _LOGGER.debug(
            f"[{self._attr_name}] [{sensor_type}] "
            f"device_id='{device_id}' / "
            f"option_key='{option_key}' / "
            f"entity_id='{entity_id}' / "
            f"options={entry.options}"
        )

        if not entity_id:
            _LOGGER.debug(
                f"[{self._attr_name}] [{sensor_type}] "
                f"外部センサー未設定のためNature Remoの値を使用 / "
                f"No external sensor configured, using Nature Remo value"
            )
            return None

        state = self.hass.states.get(entity_id)
        if state is None:
            # 起動直後は外部センサーがまだロードされていない場合があるため DEBUG に格下げ
            # Downgraded to DEBUG as sensor may not be loaded yet during startup
            _LOGGER.debug(
                f"[{self._attr_name}] 外部{sensor_type}センサー '{entity_id}' の状態が取得できません。"
                f"（起動直後の場合は一時的なものです）"
                f" / External {sensor_type} sensor '{entity_id}' state not found."
                f" (This may be temporary if HA has just started.)"
            )
            return None

        try:
            value = float(state.state)
            _LOGGER.debug(
                f"[{self._attr_name}] 外部{sensor_type}センサー '{entity_id}' から値を取得: {value}"
                f" / Got {sensor_type} value {value} from external sensor '{entity_id}'"
            )
            return value
        except (ValueError, TypeError):
            _LOGGER.warning(
                f"[{self._attr_name}] 外部{sensor_type}センサー '{entity_id}' の値が無効です: {state.state}"
                f" / Invalid {sensor_type} value from external sensor '{entity_id}': {state.state}"
            )
            return None

    def update_status(self) -> None:
        """
        コーディネーターで取得した値に更新する.
        Update values using the data from the coordinator.
        """
        _LOGGER.debug(f"[{self._attr_name}] Start update_status.")
        appliance = self._coordinator.data.get(self._appliance_id, {})

        # [Issue#4] 外部温度センサーが設定されていればそちらを優先して使用する
        # If external temperature sensor is configured, use it preferentially
        external_temperature = self._get_external_sensor_value("temperature")
        if external_temperature is not None:
            self._temperature = external_temperature
            _LOGGER.debug(
                f"[{self._attr_name}] 外部温度センサーから室温を取得: {self._temperature}℃"
                f" / Using external temperature sensor: {self._temperature}℃"
            )

        # [Issue#4] 外部湿度センサーが設定されていればそちらを優先して使用する
        # If external humidity sensor is configured, use it preferentially
        external_humidity = self._get_external_sensor_value("humidity")
        if external_humidity is not None:
            self._humidity = external_humidity
            _LOGGER.debug(
                f"[{self._attr_name}] 外部湿度センサーから湿度を取得: {self._humidity}%"
                f" / Using external humidity sensor: {self._humidity}%"
            )

        # 外部センサー未設定の場合はNature Remoデバイスの値を使用（従来通り）
        # Fall back to Nature Remo device sensor if external sensors are not configured
        device_id = self._device["device_id"]
        device_data = self._coordinator.devices.get(device_id)  # KeyError対策でgetを使用
        if device_data is None:
            _LOGGER.warning(
                f"[{self._attr_name}] デバイス '{device_id}' がcoordinatorのdevicesに見つかりません。"
                f" / Device '{device_id}' not found in coordinator devices."
            )
        else:
            device_events = device_data.get("events", {})
            # 外部温度センサー未設定の場合のみNature Remoの値を使用
            if external_temperature is None:
                if "te" in device_events:
                    self._temperature = device_events["te"].get("val")
                    _LOGGER.debug(
                        f"[{self._attr_name}] Nature Remoデバイスから室温を取得: {self._temperature}℃"
                        f" / Using Nature Remo device temperature: {self._temperature}℃"
                    )
            # 外部湿度センサー未設定の場合のみNature Remoの値を使用
            if external_humidity is None:
                if "hu" in device_events:
                    self._humidity = device_events["hu"].get("val")
                    _LOGGER.debug(
                        f"[{self._attr_name}] Nature Remoデバイスから湿度を取得: {self._humidity}%"
                        f" / Using Nature Remo device humidity: {self._humidity}%"
                    )

        # settingsから取得できる情報
        if appliance and "settings" in appliance and not self._accept_cloud_settings(
            appliance["settings"]
        ):
            _LOGGER.debug(
                f"[{self._attr_name}] local IR state is authoritative; ignoring cloud settings"
            )
        elif appliance and "settings" in appliance:
            _LOGGER.info("***Nature Remo Settings: %s", appliance["settings"])
            # 動作モード
            self._hvac_mode = self.get_remo_mode_to_hvac_mode(
                appliance["settings"].get("mode", "")
            )
            # ボタン（OFFボタン）
            self._button = appliance["settings"].get("button", "")

            # 目標温度
            temp = appliance["settings"].get("temp", "20.0")
            try:
                self._target_temperature = float(temp)
            except (ValueError, TypeError):
                self._target_temperature = 0.0

            # 風量
            self._fan_mode = appliance["settings"].get("vol", "auto")
            # 風向き
            self._swing_mode = appliance["settings"].get("dir", "auto")

        # aircon_range_mode
        if appliance and "aircon" in appliance:
            self._aircon_range_modes = (
                appliance["aircon"].get("range", {}).get("modes", {})
            )
            if self._aircon_range_modes:
                set_range_modes = [HVACMode.OFF]
                if self._aircon_range_modes.get("cool", {}):
                    set_range_modes.append(HVACMode.COOL)
                if self._aircon_range_modes.get("dry", {}):
                    set_range_modes.append(HVACMode.DRY)
                if self._aircon_range_modes.get("warm", {}):
                    set_range_modes.append(HVACMode.HEAT)
                if self._aircon_range_modes.get("blow", {}):
                    set_range_modes.append(HVACMode.FAN_ONLY)
                if self._aircon_range_modes.get("auto", {}):
                    set_range_modes.append(HVACMode.AUTO)
                self._hvac_modes = set_range_modes

        # イベントループ外（別スレッド）からも呼ばれる可能性があるため
        # schedule_update_ha_state()を使用する（スレッドセーフ）
        # async_write_ha_state() is not thread-safe; use schedule_update_ha_state() instead
        self.schedule_update_ha_state()

    def get_remo_mode_to_hvac_mode(self, remo_mode) -> HVACMode | None:
        """
        Nature Remoの動作モードをHomeAssistantの動作モードに変換する.
        Convert Nature Remo operation mode to Home Assistant HVAC mode.
        """
        return next(
            (key for key, value in MODE_MAP.items() if value == remo_mode),
            None,
        )

    def _get_external_sensor_entity_ids(self) -> list[str]:
        """
        [Issue#4 案B] 設定されている外部センサーのエンティティIDリストを返す.
        Return a list of configured external sensor entity IDs.
        """
        if self.hass is None or self._entry_id is None:
            return []

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return []

        device_id = self._device["device_id"]
        entity_ids = []

        for sensor_type in ("temperature", "humidity"):
            option_key = f"external_{sensor_type}_{device_id}"
            entity_id = entry.options.get(option_key)
            if entity_id:
                entity_ids.append(entity_id)

        return entity_ids

    def _on_external_sensor_state_changed(self, event) -> None:
        """
        [Issue#4 案B] 外部センサーの状態変化を検知したらupdate_statusを呼ぶ.
        Called when an external sensor state changes; triggers update_status.
        """
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")

        if new_state is None:
            _LOGGER.debug(
                f"[{self._attr_name}] 外部センサー '{entity_id}' の新しい状態がNullです。スキップ。"
                f" / New state of external sensor '{entity_id}' is None. Skipping."
            )
            return

        _LOGGER.debug(
            f"[{self._attr_name}] 外部センサー '{entity_id}' の状態が変化: {new_state.state}"
            f" / External sensor '{entity_id}' state changed: {new_state.state}"
        )
        self.update_status()

    async def async_added_to_hass(self):
        """
        エンティティがHome Assistantに追加されたら更新をトリガー.
        Trigger update when the entity is added to Home Assistant.

        Note:
            このメソッドが呼ばれた時点でself.hassがHAフレームワークによりセットされる。
            そのため_get_external_sensor_value()はここ以降で正しく動作する。
        """
        _LOGGER.info(
            f"[{self._attr_name}] async_added_to_hass: Climate entity complete setup"
        )
        # [local-api] 前回の楽観的状態を復元 / restore last optimistic state
        if self.is_local:
            await self._async_restore_local_state()

        # coordinatorの更新リスナー登録
        self.async_on_remove(self._coordinator.async_add_listener(self.update_status))

        # [Issue#4 案B] 外部センサーの状態変化を監視するリスナーを登録
        # Register state change listeners for external sensors
        external_entity_ids = self._get_external_sensor_entity_ids()
        if external_entity_ids:
            _LOGGER.debug(
                f"[{self._attr_name}] 外部センサーの状態変化監視を登録: {external_entity_ids}"
                f" / Registering state change listeners for: {external_entity_ids}"
            )
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    external_entity_ids,
                    self._on_external_sensor_state_changed,
                )
            )

        self.update_status()
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        """エアコンのモードを変更. / Change the operation mode of the air conditioner."""
        _LOGGER.info("Setting HVAC mode: %s", hvac_mode)
        if hvac_mode not in self.hvac_modes:
            _LOGGER.warning("Unsupported HVAC mode: %s", hvac_mode)
            return

        if self.is_local:
            await self._async_local_set(hvac_mode=hvac_mode)
            return

        if hvac_mode == HVACMode.OFF:
            payload = {"button": "power-off"}
            self._button = "power-off"
        else:
            operation_mode = MODE_MAP.get(hvac_mode)
            payload = {"operation_mode": operation_mode}
            self._button = ""
            self._hvac_mode = hvac_mode

        response = await self._api.send_command_climate(payload, self._appliance_id)
        _LOGGER.info("Set HVACMode: %s", response)
        self._hvac_mode = self.get_remo_mode_to_hvac_mode(response.get("mode", ""))
        if self._hvac_mode is HVACMode.FAN_ONLY:
            temp = "0.0"
        else:
            temp = response.get("temp", "25.0")
        self._target_temperature = float(temp)
        self._fan_mode = response.get("vol", "auto")
        self._swing_mode = response.get("dir", "auto")
        self._button = response.get("button", "")

        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """エアコンの温度を変更. / Change the temperature setting of the air conditioner."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if self.is_local:
            await self._async_local_set(
                hvac_mode=kwargs.get("hvac_mode"), temperature=temperature
            )
            return
        if temperature is None:
            _LOGGER.warning("温度が指定されていません！")
            return

        operation_mode = MODE_MAP.get(self._hvac_mode)
        if operation_mode is None:
            _LOGGER.error("Invalid HVAC mode: %s", self._hvac_mode)
            return

        _LOGGER.debug("Setting temperature to: %s", temperature)

        set_temperature = self.format_temperature(temperature)
        payload = {
            "operation_mode": operation_mode,
            "temperature": set_temperature,
        }

        await self._api.send_command_climate(payload, self._appliance_id)
        self._target_temperature = temperature
        self._button = ""
        self.async_write_ha_state()

    def format_temperature(self, value: float) -> str:
        if value.is_integer():
            return str(int(value))
        else:
            return str(value)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """風量を変更. / Change the fan mode."""
        if self.is_local:
            await self._async_local_set(fan_mode=fan_mode)
            return
        operation_mode = MODE_MAP.get(self._hvac_mode)
        if operation_mode is None:
            _LOGGER.error("Invalid HVAC mode: %s", self._hvac_mode)
            return

        payload = {
            "operation_mode": operation_mode,
            "air_volume": fan_mode,
        }

        await self._api.send_command_climate(payload, self._appliance_id)
        self._fan_mode = fan_mode
        self._button = ""
        self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """風向きを変更. / Change the swing mode."""
        if self.is_local:
            await self._async_local_set(swing_mode=swing_mode)
            return
        operation_mode = MODE_MAP.get(self._hvac_mode)
        if operation_mode is None:
            _LOGGER.error("Invalid HVAC mode: %s", self._hvac_mode)
            return

        payload = {
            "operation_mode": operation_mode,
            "air_direction": swing_mode,
        }

        await self._api.send_command_climate(payload, self._appliance_id)
        self._swing_mode = swing_mode
        self._button = ""
        self.async_write_ha_state()
    # ------------------------------------------------------------------ local API
    @property
    def is_local(self) -> bool:
        return self.local_api is not None and self.local_protocol != LOCAL_PROTOCOL_NONE

    @property
    def extra_state_attributes(self) -> dict:
        if not self.is_local:
            return {}
        return {
            "local_protocol": self.local_protocol,
            "local_host": self.local_api.host,
            "last_command_path": self._last_command_path,
            "last_local_error": self._last_local_error,
            "last_remote_ir": self._last_remote_ir,
        }

    def _cloud_names(self, key: str) -> list[str]:
        names: list[str] = []
        for mode_cfg in self._aircon_range_modes.values():
            for name in mode_cfg.get(key, []) or []:
                if name and name not in names:
                    names.append(name)
        return names

    def _local_fan_names(self) -> list[str]:
        names = self._cloud_names("vol")
        return names or list(DEFAULT_LOCAL_FAN_NAMES)

    def _local_swing_names(self) -> list[str]:
        names = self._cloud_names("dir")
        return names or list(DEFAULT_LOCAL_SWING_NAMES)

    def _fan_levels(self) -> tuple[list[str], list[str]]:
        """(non-auto fan names in ascending order, matching protocol levels)."""
        names = [n for n in self._local_fan_names() if n != "auto"]

        def sort_key(name: str):
            try:
                return (0, float(name))
            except ValueError:
                order = ["quiet", "low", "medium", "mid", "high", "powerful"]
                return (1, order.index(name) if name in order else 99)

        names.sort(key=sort_key)
        levels = FAN_LEVELS.get(len(names))
        if levels is None:  # more than 4 levels: spread over the 4 protocol levels
            levels = [FAN_LEVELS[4][min(3, i * 4 // max(1, len(names)))] for i in range(len(names))]
        return names, levels

    def _fan_to_protocol(self, name: str | None) -> str:
        if not name or name == "auto":
            return "auto"
        names, levels = self._fan_levels()
        if name in names:
            return levels[names.index(name)]
        return name if name in fujitsu.FAN_BYTES else "auto"

    def _fan_from_protocol(self, fan: str) -> str:
        if fan == "auto":
            return "auto" if "auto" in self._local_fan_names() else self._local_fan_names()[0]
        names, levels = self._fan_levels()
        if fan in levels:
            return names[levels.index(fan)]
        return "auto"

    @staticmethod
    def _swing_to_protocol(name: str | None) -> str:
        if not name:
            return "off"
        if name in fujitsu.SWING_BYTES:
            return name
        # Nature names for this Fujitsu are "still"/"swing"; anything without
        # "swing" (incl. Nature's "auto" direction) is sent as swing off.
        return "vertical" if "swing" in name else "off"

    def _swing_from_protocol(self, swing: str) -> str:
        names = self._local_swing_names()
        if swing == "off":
            for cand in ("still", "off"):
                if cand in names:
                    return cand
            return names[0]
        for name in names:
            if "swing" in name:
                return name
        return names[-1]

    def _accept_cloud_settings(self, settings: dict) -> bool:
        """For local ACs only take cloud AC settings when they changed (e.g. the
        Nature app or a cloud fallback was used) and no local send happened in the
        last LOCAL_CLOUD_HOLD_SECONDS. The cloud never learns about local IR sends."""
        if not self.is_local:
            return True
        key = str(settings.get("updated_at") or sorted(settings.items()))
        first_seen = self._cloud_settings_seen is None
        changed = key != self._cloud_settings_seen
        self._cloud_settings_seen = key
        if not self._has_local_state:
            return True  # nothing better known yet
        if first_seen:
            # state was restored after a restart: the first cloud poll is only a
            # baseline (it is usually stale because local sends never reach the cloud)
            return False
        if not changed:
            return False
        if self._last_local_send is not None and (
            time.monotonic() - self._last_local_send < LOCAL_CLOUD_HOLD_SECONDS
        ):
            return False
        return True

    async def _async_restore_local_state(self) -> None:
        last = await self.async_get_last_state()
        if last is None or last.state in ("unknown", "unavailable", None):
            return
        try:
            mode = HVACMode(last.state)
        except ValueError:
            return
        attrs = last.attributes
        if mode == HVACMode.OFF:
            self._button = "power-off"
        else:
            self._button = ""
            self._hvac_mode = mode
        if attrs.get("temperature") is not None:
            self._target_temperature = float(attrs["temperature"])
        if attrs.get("fan_mode"):
            self._fan_mode = attrs["fan_mode"]
        if attrs.get("swing_mode"):
            self._swing_mode = attrs["swing_mode"]
        self._last_command_path = attrs.get("last_command_path")
        self._has_local_state = True
        _LOGGER.debug("[%s] restored local state %s %s", self._attr_name, mode, attrs.get("temperature"))

    async def async_turn_on(self) -> None:
        if not self.is_local:
            return await super().async_turn_on()
        mode = self._hvac_mode if self._hvac_mode in HVAC_TO_FUJITSU else HVACMode.COOL
        await self._async_local_set(hvac_mode=mode)

    async def async_turn_off(self) -> None:
        if not self.is_local:
            return await super().async_turn_off()
        await self._async_local_set(hvac_mode=HVACMode.OFF)

    async def _async_local_set(
        self,
        hvac_mode: HVACMode | None = None,
        temperature: float | None = None,
        fan_mode: str | None = None,
        swing_mode: str | None = None,
    ) -> None:
        """Compute the full desired state, send it as one AR-RFF2J frame via the
        Remo local API, fall back to the cloud on failure."""
        was_off = self.hvac_mode == HVACMode.OFF
        new_mode = hvac_mode if hvac_mode is not None else self.hvac_mode
        if new_mode not in LOCAL_HVAC_MODES:
            _LOGGER.warning("[%s] mode %s cannot be sent locally", self._attr_name, new_mode)
            return
        new_temp = self._target_temperature
        if temperature is not None:
            new_temp = round(float(temperature) * 2) / 2
        if new_temp is not None and new_mode != HVACMode.OFF:
            low = fujitsu.COOL_MIN if new_mode == HVACMode.COOL else fujitsu.TEMP_MIN
            new_temp = min(max(float(new_temp), low), fujitsu.TEMP_MAX)
        new_fan = fan_mode if fan_mode is not None else self._fan_mode
        new_swing = swing_mode if swing_mode is not None else self._swing_mode

        if new_mode == HVACMode.OFF:
            if was_off and hvac_mode is None:
                # AC is off and only temp/fan/swing changed: remember, don't turn it on
                self._target_temperature = new_temp
                self._fan_mode = new_fan
                self._swing_mode = new_swing
                self._has_local_state = True
                self.async_write_ha_state()
                return
            state = fujitsu.FujitsuState(mode=fujitsu.MODE_OFF)
            cloud_payload = {"button": "power-off"}
        else:
            proto_mode = HVAC_TO_FUJITSU[new_mode]
            state = fujitsu.FujitsuState(
                mode=proto_mode,
                temperature=new_temp,
                fan=self._fan_to_protocol(new_fan),
                swing=self._swing_to_protocol(new_swing),
                power_on=was_off,  # power-on bit only when turning on from off
            )
            cloud_payload = {"operation_mode": MODE_MAP[new_mode], "button": ""}
            if new_mode != HVACMode.DRY and new_temp is not None:
                cloud_payload["temperature"] = self.format_temperature(float(new_temp))
            if fan_mode is not None:
                cloud_payload["air_volume"] = new_fan
            if swing_mode is not None:
                cloud_payload["air_direction"] = new_swing

        signal = fujitsu.build_signal(state)
        try:
            await self.local_api.send_signal(signal)
            self._last_command_path = "local"
            self._last_local_error = None
            self._last_local_send = time.monotonic()
            _LOGGER.info(
                "[%s] sent locally via %s: %s",
                self._attr_name,
                self.local_api.host,
                " ".join(f"{b:02X}" for b in fujitsu.encode_state(state)),
            )
        except NatureRemoLocalError as err:
            self._last_local_error = str(err)
            _LOGGER.warning(
                "[%s] local send to %s failed (%s); falling back to cloud API",
                self._attr_name,
                self.local_api.host,
                err,
            )
            await self._api.send_command_climate(cloud_payload, self._appliance_id)
            self._last_command_path = "cloud"

        # optimistic state
        if new_mode == HVACMode.OFF:
            self._button = "power-off"
        else:
            self._button = ""
            self._hvac_mode = new_mode
        self._target_temperature = new_temp
        self._fan_mode = new_fan
        self._swing_mode = new_swing
        self._has_local_state = True
        self.async_write_ha_state()

    def apply_remote_ir_state(self, state: "fujitsu.FujitsuState") -> None:
        """Apply a frame decoded from GET /messages (physical remote press)."""
        if state.special:  # e.g. high-power toggle: no state change we can model
            self._last_remote_ir = state.special
            self.async_write_ha_state()
            return
        if state.mode == fujitsu.MODE_OFF:
            self._button = "power-off"
        else:
            self._button = ""
            self._hvac_mode = FUJITSU_TO_HVAC.get(state.mode, self._hvac_mode)
            if state.temperature is not None:
                self._target_temperature = state.temperature
            if state.mode != fujitsu.MODE_DRY:
                self._fan_mode = self._fan_from_protocol(state.fan)
                self._swing_mode = self._swing_from_protocol(state.swing)
        self._last_remote_ir = " ".join(f"{b:02X}" for b in state.raw)
        self._last_command_path = "remote_ir"
        self._has_local_state = True
        self._last_local_send = time.monotonic()
        _LOGGER.info("[%s] state updated from received IR: %s", self._attr_name, state)
        self.async_write_ha_state()
