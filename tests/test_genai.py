"""What Frigate's generative AI adds to a review, its summary and the descriptions of its objects, from real messages"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from custom_components.camera_autonotify.tracker import (
    Decision,
    Description,
    Reason,
    ReviewTracker,
    Settings,
    Summary,
    Wait,
)

# real sequences, from Frigate's MQTT messages as archived, each by its review id
SEQUENCES: dict[str, list[dict[str, Any]]] = json.loads(
    (Path(__file__).parent / "fixtures" / "sequences.json").read_text()
)
# a person at night, an object described with no summary to follow, the tokens having run out
NIGHT = "1793901333.310511-f8uxqc"
# a person entering the barn, two objects described and a summary at threat level 1
BARN = "1792229361.648526-d03264"
T0 = 1_800_000_000.0


def payloads(review_id: str, topic: str, kind: str | None = None) -> list[dict[str, Any]]:
    return [
        m["payload"]
        for m in SEQUENCES[review_id]
        if m["topic"] == topic and (kind is None or m["payload"]["type"] == kind)
    ]


def review_message(review_id: str, kind: str) -> dict[str, Any]:
    return payloads(review_id, "reviews", kind)[0]


def descriptions(review_id: str) -> list[dict[str, Any]]:
    return payloads(review_id, "tracked_object_update")


def replay(tracker: ReviewTracker, review_id: str, start: float = T0) -> list[Decision | Wait | None]:
    """Each message of a sequence in the order they came, a second apart"""
    outcomes: list[Decision | Wait | None] = []
    for step, message in enumerate(SEQUENCES[review_id]):
        if message["topic"] == "reviews":
            outcomes.append(tracker.on_message(message["payload"], start + step))
        else:
            outcomes.append(tracker.on_description(message["payload"], start + step))
    return outcomes


def courtyard(**settings: Any) -> ReviewTracker:
    return ReviewTracker(Settings(**settings), camera="courtyard")


def test_described_with_no_summary():
    outcomes = replay(courtyard(), NIGHT)
    assert [o.reason if isinstance(o, Decision) else o for o in outcomes] == [Reason.NEW, None, Reason.DESCRIPTION]
    described = outcomes[-1]
    assert isinstance(described, Decision)
    assert described.description is not None
    assert described.description.startswith("MEDIUM RISK. A person in green")
    # the snapshot of the object described, under the review's notification
    assert described.detection_id == "1793901333.125216-vzjxnx"
    assert described.key == NIGHT
    assert described.silent
    assert described.summary is None


def test_described_then_summarised():
    outcomes = replay(courtyard(), BARN)
    reasons = [o.reason if isinstance(o, Decision) else o for o in outcomes]
    assert reasons == [Reason.NEW, None, Reason.DESCRIPTION, Reason.DESCRIPTION, Reason.SUMMARY]
    summarised = outcomes[-1]
    assert isinstance(summarised, Decision)
    assert summarised.summary == Summary(
        "A person entering a barn in the courtyard",
        "A person walks across the courtyard, enters a barn, and exits carrying a small box-like item.",
        1,
        ("visitors entering barn",),
    )
    assert summarised.previous == 3
    assert summarised.key == BARN


def test_summary_below_lowest_threat_level_left_out():
    outcomes = replay(courtyard(min_threat_level=2), BARN)
    assert outcomes[-1] is None


def test_summaries_and_descriptions_switched_off():
    outcomes = replay(courtyard(summaries=False, descriptions=False), BARN)
    assert [o.reason if isinstance(o, Decision) else o for o in outcomes] == [Reason.NEW, None, None, None, None]
    assert courtyard(summaries=False, descriptions=False).tracked == []


def test_summaries_only():
    outcomes = replay(courtyard(descriptions=False), BARN)
    assert [o.reason if isinstance(o, Decision) else o for o in outcomes] == [Reason.NEW, None, None, None, Reason.SUMMARY]


def test_kept_only_for_wait():
    tracker = courtyard(genai_wait=60)
    tracker.on_message(review_message(BARN, "new"), T0)
    tracker.on_message(review_message(BARN, "end"), T0 + 30)
    assert tracker.tracked == [BARN]
    # too late
    assert tracker.on_message(review_message(BARN, "genai"), T0 + 91) is None
    assert tracker.tracked == []


def test_nothing_but_genai_once_ended():
    tracker = courtyard()
    tracker.on_message(review_message(BARN, "new"), T0)
    tracker.on_message(review_message(BARN, "end"), T0 + 1)
    assert tracker.on_message(review_message(BARN, "end"), T0 + 2) is None


def test_summary_of_review_not_known():
    assert courtyard().on_message(review_message(BARN, "genai"), T0) is None


def test_summary_of_review_passed_over():
    tracker = courtyard(cooldown=60)
    replay(tracker, NIGHT)
    # within the cooldown, so neither the review nor anything of it is notified
    outcomes = replay(tracker, BARN, T0 + 10)
    assert outcomes == [None] * 5


def test_summary_of_review_still_held_back():
    tracker = courtyard(initial_delay=5)
    tracker.on_message(review_message(BARN, "new"), T0)
    assert tracker.on_message(review_message(BARN, "genai"), T0 + 1) is None
    decision = tracker.on_timer(BARN, T0 + 5)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.NEW


def test_description_before_review_said_with_it():
    tracker = courtyard()
    first, second = descriptions(BARN)
    assert tracker.on_description(first, T0) is None
    decision = tracker.on_message(review_message(BARN, "new"), T0 + 1)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.NEW
    assert decision.description == first["description"]
    assert decision.key == BARN
    # the second object joins the review later, with its description already there
    tracker.on_description(second, T0 + 2)
    update = review_message(BARN, "end") | {"type": "update"}
    update["after"] = update["after"] | {"end_time": None}
    decision = tracker.on_message(update, T0 + 3)
    assert isinstance(decision, Decision)
    assert decision.reason is Reason.DESCRIPTION
    assert decision.description == second["description"]


def test_description_before_review_said_once_ended():
    tracker = courtyard()
    first, second = descriptions(BARN)
    tracker.on_message(review_message(BARN, "new"), T0)
    tracker.on_description(second, T0 + 1)
    decision = tracker.on_message(review_message(BARN, "end"), T0 + 2)
    assert isinstance(decision, Decision)
    assert decision.description == second["description"]


def test_description_while_held_back_said_with_first():
    tracker = courtyard(initial_delay=5)
    first, _ = descriptions(BARN)
    tracker.on_message(review_message(BARN, "new"), T0)
    assert tracker.on_description(first, T0 + 1) is None
    decision = tracker.on_timer(BARN, T0 + 5)
    assert isinstance(decision, Decision)
    assert decision.description == first["description"]


def test_description_without_review_left_out():
    tracker = courtyard()
    first, _ = descriptions(BARN)
    assert tracker.on_description(first, T0) is None


def test_description_without_review_by_itself():
    tracker = courtyard(unreviewed_descriptions=True)
    first, _ = descriptions(BARN)
    alone = tracker.on_description(first, T0)
    assert isinstance(alone, Decision)
    assert alone.reason is Reason.DESCRIPTION
    assert alone.key == first["id"]
    assert alone.detection_id == first["id"]
    assert not alone.is_update
    # the review, when it comes, takes the place of that notification
    decision = tracker.on_message(review_message(BARN, "new"), T0 + 1)
    assert isinstance(decision, Decision)
    assert decision.key == first["id"]
    assert decision.description == first["description"]
    later = tracker.on_message(review_message(BARN, "genai"), T0 + 2)
    assert isinstance(later, Decision)
    assert later.key == first["id"]


def test_description_forgotten_after_wait():
    tracker = courtyard(genai_wait=60)
    first, _ = descriptions(BARN)
    tracker.on_description(first, T0)
    decision = tracker.on_message(review_message(BARN, "new"), T0 + 61)
    assert isinstance(decision, Decision)
    assert decision.description is None


def test_description_of_another_camera():
    tracker = ReviewTracker(Settings(unreviewed_descriptions=True), camera="driveway")
    first, _ = descriptions(BARN)
    assert tracker.on_description(first, T0) is None


def test_description_of_review_passed_over():
    tracker = courtyard(cooldown=60)
    replay(tracker, NIGHT)
    tracker.on_message(review_message(BARN, "new"), T0 + 10)
    first, _ = descriptions(BARN)
    assert tracker.on_description(first, T0 + 11) is None


def test_description_of_object_in_more_than_one_review():
    """An object that stays put, such as a parked car, is in later reviews too, so is told with the latest"""
    tracker = courtyard(cooldown=0)
    first, _ = descriptions(BARN)
    earlier = review_message(BARN, "new")
    later = json.loads(json.dumps(earlier))
    later["after"]["id"] = "later"
    tracker.on_message(earlier, T0)
    tracker.on_message(later, T0 + 100)
    decision = tracker.on_description(first, T0 + 101)
    assert isinstance(decision, Decision)
    assert decision.review.id == "later"


def test_zone_told_descriptions_of_its_reviews_only():
    first, _ = descriptions(BARN)
    # no zone in a description, so nothing by itself
    assert ReviewTracker(Settings(unreviewed_descriptions=True), zone="Barn_Door").on_description(first, T0) is None
    tracker = ReviewTracker(Settings(unreviewed_descriptions=True), zone="Barn_Door")
    outcomes = replay(tracker, BARN)
    # the zone is only entered by the time the review ends
    assert [o.reason if isinstance(o, Decision) else o for o in outcomes] == [
        None,
        Reason.NEW,
        Reason.DESCRIPTION,
        Reason.DESCRIPTION,
        Reason.SUMMARY,
    ]


def test_not_descriptions():
    tracker = courtyard(unreviewed_descriptions=True)
    assert tracker.on_description({"type": "face", "id": "x", "camera": "courtyard", "name": "Jey"}, T0) is None
    assert tracker.on_description({"type": "description", "id": "x", "camera": "courtyard"}, T0) is None
    assert tracker.on_description("[]", T0) is None
    assert Description.from_payload({"type": "description", "id": "x", "camera": "c", "description": "  "}) is None


def test_summary_read():
    assert Summary.from_metadata(None) is None
    assert Summary.from_metadata("not json") is None
    assert Summary.from_metadata({"confidence": 1}) is None
    assert Summary.from_metadata('{"title": "Bird", "potential_threat_level": "high"}') == Summary("Bird", "", 0)
    assert Summary.from_metadata({"title": "A", "shortSummary": "B", "other_concerns": "x"}) == Summary("A", "B", 0)
