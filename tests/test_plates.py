"""Plates: categories, matching, corrections, ignore, and what's known of a plate's visits"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.camera_autonotify.plates import (
    Category,
    PlateEntry,
    PlateRegister,
    analyse,
    distance,
    normalised,
    said_hours,
)


def register() -> PlateRegister:
    """As anpr2mqtt's example config: a known car with corrections, a fleet by expression, a dangerous van, and the
    misread of a tanker's logo ignored"""
    return PlateRegister([
        Category.from_data(
            "Family cars",
            {
                "plates": [
                    {"plate": "TJ912UKL", "description": "Joe's mini", "corrections": ["J912UKL", "TJ91.KL"]},
                    "MY13 CAR",
                ],
                "description": "Family car",
            },
        ),
        Category.from_data("Amazon Prime", {"plates": [{"plate": "AM4\\d{2}PRM"}]}),
        Category.from_data("Watch list", {"kind": "dangerous", "plates": [{"plate": "B4DM3N"}]}),
        Category.from_data("Ignored reads", {"ignore": True, "plates": [{"plate": "^I\\dZ$"}]}),
    ])


def test_normalised():
    assert normalised("my13 car") == "MY13CAR"
    assert normalised("PX19-TVD") == "PX19TVD"


def test_distance():
    assert distance("PX19TVD", "PX19TVD") == 0
    assert distance("PX19TVD", "PX19TV0") == 1
    assert distance("PX19TVD", "X19TVD") == 1
    assert distance("", "AB") == 2


@pytest.mark.parametrize(
    ("read", "plate", "category", "kind", "description"),
    [
        ("tj912ukl", "TJ912UKL", "Family cars", "known", "Joe's mini"),
        # corrected, by a string, and by an expression
        ("J912UKL", "TJ912UKL", "Family cars", "known", "Joe's mini"),
        ("TJ91XKL", "TJ912UKL", "Family cars", "known", "Joe's mini"),
        # the category's own description where the plate has none
        ("MY13CAR", "MY13CAR", "Family cars", "known", "Family car"),
        # within a character
        ("MY13CAB", "MY13CAR", "Family cars", "known", "Family car"),
        ("AM412PRM", "AM412PRM", "Amazon Prime", "known", None),
        ("B4DM3N", "B4DM3N", "Watch list", "dangerous", None),
        ("I3Z", "I3Z", "Ignored reads", "ignored", None),
        ("PX19TVD", "PX19TVD", None, "unknown", None),
    ],
)
def test_matched(read: str, plate: str, category: str | None, kind: str, description: str | None):
    found = register().match(read)
    assert (found.plate, found.category.name if found.category else None, found.kind, found.description) == (
        plate,
        category,
        kind,
        description,
    )
    assert found.read == read


def test_exact_before_within_a_character():
    """A plate known exactly isn't taken for another a character away"""
    plates = PlateRegister([
        Category.from_data("Near", {"plates": ["AB12CDF"]}),
        Category.from_data("Exact", {"plates": ["AB12CDE"]}),
    ])
    found = plates.match("AB12CDE").category
    assert found is not None
    assert found.name == "Exact"


def test_dangerous_first():
    plates = PlateRegister([
        Category.from_data("Known", {"plates": ["B4DM3N"]}),
        Category.from_data("Watch", {"kind": "dangerous", "plates": ["B4DM3N"]}),
    ])
    assert plates.match("B4DM3N").kind == "dangerous"


def test_short_plates_not_fuzzy():
    """Too short to say a character off is the same plate"""
    plates = PlateRegister([Category.from_data("Short", {"plates": ["A1"]})])
    assert plates.match("A2").kind == "unknown"


def test_bad_pattern_never_matches():
    plates = PlateRegister([Category.from_data("Bad", {"plates": ["AB[12"]})])
    assert plates.match("AB1").kind == "unknown"


def test_entries_from_data():
    assert PlateEntry.from_data("  ") is None
    assert PlateEntry.from_data({"description": "no plate"}) is None
    assert PlateEntry.from_data({"plate": "AB1", "corrections": "AB7"}) == PlateEntry("AB1", None, ("AB7",))
    assert PlateEntry.from_data({"plate": "AB1", "description": "   ", "corrections": 123}) == PlateEntry("AB1")
    assert Category.from_data("X", {"plates": [None, 5], "description": "  ", "icon": " "}) == Category("X")


