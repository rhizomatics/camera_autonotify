from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.camera_autonotify.tracker import (
    STALE_AFTER,
    Decision,
    Reason,
    Review,
    ReviewTracker,
    Settings,
    Wait,
)

# real reviews, from the Frigate API, as the `after` of an MQTT message
REVIEWS: list[dict[str, Any]] = json.loads((Path(__file__).parent / "fixtures" / "reviews.json").read_text())
T0 = 1_800_000_000.0


def review(camera: str = "courtyard", **changes: Any) -> dict[str, Any]:
    """The first fixture of a camera, as still going on, with any of its fields or data changed"""
    base = json.loads(json.dumps(next(r for r in REVIEWS if r["camera"] == camera)))
    base["end_time"] = None
    for key, value in changes.items():
        if key in base["data"]:
            base["data"][key] = value
        else:
            base[key] = value
    return base


def message(kind: str, after: dict[str, Any]) -> dict[str, Any]:
    if kind == "end" and after.get("end_time") is None:
        after = after | {"end_time": after["start_time"] + 30}
    return {"type": kind, "before": after, "after": after}


def camera_tracker(**settings: Any) -> ReviewTracker:
    return ReviewTracker(Settings(**settings), camera="courtyard")


def test_reviews_read_from_payload():
    for after in REVIEWS:
        parsed = Review.from_payload(after)
        assert parsed.id == after["id"]
        assert parsed.zones == tuple(after["data"]["zones"])
        assert parsed.ended
    car_and_person = Review.from_payload(next(r for r in REVIEWS if r["data"]["objects"] == ["car", "person"]))
    assert car_and_person.label == "Car and Person"


def test_label_with_sub_labels_and_audio():
    parsed = Review.from_payload(review(objects=["person"], sub_labels=[["Jeff", 0.9]], audio=["dog_bark"]))
    assert parsed.objects == ("person", "dog_bark")
    assert parsed.label == "Person and Dog bark (Jeff)"
    assert Review.from_payload(review(objects=[], audio=[])).label == "Something"


def test_new_alert_notified():
    tracker = camera_tracker()
    after = review()
    decision = tracker.on_message(message("new", after), T0)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.NEW
    assert not decision.is_update
    assert not decision.silent
    assert decision.detection_id == after["data"]["detections"][0]
    assert tracker.tracked == [after["id"]]


def test_payload_as_received():
    tracker = camera_tracker()
    assert isinstance(tracker.on_message(json.dumps(message("new", review())).encode(), T0), Decision)


@pytest.mark.parametrize(
    "payload",
    [{}, {"type": "new"}, {"type": "new", "after": {"id": "x"}}, {"type": "new", "after": "x"}],
)
def test_malformed_ignored(payload: dict[str, Any]):
    assert camera_tracker().on_message(payload, T0) is None


def test_other_camera_ignored():
    tracker = camera_tracker()
    assert tracker.on_message(message("new", review("driveway")), T0) is None
    assert tracker.tracked == []


@pytest.mark.parametrize(
    ("severities", "severity", "notified"),
    [
        (frozenset({"alert"}), "alert", True),
        (frozenset({"alert"}), "detection", False),
        (frozenset({"alert", "detection"}), "detection", True),
        (frozenset({"detection"}), "alert", False),
    ],
)
def test_severity(severities: frozenset[str], severity: str, notified: bool):
    decision = camera_tracker(severities=severities).on_message(message("new", review(severity=severity)), T0)
    assert isinstance(decision, Decision) is notified


def test_detection_raised_to_alert_is_then_notified():
    tracker = camera_tracker()
    assert tracker.on_message(message("new", review(severity="detection")), T0) is None
    decision = tracker.on_message(message("update", review(severity="alert")), T0 + 5)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.NEW


def test_detection_raised_to_alert_is_an_update():
    tracker = camera_tracker(severities=frozenset({"alert", "detection"}))
    assert isinstance(tracker.on_message(message("new", review(severity="detection")), T0), Decision)
    decision = tracker.on_message(message("update", review(severity="alert")), T0 + 5)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.SEVERITY
    assert decision.is_update
    assert decision.silent


