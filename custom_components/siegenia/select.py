from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DATA_CLIENT, DATA_COORDINATOR
from .device import build_device_info

_LOGGER = logging.getLogger(__name__)

# The device reports and accepts the fan mode as an upper case string. Home
# Assistant wants slugs it can translate, so the two are kept apart here.
# AUTO shows up on the timer parameters, not as a mode you can select.
FANMODES = ("IN", "OUT", "IN_OUT", "IN_OUT_WRG")


def _combined(data: dict | None) -> dict:
    data = data or {}
    merged: dict = {}
    for key in ("state", "params", "info", "details"):
        v = data.get(key) or {}
        if isinstance(v, dict):
            merged.update(v)
    return merged


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    if isinstance(_combined(coordinator.data).get("fanmode"), str):
        async_add_entities([SiegeniaFanModeSelect(hass, entry)], True)


class SiegeniaFanModeSelect(CoordinatorEntity, SelectEntity):
    """Operating mode: supply air, extract air, both, both with heat recovery."""

    _attr_icon = "mdi:swap-vertical-bold"
    _attr_translation_key = "fanmode"
    _attr_options = [mode.lower() for mode in FANMODES]

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
        super().__init__(coordinator)
        self._client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
        self._entry = entry
        system_name = self._get_system_name()
        self._attr_name = (
            f"{system_name} Operating Mode" if system_name else "Siegenia Operating Mode"
        )
        self._attr_unique_id = f"{entry.entry_id}-fanmode"

    def _get_system_name(self) -> str | None:
        """Get the system name from device info."""
        data = self.coordinator.data or {}
        for part in ("state", "params", "info", "details"):
            d = data.get(part) or {}
            if isinstance(d, dict):
                system_name = d.get("systemname") or d.get("device_name")
                if system_name:
                    return system_name
        return None

    @property
    def device_info(self):
        return build_device_info(
            self.coordinator.data, self._entry.entry_id, self._entry.data.get("host")
        )

    @property
    def current_option(self) -> str | None:
        mode = _combined(self.coordinator.data).get("fanmode")
        if not isinstance(mode, str):
            return None
        option = mode.lower()
        # A device in a mode this integration does not offer (AUTO) reports no
        # option rather than a wrong one.
        return option if option in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        await self._client.set_device_params({"fanmode": option.upper()})
        await self.coordinator.async_request_refresh()
