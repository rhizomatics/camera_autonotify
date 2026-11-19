"""Number plates read by anpr2mqtt: found, when they're notified, what's said, the linked camera, and its health"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant, State
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.camera_autonotify.anpr import (
    STARTUP_GRACE,
    AnprNotifier,
    PlateTracker,
    Sighting,
    dvla,
    find_linked_camera,
)
from custom_components.camera_autonotify.const import (
    CONF_KIND_PRIORITIES,
    CONF_KIND_SCENARIOS,
    CONF_LINKED_CAMERA,
    CONF_LINKED_CAMERA_AUTO,
    DOMAIN,
    TYPE_ANPR,
)
from custom_components.camera_autonotify.texts import async_load_texts
from tests.ha_testing import MockConfigEntry, async_fire_time_changed, async_mock_service

from .conftest import FRIGATE_ENTRY_ID, add_frigate, mock_supernotify
from .test_discovery import set_up_discovery
from .test_settings import fields_of

SENSOR = "sensor.anpr_driveway"
IMAGE = "image.anpr_driveway"
NOW = datetime(2026, 11, 9, 14, 25, 3, tzinfo=dt_util.UTC)


def add_anpr(hass: HomeAssistant, camera: str = "driveway", area: str | None = None) -> str:
    """anpr2mqtt's device, sensor and image for a camera, as its MQTT discovery makes them, and a target sensor with
    no device, and another MQTT sensor, neither to be taken for a camera"""
    mqtt = MockConfigEntry(domain="mqtt", entry_id="01MQTT")
    mqtt.add_to_hass(hass)
    area_id = ar.async_get(hass).async_get_or_create(area).id if area else None
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt.entry_id,
        identifiers={("mqtt", f"{camera}.anpr2mqtt")},
        name=f"anpr2mqtt on {camera}",
        manufacturer="Rhizomatics",
        model="anpr2mqtt",
    )
    if area_id:
        dr.async_get(hass).async_update_device(device.id, area_id=area_id)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "mqtt",
        f"anpr_{camera}",
        device_id=device.id,
        config_entry=mqtt,
        suggested_object_id=f"anpr_{camera}",
        original_name=f"anpr {camera}",
    )
    registry.async_get_or_create(
        "image", "mqtt", f"anpr_{camera}", device_id=device.id, config_entry=mqtt, suggested_object_id=f"anpr_{camera}"
    )
    registry.async_get_or_create("sensor", "mqtt", "plate_known", config_entry=mqtt, suggested_object_id="plate_known")
    other = dr.async_get(hass).async_get_or_create(config_entry_id=mqtt.entry_id, identifiers={("mqtt", "x")}, name="x")
    registry.async_get_or_create("sensor", "mqtt", "other", device_id=other.id, config_entry=mqtt)
    hass.states.async_set(IMAGE, "2026-11-09T14:25:03", {"access_token": "t0k3n"})
    return device.id


def attributes(**given: Any) -> dict[str, Any]:
    """A sighting as anpr2mqtt publishes it, an unknown car seen twice before, from the filesystem, now"""
    return {
        "description": None,
        "known": False,
        "dangerous": False,
        "ignore": False,
        "priority": None,
        "camera": "driveway",
        "linked_cameras": {},
        "reg_info": None,
        "history": {"previous_sightings": 2, "last_seen": "2026-11-02T09:10:00", "is_new_visit": True},
        "source": "filesystem",
        "event_time": dt_util.utcnow().isoformat(),
        **given,
    }


def state(plate: str = "PX19TVD", **given: Any) -> State:
    return State(SENSOR, plate, attributes(**given))


async def anpr_entry(hass: HomeAssistant, **options: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="anpr driveway",
        data={CONF_TYPE: TYPE_ANPR, "source": "anpr2mqtt", "source_entry_id": "01MQTT", "source_name": "anpr_driveway"},
        options=options,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(autouse=True)
def frozen(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    freezer.move_to(NOW)
    return freezer


# --- which changes are new sightings


def test_sighting_kinds():
    assert Sighting.from_state(state()).kind == "unknown"
    assert Sighting.from_state(state(known=True)).kind == "known"
    assert Sighting.from_state(state(known=True, ignore=True)).kind == "ignored"
    assert Sighting.from_state(state(known=True, ignore=True, dangerous=True)).kind == "dangerous"


def test_sighting_without_history():
    found = Sighting.from_state(state(history=None, linked_cameras=None))
    assert (found.previous, found.last_seen, found.new_visit, found.linked_cameras) == (0, None, True, {})


def tracker() -> PlateTracker:
    return PlateTracker(started=NOW.timestamp() - STARTUP_GRACE - 1)


def test_new_plate_notified():
    assert tracker().sighting(state("PREVIOUS"), state(), NOW.timestamp()) is not None


@pytest.mark.parametrize("cleared", ["unknown", "unavailable"])
def test_not_a_plate(cleared: str):
    assert tracker().sighting(state(), State(SENSOR, cleared), NOW.timestamp()) is None


def test_retained_as_followed():
    """The state anpr2mqtt retained arrives as the sensor is followed, and is remembered, not notified"""
    plates = PlateTracker(started=NOW.timestamp())
    assert plates.sighting(None, state(), NOW.timestamp() + 1) is None
    assert plates.last_plate == "PX19TVD"


def test_other_kinds_of_detection_left_alone():
    """A face or a line crossed, which anpr2mqtt can read from a camera's images too, not yet notified"""
    assert tracker().sighting(state("PREVIOUS"), state("Jey", target_type="face"), NOW.timestamp()) is None
    assert tracker().sighting(state("PREVIOUS"), state(target_type="plate"), NOW.timestamp()) is not None


