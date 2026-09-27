from __future__ import annotations

from typing import Any, Dict

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, DATA_COORDINATOR
from .device import build_device_info

# key -> (unit, device_class, state_class). A device class gets the reading the
# right icon and formatting; the measurement state class is what makes Home
# Assistant keep long term statistics for it.
TEMPERATURE = ("°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT)
HUMIDITY = ("%", SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT)
CO2 = ("ppm", SensorDeviceClass.CO2, SensorStateClass.MEASUREMENT)
PLAIN = (None, None, None)

SENSOR_META: dict[str, tuple[str | None, SensorDeviceClass | None, SensorStateClass | None]] = {
    "airbase.humidity.indoor": HUMIDITY,
    "airbase.humidity.outdoor": HUMIDITY,
    "airbase.temperature.indoor": TEMPERATURE,
    "airbase.temperature.outdoor": TEMPERATURE,
    "airquality.co2content": CO2,
    "humidity.indoor": HUMIDITY,
    "humidity.outdoor": HUMIDITY,
    "temperature.indoor": TEMPERATURE,
    "temperature.outdoor": TEMPERATURE,
    "co2_value": CO2,
    "fanmode": PLAIN,
    "maxfanpower": ("m³/h", None, None),
    "systemname": PLAIN,
    "connection": PLAIN,
    "airquality": (None, None, SensorStateClass.MEASUREMENT),
    "maxfanpowermanual": PLAIN,
    # From getDeviceDetails rather than getDeviceParams.
    "operatinghours": ("h", SensorDeviceClass.DURATION, SensorStateClass.TOTAL_INCREASING),
    "airfilterremainingterm": ("d", SensorDeviceClass.DURATION, SensorStateClass.MEASUREMENT),
}

def _flatten(data: Dict[str, Any], parent: str = "", out: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if out is None:
        out = {}
    for k, v in (data or {}).items():
        key = f"{parent}.{k}" if parent else str(k)
        if isinstance(v, dict):
            _flatten(v, key, out)
        else:
            out[key] = v
    return out

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data[DATA_COORDINATOR]

    combined = {}
    for part in ("state", "params", "info", "details"):
        d = (coordinator.data or {}).get(part) or {}
        if isinstance(d, dict):
            combined.update(d)
    flat = _flatten(combined)
    flat.update(combined)

    entities: list[SensorEntity] = []
    for key, meta in SENSOR_META.items():
        if key in flat:
            entities.append(SiegeniaKeySensor(coordinator, entry, key, meta))

    if isinstance(combined.get("warnings"), list):
        entities.append(SiegeniaWarningsSensor(coordinator, entry))

    entities.append(SiegeniaRawStateSensor(coordinator, entry))
    async_add_entities(entities)

class SiegeniaKeySensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        key: str,
        meta: tuple[str | None, SensorDeviceClass | None, SensorStateClass | None],
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        unit, device_class, state_class = meta
        if device_class:
            self._attr_device_class = device_class
        if state_class:
            self._attr_state_class = state_class
        # Get system name from device info
        system_name = self._get_system_name()
        name = key.replace("_", " ").replace(".", " ").title()
        self._attr_name = f"{system_name} {name}" if system_name else f"Siegenia {name}"
        slug = key.lower().replace(" ", "-").replace(".", "-").replace("_", "-")
        self._attr_unique_id = f"{entry.entry_id}-{slug}"
        if unit:
            self._attr_native_unit_of_measurement = unit

    @property
    def device_info(self):
        return build_device_info(
            self.coordinator.data, self._entry.entry_id, self._entry.data.get("host")
        )
            
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
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        combined = {}
        for part in ("state", "params", "info", "details"):
            d = data.get(part) or {}
            if isinstance(d, dict):
                combined.update(d)
        flat = combined.copy()
        def _flatten_in(x: dict, parent: str = "", out: dict | None = None):
            if out is None:
                out = {}
            for k, v in (x or {}).items():
                kk = f"{parent}.{k}" if parent else str(k)
                if isinstance(v, dict):
                    _flatten_in(v, kk, out)
                else:
                    out[kk] = v
            return out
        flat.update(_flatten_in(combined))
        return flat.get(self._key)

class SiegeniaRawStateSensor(CoordinatorEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:code-json"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        system_name = self._get_system_name()
        self._attr_name = f"{system_name} Raw State" if system_name else "Siegenia Raw State"
        self._attr_unique_id = f"{entry.entry_id}-raw-state"
        
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

    def _combined(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}
        combined: Dict[str, Any] = {}
        for part in ("state", "params", "info", "details"):
            d = data.get(part) or {}
            if isinstance(d, dict):
                combined.update(d)
        return combined

    @property
    def native_value(self) -> int | None:
        """Number of reported parameters -- the payload itself is an attribute.

        A state is capped at 255 characters and the device dump is around a
        kilobyte, so returning the JSON here made Home Assistant discard the
        state and log an error on every single coordinator update.
        """
        return len(self._combined()) or None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        from json import dumps

        return {"raw": dumps(self._combined(), ensure_ascii=False)}


class SiegeniaWarningsSensor(CoordinatorEntity, SensorEntity):
    """Number of active device warnings, with the raw list as an attribute."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        system_name = self._get_system_name()
        self._attr_name = f"{system_name} Warnings" if system_name else "Siegenia Warnings"
        self._attr_unique_id = f"{entry.entry_id}-warnings"

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

    def _warnings(self) -> list:
        data = self.coordinator.data or {}
        for part in ("state", "params", "info", "details"):
            d = data.get(part) or {}
            if isinstance(d, dict) and isinstance(d.get("warnings"), list):
                return d["warnings"]
        return []

    @property
    def native_value(self) -> int:
        return len(self._warnings())

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {"warnings": self._warnings()}
