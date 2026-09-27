from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, DATA_CLIENT, DATA_COORDINATOR
from .device import build_device_info

_LOGGER = logging.getLogger(__name__)


def _combined(data: dict | None) -> dict:
    data = data or {}
    merged: dict = {}
    for key in ("state", "params", "info"):
        v = data.get(key) or {}
        if isinstance(v, dict):
            merged.update(v)
    return merged


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    # The devices keep their own clock, which the eco timer runs on, and it
    # drifts. Only offer the button when the device actually reports one.
    if isinstance(_combined(coordinator.data).get("clock"), dict):
        async_add_entities([SiegeniaSyncClockButton(hass, entry)])


class SiegeniaSyncClockButton(CoordinatorEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
        super().__init__(coordinator)
        self._client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
        self._entry = entry
        system_name = self._get_system_name()
        self._attr_name = f"{system_name} Sync Clock" if system_name else "Siegenia Sync Clock"
        self._attr_unique_id = f"{entry.entry_id}-syncclock"

    def _get_system_name(self) -> str | None:
        """Get the system name from device info."""
        data = self.coordinator.data or {}
        for part in ("state", "params", "info"):
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
    def extra_state_attributes(self) -> dict:
        """Expose the device clock so the drift is visible without a press."""
        clock = _combined(self.coordinator.data).get("clock")
        if not isinstance(clock, dict):
            return {}
        try:
            return {
                "device_clock": "{:04d}-{:02d}-{:02d} {:02d}:{:02d}".format(
                    int(clock["year"]),
                    int(clock["month"]),
                    int(clock["day"]),
                    int(clock["hour"]),
                    int(clock["minute"]),
                )
            }
        except (KeyError, TypeError, ValueError):
            return {}

    async def async_press(self) -> None:
        """Write Home Assistant's local time to the device clock."""
        now = dt_util.now()
        params = {
            "clock": {
                "year": now.year,
                "month": now.month,
                "day": now.day,
                "hour": now.hour,
                "minute": now.minute,
            }
        }
        _LOGGER.debug("Syncing device clock to %s", params["clock"])
        await self._client.set_device_params(params)
        await self.coordinator.async_request_refresh()