def test_corrections_respect_category_priority():
    """Higher-priority categories' corrections win, and lower-priority corrections don't steal exact matches"""
    plates = PlateRegister([
        Category.from_data(
            "Known",
            {
                "plates": [
                    {"plate": "TJ912UKL", "corrections": ["SHARED1", "B4DM.*"]},
                    {"plate": "AB12CDE"},
                    {"plate": "AB12CDF", "corrections": ["AB12CD."]},
                ]
            },
        ),
        Category.from_data("Watch", {"kind": "dangerous", "plates": [{"plate": "B4DM3N", "corrections": ["SHARED1"]}]}),
        Category.from_data("Ignored", {"ignore": True, "plates": [{"plate": "I3Z", "corrections": ["SHARED2"]}]}),
        Category.from_data("Other", {"plates": [{"plate": "OT11HER", "corrections": ["SHARED2"]}]}),
    ])
    # dangerous and ignored corrections win over known corrections
    assert (plates.correct("SHARED1"), plates.match("SHARED1").kind) == ("B4DM3N", "dangerous")
    assert (plates.correct("SHARED2"), plates.match("SHARED2").kind) == ("I3Z", "ignored")
    # known regex correction does not shadow an exact dangerous plate or exact known plate
    assert (plates.match("B4DM3N").plate, plates.match("B4DM3N").kind) == ("B4DM3N", "dangerous")
    assert plates.match("AB12CDE").plate == "AB12CDE"


def at(hour: int, minute: int = 0, day: int = 10) -> datetime:
    return datetime(2026, 11, day, hour, minute)


def test_history():
    sightings = [at(9, 15, day=1), at(13, 5, day=2), at(13, 40, day=3)]
    found = analyse(sightings, at(14, day=10), min_gap=300)
    assert found.previous_sightings == 3
    assert found.last_seen == "2026-11-03T13:40:00"
    assert found.hourly_counts == {9: 1, 13: 2}
    assert (found.earliest_time, found.latest_time) == ("09:15:00", "13:40:00")
    # later in the day than ever seen before
    assert found.within_time_range is False
    assert found.is_new_visit
    assert analyse(sightings, at(10, day=10), min_gap=300).within_time_range is True


def test_new_visit_after_gap():
    assert not analyse([at(9)], at(9, 4), min_gap=300).is_new_visit
    assert analyse([at(9)], at(9, 6), min_gap=300).is_new_visit
    # no gap, as anpr2mqtt to begin with, every sighting a visit
    assert analyse([at(9)], at(9, 1), min_gap=0).is_new_visit


def test_no_history():
    found = analyse([], at(9), min_gap=300)
    assert (found.previous_sightings, found.within_time_range, found.is_new_visit) == (0, None, True)


def test_said_hours():
    assert said_hours({0: 1, 9: 2, 12: 3, 13: 15}) == "12am: 1, 9am: 2, 12pm: 3, 1pm: 15"


NOW = datetime(2026, 11, 28, 12)


def days_ago(*days: float) -> list[datetime]:
    return [NOW - timedelta(days=day) for day in days]


@pytest.mark.parametrize(
    ("sightings", "found"),
    [
        # 5 days of 7, in each of the last two weeks
        (days_ago(1, 2, 3, 4, 5, 8, 9, 10, 11, 12), "daily"),
        # 5 days in one week only, but still both weeks
        (days_ago(1, 2, 3, 4, 5, 9), "weekly"),
        # twice the same day counts once, so only 4 days in the first week
        (days_ago(1, 1.1, 2, 3, 4, 8, 9, 10, 11, 12), "weekly"),
        (days_ago(3, 10), "weekly"),
        # not in the last week
        (days_ago(10, 20, 40), "occasional"),
        # once a month, back to its first sighting
        (days_ago(25, 55, 85), "occasional"),
        # a month missed, so only seen before
        (days_ago(10, 75), "previously_seen"),
        # too new to say more
        (days_ago(10), "previously_seen"),
        # future sightings do not vacuously satisfy monthly regularity
        ([NOW + timedelta(days=40)], "previously_seen"),
        ([], None),
    ],
)
def test_visitor(sightings: list[datetime], found: str | None):
    assert analyse(sightings, NOW, min_gap=300).visitor == found
