"""anpr2mqtt's events without a target, such as a face: found, what's a new event, what's said, and the settings"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant, State
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.camera_autonotify.anpr import STALE_AFTER, STARTUP_GRACE
from custom_components.camera_autonotify.anpr_events import AnprEvent, EventTracker
from custom_components.camera_autonotify.const import DOMAIN, TYPE_ANPR_EVENT
from tests.ha_testing import MockConfigEntry

from .conftest import add_frigate, mock_supernotify
from .test_discovery import set_up_discovery
from .test_settings import fields_of

EVENT = "event.face_front"
FACE = "image.face_front"
SCENE = "image.face_front_face_background"
NOW = datetime(2026, 11, 27, 12, 0, 0, tzinfo=dt_util.UTC)


def add_events(hass: HomeAssistant, scene: bool = True) -> str:
    """anpr2mqtt's device for a camera, with its plate sensor, and a face event, its face image, and the scene"""
    mqtt = MockConfigEntry(domain="mqtt", entry_id="01MQTT")
    mqtt.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt.entry_id,
        identifiers={("mqtt", "front.anpr2mqtt")},
        name="anpr2mqtt on front",
        manufacturer="Rhizomatics",
        model="anpr2mqtt",
    )
    registry = er.async_get(hass)
    for domain, unique_id in [("sensor", "anpr_front"), ("event", "face_front"), ("image", "face_front")] + (
        [("image", "face_front_face_background")] if scene else []
    ):
        registry.async_get_or_create(
            domain,
            "mqtt",
            unique_id,
            device_id=device.id,
            config_entry=mqtt,
            suggested_object_id=unique_id,
            original_name=unique_id,
        )
    hass.states.async_set(FACE, "2026-11-27T12:00:00", {"access_token": "f4c3"})
    return device.id


def fired(when: datetime = NOW, **given: Any) -> dict[str, Any]:
    """An event's attributes, from its own payload, as anpr2mqtt publishes a face"""
    return {
        "event_type": "face",
        "target_type": "face",
        "target": None,
        "description": "Face",
        "camera": "front",
        "linked_cameras": {},
        "event_time": when.isoformat(),
        "image_event": "FACE_SNAP",
        "images": {"camera": {"today": 3}},
    } | given


def state(value: str = NOW.isoformat(), **given: Any) -> State:
    return State(EVENT, value, fired(**given))


def test_what_is_a_new_event():
    tracker = EventTracker(NOW.timestamp() - 100)
    now = NOW.timestamp()
    later = (NOW + timedelta(seconds=5)).isoformat()
    found = tracker.event(state(), state(later, event_time=later), now + 5)
    assert found == AnprEvent("face", "Face", "front", {}, later, "face", "FACE_SNAP")
    assert found.said == "Face"
    # added, or restored as Home Assistant started
    assert tracker.event(None, state(), now) is None
    # only its image counts updated
    assert tracker.event(state(), state(images={"camera": {"today": 4}}), now) is None
    assert tracker.event(state(), State(EVENT, "unavailable"), now) is None
    old = (NOW - timedelta(seconds=STALE_AFTER + 1)).isoformat()
    assert tracker.event(state(), state(old, event_time=old), now) is None


def test_restored_once_back_not_new():
    tracker = EventTracker(NOW.timestamp())
    assert tracker.event(State(EVENT, "unavailable"), state(), NOW.timestamp() + 1) is None
    assert tracker.event(State(EVENT, "unavailable"), state(), NOW.timestamp() + STARTUP_GRACE + 1) is not None


def test_said_by_event_name_without_description():
    assert AnprEvent("scene_change").said == "Scene change"


def event_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_ANPR_EVENT]


async def test_found_and_set_up(hass: HomeAssistant):
    """The event entity, its own entry, by its unique id, set up as Frigate's cameras are, beside the plate sensor"""
    add_events(hass)
    await set_up_discovery(hass, anpr2mqtt_silent=True)
    assert [(e.unique_id, e.data["source_name"], e.data["source"]) for e in event_entries(hass)] == [
        ("anpr2mqtt:event:face_front", "face_front", "anpr2mqtt")
    ]
    # and the plate sensor, as chosen for anpr2mqtt
    assert any(e.unique_id == "anpr2mqtt:anpr_front" for e in hass.config_entries.async_entries(DOMAIN))


