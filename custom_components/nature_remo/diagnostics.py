"""Diagnostics for Nature Remo (sensitive data redacted)."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

TO_REDACT = {
    CONF_API_KEY,
    "token",
    "access_token",
    "serial_number",
    "mac_address",
    "bt_mac_address",
    "latitude",
    "longitude",
    "nickname",
    "users",
    "unique_id",
    "host",
    "ip",
    "ip_address",
}

_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _redact_options(options: dict[str, Any]) -> dict[str, Any]:
    """Options store Remo IP addresses under device ids; hide those values."""
    return {
        key: ("**REDACTED**" if isinstance(value, str) and _IP_RE.match(value) else value)
        for key, value in options.items()
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = getattr(entry, "runtime_data", None)
    coordinator = getattr(runtime, "coordinator", None)
    data: dict[str, Any] = {}
    if coordinator is not None:
        data = {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
            "devices": getattr(coordinator, "devices", {}),
            "aircons": getattr(coordinator, "aircons", {}),
            "lights": getattr(coordinator, "lights", {}),
            "locks": getattr(coordinator, "locks", {}),
            "ir_remotes": getattr(coordinator, "ir_remotes", {}),
            "smart_meters": getattr(coordinator, "smart_meters", {}),
        }
    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": _redact_options(dict(entry.options)),
        },
        "coordinator": async_redact_data(data, TO_REDACT),
    }
