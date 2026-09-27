
from __future__ import annotations

from typing import Optional

from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, DATA_CLIENT, DATA_COORDINATOR
from .device import build_device_info

def _combined(data: dict | None) -> dict:
    data = data or {}
    merged = {}
    for key in ("state", "params", "info"):
        v = data.get(key) or {}
        if isinstance(v, dict):
            merged.update(v)
    return merged

def _raw_max_m3h(d: dict) -> int:
    for k in ("maxfanpower", "max_fan_power"):
        if k in d and d.get(k):
            try:
                v = int(d.get(k))
                if v > 0:
                    return v
            except Exception:
                continue
    return 60

def _manual_cap_m3h(d: dict, raw_max: int) -> Optional[int]:
    for k in ("maxfanpowermanual", "manual_maxfanpower"):
        if k in d and d.get(k) is not None:
            try:
                val = int(d.get(k))
                if val <= 0:
                    continue
                if val <= 100:
                    return max(1, int(round(raw_max * val / 100)))
                return val
            except Exception:
                continue
    return None

def _effective_max_m3h(d: dict) -> int:
    raw_max = _raw_max_m3h(d)
    cap = _manual_cap_m3h(d, raw_max)
    if cap is not None:
        return min(raw_max, cap)
    return raw_max

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    d = _combined(coord.data)
    entities: list[NumberEntity] = []
    if any(k in d for k in ("fanpower", "maxfanpower", "maxfanpowermanual", "max_fan_power", "manual_maxfanpower")):
        entities.append(SiegeniaFanPowerNumber(hass, entry))
    # Auto mode and silent mode each cap the airflow. The device stores both as
    # a percentage of maxfanpower; the app shows m3/h, so this does too.
    if "automode_maxairflow" in d:
        entities.append(
            SiegeniaAirflowNumber(
                hass, entry, "automode_maxairflow", "Auto Mode Max Airflow", "mdi:fan-auto"
            )
        )
    if "ecomode_maxairflow" in d:
        entities.append(
            SiegeniaAirflowNumber(
                hass, entry, "ecomode_maxairflow", "Silent Mode Max Airflow", "mdi:volume-low"
            )
        )
    if "automode_co2sensity" in d:
        entities.append(SiegeniaSensitivityNumber(hass, entry))
    if entities:
        async_add_entities(entities, True)


class _SiegeniaNumberBase(CoordinatorEntity, NumberEntity):
    """Shared plumbing for the parameter-backed numbers."""

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

    def _raw(self) -> int:
        try:
            return int(_combined(self.coordinator.data).get(self._param, 0) or 0)
        except (TypeError, ValueError):
            return 0


class SiegeniaSensitivityNumber(_SiegeniaNumberBase):
    """Sensor sensitivity of the automatic mode, a plain percentage."""

    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_mode = "slider"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, entry, "automode_co2sensity", "Sensor Sensitivity", "mdi:air-filter"
        )

    @property
    def native_value(self) -> float | None:
        return float(self._raw())

    async def async_set_native_value(self, value: float) -> None:
        pct = int(max(0.0, min(100.0, value)))
        await self._client.set_device_params({self._param: pct})
        await self.coordinator.async_request_refresh()


class SiegeniaAirflowNumber(_SiegeniaNumberBase):
    """An airflow cap the device stores as a percentage of maxfanpower."""

    _attr_native_unit_of_measurement = "m³/h"
    _attr_native_min_value = 0.0
    _attr_native_step = 1.0
    _attr_mode = "slider"

    @property
    def native_max_value(self) -> float:
        return float(_raw_max_m3h(_combined(self.coordinator.data)))

    @property
    def native_value(self) -> float | None:
        max_m3h = _raw_max_m3h(_combined(self.coordinator.data))
        return round(max_m3h * self._raw() / 100, 0)

    async def async_set_native_value(self, value: float) -> None:
        max_m3h = _raw_max_m3h(_combined(self.coordinator.data))
        value = max(0.0, min(float(value), float(max_m3h)))
        pct = int(round((value * 100) / max(1.0, float(max_m3h))))
        await self._client.set_device_params({self._param: pct})
        await self.coordinator.async_request_refresh()

class SiegeniaFanPowerNumber(CoordinatorEntity, NumberEntity):
    _attr_icon = "mdi:fan"
    _attr_native_unit_of_measurement = "m³/h"
    _attr_mode = "auto"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        coord = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
        super().__init__(coord)
        self._client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
        self._entry = entry
        # Get system name from device info
        system_name = self._get_system_name()
        self._attr_name = f"{system_name} Fan Power" if system_name else "Siegenia Fan Power"
        self._attr_unique_id = f"{entry.entry_id}-fanpower"

    @property
    def device_info(self):
        return build_device_info(
            self.coordinator.data, self._entry.entry_id, self._entry.data.get("host")
        )
        
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

    def _d(self) -> dict:
        return _combined(self.coordinator.data)

    @property
    def native_min_value(self) -> float:
        return 0.0

    @property
    def native_max_value(self) -> float:
        return float(_effective_max_m3h(self._d()))

    @property
    def native_step(self) -> float:
        return 1.0

    @property
    def native_value(self) -> float | None:
        d = self._d()
        try:
            pct = int(d.get("fanpower", 0) or 0)  # percent 0..100
        except Exception:
            pct = 0
        eff_max = _effective_max_m3h(d)
        return round(eff_max * pct / 100, 0)

    async def async_set_native_value(self, value: float) -> None:
        d = self._d()
        eff_max = _effective_max_m3h(d)
        value = max(0.0, min(float(value), float(eff_max)))
        pct = int(round((value * 100) / max(1.0, float(eff_max))))
        await self._client.set_device_params({"automode": False, "auto_mode": False, "fanpower": pct})
        await self.coordinator.async_request_refresh()
