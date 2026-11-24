"""Objects notified from their events before Frigate has a review of them, as a car that stops as it comes into view
isn't, until it moves, modelled on the doorbell camera's car of 2026-11-24"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.camera_autonotify.const import CONF_NOTIFY_FROM
from custom_components.camera_autonotify.frigate import review_severity
from custom_components.camera_autonotify.tracker import (
    NOTIFY_FROM_REVIEWS,
    STALE_AFTER,
    Decision,
    Reason,
    ReviewTracker,
    Settings,
    Wait,
)
from tests.ha_testing import async_fire_time_changed

from .conftest import FakeMQTT, add_frigate, mock_supernotify
from .test_discovery import set_up_discovery
from .test_settings import entry_titled

T0 = 1_795_541_603.0
CAR = "1795541603.399195-ahh838"
REVIEW = "1795541695.604519-pbpsfk"
# the doorbell camera's review config, alerts only in its zones
DOORBELL = {
    "cameras": {
        "doorbell": {
            "review": {
                "alerts": {"labels": ["car", "person"], "required_zones": ["pend_entrance", "pend"]},
                "detections": {"labels": ["sheep"], "required_zones": []},
            }
        }
    }
}


def severity(camera: str, label: str, zones: tuple[str, ...]) -> str | None:
    return review_severity(DOORBELL, camera, label, zones)


def tracker(zone: str | None = None, **settings: Any) -> ReviewTracker:
    if zone:
        return ReviewTracker(Settings(**settings), zone=zone, severity=severity)
    return ReviewTracker(Settings(**settings), camera="doorbell", severity=severity)


def event(
    kind: str = "update",
    object_id: str = CAR,
    zones: tuple[str, ...] = ("pend",),
    stationary: bool = False,
    label: str = "car",
) -> dict[str, Any]:
    after = {
        "id": object_id,
        "camera": "doorbell",
        "label": label,
        "sub_label": None,
        "current_zones": list(zones),
        "entered_zones": list(zones),
        "stationary": stationary,
        "false_positive": False,
        "position_changes": 0,
    }
    return {"type": kind, "before": after, "after": after}


def reviewed(object_ids: tuple[str, ...] = (CAR,), kind: str = "new", review_id: str = REVIEW) -> dict[str, Any]:
    after = {
        "id": review_id,
        "camera": "doorbell",
        "severity": "alert",
        "start_time": T0 + 92,
        "end_time": T0 + 94 if kind == "end" else None,
        "data": {"objects": ["car"], "zones": ["pend"], "detections": list(object_ids), "sub_labels": []},
    }
    return {"type": kind, "before": after, "after": after}


def test_severity_by_frigate_config():
    assert severity("doorbell", "car", ("pend",)) == "alert"
    # outside the zones alerts need, and not a detection's label
    assert severity("doorbell", "car", ()) is None
    assert severity("doorbell", "sheep", ()) == "detection"
    assert severity("front", "car", ("pend",)) is None
    any_detection = {"cameras": {"gate": {"review": {"alerts": {"labels": ["person"]}, "detections": {}}}}}
    assert review_severity(any_detection, "gate", "cat", ()) == "detection"
    assert review_severity(any_detection, "gate", "person", ()) == "alert"


def test_car_stopping_in_view_notified_from_its_event():
    found = tracker()
    # seen as it stops, at the edge of the frame, not yet in a zone
    assert found.on_event(event(zones=()), T0) is None
    wait = found.on_event(event(), T0 + 1)
    assert wait == Wait(CAR, T0 + 3, Reason.NEW)
    # no review by then, so notified by itself
    decision = found.on_timer(CAR, T0 + 3)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.NEW
    assert decision.review.label == "Car"
    assert decision.review.zones == ("pend",)
    assert decision.review.severity == "alert"
    assert decision.review.standalone
    assert decision.key == decision.detection_id == CAR
    assert not decision.silent
    # nothing more for the event alone
    assert found.on_event(event(stationary=True), T0 + 10) is None


def test_review_takes_over_the_notification():
    found = tracker()
    found.on_event(event(), T0)
    found.on_timer(CAR, T0 + 2)
    # the car moves off, 92s later, and is reviewed at last
    decision = found.on_message(reviewed(), T0 + 92)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.REVIEWED
    assert decision.review.id == REVIEW
    assert decision.previous == 1
    assert decision.silent
    assert decision.key == decision.detection_id == CAR
    assert not decision.review.standalone
    assert found.tracked == [REVIEW]
    # and its updates follow, as any review's
    assert found.on_message(reviewed(kind="update"), T0 + 93) is None


def test_review_ending_as_it_takes_over():
    found = tracker(summaries=False, descriptions=False)
    found.on_event(event(), T0)
    found.on_timer(CAR, T0 + 2)
    decision = found.on_message(reviewed(kind="end"), T0 + 94)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.REVIEWED
    assert found.tracked == []


def test_review_within_the_wait_notified_itself():
    found = tracker()
    found.on_event(event(), T0)
    decision = found.on_message(reviewed(), T0 + 1)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.NEW
    assert decision.key == REVIEW
    assert found.on_timer(CAR, T0 + 2) is None


def test_object_already_reviewed_left_to_the_review():
    found = tracker()
    found.on_message(reviewed(), T0)
    assert found.on_event(event(), T0 + 1) is None


@pytest.mark.parametrize(
    ("message", "settings"),
    [
        (event(stationary=True), {}),
        (event(zones=()), {}),
        (event(kind="end"), {}),
        # a detection, alerts only being chosen
        (event(label="sheep", zones=("pend",)), {}),
        (event(), {"labels": frozenset({"person"})}),
        (event(), {"zones": ("pend_entrance",)}),
        (event(), {"notify_from": NOTIFY_FROM_REVIEWS}),
    ],
)
def test_events_not_notified(message: dict[str, Any], settings: dict[str, Any]):
    assert tracker(**settings).on_event(message, T0) is None


def test_not_without_frigate_config():
    found = ReviewTracker(Settings(), camera="doorbell")
    assert found.on_event(event(), T0) is None


def test_other_camera_not_ours():
    found = ReviewTracker(Settings(), camera="driveway", severity=severity)
    assert found.on_event(event(), T0) is None


def test_ended_before_due_not_notified():
    found = tracker()
    found.on_event(event(), T0)
    assert found.on_event(event(kind="end"), T0 + 1) is None
    assert found.on_timer(CAR, T0 + 2) is None


def test_initial_delay_kept():
    assert tracker(initial_delay=5).on_event(event(), T0) == Wait(CAR, T0 + 5, Reason.NEW)


def test_cooldown_passes_over_once():
    found = tracker()
    found.on_message(reviewed(object_ids=("someone",), review_id="person-review"), T0)
    found.on_event(event(), T0 + 1)
    assert found.on_timer(CAR, T0 + 3) is None
    # considered once only, so not notified late as the cooldown ends
    assert found.on_event(event(), T0 + 60) is None


def test_final_update_when_the_event_ends():
    found = tracker(final_update=True)
    found.on_event(event(), T0)
    found.on_timer(CAR, T0 + 2)
    decision = found.on_event(event(kind="end"), T0 + 60)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.FINAL
    assert decision.key == CAR


def test_description_updates_the_event_notification():
    found = tracker()
    found.on_event(event(), T0)
    found.on_timer(CAR, T0 + 2)
    decision = found.on_description(
        {"type": "description", "id": CAR, "camera": "doorbell", "description": "A van parks."}, T0 + 30
    )
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.DESCRIPTION
    assert decision.key == CAR


def test_zone_notified_from_events_on_any_camera():
    found = tracker(zone="pend")
    found.on_event(event(), T0)
    decision = found.on_timer(CAR, T0 + 2)
    assert isinstance(decision, Decision)
    assert tracker(zone="pend_entrance").on_event(event(), T0) is None


async def test_event_notified_through_mqtt(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up_discovery(hass)
    car = event(zones=("Pend",))
    car["after"]["camera"] = "courtyard"
    fake_mqtt.publish("frigate/events", car)
    await hass.async_block_till_done()
    assert calls == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data["title"] == "Car detected at Pend"
    assert calls[0].data["extra_data"]["mobile_push_notification_tag"] == f"frigate_{CAR}"

    # the review takes its place, tied to it
    review = reviewed()
    review["after"]["camera"] = "courtyard"
    review["after"]["data"]["zones"] = ["Pend"]
    fake_mqtt.publish("frigate/reviews", review)
    await hass.async_block_till_done()
    assert len(calls) == 2
    assert calls[1].data["extra_data"]["mobile_push_notification_tag"] == f"frigate_{CAR}"
    assert calls[1].context.parent_id == calls[0].context.id


async def test_reviews_only(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    hass.config_entries.async_update_entry(entry, options={CONF_NOTIFY_FROM: NOTIFY_FROM_REVIEWS})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    car = event(zones=("Pend",))
    car["after"]["camera"] = "courtyard"
    fake_mqtt.publish("frigate/events", car)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()
    assert calls == []


async def test_event_not_understood(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up_discovery(hass)
    fake_mqtt.publish("frigate/events", "not json")
    fake_mqtt.publish("frigate/events", "[]")
    fake_mqtt.publish("frigate/events", {"type": "new", "after": {"id": CAR, "camera": "courtyard"}})
    await hass.async_block_till_done()
    assert calls == []


def test_zone_left_before_notified_not_ours():
    entered = event(zones=("pend_entrance",))
    entered["after"]["entered_zones"] = ["pend", "pend_entrance"]
    assert tracker(zone="pend").on_event(entered, T0) is None


def test_messages_after_the_event_ended_ignored():
    found = tracker()
    found.on_event(event(), T0)
    found.on_timer(CAR, T0 + 2)
    found.on_event(event(kind="end"), T0 + 10)
    assert found.tracked == [CAR]
    assert found.on_event(event(kind="update"), T0 + 11) is None


def test_considered_forgotten_in_time():
    found = tracker()
    found.on_event(event(kind="end"), T0)
    found.on_event(event(), T0 + 1)
    found.on_event(event(kind="end"), T0 + 2)
    assert found.on_event(event(), T0 + 2 + STALE_AFTER + 10) is not None


async def test_event_with_bad_fields_logged(hass: HomeAssistant, fake_mqtt: FakeMQTT, caplog: pytest.LogCaptureFixture):
    add_frigate(hass)
    await set_up_discovery(hass)
    car = event(zones=("Pend",))
    car["after"] |= {"camera": "courtyard", "current_zones": 5}
    fake_mqtt.publish("frigate/events", car)
    await hass.async_block_till_done()
    assert "Event not understood" in caplog.text
