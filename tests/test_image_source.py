"""An image processing entity, such as OpenALPR's, as a source of its own, by Home Assistant's Core interface"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant

from custom_components.camera_autonotify.const import DOMAIN, TYPE_IMAGE_PROCESSING
from custom_components.camera_autonotify.image_source import ImageSourceWatcher

from .conftest import add_frigate
from .test_discovery import set_up_discovery
from .test_imaging import ALPR, DOODS, FACES, processing
from .test_vehicles import FAMILY, FakeRegister, global_settings, register  # noqa: F401

CAMERA = "camera.courtyard"


@pytest.fixture
def sent() -> Iterator[AsyncMock]:
    with patch("custom_components.camera_autonotify.image_source.async_notify_message", AsyncMock()) as notify:
        yield notify


def last(sent: AsyncMock) -> tuple[Any, ...]:
    """What the last notification was sent with"""
    assert sent.await_args is not None
    return tuple(sent.await_args.args)


def entries(hass: HomeAssistant) -> dict[str, Any]:
    return {e.title: e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_IMAGE_PROCESSING}


async def test_set_up_by_device_class(hass: HomeAssistant):
    """An ANPR/ALPR or face entity set up by itself, for its plates or faces, any other left out"""
    add_frigate(hass)
    processing(hass, ALPR, "alpr")
    processing(hass, FACES, "face")
    processing(hass, DOODS, None)
    await set_up_discovery(hass)
    found = entries(hass)
    assert set(found) == {"Openalpr Courtyard (Image processing)", "Faces Courtyard (Image processing)"}
    assert found["Openalpr Courtyard (Image processing)"].data["image_processing_events"] == ["plates"]
    assert found["Faces Courtyard (Image processing)"].data["image_processing_events"] == ["faces"]


async def test_offered_without_automatic_discovery(hass: HomeAssistant):
    add_frigate(hass)
    processing(hass, ALPR, "alpr")
    await set_up_discovery(hass, auto_discover=False)
    offered = [
        f for f in hass.config_entries.flow.async_progress() if f["context"].get("unique_id") == f"image_processing:{ALPR}"
    ]
    assert [f["step_id"] for f in offered] == ["confirm_image_processing"]
    assert offered[0]["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY
    result = await hass.config_entries.flow.async_configure(offered[0]["flow_id"], {})
    assert result["title"] == "Openalpr Courtyard (Image processing)"
    assert result["data"]["image_processing_events"] == ["plates"]


async def watching(hass: HomeAssistant, entity_id: str, events: list[str], **options: Any) -> ImageSourceWatcher:
    from tests.ha_testing import MockConfigEntry

    hass.states.async_set(CAMERA, "idle", {"friendly_name": "Courtyard"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Courtyard (Image processing)",
        data={CONF_TYPE: TYPE_IMAGE_PROCESSING, "source_name": entity_id, "image_processing_events": events},
        options=options,
    )
    entry.add_to_hass(hass)
    watcher = ImageSourceWatcher(hass, entry)
    watcher.async_start()
    return watcher


async def test_plate_notified(hass: HomeAssistant, register: FakeRegister, sent: AsyncMock):  # noqa: F811
    """Classified, looked up and counted, as Frigate's are, with the camera's image, and not again within the quiet
    period"""
    global_settings(hass, {"Family cars": FAMILY})
    await watching(hass, ALPR, ["plates"], camera_entity=CAMERA)
    for _ in range(2):
        hass.bus.async_fire("image_processing.found_plate", {"plate": "J912UKL", "entity_id": ALPR, "confidence": 91.0})
        await hass.async_block_till_done()
    sent.assert_awaited_once()
    title, message, priority = last(sent)[1:4]
    assert title == "Joe's mini at Courtyard"
    assert message.startswith("Joe's mini (TJ912UKL)")
    assert priority == "medium"
    assert last(sent)[6] == {"media": {"camera_entity_id": CAMERA}}
    from custom_components.camera_autonotify.vehicles import vehicles

    assert vehicles(hass).sightings("TJ912UKL")


async def test_no_camera_chosen(hass: HomeAssistant, sent: AsyncMock):
    """Said as at the entry, with no image"""
    await watching(hass, ALPR, ["plates"])
    hass.bus.async_fire("image_processing.found_plate", {"plate": "PX19TVD", "entity_id": ALPR, "confidence": 91.0})
    await hass.async_block_till_done()
    assert last(sent)[1] == "PX19TVD at Courtyard"
    assert last(sent)[6] == {}


async def test_not_sure_enough_nor_another_entity(hass: HomeAssistant, sent: AsyncMock):
    await watching(hass, ALPR, ["plates"], image_processing_confidence=95)
    hass.bus.async_fire("image_processing.found_plate", {"plate": "PX19TVD", "entity_id": ALPR, "confidence": 91.0})
    hass.bus.async_fire(
        "image_processing.found_plate", {"plate": "PX19TVD", "entity_id": "image_processing.other", "confidence": 99.0}
    )
    await hass.async_block_till_done()
    sent.assert_not_awaited()


async def test_faces_notified(hass: HomeAssistant, sent: AsyncMock):
    await watching(hass, FACES, ["faces"], camera_entity=CAMERA, priority="low")
    hass.bus.async_fire("image_processing.detect_face", {"name": "Joe", "entity_id": FACES, "confidence": 90})
    hass.bus.async_fire("image_processing.detect_face", {"entity_id": FACES})
    # a plate event of the same entity is no face
    hass.bus.async_fire("image_processing.found_plate", {"plate": "PX19TVD", "entity_id": FACES, "confidence": 99.0})
    await hass.async_block_till_done()
    said = sorted((call.args[1], call.args[2], call.args[3]) for call in sent.await_args_list)
    assert said == [("Face detected at Courtyard", "Face not recognised", "low"), ("Joe detected at Courtyard", "", "low")]


async def test_settings(hass: HomeAssistant):
    from .test_settings import fields_of

    add_frigate(hass)
    processing(hass, ALPR, "alpr")
    await set_up_discovery(hass)
    entry = next(iter(entries(hass).values()))
    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert form["step_id"] == "image_processing"
    assert {"camera_entity", "image_processing_confidence", "quiet_period", "priority"} <= set(fields_of(dict(form)))
    await hass.config_entries.options.async_configure(
        form["flow_id"],
        {"camera_entity": CAMERA, "image_processing_confidence": 90, "quiet_period": 300, "priority": "medium", "notify": {}},
    )
    # only what differs from as they come
    assert dict(entry.options) == {"camera_entity": CAMERA, "image_processing_confidence": 90}
