from __future__ import annotations

from .const import DOMAIN


def _info_from_data(data: dict | None) -> dict:
    info = (data or {}).get("info") or {}
    return info if isinstance(info, dict) else {}


def _coerce_str(value) -> str | None:
    if value is None:
        return None
    return str(value)


def device_active(data: dict | None) -> bool | None:
    """Return the unit's master on/off flag, or None if the device does not report it.

    getDeviceParams nests it as ``devicestate.deviceactive``, getDeviceState reports
    it as a top-level ``deviceactive``.
    """
    data = data or {}
    params = data.get("params") or {}
    devicestate = params.get("devicestate") if isinstance(params, dict) else None
    if isinstance(devicestate, dict) and isinstance(devicestate.get("deviceactive"), bool):
        return devicestate["deviceactive"]
    state = data.get("state") or {}
    if isinstance(state, dict) and isinstance(state.get("deviceactive"), bool):
        return state["deviceactive"]
    return None


def device_active_params(active: bool) -> dict:
    """setDeviceParams payload that switches the whole unit on or off."""
    return {"devicestate": {"deviceactive": active}}


def build_device_info(data: dict | None, entry_id: str, host: str | None = None) -> dict:
    info = _info_from_data(data)
    serial_raw = info.get("serialnr") or info.get("serial_number")
    identifiers = {(DOMAIN, str(serial_raw))} if serial_raw else {(DOMAIN, entry_id)}

    device_info = {
        "identifiers": identifiers,
        "manufacturer": "Siegenia",
    }

    name = (
        info.get("systemname")
        or info.get("devicename")
        or info.get("device_name")
        or info.get("name")
    )
    if not name and host:
        name = f"Siegenia {host}"
    if name:
        device_info["name"] = name

    model = _coerce_str(info.get("model") or info.get("type") or info.get("hardwareversion"))
    if model:
        device_info["model"] = model

    sw_version = _coerce_str(info.get("softwareversion"))
    if sw_version:
        device_info["sw_version"] = sw_version

    hw_version = _coerce_str(info.get("hardwareversion"))
    if hw_version:
        device_info["hw_version"] = hw_version

    serial = _coerce_str(serial_raw)
    if serial:
        device_info["serial_number"] = serial

    return device_info
