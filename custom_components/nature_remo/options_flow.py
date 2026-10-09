import logging

from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

import voluptuous as vol

from .const import (
    DOMAIN,
    LOCAL_PROTOCOLS,
    LOCAL_PROTOCOL_NONE,
    OPT_LOCAL_POLL,
    OPT_LOCAL_PROTOCOL,
)

_LOGGER = logging.getLogger(__name__)


class NatureRemoOptionsFlowHandler(config_entries.OptionsFlow):
    """
    Nature Remo のオプション設定フローを定義する.
    Defines the options flow for Nature Remo integration.
    """

    async def async_step_init(self, user_input=None):

        device_registry = async_get_device_registry(self.hass)
        devices = [
            dev
            for dev in device_registry.devices.values()
            if dev.config_entries and self.config_entry.entry_id in dev.config_entries
        ]

        options = self.config_entry.options
        lang = self.hass.config.language

        if lang == "ja":
            interval_label = "更新間隔（秒）"
            ip_label_suffix = "：IPアドレス"
            ext_temp_label_suffix = "：外部温度センサー"
            ext_humidity_label_suffix = "：外部湿度センサー"
            local_poll_label_suffix = "：ローカルAPIでリモコン操作を検知（/messagesをポーリング）"
            local_protocol_label_suffix = "：ローカルIRプロトコル（none=クラウド）"
        else:
            interval_label = "Update Interval (seconds)"
            ip_label_suffix = ": IP Address"
            ext_temp_label_suffix = ": External Temperature Sensor"
            ext_humidity_label_suffix = ": External Humidity Sensor"
            local_poll_label_suffix = ": Detect remote presses via local API (poll /messages)"
            local_protocol_label_suffix = ": Local IR protocol (none = cloud)"

        # ラベル → optionsキー のマッピング
        # label → options key mapping
        special_key_map = {interval_label: "update_interval"}
        label_key_map = {}

        interval_default = options.get("update_interval", 60)
        data_schema = {
            vol.Optional(interval_label, default=interval_default): vol.In(
                [30, 60, 90]
            ),
        }

        for device in devices:
            name = device.name_by_user or device.name or "Unknown Device"

            # [案B] HAの内部device_idではなく、Nature RemoのdeviceID（identifiers）を使用する
            # Use Nature Remo device ID from identifiers instead of HA internal device ID
            nature_remo_device_id = next(
                (identifier_id for domain, identifier_id in device.identifiers if domain == DOMAIN),
                None,
            )

            if nature_remo_device_id is None:
                _LOGGER.warning(
                    f"デバイス '{name}' のNature Remo device IDが見つかりません。スキップします。"
                    f" / Nature Remo device ID not found for device '{name}'. Skipping."
                )
                continue

            _LOGGER.debug(
                f"デバイス '{name}' のNature Remo device ID: {nature_remo_device_id}"
                f" / Nature Remo device ID for '{name}': {nature_remo_device_id}"
            )

            # デバイスごとのIPアドレス設定
            # IP address setting per device (using HA internal ID as before)
            ip_label = f"{name} {ip_label_suffix}"
            ip_key = device.id  # IPアドレスはHA内部IDのままでよい
            label_key_map[ip_label] = ip_key
            data_schema[
                vol.Optional(
                    ip_label,
                    default=options.get(ip_key, ""),
                )
            ] = str

            # デバイスごとの外部温度センサー
            # External temperature sensor per device
            ext_temp_label = f"{name} {ext_temp_label_suffix}"
            ext_temp_key = f"external_temperature_{nature_remo_device_id}"  # [案B] Nature Remo device IDを使用
            label_key_map[ext_temp_label] = ext_temp_key
            data_schema[
                vol.Optional(
                    ext_temp_label,
                    description={"suggested_value": options.get(ext_temp_key)},
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="temperature",
                    multiple=False,
                )
            )

            # デバイスごとの外部湿度センサー
            # External humidity sensor per device
            ext_humidity_label = f"{name} {ext_humidity_label_suffix}"
            ext_humidity_key = f"external_humidity_{nature_remo_device_id}"  # [案B] Nature Remo device IDを使用
            label_key_map[ext_humidity_label] = ext_humidity_key
            data_schema[
                vol.Optional(
                    ext_humidity_label,
                    description={"suggested_value": options.get(ext_humidity_key)},
                )
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="humidity",
                    multiple=False,
                )
            )

            # [local-api] デバイスごとのローカル受信ポーリング（既定OFF）
            # Per Remo device: poll GET /messages to pick up physical remote presses (default off)
            poll_label = f"{name} {local_poll_label_suffix}"
            poll_key = OPT_LOCAL_POLL.format(device_id=nature_remo_device_id)
            label_key_map[poll_label] = poll_key
            data_schema[
                vol.Optional(poll_label, default=bool(options.get(poll_key, False)))
            ] = bool

        # [local-api] エアコンごとのローカルIRプロトコル
        # Per AC appliance: local IR protocol used with the Remo local API
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
        coordinator = entry_data.get("coordinator")
        aircons = getattr(coordinator, "aircons", {}) if coordinator else {}
        for appliance_id, appliance in aircons.items():
            ac_name = appliance.get("name", appliance_id)
            proto_label = f"Nature Remo {ac_name} {local_protocol_label_suffix}"
            proto_key = OPT_LOCAL_PROTOCOL.format(appliance_id=appliance_id)
            label_key_map[proto_label] = proto_key
            data_schema[
                vol.Optional(
                    proto_label,
                    default=options.get(proto_key, LOCAL_PROTOCOL_NONE),
                )
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=LOCAL_PROTOCOLS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        if user_input is not None:
            result = {}

            for label, value in user_input.items():
                if label in special_key_map:
                    result[special_key_map[label]] = value
                elif label in label_key_map:
                    result[label_key_map[label]] = value

            lang = self.hass.config.language
            if lang == "ja":
                title = "再読み込みが必要です"
                message = "Nature Remoの統合を再読み込みしてください。"
            else:
                title = "Reload Required"
                message = "Please reload the Nature Remo integration to apply changes."

            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": title,
                    "message": message,
                    "notification_id": "nature_remo_reload_needed",
                },
                blocking=True,
            )

            return self.async_create_entry(title="", data=result)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(data_schema),
        )