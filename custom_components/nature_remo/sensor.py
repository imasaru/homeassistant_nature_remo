from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo  # type: ignore[attr-defined]

from .coordinator import NatureRemoCoordinator
from .const import DOMAIN

PARALLEL_UPDATES = 0  # read-only, data comes from the coordinator


SENSOR_TYPES: dict[str, dict[str, Any]] = {
    "te": {
        "name": "Temperature",
        "unit": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    "hu": {
        "name": "Humidity",
        "unit": "%",
        "device_class": "humidity",
        "state_class": "measurement",
    },
    "il": {
        "name": "Illuminance",
        "unit": None,  # 単位は指定しない
        "device_class": "illuminance",
        "state_class": "measurement",
    },
    "buy_power": {
        "name": "Buy Power",
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
    },
    "sold_power": {
        "name": "Sold Power",
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
    },
    "current_power": {
        "name": "Current Power",
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
    },
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """
    インテグレーション初期化時に呼ばれるセットアップ関数
    Nature Remoから取得した情報を元にセンサーエンティティを追加する

    Called when the integration is initialized.
    Adds sensor entities based on information retrieved from Nature Remo.
    """
    coordinator: NatureRemoCoordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity | BinarySensorEntity] = []

    # 電気使用量センサー
    for appliance_id, data in coordinator.smart_meters.items():
        for key, desc in SENSOR_TYPES.items():
            if key in data:
                entities.append(
                    NatureRemoSensor(
                        coordinator,
                        appliance_id,
                        data["name"],
                        data["device"],
                        key,
                        desc,
                    )
                )

    # 温度、湿度、照度センサー
    for device_id, data in coordinator.devices.items():
        for key in ("te", "hu", "il"):
            if key in data["events"]:
                entities.append(
                    NatureRemoSensor(
                        coordinator,
                        device_id,
                        data["name"],
                        {
                            "device_id": data["device_id"],
                            "name": data["name"],
                            "firmware_version": data["firmware_version"],
                        },
                        key,
                        SENSOR_TYPES[key],
                    )
                )

    # モーションセンサー
    for device_id, data in coordinator.motion_sensors.items():
        # モーション検出センサー（ON/OFF）の追加
        entities.append(
            NatureRemoMotionBinarySensor(
                coordinator,
                device_id,
                data["name"],
                {
                    "device_id": data["device_id"],
                    "name": data["name"],
                    "firmware_version": data["firmware_version"],
                },
            )
        )
        # モーション検出センサー（検出時刻）の追加
        entities.append(
            NatureRemoMotionTimeSensor(
                coordinator,
                device_id,
                data["name"],
                {
                    "device_id": data["device_id"],
                    "name": data["name"],
                    "firmware_version": data["firmware_version"],
                },
            )
        )

    async_add_entities(entities)


class NatureRemoSensor(CoordinatorEntity[NatureRemoCoordinator], SensorEntity):
    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        name: str,
        device: dict[str, Any],
        key: str,
        description: dict[str, Any],
    ) -> None:
        """
        センサークラスの初期化
        Initialize a base sensor entity for Nature Remo.
        """
        super().__init__(coordinator)
        self._attr_unique_id = f"nature_remo_sensor_{appliance_id}_{key}"
        self._attr_name = f"Nature Remo {name} {description['name']}"
        self._device = device
        self._appliance_id = appliance_id
        self._attr_native_unit_of_measurement = description["unit"]
        self._attr_device_class = description["device_class"]
        self._attr_state_class = description["state_class"]
        self._key = key

    @property
    def device_info(self) -> DeviceInfo | None:
        """
        デバイス情報を返却する
        Return device info to be shown in Home Assistant UI.
        """
        return {
            "identifiers": {(DOMAIN, self._device["device_id"])},
            "name": self._device["name"],
            "manufacturer": "Nature",
            "model": self._device.get("firmware_version", "Nature Remo"),
        }

    @property
    def native_value(self) -> Any:
        """
        センサーの現在値を返却する
        Return the current value of the sensor.
        """
        if self._key in ("te", "hu", "il"):
            # 温度、湿度、照度
            return self.coordinator.devices[self._appliance_id]["events"][self._key][
                "val"
            ]

        # 電気使用量
        return self.coordinator.smart_meters[self._appliance_id][self._key]

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """
        センサーに追加の属性（Attributes）を付与する
        照度センサー（il）の場合、Nature Remoが返す0〜200の相対的な明るさスケールを補足情報として返す。

        Adds extra attributes to the sensor.
        For illuminance sensors ("il"), it returns supplemental info about Nature Remo's relative brightness scale (0–200).
        """
        attributes: dict[str, str] = {}

        if self._key == "il":
            attributes["raw_sensor_scale"] = "0-200"
            attributes["note"] = "This is a relative scale used by Nature Remo."

        return attributes


class NatureRemoMotionTimeSensor(CoordinatorEntity[NatureRemoCoordinator], SensorEntity):
    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        device_id: str,
        name: str,
        device: dict[str, Any],
    ) -> None:
        """
        モーション検出時刻センサーの初期化
        Initialize the motion detection timestamp sensor.
        """
        super().__init__(coordinator)
        self._device_id = device_id
        self._device = device
        self._attr_name = f"Nature Remo {name} Last Motion"
        self._attr_unique_id = f"{device_id}_last_motion"
        self._attr_device_class = None  # 時刻だから特に設定なし（UIで表示できる）
        self._attr_native_unit_of_measurement = None

    @property
    def device_info(self) -> DeviceInfo | None:
        """
        モーション検出時刻センサーのデバイス情報
        Return device info for the motion time sensor.
        """
        return {
            "identifiers": {(DOMAIN, self._device["device_id"])},
            "name": self._device["name"],
            "manufacturer": "Nature",
            "model": self._device.get("firmware_version", "Nature Remo"),
        }

    @property
    def native_value(self) -> str | None:
        """
        最新のモーション検出時刻をISO形式で返す
        Return the last motion detection timestamp in ISO format.
        """
        motion = self.coordinator.motion_sensors.get(self._device_id)
        last = motion.get("last_motion") if motion else None
        if isinstance(last, datetime):
            return last.isoformat()
        return None


class NatureRemoMotionBinarySensor(
    CoordinatorEntity[NatureRemoCoordinator], BinarySensorEntity
):
    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        device_id: str,
        name: str,
        device: dict[str, Any],
    ) -> None:
        """
        モーション検出センサーの初期化
        Initialize the binary motion sensor entity.
        """
        super().__init__(coordinator)
        self._device = device
        self._device_id = device_id
        self._attr_name = f"Nature Remo {name} Motion"
        self._attr_unique_id = f"{device_id}_motion"
        self._attr_device_class = BinarySensorDeviceClass.MOTION

    @property
    def device_info(self) -> DeviceInfo | None:
        """
        モーション検出センサーのデバイス情報
        Return device info for the motion sensor.
        """
        return {
            "identifiers": {(DOMAIN, self._device["device_id"])},
            "name": self._device["name"],
            "manufacturer": "Nature",
            "model": self._device.get("firmware_version", "Nature Remo"),
        }

    @property
    def is_on(self) -> bool:
        """
        最後にモーション検出してから5分以内の場合は「ON」を返す
        Return True if motion was detected within the last 5 minutes.
        """
        motion = self.coordinator.motion_sensors.get(self._device_id)
        last = motion.get("last_motion") if motion else None
        if isinstance(last, datetime):
            now = datetime.now(timezone.utc)
            return (now - last) < timedelta(minutes=5)
        return False