def test_republished():
    assert tracker().sighting(state("PREVIOUS"), state(trigger="homeassistant/status"), NOW.timestamp()) is None


def test_same_sighting_with_details_added():
    """The DVLA's details added later, the same plate at the same time"""
    before = state()
    after = state(reg_info={"make": "MITSUBISHI"}, event_time=before.attributes["event_time"])
    assert tracker().sighting(before, after, NOW.timestamp()) is None


def test_stale_sighting():
    old = (NOW - timedelta(minutes=11)).isoformat()
    assert tracker().sighting(state("PREVIOUS"), state(event_time=old), NOW.timestamp()) is None


def test_same_plate_same_visit():
    plates = tracker()
    assert plates.sighting(state("PREVIOUS"), state(), NOW.timestamp()) is not None
    same_visit = {"previous_sightings": 3, "last_seen": NOW.isoformat(), "is_new_visit": False}
    assert plates.sighting(State(SENSOR, "unknown"), state(history=same_visit), NOW.timestamp() + 30) is None
    # but a new visit is
    assert plates.sighting(State(SENSOR, "unknown"), state(), NOW.timestamp() + 600) is not None


# --- what's said


async def test_title_and_message(hass: HomeAssistant):
    await async_load_texts(hass)
    add_anpr(hass)
    notifier = AnprNotifier(hass, await anpr_entry(hass))
    known = Sighting.from_state(
        state(description="Jey's Outlander", reg_info={"make": "MITSUBISHI", "colour": "WHITE", "taxStatus": "Taxed"})
    )
    assert notifier.title(known, None) == "Jey's Outlander at Driveway"
    assert notifier.message(known).splitlines() == [
        "Plate PX19TVD",
        "Previous sightings: 2, last on Monday 2 November 09:10",
        "DVLA: MITSUBISHI, WHITE, Taxed",
    ]
    # named by its plate where anpr2mqtt has no description, and never seen before
    unknown = Sighting.from_state(state(history={"previous_sightings": 0}))
    assert notifier.title(unknown, None) == "PX19TVD at Driveway"
    assert notifier.message(unknown) == "Not seen before"


def test_dvla():
    assert dvla({"make": "FORD", "colour": "", "yearOfManufacture": 2019}) == "FORD, 2019"
    assert dvla("No details") == "No details"
    assert dvla({}) is None
    assert dvla(None) is None


