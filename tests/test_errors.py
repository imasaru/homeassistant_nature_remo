"""Setup auth/cloud failures already covered in test_config_flow; this file
adds diagnostics with a live coordinator and options-flow coverage."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.const import DOMAIN
from custom_components.nature_remo.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .test_coordinator import APPLIANCES, DEVICE_LIVING

SETUP_GET_USER = "custom_components.nature_remo.async_get_user"
USER = {"id": "user-123", "nickname": "Home"}


def _schema_labels(schema) -> list[str]:
    labels: list[str] = []
    for key in schema.schema:
        labels.append(key.schema if hasattr(key, "schema") else str(key))
    return labels


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user-123",
        data={CONF_API_KEY: "tok"},
        options={"update_interval": 60},
    )
    entry.add_to_hass(hass)
    with (
        patch(SETUP_GET_USER, return_value=USER),
        patch(
            "custom_components.nature_remo.api.NatureRemoAPI.get_devices",
            return_value=[DEVICE_LIVING],
        ),
        patch(
            "custom_components.nature_remo.api.NatureRemoAPI.get_appliances",
            return_value=APPLIANCES,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_diagnostics_redacts_coordinator_secrets(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)
    entry.runtime_data.coordinator.devices["dev1"]["mac_address"] = "aa:bb:cc:dd:ee:ff"
    entry.runtime_data.coordinator.devices["dev1"]["serial_number"] = "SN-SECRET"
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    assert "tok" not in text
    assert "aa:bb:cc:dd:ee:ff" not in text
    assert "SN-SECRET" not in text
    assert "Living" in str(diag["coordinator"]["devices"])
    assert diag["coordinator"]["last_update_success"] is True


async def test_options_flow_saves_interval_and_ip(hass: HomeAssistant) -> None:
    await async_setup_component(hass, "persistent_notification", {})
    entry = await _setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    user_input: dict[str, object] = {}
    for label in _schema_labels(result["data_schema"]):
        if "Update Interval" in label or "更新間隔" in label:
            user_input[label] = 30
        elif "IP Address" in label or "IPアドレス" in label:
            user_input[label] = "192.168.11.50"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["update_interval"] == 30
    assert "192.168.11.50" in entry.options.values()


async def test_options_flow_japanese_labels_and_skip_unknown_device(
    hass: HomeAssistant,
) -> None:
    await async_setup_component(hass, "persistent_notification", {})
    entry = await _setup_entry(hass)
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("not_remo", "orphan")},
        name="Orphan",
    )
    hass.config.language = "ja"
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    labels = _schema_labels(result["data_schema"])
    assert any("更新間隔" in label for label in labels)
    interval = next(label for label in labels if "更新間隔" in label)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {interval: 90}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["update_interval"] == 90
