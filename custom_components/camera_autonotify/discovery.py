"""Find Frigate cameras, and zones if wanted, anpr2mqtt's cameras, and Home Assistant's image processing entities, and
set each up or offer it as a discovered config entry"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_INTEGRATION_DISCOVERY
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME, CONF_TYPE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import discovery_flow
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.start import async_at_started

from .const import (
    CONF_ANPR2MQTT_DISCOVER,
    CONF_ANPR2MQTT_SILENT,
    CONF_AUTO_DISCOVER,
    CONF_DISCOVER_ZONES,
    CONF_FRIGATE_DISCOVER,
    CONF_FRIGATE_SILENT,
    CONF_IMAGE_PROCESSING_DISCOVER,
    CONF_IMAGE_PROCESSING_EVENTS,
    CONF_IMAGE_PROCESSING_SILENT,
    CONF_SOURCE,
    CONF_SOURCE_ENTRY_ID,
    CONF_SOURCE_NAME,
    DOMAIN,
    FRIGATE_DOMAIN,
    SOURCE_ANPR2MQTT,
    SOURCE_FRIGATE,
    SOURCE_IMAGE_PROCESSING,
    TYPE_ANPR,
    TYPE_ANPR_EVENT,
    TYPE_CAMERA,
    TYPE_DISCOVERY,
    TYPE_IMAGE_PROCESSING,
    TYPE_ZONE,
)
from .imaging import IMAGE_PROCESSING_DOMAIN, kind_of

if TYPE_CHECKING:
    from homeassistant.helpers.entity_registry import EventEntityRegistryUpdatedData

CAMERA_DOMAIN = "camera"
# where each kind of entry is from, a Frigate camera or zone otherwise
SOURCES = {TYPE_ANPR: SOURCE_ANPR2MQTT, TYPE_ANPR_EVENT: SOURCE_ANPR2MQTT, TYPE_IMAGE_PROCESSING: SOURCE_IMAGE_PROCESSING}
# the unique id the Frigate integration gives a camera's entity, `{entry_id}:camera:{name}`, the name as in Frigate
CAMERA_UNIQUE_ID = ":camera:"


@dataclass(frozen=True)
class Found:
    """A Frigate camera or zone, each a device of the Frigate integration, an anpr2mqtt sensor, or an image processing
    entity, with what it finds"""

    device_id: str
    name: str
    type: str
    source_entry_id: str
    # the camera's name as Frigate has it, as reviews give it, or a zone's as slugified for its device, since reviews
    # give a zone as written in the Frigate config, with whatever case it has there
    source_name: str
    events: tuple[str, ...] = field(default=())


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
        source_entry_id, sep, camera = entity.unique_id.partition(CAMERA_UNIQUE_ID)
        device = device_registry.async_get(entity.device_id) if entity.device_id else None
        if not sep or not isinstance(device, dr.DeviceEntry):
            continue
        found.append(Found(device.id, _device_name(device), TYPE_CAMERA, source_entry_id, camera))
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


MQTT_DOMAIN = "mqtt"
SENSOR_DOMAIN = "sensor"
EVENT_DOMAIN = "event"
# each of anpr2mqtt's entities by its domain: a plate sensor, or another event, such as a face, from anpr2mqtt 1.4.0
ANPR_TYPES = {SENSOR_DOMAIN: TYPE_ANPR, EVENT_DOMAIN: TYPE_ANPR_EVENT}


@callback
def find_anpr(hass: HomeAssistant) -> list[Found]:
    """Each plate sensor or event entity of anpr2mqtt's, one per camera and event, known by its device's manufacturer
    and model, so the sensors of its targets, which have no device, and anything else of MQTT's are left out"""
    device_registry = dr.async_get(hass)
    found: list[Found] = []
    for entity in er.async_get(hass).entities.values():
        if entity.platform != MQTT_DOMAIN or entity.domain not in ANPR_TYPES or entity.disabled or not entity.device_id:
            continue
        device = device_registry.async_get(entity.device_id)
        if not isinstance(device, dr.DeviceEntry) or device.manufacturer != "Rhizomatics" or device.model != "anpr2mqtt":
            continue
        name = entity.name or entity.original_name or entity.entity_id
        found.append(Found(device.id, str(name), ANPR_TYPES[entity.domain], entity.config_entry_id or "", entity.unique_id))
    return found