@pytest.mark.parametrize(
    ("given", "options", "priority"),
    [
        ({}, {}, "high"),
        ({"dangerous": True}, {}, "critical"),
        ({"known": True, "priority": "low"}, {}, "low"),
        ({"known": True}, {}, "medium"),
        ({"ignore": True}, {}, None),
        ({"known": True}, {CONF_KIND_PRIORITIES["known"]: "none"}, None),
        ({"ignore": True}, {CONF_KIND_PRIORITIES["ignored"]: "low"}, "low"),
    ],
)
async def test_priority_by_kind(hass: HomeAssistant, given: dict[str, Any], options: dict[str, Any], priority: str | None):
    notifier = AnprNotifier(hass, await anpr_entry(hass, **options))
    assert notifier.priority(Sighting.from_state(state(**given))) == priority


async def test_supernotify_call(hass: HomeAssistant):
    """The kind's scenarios applied, and only those of a kind allowed, the image from anpr2mqtt's image entity, served
    by Home Assistant, and the image entity as the camera without a linked camera"""
    await async_process_ha_core_config(hass, {"external_url": "https://example.ui.nabu.casa"})
    await async_load_texts(hass)
    add_anpr(hass)
    entry = await anpr_entry(
        hass,
        **{
            CONF_KIND_SCENARIOS["unknown"]: ["unknown_vehicle"],
            CONF_KIND_SCENARIOS["known"]: ["known_vehicle"],
            "deliveries": ["email"],
        },
    )
    data = AnprNotifier(hass, entry).supernotify_data(Sighting.from_state(state()), "high")
    assert data["title"] == "PX19TVD at Driveway"
    # the plate not said twice, being the title already
    assert data["spoken_message"] == "PX19TVD at Driveway"
    assert data["apply_scenarios"] == ["unknown_vehicle"]
    assert data["constrain_scenarios"] == ["known_vehicle", "unknown_vehicle"]
    assert data["media"] == {
        "snapshot_url": f"https://example.ui.nabu.casa/api/image_proxy/{IMAGE}?token=t0k3n",
        "camera_entity_id": IMAGE,
    }
    assert data["delivery"] == ["email"]


async def test_frigate_sighting_by_notification_proxy(hass: HomeAssistant):
    """Never Frigate's own LAN address, but the notification proxy, and the clip when tapped, the linked Frigate
    camera being the camera"""
    await async_process_ha_core_config(hass, {"external_url": "https://example.ui.nabu.casa"})
    await async_load_texts(hass)
    add_frigate(hass, cameras={"driveway": []})
    add_anpr(hass)
    camera = er.async_get(hass).async_get_entity_id("camera", "frigate", f"{FRIGATE_ENTRY_ID}:camera:driveway")
    notifier = AnprNotifier(hass, await anpr_entry(hass))
    found = Sighting.from_state(
        state(source="frigate", frigate_event_id="1792602227.86265-dyoaxn", linked_cameras={"frigate": "driveway"})
    )
    data = notifier.supernotify_data(found, "high")
    proxy = "https://example.ui.nabu.casa/api/frigate/notifications/1792602227.86265-dyoaxn"
    assert data["media"] == {"snapshot_url": f"{proxy}/snapshot.jpg", "camera_entity_id": camera}
    assert data["actions"] == [{"level": "notification", "uri": f"{proxy}/driveway/master.m3u8"}]


# --- the linked camera


async def test_linked_by_anpr2mqtt(hass: HomeAssistant):
    add_frigate(hass, cameras={"gate": [], "driveway": []})
    add_anpr(hass)
    camera = er.async_get(hass).async_get_entity_id("camera", "frigate", f"{FRIGATE_ENTRY_ID}:camera:gate")
    assert find_linked_camera(hass, None, {"unifiprotect": "front", "frigate": "gate"}, "driveway") == camera


def area_of_camera(hass: HomeAssistant, name: str, area: str) -> str:
    """A Frigate camera's device put in an area, its entity having no name of its own to have an area by"""
    entity_id = er.async_get(hass).async_get_entity_id("camera", "frigate", f"{FRIGATE_ENTRY_ID}:camera:{name}")
    assert entity_id is not None
    entity = er.async_get(hass).async_get(entity_id)
    assert entity is not None and entity.device_id is not None
    area_id = ar.async_get(hass).async_get_or_create(area).id
    dr.async_get(hass).async_update_device(entity.device_id, area_id=area_id)
    return entity_id


