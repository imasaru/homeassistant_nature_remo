"""Zeroconf discovery tests for Nature Remo (no network, no IR sent)."""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import IPv4Address
from typing import Any
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.api import NatureRemoAuthError
from custom_components.nature_remo.const import DOMAIN

USER = {"id": "user-123", "nickname": "Home"}
FLOW_GET_USER = "custom_components.nature_remo.config_flow.async_get_user"

DISCOVERY_HOST = "192.168.1.50"
OLD_HOST = "192.168.1.10"
INSTANCE = "Remo-9D3182"


@dataclass
class FakeZeroconfServiceInfo:
    """Stand-in for homeassistant.components.zeroconf.ZeroconfServiceInfo.

    The venv does not install the zeroconf package, so the real class cannot
    be imported without pulling in that dependency.
    """

    ip_address: IPv4Address
    ip_addresses: list[IPv4Address]
    port: int | None
    hostname: str
    type: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def host(self) -> str:
        return str(self.ip_address)


def _info(
    host: str = DISCOVERY_HOST,
    instance: str = INSTANCE,
    properties: dict[str, Any] | None = None,
) -> FakeZeroconfServiceInfo:
    ip = IPv4Address(host)
    return FakeZeroconfServiceInfo(
        ip_address=ip,
        ip_addresses=[ip],
        port=80,
        hostname=f"{instance}.local.",
        type="_remo._tcp.local.",
        name=f"{instance}._remo._tcp.local.",
        properties=properties or {},
    )


async def _start_discovery(
    hass: HomeAssistant, info: FakeZeroconfServiceInfo | None = None
) -> dict[str, Any]:
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=info or _info(),
    )


async def test_discovery_new_device_confirm_creates_entry(hass: HomeAssistant) -> None:
    """A new Remo asks for the token, then creates a config entry."""
    result = await _start_discovery(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert result["description_placeholders"] == {
        "name": INSTANCE,
        "host": DISCOVERY_HOST,
    }

    with (
        patch(FLOW_GET_USER, return_value=USER),
        patch("custom_components.nature_remo.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: " tok "}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"] == {CONF_API_KEY: "tok"}
    assert result["result"].unique_id == "user-123"


async def test_discovery_known_device_updates_ip(hass: HomeAssistant) -> None:
    """A Remo already in the registry has its stored local IP updated."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="user-123", data={CONF_API_KEY: "tok"}
    )
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "remo-dev-1")},
        serial_number=INSTANCE,
        name="Living Remo",
    )
    hass.config_entries.async_update_entry(entry, options={device.id: OLD_HOST})

    result = await _start_discovery(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.options[device.id] == DISCOVERY_HOST


async def test_discovery_already_configured_same_ip(hass: HomeAssistant) -> None:
    """Discovering a Remo whose stored IP is already current just aborts."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user-123",
        data={CONF_API_KEY: "tok"},
        options={"some-device-id": DISCOVERY_HOST},
    )
    entry.add_to_hass(hass)

    result = await _start_discovery(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.options["some-device-id"] == DISCOVERY_HOST


async def test_discovery_already_configured_account(hass: HomeAssistant) -> None:
    """Confirming a new Remo with a token for an existing account aborts."""
    MockConfigEntry(
        domain=DOMAIN, unique_id="user-123", data={CONF_API_KEY: "old"}
    ).add_to_hass(hass)

    result = await _start_discovery(hass)
    assert result["type"] is FlowResultType.FORM

    with patch(FLOW_GET_USER, return_value=USER):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_discovery_invalid_token(hass: HomeAssistant) -> None:
    """A rejected token leaves the confirm form open with an error."""
    result = await _start_discovery(hass)
    with patch(FLOW_GET_USER, side_effect=NatureRemoAuthError):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "bad"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert result["errors"] == {"base": "invalid_auth"}

    with (
        patch(FLOW_GET_USER, return_value=USER),
        patch("custom_components.nature_remo.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "good"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "user-123"