@pytest.mark.parametrize(
    ("labels", "objects", "notified"),
    [
        (frozenset(), ["person"], True),
        (frozenset({"car"}), ["person"], False),
        (frozenset({"car"}), ["car", "person"], True),
        (frozenset({"dog_bark"}), ["person"], False),
    ],
)
def test_labels(labels: frozenset[str], objects: list[str], notified: bool):
    decision = camera_tracker(labels=labels).on_message(message("new", review(objects=objects)), T0)
    assert isinstance(decision, Decision) is notified


def test_label_filter_met_later():
    tracker = camera_tracker(labels=frozenset({"car"}))
    assert tracker.on_message(message("new", review(objects=["person"])), T0) is None
    decision = tracker.on_message(message("update", review(objects=["person", "car"])), T0 + 5)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.NEW


@pytest.mark.parametrize(
    ("zones", "multi", "order", "entered", "notified"),
    [
        ((), False, False, [], True),
        (("Pend",), False, False, ["Driveway", "Pend"], True),
        (("pend",), False, False, ["Driveway", "Pend"], True),
        (("Barn_Door",), False, False, ["Driveway", "Pend"], False),
        (("Pend", "Barn_Door"), False, False, ["Pend"], True),
        (("Pend", "Barn_Door"), True, False, ["Pend"], False),
        (("Pend", "Barn_Door"), True, False, ["Barn_Door", "Pend"], True),
        (("Driveway", "Pend"), False, True, ["Driveway", "Turning_Circle", "Pend"], True),
        (("Pend", "Driveway"), False, True, ["Driveway", "Turning_Circle", "Pend"], False),
        (("Pend", "Driveway"), True, True, ["Pend"], False),
    ],
)
def test_zones(zones: tuple[str, ...], multi: bool, order: bool, entered: list[str], notified: bool):
    tracker = camera_tracker(zones=zones, zone_multi=multi, zone_order=order)
    decision = tracker.on_message(message("new", review(zones=entered)), T0)
    assert isinstance(decision, Decision) is notified


def test_cooldown_between_reviews():
    tracker = camera_tracker(cooldown=30)
    assert isinstance(tracker.on_message(message("new", review(id="a")), T0), Decision)
    assert tracker.on_message(message("new", review(id="b")), T0 + 10) is None
    # nor any of its updates, once passed over
    assert tracker.on_message(message("update", review(id="b", objects=["person", "car"])), T0 + 40) is None
    assert tracker.on_message(message("end", review(id="b")), T0 + 41) is None
    assert "b" not in tracker.tracked
    assert isinstance(tracker.on_message(message("new", review(id="c")), T0 + 31), Decision)


def test_updates():
    tracker = camera_tracker()
    tracker.on_message(message("new", review(objects=["person"])), T0)
    assert tracker.on_message(message("update", review(objects=["person"])), T0 + 1) is None

    car = tracker.on_message(message("update", review(objects=["person", "car"])), T0 + 2)
    assert isinstance(car, Decision)
    assert (car.reason, car.previous, car.silent) == (Reason.LABEL, 1, True)

    face = tracker.on_message(message("update", review(objects=["person", "car"], sub_labels=["Jeff"])), T0 + 3)
    assert isinstance(face, Decision)
    assert face.reason is Reason.SUB_LABEL
    assert face.review.label == "Person and Car (Jeff)"
    assert face.previous == 2


def test_update_only_for_labels_chosen():
    tracker = camera_tracker(labels=frozenset({"person"}))
    tracker.on_message(message("new", review(objects=["person"])), T0)
    assert tracker.on_message(message("update", review(objects=["person", "bird"])), T0 + 1) is None


def test_sub_label_update_switched_off():
    tracker = camera_tracker(update_sub_label=False)
    tracker.on_message(message("new", review(objects=["person"])), T0)
    assert tracker.on_message(message("update", review(objects=["person"], sub_labels=["Jeff"])), T0 + 1) is None


def test_zone_update_only_for_zones_chosen():
    tracker = camera_tracker(zones=("Pend", "Back_Door"))
    tracker.on_message(message("new", review(zones=["Pend"])), T0)
    assert tracker.on_message(message("update", review(zones=["Pend", "Barn_Door"])), T0 + 1) is None
    decision = tracker.on_message(message("update", review(zones=["Pend", "Barn_Door", "Back_Door"])), T0 + 2)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.ZONE


