from __future__ import annotations

import logging
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DATA_CLIENT, DATA_COORDINATOR
from .device import build_device_info

_LOGGER = logging.getLogger(__name__)

# ecomode_start / ecomode_end count quarter hours since midnight: the device
# reports 88 for the 22:00 the app shows, and 24 for 6:00.
QUARTERS_PER_DAY = 96


def _combined(data: dict | None) -> dict:
    data = data or {}
    merged: dict = {}
    for key in ("state", "params", "info", "details"):
        v = data.get(key) or {}
        if isinstance(v, dict):
            merged.update(v)
    return merged


def _to_time(quarters: object) -> dt_time | None:
    try:
        value = int(quarters)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not 0 <= value < QUARTERS_PER_DAY:
        return None
    return dt_time(hour=value // 4, minute=(value % 4) * 15)


def _to_quarters(value: dt_time) -> int:
    # The device only stores quarter hours, so anything finer is rounded down
    # rather than silently landing on a different hour.
    return (value.hour * 4 + value.minute // 15) % QUARTERS_PER_DAY


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    params = _combined(coordinator.data)
    entities = []
    if _to_time(params.get("ecomode_start")) is not None:
        entities.append(SiegeniaEcoTime(hass, entry, "ecomode_start", "Silent Mode On"))
    if _to_time(params.get("ecomode_end")) is not None:
        entities.append(SiegeniaEcoTime(hass, entry, "ecomode_end", "Silent Mode Off"))
    if entities:
        async_add_entities(entities, True)


class SiegeniaEcoTime(CoordinatorEntity, TimeEntity):
    """Start or end of the silent mode window."""

    _attr_icon = "mdi:clock-outline"

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, param: str, label: str
    ) -> None:
        coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
        super().__init__(coordinator)
        self._client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
        self._entry = entry
        self._param = param
        system_name = self._get_system_name()
        self._attr_name = f"{system_name} {label}" if system_name else f"Siegenia {label}"
        self._attr_unique_id = f"{entry.entry_id}-{param.replace('_', '-')}"

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
    def native_value(self) -> dt_time | None:
        return _to_time(_combined(self.coordinator.data).get(self._param))

    async def async_set_value(self, value: dt_time) -> None:
        await self._client.set_device_params({self._param: _to_quarters(value)})
        await self.coordinator.async_request_refresh()