async def test_linked_by_area(hass: HomeAssistant):
    add_frigate(hass, cameras={"drive": [], "garden": []})
    add_anpr(hass, camera="lane", area="Front")
    sensor = er.async_get(hass).async_get("sensor.anpr_lane")
    # nothing in the area, and no camera named `camera.lane`
    assert find_linked_camera(hass, sensor, {}, "lane") is None
    drive = area_of_camera(hass, "drive", "Front")
    assert find_linked_camera(hass, sensor, {}, "lane") == drive


async def test_linked_by_name(hass: HomeAssistant):
    add_frigate(hass, cameras={"driveway": [], "garden": []})
    add_anpr(hass)
    camera = er.async_get(hass).async_get_entity_id("camera", "frigate", f"{FRIGATE_ENTRY_ID}:camera:driveway")
    assert camera == "camera.driveway"
    assert find_linked_camera(hass, er.async_get(hass).async_get(SENSOR), {}, "driveway") == camera


async def test_linked_to_frigate_not_onvif_nor_anpr2mqtt(hass: HomeAssistant):
    """The driveway as it is on the live install: anpr2mqtt's own camera, the same camera by ONVIF, and Frigate's,
    all in the same area, only Frigate's being a camera whose events a plate belongs with"""
    add_frigate(hass, cameras={"driveway": []})
    device_id = add_anpr(hass, area="Front")
    registry = er.async_get(hass)
    mqtt = hass.config_entries.async_get_entry("01MQTT")
    registry.async_get_or_create("camera", "mqtt", "anpr_driveway", device_id=device_id, config_entry=mqtt)
    onvif = MockConfigEntry(domain="onvif")
    onvif.add_to_hass(hass)
    camera = dr.async_get(hass).async_get_or_create(config_entry_id=onvif.entry_id, identifiers={("onvif", "drive")})
    registry.async_get_or_create(
        "camera", "onvif", "drive_main", device_id=camera.id, config_entry=onvif, suggested_object_id="driveway_main"
    )
    front = ar.async_get(hass).async_get_area_by_name("Front")
    assert front is not None
    dr.async_get(hass).async_update_device(camera.id, area_id=front.id)
    frigate = area_of_camera(hass, "driveway", "Front")
    assert find_linked_camera(hass, registry.async_get(SENSOR), {}, "driveway") == frigate


async def test_not_linked_when_unsure(hass: HomeAssistant):
    """Two cameras in the same area, so neither, rather than a guess"""
    add_frigate(hass, cameras={"drive": [], "garden": []})
    add_anpr(hass, area="Front")
    for name in ("drive", "garden"):
        area_of_camera(hass, name, "Front")
    assert find_linked_camera(hass, er.async_get(hass).async_get(SENSOR), {}, "driveway") is None


async def test_linked_as_chosen(hass: HomeAssistant):
    add_anpr(hass)
    chosen = AnprNotifier(hass, await anpr_entry(hass, **{CONF_LINKED_CAMERA_AUTO: False, CONF_LINKED_CAMERA: "camera.x"}))
    assert chosen.linked_camera() == "camera.x"
    none = AnprNotifier(hass, await anpr_entry(hass, **{CONF_LINKED_CAMERA_AUTO: False}))
    assert none.linked_camera() is None


# --- found, set up, and notified


async def set_up_anpr(hass: HomeAssistant) -> None:
    """Global Settings set up, and each anpr2mqtt source found confirmed, as it's offered even with automatic setup"""
    await set_up_discovery(hass)
    await confirm_anpr(hass)


async def confirm_anpr(hass: HomeAssistant) -> None:
    for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN):
        if flow["step_id"] == "confirm_anpr":
            await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()


async def test_found_and_set_up(hass: HomeAssistant):
    """Only anpr2mqtt's camera sensors, by its device, one entry each, by the sensor's unique id, once confirmed"""
    add_anpr(hass)
    await set_up_discovery(hass)
    assert [e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_ANPR] == []
    await confirm_anpr(hass)
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_ANPR]
    assert [(e.unique_id, e.data["source_name"]) for e in entries] == [("anpr2mqtt:anpr_driveway", "anpr_driveway")]


