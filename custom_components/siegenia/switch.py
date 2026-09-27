from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, DATA_CLIENT, DATA_COORDINATOR
from .device import build_device_info

def _combined(data: dict | None) -> dict:
    data = data or {}
    merged = {}
    for key in ("state", "params", "info", "details"):
        v = data.get(key) or {}
        if isinstance(v, dict):
            merged.update(v)
    return merged

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    params = _combined(coord.data)
    entities: list[SwitchEntity] = [SiegeniaAutoModeSwitch(hass, entry)]
    # Silent mode and its timer only exist on devices that report them.
    if isinstance(params.get("ecomode"), bool):
        entities.append(
            SiegeniaParamSwitch(hass, entry, "ecomode", "Silent Mode", "mdi:volume-low")
        )
    if isinstance(params.get("ecotimer"), bool):
        entities.append(
            SiegeniaParamSwitch(
                hass, entry, "ecotimer", "Silent Mode Timer", "mdi:timer-outline"
            )
        )
    async_add_entities(entities, True)


class SiegeniaParamSwitch(CoordinatorEntity, SwitchEntity):
    """A switch backed by one boolean device parameter."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        param: str,
        label: str,
        icon: str | None = None,
    ) -> None:
        coord = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
        super().__init__(coord)
        self._client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
        self._entry = entry
        self._param = param
        if icon:
            self._attr_icon = icon
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
    def is_on(self) -> bool:
        return bool(_combined(self.coordinator.data).get(self._param, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.set_device_params({self._param: True})
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.set_device_params({self._param: False})
        await self.coordinator.async_request_refresh()

class SiegeniaAutoModeSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        coord = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
        super().__init__(coord)
        self._client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
        self._entry = entry
        # Get system name from device info
        system_name = self._get_system_name()
        self._attr_name = f"{system_name} Auto Mode" if system_name else "Siegenia Auto Mode"
        self._attr_unique_id = f"{entry.entry_id}-automode"
        
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

    def _d(self) -> dict:
        return _combined(self.coordinator.data)

    @property
    def is_on(self) -> bool:
        d = self._d()
        return bool(d.get("automode", d.get("auto_mode", False)))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.set_device_params({"automode": True, "auto_mode": True})
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.set_device_params({"automode": False, "auto_mode": False})
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        return build_device_info(
            self.coordinator.data, self._entry.entry_id, self._entry.data.get("host")
        )
