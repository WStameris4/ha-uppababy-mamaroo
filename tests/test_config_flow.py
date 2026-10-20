"""Config flow tests."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mamaroo.const import CONF_BLUETOOTH_ID, CONF_PAIRING_ID, DOMAIN
from custom_components.mamaroo.device import MamarooError

BLUETOOTH_ID = UUID("0a0b0c0d-0000-1111-2222-333344445555")
PAIRING_ID = UUID("00112233-4455-6677-8899-aabbccddeeff")


async def test_pair_creates_entry(hass: HomeAssistant) -> None:
    with patch("custom_components.mamaroo.config_flow.latest_swing", return_value=object()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    with (
        patch(
            "custom_components.mamaroo.config_flow.async_pair",
            return_value=(BLUETOOTH_ID, PAIRING_ID),
        ),
        patch("custom_components.mamaroo.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_PAIRING_ID: str(PAIRING_ID),
        CONF_BLUETOOTH_ID: str(BLUETOOTH_ID),
    }
    assert result["result"].unique_id == str(BLUETOOTH_ID)


async def test_pair_failure_shows_error(hass: HomeAssistant) -> None:
    with patch("custom_components.mamaroo.config_flow.latest_swing", return_value=object()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    with patch(
        "custom_components.mamaroo.config_flow.async_pair",
        side_effect=MamarooError("refused"),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "pairing_failed"}


async def test_no_swing_aborts(hass: HomeAssistant) -> None:
    with patch("custom_components.mamaroo.config_flow.latest_swing", return_value=None):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"
