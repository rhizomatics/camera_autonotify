"""The device of each camera's entry, linked to the device the Frigate integration has for the camera"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from .compat import LINKED_DEVICES

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


@callback
def async_register_device(hass: HomeAssistant, entry: ConfigEntry, name: str) -> dr.DeviceEntry | None:
    """A device for the entry, so it's listed under the entry on the integration's page, and shown alongside the
    camera's own device, linked to it by the identifiers they have in common, and none at all before devices were
    linked"""
    if not LINKED_DEVICES:
        return None
    source = dr.async_get(hass).async_get(entry.data.get(CONF_DEVICE_ID, ""))
    if not isinstance(source, dr.DeviceEntry):
        # gone from Frigate since it was set up
        return None
    area = ar.async_get(hass).async_get_area(source.area_id) if source.area_id else None
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers=set(source.identifiers),
        connections=set(source.connections),
        name=name,
        manufacturer=source.manufacturer,
        model=source.model,
        suggested_area=area.name if area is not None else None,
    )
