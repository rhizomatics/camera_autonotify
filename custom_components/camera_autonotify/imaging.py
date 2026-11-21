"""Home Assistant's image processing entities, as a source of their own, by the Core interface alone: an entity's
device class, `alpr` or `face`, in its state, and the events it fires, `image_processing.found_plate` for each plate an
ANPR/ALPR entity such as OpenALPR's reads, and `image_processing.detect_face` for each face a face entity finds
"""

from __future__ import annotations

from homeassistant.components.image_processing.const import EVENT_DETECT_FACE, ImageProcessingDeviceClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

IMAGE_PROCESSING_DOMAIN = "image_processing"
# fired by an ANPR/ALPR entity for each new plate, Home Assistant having no constant for it outside OpenALPR's own
EVENT_FOUND_PLATE = "image_processing.found_plate"
# what an entity finds, by its device class
KIND_PLATES = "plates"
KIND_FACES = "faces"
EVENTS = {KIND_PLATES: EVENT_FOUND_PLATE, KIND_FACES: EVENT_DETECT_FACE}
# the faces an entity names as no one
UNNAMED = frozenset({"", "unknown", "none"})


def kind_of(device_class: object) -> str | None:
    """What an entity finds, by its device class: plates for ANPR/ALPR, faces for face recognition, nothing that's
    notified otherwise"""
    if device_class == ImageProcessingDeviceClass.ALPR:
        return KIND_PLATES
    if device_class == ImageProcessingDeviceClass.FACE:
        return KIND_FACES
    return None


@callback
def platform_name(hass: HomeAssistant, entity_id: str) -> str:
    """The integration an entity is of, such as `openalpr_cloud`, where it has a registry entry, many set up from
    YAML having none"""
    entry = er.async_get(hass).async_get(entity_id)
    return entry.platform if entry is not None else IMAGE_PROCESSING_DOMAIN
