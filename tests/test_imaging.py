"""What an image processing entity finds, by its device class, and which integration it's of"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.camera_autonotify.imaging import KIND_FACES, KIND_PLATES, kind_of, platform_name

ALPR = "image_processing.openalpr_courtyard"
FACES = "image_processing.faces_courtyard"
DOODS = "image_processing.doods_courtyard"


def processing(hass: HomeAssistant, entity_id: str, device_class: str | None) -> None:
    """An image processing entity's state, as Home Assistant's Core has it, set up from YAML with no registry entry"""
    name = entity_id.split(".")[1].replace("_", " ").title()
    attributes = {"friendly_name": name, **({"device_class": device_class} if device_class else {})}
    hass.states.async_set(entity_id, "unknown", attributes)


def test_kind_of():
    assert kind_of("alpr") == KIND_PLATES
    assert kind_of("face") == KIND_FACES
    # an object detector, such as DOODS, or OCR, finds nothing that's notified
    assert kind_of(None) is None
    assert kind_of("ocr") is None


async def test_platform_name(hass: HomeAssistant):
    """By its registry entry, many set up from YAML having none"""
    assert platform_name(hass, ALPR) == "image_processing"
    er.async_get(hass).async_get_or_create("image_processing", "openalpr_cloud", "abc", suggested_object_id="lpr")
    assert platform_name(hass, "image_processing.lpr") == "openalpr_cloud"
