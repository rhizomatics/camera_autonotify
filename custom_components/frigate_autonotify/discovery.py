"""Find Frigate cameras, and zones if wanted, and set each up or offer it as a discovered config entry"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_INTEGRATION_DISCOVERY
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME, CONF_TYPE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import discovery_flow
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_AUTO_DISCOVER,
    CONF_DISCOVER_ZONES,
    CONF_FRIGATE_ENTRY_ID,
    CONF_FRIGATE_NAME,
    DOMAIN,
    FRIGATE_DOMAIN,
    TYPE_CAMERA,
    TYPE_DISCOVERY,
    TYPE_ZONE,
)

if TYPE_CHECKING:
    from homeassistant.helpers.entity_registry import EventEntityRegistryUpdatedData

CAMERA_DOMAIN = "camera"
# the unique id the Frigate integration gives a camera's entity, `{entry_id}:camera:{name}`, the name as in Frigate
CAMERA_UNIQUE_ID = ":camera:"


@dataclass(frozen=True)
class Found:
    """A Frigate camera or zone, each a device of the Frigate integration"""

    device_id: str
    name: str
    type: str
    frigate_entry_id: str
    # the camera's name as Frigate has it, as reviews give it, or a zone's as slugified for its device, since reviews
    # give a zone as written in the Frigate config, with whatever case it has there
    frigate_name: str


def _device_name(device: dr.DeviceEntry) -> str:
    return device.name_by_user or device.name or device.id


@callback
def find_cameras(hass: HomeAssistant) -> list[Found]:
    """The device of each Frigate camera, known by its camera entity"""
    device_registry = dr.async_get(hass)
    found: list[Found] = []
    for entity in er.async_get(hass).entities.values():
        if entity.platform != FRIGATE_DOMAIN or entity.domain != CAMERA_DOMAIN or entity.disabled:
            continue
        frigate_entry_id, sep, camera = entity.unique_id.partition(CAMERA_UNIQUE_ID)
        device = device_registry.async_get(entity.device_id) if entity.device_id else None
        if not sep or not isinstance(device, dr.DeviceEntry):
            continue
        found.append(Found(device.id, _device_name(device), TYPE_CAMERA, frigate_entry_id, camera))
    return found


@callback
def find_zones(hass: HomeAssistant) -> list[Found]:
    """The device of each Frigate zone, the devices of a Frigate server that are neither the server nor a camera"""
    device_registry = dr.async_get(hass)
    cameras = {camera.device_id for camera in find_cameras(hass)}
    found: list[Found] = []
    for entry in hass.config_entries.async_entries(FRIGATE_DOMAIN):
        prefix = f"{entry.entry_id}:"
        for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
            if device.id in cameras or device.disabled:
                continue
            zone = next(
                (
                    value[len(prefix) :]
                    for domain, value in device.identifiers
                    if domain == FRIGATE_DOMAIN and value.startswith(prefix)
                ),
                None,
            )
            if zone:
                found.append(Found(device.id, _device_name(device), TYPE_ZONE, entry.entry_id, zone))
    return found


@callback
def _discovery_options(hass: HomeAssistant) -> dict[str, bool]:
    """The choices of the discovery entry, nothing found while it's disabled or deleted"""
    for entry in hass.config_entries.async_entries(DOMAIN, include_disabled=False):
        if entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            return {
                CONF_AUTO_DISCOVER: bool(entry.options.get(CONF_AUTO_DISCOVER, True)),
                CONF_DISCOVER_ZONES: bool(entry.options.get(CONF_DISCOVER_ZONES, False)),
            }
    return {}


@callback
def async_discover(hass: HomeAssistant) -> None:
    """Set up every camera found, or with automatic discovery off, offer each to be added, and zones only if wanted"""
    options = _discovery_options(hass)
    if not options:
        return
    source = SOURCE_IMPORT if options[CONF_AUTO_DISCOVER] else SOURCE_INTEGRATION_DISCOVERY
    found = find_cameras(hass) + (find_zones(hass) if options[CONF_DISCOVER_ZONES] else [])
    for item in found:
        # those already configured, ignored or in progress are dropped by the flow's unique id
        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            context={"source": source},
            data={
                CONF_DEVICE_ID: item.device_id,
                CONF_NAME: item.name,
                CONF_TYPE: item.type,
                CONF_FRIGATE_ENTRY_ID: item.frigate_entry_id,
                CONF_FRIGATE_NAME: item.frigate_name,
            },
        )


@callback
def async_start_discovery(hass: HomeAssistant) -> None:
    """Look for cameras now, and again whenever Frigate adds an entity, as it does for a new camera or zone"""

    @callback
    def entity_registry_updated(event: Event[EventEntityRegistryUpdatedData]) -> None:
        if event.data["action"] != "create":
            return
        entity = er.async_get(hass).async_get(event.data["entity_id"])
        if entity is not None and entity.platform == FRIGATE_DOMAIN:
            async_discover(hass)

    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, entity_registry_updated)
    async_discover(hass)