def test_every_notification_sounds_without_alert_once():
    tracker = camera_tracker(alert_once=False)
    tracker.on_message(message("new", review(objects=["person"])), T0)
    decision = tracker.on_message(message("update", review(objects=["person", "car"])), T0 + 1)
    assert isinstance(decision, Decision)
    assert not decision.silent


def test_initial_delay_sends_review_as_it_then_is():
    tracker = camera_tracker(initial_delay=5)
    after = review(objects=["person"])
    wait = tracker.on_message(message("new", after), T0)
    assert wait == Wait(after["id"], T0 + 5, Reason.NEW)
    # changes while held back go in the one notification, not one of their own
    assert tracker.on_message(message("update", review(objects=["person", "car"])), T0 + 2) is None
    decision = tracker.on_timer(after["id"], T0 + 5)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.NEW
    assert decision.review.objects == ("person", "car")
    assert tracker.on_timer(after["id"], T0 + 6) is None


def test_ended_while_held_back_told_once():
    tracker = camera_tracker(initial_delay=5, final_update=True)
    after = review()
    tracker.on_message(message("new", after), T0)
    assert tracker.on_message(message("end", after), T0 + 2) is None
    decision = tracker.on_timer(after["id"], T0 + 5)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.NEW
    assert tracker.tracked == []


def test_review_only_seen_ended_told_once():
    tracker = camera_tracker(final_update=True)
    decision = tracker.on_message(message("end", review()), T0)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.NEW
    assert tracker.tracked == []


def test_unwanted_end_not_tracked():
    tracker = camera_tracker()
    assert tracker.on_message(message("end", review(severity="detection")), T0) is None
    assert tracker.tracked == []


def test_end_forgotten_without_final_update():
    tracker = camera_tracker()
    after = review()
    tracker.on_message(message("new", after), T0)
    assert tracker.on_message(message("end", after), T0 + 30) is None
    assert tracker.tracked == []


def test_final_update():
    tracker = camera_tracker(final_update=True)
    after = review()
    tracker.on_message(message("new", after), T0)
    decision = tracker.on_message(message("end", after), T0 + 30)
    assert isinstance(decision, Decision)
    assert decision.is_final
    assert decision.silent
    assert tracker.tracked == []


def test_final_update_delayed():
    tracker = camera_tracker(final_update=True, final_delay=10)
    after = review()
    tracker.on_message(message("new", after), T0)
    assert tracker.on_message(message("end", after), T0 + 30) == Wait(after["id"], T0 + 40, Reason.FINAL)
    decision = tracker.on_timer(after["id"], T0 + 40)
    assert isinstance(decision, Decision)
    assert decision.is_final
    assert tracker.tracked == []


def test_nothing_after_timeout():
    tracker = camera_tracker(timeout=60)
    tracker.on_message(message("new", review(objects=["person"])), T0)
    assert tracker.on_message(message("update", review(objects=["person", "car"])), T0 + 61) is None
    assert tracker.tracked == []


def test_stale_reviews_forgotten():
    tracker = camera_tracker()
    tracker.on_message(message("new", review(id="old")), T0)
    tracker.on_message(message("new", review(id="new")), T0 + STALE_AFTER + 1)
    assert tracker.tracked == ["new"]


def test_timer_for_unknown_review():
    assert camera_tracker().on_timer("nothing", T0) is None


def test_zone_tracker_follows_any_camera():
    tracker = ReviewTracker(Settings(), zone="pend")
    assert tracker.on_message(message("new", review("courtyard", zones=["Barn_Door"])), T0) is None
    courtyard = tracker.on_message(message("new", review("courtyard", id="c", zones=["Pend"])), T0)
    driveway = tracker.on_message(
        message("new", review("driveway", id="d", zones=["Driveway", "Pend"])), T0 + Settings().cooldown
    )
    assert isinstance(courtyard, Decision)
    assert isinstance(driveway, Decision)
    assert driveway.review.camera == "driveway"
