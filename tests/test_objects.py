"""The object tracker, any kind of object, a plate being one, kept by a salted hash"""

from __future__ import annotations

from custom_components.camera_autonotify.objects import DAY, KIND_PLATE, ObjectTracker, Sighting

SALT = bytes(32)


def test_kinds_kept_apart():
    """A plate and a face with the same text are different objects"""
    tracker = ObjectTracker(SALT)
    tracker.record(KIND_PLATE, "JEY1", Sighting(100, "gate", "frigate"))
    tracker.record("face", "JEY1", Sighting(200))
    assert tracker.sightings(KIND_PLATE, "JEY1") == [Sighting(100, "gate", "frigate")]
    assert tracker.sightings("face", "JEY1") == [Sighting(200)]
    assert tracker.key(KIND_PLATE, "JEY1") != tracker.key("face", "JEY1")
    assert "JEY1" not in str(tracker.as_dict())


def test_round_trip():
    tracker = ObjectTracker(SALT)
    tracker.record(KIND_PLATE, "PX19TVD", Sighting(100, "gate", None))
    tracker.remember("dvla", KIND_PLATE, "PX19TVD", 100, {"found": {"make": "FORD"}, "status": 200})
    again = ObjectTracker(SALT, tracker.as_dict())
    assert again.sightings(KIND_PLATE, "PX19TVD") == [Sighting(100, "gate", None)]
    assert again.lookup("dvla", KIND_PLATE, "PX19TVD", 150, ttl=60) == {"at": 100, "found": {"make": "FORD"}, "status": 200}
    assert again.lookup("dvla", KIND_PLATE, "PX19TVD", 200, ttl=60) is None


def test_merge_only_new():
    tracker = ObjectTracker(SALT)
    tracker.record(KIND_PLATE, "PX19TVD", Sighting(100))
    assert tracker.merge(KIND_PLATE, "PX19TVD", [Sighting(100), Sighting(50), Sighting(50)]) == 1
    assert [s.at for s in tracker.sightings(KIND_PLATE, "PX19TVD")] == [50, 100]


def test_forget_one_or_every_one_of_a_kind():
    tracker = ObjectTracker(SALT)
    tracker.record(KIND_PLATE, "A1", Sighting(1))
    tracker.record(KIND_PLATE, "B2", Sighting(2))
    tracker.record("face", "Jo", Sighting(3))
    assert tracker.forget(KIND_PLATE, "A1") == 1
    assert tracker.forget(KIND_PLATE) == 1
    assert tracker.sightings("face", "Jo")


def test_prune_daily():
    tracker = ObjectTracker(SALT)
    tracker.record(KIND_PLATE, "OLD", Sighting(0))
    tracker.record(KIND_PLATE, "BOTH", Sighting(0))
    tracker.record(KIND_PLATE, "BOTH", Sighting(5 * DAY))
    tracker.remember("dvla", KIND_PLATE, "OLD", 0, {"found": None, "status": 404})
    assert tracker.prune(5 * DAY, keep=2 * DAY, ttl=DAY)
    assert tracker.sightings(KIND_PLATE, "OLD") == []
    assert tracker.sightings(KIND_PLATE, "BOTH") == [Sighting(5 * DAY)]
    assert tracker.lookup("dvla", KIND_PLATE, "OLD", 5 * DAY, ttl=10 * DAY) is None
    # not again within the day
    tracker.record(KIND_PLATE, "OLD", Sighting(0))
    assert not tracker.prune(5 * DAY + 60, keep=2 * DAY, ttl=DAY)
    assert tracker.prune(6 * DAY + 60, keep=2 * DAY, ttl=DAY)


def test_bad_sightings_skipped():
    tracker = ObjectTracker(SALT, {"objects": {ObjectTracker(SALT).key(KIND_PLATE, "X"): {"sightings": ["?", [], [7]]}}})
    assert tracker.sightings(KIND_PLATE, "X") == [Sighting(7)]