@callback
def find_image_processing(hass: HomeAssistant) -> list[Found]:
    """Each image processing entity whose device class says it finds plates or faces, by its state, as Home Assistant's
    Core interface has it"""
    found: list[Found] = []
    for state in hass.states.async_all(IMAGE_PROCESSING_DOMAIN):
        if kind := kind_of(state.attributes.get("device_class")):
            found.append(Found("", state.name, TYPE_IMAGE_PROCESSING, "", state.entity_id, (kind,)))
    return found


@dataclass(frozen=True)
class SourceDiscovery:
    """Whether a source's cameras and the like are found, and if so, set up without asking rather than offered as
    discovered, as Home Assistant offers any device found"""

    find: bool = True
    silent: bool = False


# each kind of entry by the source whose settings it follows
FRIGATE = "frigate"
ANPR2MQTT = "anpr2mqtt"
IMAGE_PROCESSING = "image_processing"
SOURCE_OF = {TYPE_ANPR: ANPR2MQTT, TYPE_ANPR_EVENT: ANPR2MQTT, TYPE_IMAGE_PROCESSING: IMAGE_PROCESSING}


def discovery_settings(options: Mapping[str, Any]) -> dict[str, SourceDiscovery]:
    """Each source's choices in Global Settings, Frigate's and image processing's set up without asking where the one
    choice of earlier versions was on, until saved again"""
    legacy = bool(options.get(CONF_AUTO_DISCOVER, False))
    return {
        FRIGATE: SourceDiscovery(
            bool(options.get(CONF_FRIGATE_DISCOVER, True)), bool(options.get(CONF_FRIGATE_SILENT, legacy))
        ),
        ANPR2MQTT: SourceDiscovery(
            bool(options.get(CONF_ANPR2MQTT_DISCOVER, True)), bool(options.get(CONF_ANPR2MQTT_SILENT, False))
        ),
        IMAGE_PROCESSING: SourceDiscovery(
            bool(options.get(CONF_IMAGE_PROCESSING_DISCOVER, True)), bool(options.get(CONF_IMAGE_PROCESSING_SILENT, legacy))
        ),
    }


@callback
def _global_options(hass: HomeAssistant) -> Mapping[str, Any] | None:
    """Global Settings' choices, nothing found while it's disabled or deleted"""
    for entry in hass.config_entries.async_entries(DOMAIN, include_disabled=False):
        if entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            return entry.options
    return None


@callback
def async_discover(hass: HomeAssistant) -> None:
    """Offer each camera, zone and source found as discovered, or set it up without asking, by its source's choices,
    and zones only if wanted"""
    options = _global_options(hass)
    if options is None:
        return
    settings = discovery_settings(options)
    found: list[Found] = []
    if settings[FRIGATE].find:
        found += find_cameras(hass) + (find_zones(hass) if options.get(CONF_DISCOVER_ZONES) else [])
    if settings[ANPR2MQTT].find:
        found += find_anpr(hass)
    if settings[IMAGE_PROCESSING].find:
        found += find_image_processing(hass)
    for item in found:
        data: dict[str, object] = {
            CONF_DEVICE_ID: item.device_id,
            CONF_NAME: item.name,
            CONF_TYPE: item.type,
            CONF_SOURCE: SOURCES.get(item.type, SOURCE_FRIGATE),
            CONF_SOURCE_ENTRY_ID: item.source_entry_id,
            CONF_SOURCE_NAME: item.source_name,
        }
        source = SOURCE_IMPORT if settings[SOURCE_OF.get(item.type, FRIGATE)].silent else SOURCE_INTEGRATION_DISCOVERY
        if item.type == TYPE_IMAGE_PROCESSING:
            # what it finds, by its device class
            data[CONF_IMAGE_PROCESSING_EVENTS] = list(item.events)
        # those already configured, ignored or in progress are dropped by the flow's unique id
        discovery_flow.async_create_flow(hass, DOMAIN, context={"source": source}, data=data)


@callback
def async_start_discovery(hass: HomeAssistant) -> None:
    """Look for cameras now, again whenever Frigate adds an entity, as it does for a new camera or zone, and once Home
    Assistant has started, for image processing entities"""

    @callback
    def entity_registry_updated(event: Event[EventEntityRegistryUpdatedData]) -> None:
        if event.data["action"] != "create":
            return
        entity = er.async_get(hass).async_get(event.data["entity_id"])
        if entity is not None and entity.platform in (FRIGATE_DOMAIN, MQTT_DOMAIN):
            async_discover(hass)

    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, entity_registry_updated)
    async_discover(hass)

    @callback
    def started(_hass: HomeAssistant) -> None:
        # image processing entities, set up from YAML, often with no registry entry, and maybe only after this
        async_discover(hass)

    async_at_started(hass, started)