async def test_offered_with_automatic_discovery_off(hass: HomeAssistant):
    add_events(hass)
    await set_up_discovery(hass, auto_discover=False)
    flow = next(f for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN) if f["step_id"] == "confirm_anpr_event")
    await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    assert len(event_entries(hass)) == 1


@pytest.fixture
async def external_url(hass: HomeAssistant) -> None:
    await async_process_ha_core_config(hass, {"external_url": "https://home.example"})


async def test_notified(hass: HomeAssistant, freezer: FrozenDateTimeFactory, external_url: None):
    freezer.move_to(NOW)
    calls = mock_supernotify(hass)
    add_events(hass)
    hass.states.async_set(EVENT, NOW.isoformat(), fired())
    await set_up_discovery(hass, anpr2mqtt_silent=True)
    freezer.tick(STARTUP_GRACE + 1)
    when = dt_util.utcnow()
    hass.states.async_set(EVENT, when.isoformat(), fired(when))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 1
    data = calls[0].data
    assert data["title"] == "Face at Front"
    assert data["priority"] == "medium"
    assert data["media"] == {
        "snapshot_url": "https://home.example/api/image_proxy/image.face_front?token=f4c3",
        "camera_entity_id": FACE,
    }
    assert data["extra_data"]["group"] == "anpr_front"
    assert data["extra_data"]["mobile_push_notification_tag"].startswith("anpr_event_")

    # another straight after, within the quiet period, isn't
    freezer.tick(5)
    when = dt_util.utcnow()
    hass.states.async_set(EVENT, when.isoformat(), fired(when))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 1


async def test_linked_camera_scenarios_and_priority(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    freezer.move_to(NOW)
    calls = mock_supernotify(hass)
    add_frigate(hass, cameras={"front": []})
    add_events(hass, scene=False)
    hass.states.async_set("camera.front", "idle", {"friendly_name": "Front Door"})
    await set_up_discovery(hass, anpr2mqtt_silent=True)
    entry = event_entries(hass)[0]
    hass.config_entries.async_update_entry(entry, options={"priority": "high", "scenarios": ["face_seen"]})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(STARTUP_GRACE + 1)
    when = dt_util.utcnow()
    hass.states.async_set(EVENT, NOW.isoformat(), fired())
    hass.states.async_set(EVENT, when.isoformat(), fired(when, linked_cameras={"frigate": "front"}))
    await hass.async_block_till_done(wait_background_tasks=True)
    data = calls[-1].data
    assert data["title"] == "Face at Front Door"
    assert data["priority"] == "high"
    assert data["apply_scenarios"] == ["face_seen"]
    assert data["media"]["camera_entity_id"] == "camera.front"


async def test_not_notified_when_chosen(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    freezer.move_to(NOW)
    calls = mock_supernotify(hass)
    add_events(hass)
    await set_up_discovery(hass, anpr2mqtt_silent=True)
    entry = event_entries(hass)[0]
    hass.config_entries.async_update_entry(entry, options={"priority": "none"})
    await hass.config_entries.async_reload(entry.entry_id)
    freezer.tick(STARTUP_GRACE + 1)
    when = dt_util.utcnow()
    hass.states.async_set(EVENT, NOW.isoformat(), fired())
    hass.states.async_set(EVENT, when.isoformat(), fired(when))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls == []


async def test_event_entity_gone(hass: HomeAssistant):
    """Removed from anpr2mqtt, so a repair rather than retrying"""
    add_events(hass)
    await set_up_discovery(hass, anpr2mqtt_silent=True)
    entry = event_entries(hass)[0]
    registry = er.async_get(hass)
    registry.async_remove(registry.async_get_entity_id("event", "mqtt", "face_front") or "")
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"source_gone_{entry.entry_id}") is not None


async def test_settings_form(hass: HomeAssistant):
    mock_supernotify(hass)
    add_events(hass)
    await set_up_discovery(hass, anpr2mqtt_silent=True)
    entry = event_entries(hass)[0]
    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert form["step_id"] == "anpr_event"
    shown = fields_of(dict(form))
    assert set(shown) == {
        "linked_camera_auto",
        "linked_camera",
        "quiet_period",
        "priority",
        "scenarios",
        "notify.target",
        "notify.custom_target",
        "notify.deliveries",
    }
    assert shown["priority"].config["options"][-1] == "none"
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {"linked_camera_auto": True, "quiet_period": 60, "priority": "medium", "scenarios": ["face_seen"], "notify": {}},
    )
    # only what differs from how it comes
    assert result["data"] == {"quiet_period": 60, "scenarios": ["face_seen"]}
