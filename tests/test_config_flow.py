"""Config flow and setup tests for Nature Remo (no network, no IR sent)."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.api import (
    NatureRemoAuthError,
    NatureRemoConnectionError,
)
from custom_components.nature_remo.const import DOMAIN

USER = {"id": "user-123", "nickname": "Home"}
FLOW_GET_USER = "custom_components.nature_remo.config_flow.async_get_user"
SETUP_GET_USER = "custom_components.nature_remo.async_get_user"


async def test_user_flow_success(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(FLOW_GET_USER, return_value=USER), patch(
        "custom_components.nature_remo.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Remo", CONF_API_KEY: " tok "}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Remo"
    assert result["data"] == {CONF_API_KEY: "tok"}
    assert result["result"].unique_id == "user-123"


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (NatureRemoAuthError, "invalid_auth"),
        (NatureRemoConnectionError, "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
async def test_user_flow_errors_recover(hass: HomeAssistant, side_effect, error) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(FLOW_GET_USER, side_effect=side_effect):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "bad"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    with patch(FLOW_GET_USER, return_value=USER), patch(
        "custom_components.nature_remo.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "good"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_duplicate_account(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="user-123", data={CONF_API_KEY: "old"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(FLOW_GET_USER, return_value=USER):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_duplicate_legacy_token(hass: HomeAssistant) -> None:
    """An old entry without unique id is still matched by its token."""
    MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "tok"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "tok"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="user-123", data={CONF_API_KEY: "old"})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with patch(FLOW_GET_USER, side_effect=NatureRemoAuthError):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "still-bad"}
        )
    assert result["errors"] == {"base": "invalid_auth"}

    with patch(FLOW_GET_USER, return_value=USER), patch(
        "custom_components.nature_remo.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new"


async def test_reauth_wrong_account(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="user-123", data={CONF_API_KEY: "old"})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    with patch(FLOW_GET_USER, return_value={"id": "someone-else"}):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "other"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data[CONF_API_KEY] == "old"


async def test_reconfigure_adopts_unique_id(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "old"})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    with patch(FLOW_GET_USER, return_value=USER), patch(
        "custom_components.nature_remo.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_API_KEY] == "new"
    assert entry.unique_id == "user-123"


async def test_setup_auth_failed_starts_reauth(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "revoked"})
    entry.add_to_hass(hass)
    with patch(SETUP_GET_USER, side_effect=NatureRemoAuthError):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == config_entries.SOURCE_REAUTH for f in flows)


async def test_setup_cloud_down_retries(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: "tok"})
    entry.add_to_hass(hass)
    with patch(SETUP_GET_USER, side_effect=NatureRemoConnectionError):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics_redacts(hass: HomeAssistant) -> None:
    from custom_components.nature_remo.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "secret-token"},
        options={"update_interval": 60, "abc123": "192.168.1.20"},
    )
    entry.add_to_hass(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    assert "secret-token" not in text
    assert "192.168.1.20" not in text
    assert diag["entry"]["options"]["update_interval"] == 60


async def test_light_action_registered_once_and_validates(hass: HomeAssistant) -> None:
    """send_light_mode is registered by async_setup and rejects unknown lights."""
    from homeassistant.exceptions import ServiceValidationError
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "send_light_mode")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "send_light_mode",
            {"entity_id": "light.nope", "mode": "on"},
            blocking=True,
            return_response=True,
        )
