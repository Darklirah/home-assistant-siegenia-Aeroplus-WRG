
from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, DATA_CLIENT, DATA_COORDINATOR
from .device import build_device_info, device_active, device_active_params

_LOGGER = logging.getLogger(__name__)

PERCENTAGE_FLAG = getattr(FanEntityFeature, "SET_PERCENTAGE", getattr(FanEntityFeature, "SET_SPEED", 0))
DEFAULT_MAX_M3H = 60

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    client = data[DATA_CLIENT]
    coordinator = data[DATA_COORDINATOR]
    async_add_entities([SiegeniaFanEntity(client, coordinator, entry)], True)


class SiegeniaFanEntity(CoordinatorEntity, FanEntity):
    _attr_has_entity_name = True

    def __init__(self, client, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        # has_entity_name: Home Assistant prefixes the device name itself, so the
        # system name must not be part of the entity name or it shows up twice.
        self._attr_name = "Fan"
        self._attr_unique_id = f"{entry.entry_id}-fan"
        self._last_pct: int | None = None

    @property
    def device_info(self):
        return build_device_info(
            self.coordinator.data, self._entry.entry_id, self._entry.data.get("host")
        )

    def _combined(self) -> dict:
        data = self.coordinator.data or {}
        merged: dict[str, Any] = {}
        for part in ("state", "params", "info", "details"):
            v = data.get(part) or {}
            if isinstance(v, dict):
                merged.update(v)
        return merged

    def _raw_max_m3h(self, d: dict) -> int:
        for k in ("maxfanpower", "max_fan_power"):
            if k in d:
                try:
                    val = int(d.get(k) or 0)
                    if val > 0:
                        return val
                except Exception:
                    continue
        return DEFAULT_MAX_M3H

    def _manual_cap_m3h(self, d: dict, raw_max: int) -> Optional[int]:
        for k in ("maxfanpowermanual", "manual_maxfanpower"):
            if k in d and d.get(k) is not None:
                try:
                    val = int(d.get(k))
                    if val <= 0:
                        continue
                    # Heuristic: <=100 => treat as percent cap; >100 => absolute m³/h
                    if val <= 100:
                        return max(1, int(round(raw_max * val / 100)))
                    return val
                except Exception:
                    continue
        return None

    def _effective_max_m3h(self, d: dict) -> int:
        raw_max = self._raw_max_m3h(d)
        cap = self._manual_cap_m3h(d, raw_max)
        if cap is not None:
            return min(raw_max, cap)
        return raw_max

    @property
    def is_on(self) -> bool:
        if device_active(self.coordinator.data) is False:
            return False
        d = self._combined()
        for k in ("power", "on", "enabled"):
            if k in d:
                return bool(d.get(k))
        try:
            p = int(d.get("fanpower", 0) or 0)  # percent
            return p > 0
        except Exception:
            return False

    @property
    def percentage(self) -> int | None:
        d = self._combined()
        try:
            p = int(d.get("fanpower", 0) or 0)  # Siegenia reports percent 0..100
        except Exception:
            p = 0
        p = max(0, min(100, p))
        if p > 0:
            self._last_pct = p
        return p

    @property
    def supported_features(self) -> int:
        return PERCENTAGE_FLAG | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._combined()
        raw_max = self._raw_max_m3h(d)
        eff_max = self._effective_max_m3h(d)
        try:
            p = int(d.get("fanpower", 0) or 0)
        except Exception:
            p = 0
        airflow = round(eff_max * p / 100) if eff_max else None
        manual_cap_field = None
        for k in ("maxfanpowermanual", "manual_maxfanpower"):
            if k in d:
                manual_cap_field = d.get(k)
                break
        return {
            "fanmode": d.get("fanmode"),
            "fanpower_percent": p,
            "raw_maxfanpower_m3h": raw_max,
            "manual_cap_reported": manual_cap_field,
            "effective_maxfanpower_m3h": eff_max,
            "airflow_m3h": airflow,
            "systemname": d.get("systemname") or d.get("device_name"),
        }

    async def async_set_percentage(self, percentage: int) -> None:
        target_pct = max(0, min(100, int(percentage or 0)))
        params: dict[str, Any] = {
            "automode": False,
            "auto_mode": False,
            "fanpower": target_pct,
        }
        await self._client.set_device_params(params)
        await self.coordinator.async_request_refresh()

    def _has_power_param(self) -> bool:
        """Aeroplus devices expose power/on/enabled -- AEROVITAL (type 5) does not."""
        d = self._combined()
        return any(k in d for k in ("power", "on", "enabled"))

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        # Home Assistant passes percentage and preset_mode positionally
        # (fan/__init__.py: async_turn_on(percentage, preset_mode, **kwargs)),
        # so they have to be named parameters or the call raises a TypeError.
        if percentage is not None:
            if device_active(self.coordinator.data) is False:
                await self._client.set_device_params(device_active_params(True))
            await self.async_set_percentage(percentage)
            return
        if device_active(self.coordinator.data) is not None:
            # The unit has a real master switch: power it up and keep its fan settings.
            params = device_active_params(True)
            d = self._combined()
            if not d.get("automode") and not int(d.get("fanpower", 0) or 0):
                params["fanpower"] = self._last_pct or 50
            await self._client.set_device_params(params)
        elif self._has_power_param():
            await self._client.set_device_params({"power": True, "on": True, "enabled": True})
        else:
            # No on/off parameter: the unit runs whenever fanpower > 0.
            await self._client.set_device_params(
                {"automode": False, "fanpower": self._last_pct or 50}
            )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if device_active(self.coordinator.data) is not None:
            # Switch the whole unit off; fan power and mode stay as they are for turn_on.
            params = device_active_params(False)
        elif self._has_power_param():
            params = {"power": False, "on": False, "enabled": False, "fanpower": 0}
        else:
            # Auto mode would ramp the fan straight back up, so switch it off too.
            params = {"automode": False, "fanpower": 0}
        await self._client.set_device_params(params)
        await self.coordinator.async_request_refresh()
