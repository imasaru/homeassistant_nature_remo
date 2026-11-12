"""Coordinator update success and failure (no network, no IR)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.nature_remo.api import NatureRemoAPI
from custom_components.nature_remo.coordinator import NatureRemoCoordinator

DEVICE_LIVING = {
    "id": "dev1",
    "name": "Living",
    "firmware_version": "Remo/1.0.0",
    "newest_events": {
        "te": {"val": 22.5},
        "hu": {"val": 40},
        "il": {"val": 12},
        "mo": {"created_at": "2026-11-12T15:00:00Z"},
    },
}
DEVICE_BEDROOM = {
    "id": "dev2",
    "name": "Bedroom",
    "firmware_version": "Remo/1.0.0",
    "newest_events": {"te": {"val": 20.0}},
}
DEVICE_HALL = {
    "id": "dev3",
    "name": "Hall",
    "firmware_version": "Remo/1.0.0",
    "newest_events": {"mo": {}},  # motion event without created_at
}


def _appliance(
    appliance_id: str,
    typ: str,
    name: str,
    signals: list[dict[str, str]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": appliance_id,
        "type": typ,
        "nickname": name,
        "device": {
            "id": "dev1",
            "name": "Living",
            "firmware_version": "Remo/1.0.0",
        },
        "signals": signals or [],
    }
    data.update(extra)
    return data


APPLIANCES = [
    _appliance("ac1", "AC", "Living AC", [{"name": "on", "id": "s-on"}]),
    _appliance("ac2", "AC", "Quiet AC"),
    _appliance("li1", "LIGHT", "Ceiling", [{"name": "off", "id": "s-off"}]),
    _appliance("li2", "LIGHT", "Lamp"),
    _appliance("ir1", "IR", "TV", [{"name": "on", "id": "s1"}]),
    _appliance("ir2", "IR", "Fan"),
    _appliance(
        "sm1",
        "EL_SMART_METER",
        "Meter",
        smart_meter={
            "echonetlite_properties": [
                {"epc": "211", "val": "1"},
                {"epc": "215", "val": "8"},
                {"epc": "224", "val": "10"},
                {"epc": "225", "val": "0"},
                {"epc": "227", "val": "2"},
                {"epc": "231", "val": "300"},
                {"epc": "999", "val": "x"},  # unknown + non-int val
            ]
        },
    ),
    _appliance("other", "UNKNOWN", "X"),
]


def _mock_api(devices: Any, appliances: Any) -> MagicMock:
    api = MagicMock()
    api.get_devices = AsyncMock(return_value=devices)
    api.get_appliances = AsyncMock(return_value=appliances)
    api.parse_smart_meter_properties = NatureRemoAPI("tok").parse_smart_meter_properties
    return api


async def test_coordinator_parses_devices_and_appliances(hass: HomeAssistant) -> None:
    coord = NatureRemoCoordinator(
        hass,
        _mock_api([DEVICE_LIVING, DEVICE_BEDROOM, DEVICE_HALL], APPLIANCES),
        60,
    )
    data = await coord._async_update_data()
    assert "ac1" in data
    assert coord.devices["dev1"]["name"] == "Living"
    assert "dev1" in coord.motion_sensors
    assert coord.motion_sensors["dev1"]["last_motion"] is not None
    assert "dev2" not in coord.motion_sensors
    assert "dev3" not in coord.motion_sensors
    assert "ac1" in coord.aircons and "ac1" in coord.ir_remotes
    assert "ac2" in coord.aircons and "ac2" not in coord.ir_remotes
    assert "li1" in coord.lights and "li1" in coord.ir_remotes
    assert "li2" in coord.lights and "li2" not in coord.ir_remotes
    assert "ir1" in coord.ir_remotes and "ir2" not in coord.ir_remotes
    meter = coord.smart_meters["sm1"]
    assert meter["buy_power"] == 10
    assert meter["sold_power"] == 2
    assert meter["current_power"] == 300


async def test_coordinator_none_payloads_are_empty(hass: HomeAssistant) -> None:
    coord = NatureRemoCoordinator(hass, _mock_api(None, None), 60)
    assert await coord._async_update_data() == {}
    assert coord.devices == {}
    assert coord.aircons == {}


@pytest.mark.parametrize(
    "exc",
    [ClientError("boom"), TimeoutError(), ValueError("bad json")],
)
async def test_coordinator_update_failures(
    hass: HomeAssistant, exc: BaseException
) -> None:
    api = MagicMock()
    api.get_devices = AsyncMock(side_effect=exc)
    coord = NatureRemoCoordinator(hass, api, 60)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


def test_parse_smart_meter_units_and_missing_values() -> None:
    api = NatureRemoAPI("tok")
    parsed = api.parse_smart_meter_properties(
        [
            {"epc": "211", "val": "10"},
            {"epc": "225", "val": "1"},  # 0.1
            {"epc": "224", "val": "5"},
            {"epc": None},
        ]
    )
    assert parsed["buy_power"] == pytest.approx(5.0)
    assert parsed["sold_power"] == 0
    assert parsed["instant_power"] == 0
