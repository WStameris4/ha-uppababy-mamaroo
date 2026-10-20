"""Config flow for the Mamaroo integration."""

from __future__ import annotations

import logging
from typing import Any

from bleak.exc import BleakError

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_ADDRESS, CONF_BLUETOOTH_ID, CONF_PAIRING_ID, DOMAIN
from .device import MamarooError, async_pair, latest_swing

_LOGGER = logging.getLogger(__name__)


class MamarooConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair Home Assistant with the swing."""

    VERSION = 1

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a discovered swing."""
        # Its address rotates, so one flow stands for every advertisement.
        self._async_abort_entries_match()
        await self.async_set_unique_id(DOMAIN)
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_pair()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a manual start."""
        self._async_abort_entries_match()
        if latest_swing(self.hass) is None:
            return self.async_abort(reason="no_devices_found")
        return await self.async_step_pair()

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for pairing mode, then register a pairing ID."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                bluetooth_id, pairing_id, address = await async_pair(self.hass)
            except (BleakError, MamarooError, TimeoutError) as err:
                _LOGGER.warning("Pairing failed: %s", err)
                errors["base"] = "pairing_failed"
            else:
                await self.async_set_unique_id(
                    str(bluetooth_id) if bluetooth_id else DOMAIN,
                    raise_on_progress=False,
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Mamaroo Smart Swing",
                    data={
                        CONF_PAIRING_ID: str(pairing_id),
                        CONF_BLUETOOTH_ID: str(bluetooth_id) if bluetooth_id else None,
                        CONF_ADDRESS: address,
                    },
                )
        return self.async_show_form(step_id="pair", errors=errors)