async def test_notified_on_a_new_sighting(hass: HomeAssistant, frozen: FrozenDateTimeFactory):
    calls = mock_supernotify(hass)
    add_anpr(hass)
    hass.states.async_set(SENSOR, "RETAINED", attributes())
    await set_up_anpr(hass)
    hass.states.async_set(SENSOR, "PX19TVD", attributes())
    await hass.async_block_till_done()
    # too soon after starting, so taken as retained
    assert calls == []
    frozen.tick(STARTUP_GRACE + 1)
    hass.states.async_set(SENSOR, "unknown", {})
    hass.states.async_set(SENSOR, "AB12CDE", attributes())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [call.data["title"] for call in calls] == ["AB12CDE at Driveway"]


async def test_plain_notification_without_supernotify(hass: HomeAssistant):
    phones = async_mock_service(hass, "notify", "send_message")
    add_anpr(hass)
    notifier = AnprNotifier(hass, await anpr_entry(hass, targets=["notify.phone"]))
    await notifier.async_notify(Sighting.from_state(state()))
    assert phones[0].data == {
        "entity_id": ["notify.phone"],
        "title": "PX19TVD at Driveway",
        "message": "Previous sightings: 2, last on Monday 2 November 09:10",
    }


async def test_no_delivery(hass: HomeAssistant):
    calls = mock_supernotify(hass)
    notifier = AnprNotifier(hass, await anpr_entry(hass))
    await notifier.async_notify(Sighting.from_state(state(ignore=True)))
    assert calls == []


async def test_anpr2mqtt_down_and_back(hass: HomeAssistant, frozen: FrozenDateTimeFactory):
    """Unavailable for as long as a Frigate server's retries take, then back"""
    calls = mock_supernotify(hass)
    add_anpr(hass)
    hass.states.async_set(SENSOR, "PX19TVD", attributes())
    await set_up_anpr(hass)
    hass.states.async_set(SENSOR, "unavailable", {})
    await hass.async_block_till_done()
    frozen.tick(60 * 4 + 1)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [call.data["title"] for call in calls] == ["anpr driveway plate reader is not responding"]
    hass.states.async_set(SENSOR, "unknown", {})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls[-1].data["title"] == "anpr driveway plate reader is back"


async def test_brief_outage_not_notified(hass: HomeAssistant, frozen: FrozenDateTimeFactory):
    calls = mock_supernotify(hass)
    add_anpr(hass)
    hass.states.async_set(SENSOR, "PX19TVD", attributes())
    await set_up_anpr(hass)
    hass.states.async_set(SENSOR, "unavailable", {})
    hass.states.async_set(SENSOR, "unknown", {})
    frozen.tick(60 * 5)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls == []


# --- the settings


async def test_settings_form(hass: HomeAssistant):
    mock_supernotify(hass)
    add_frigate(hass, cameras={"driveway": []})
    add_anpr(hass)
    hass.states.async_set(SENSOR, "PX19TVD", attributes(linked_cameras={"frigate": "driveway"}))
    await set_up_anpr(hass)
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_ANPR)
    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert form["step_id"] == "anpr"
    placeholders = form["description_placeholders"] or {}
    assert "Driveway" in placeholders["linked"]
    shown = fields_of(dict(form))
    assert shown["vehicles.priority_known"].config["options"][0] == "anpr2mqtt"
    # only cameras of integrations whose events a plate belongs with
    assert {f["integration"] for f in shown["linked_camera"].config["filter"]} == {
        "frigate",
        "unifiprotect",
        "viseron",
        "blueiris",
    }
    assert {"linked_camera_auto", "linked_camera", "vehicles.scenarios_unknown", "notify.deliveries"} <= set(shown)
    await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            CONF_LINKED_CAMERA_AUTO: True,
            "vehicles": {CONF_KIND_PRIORITIES["known"]: "none", CONF_KIND_PRIORITIES["unknown"]: "high"},
            "notify": {},
        },
    )
    await hass.async_block_till_done()
    # only what differs from as they come
    assert dict(entry.options) == {CONF_KIND_PRIORITIES["known"]: "none"}


async def test_settings_without_linked_camera(hass: HomeAssistant):
    add_anpr(hass)
    await set_up_anpr(hass)
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_ANPR)
    form = await hass.config_entries.options.async_init(entry.entry_id)
    placeholders = form["description_placeholders"] or {}
    assert placeholders["linked"].startswith("No linked camera was found")
