"""Number plates: the vehicle categories they're matched to, with each plate's corrections, and what's known of a
plate's visits, from any source of plates, Frigate's or anpr2mqtt's

Pure logic, with no Home Assistant in it, the time passed in.

A category is a single vehicle, every family car, or a delivery company's vans: known or dangerous, or ignored, its
plates dropped, as a misread of a tanker's logo. Each plate of it is a plate, or a regular expression for a run of
them, with the reads that are really it, its corrections. A plate read is corrected first, then matched, exactly,
by expression, or within one character, as Frigate's own `match_distance` does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

KIND_KNOWN = "known"
KIND_DANGEROUS = "dangerous"
KIND_UNKNOWN = "unknown"
KIND_IGNORED = "ignored"
# characters that make a plate a regular expression rather than itself
PATTERN_CHARS = frozenset(".*+?[](){}|^$\\")
# a misread within this many characters of a plate still matches it
MATCH_DISTANCE = 1


def normalised(plate: str) -> str:
    """A plate as compared, upper case, with no spaces or punctuation"""
    return re.sub(r"[^A-Z0-9]", "", plate.upper())


def redacted(plate: str) -> str:
    """A plate as logged, only its first two characters and its last shown, `PX****D`"""
    plate = normalised(plate)
    if len(plate) <= 4:
        return plate[:1] + "*" * (len(plate) - 1)
    return plate[:2] + "*" * (len(plate) - 3) + plate[-1]


def is_pattern(text: str) -> bool:
    return any(char in PATTERN_CHARS for char in text)


def distance(first: str, second: str) -> int:
    """Levenshtein distance, the fewest single character edits from one to the other"""
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for i, a in enumerate(first, 1):
        current = [i]
        for j, b in enumerate(second, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def _matches(text: str, plate: str, fuzzy: bool) -> bool:
    if is_pattern(text):
        try:
            return re.fullmatch(text, plate, re.IGNORECASE) is not None
        except re.error:
            return False
    wanted = normalised(text)
    return plate == wanted or (fuzzy and len(wanted) > MATCH_DISTANCE + 2 and distance(plate, wanted) <= MATCH_DISTANCE)


@dataclass(frozen=True)
class PlateEntry:
    """A plate of a category, or a pattern for a run of them, with the reads that are really it"""

    plate: str
    description: str | None = None
    corrections: tuple[str, ...] = ()

    @classmethod
    def from_data(cls, data: object) -> PlateEntry | None:
        if isinstance(data, str):
            return cls(data.strip()) if data.strip() else None
        if not isinstance(data, dict) or not str(data.get("plate") or "").strip():
            return None
        corrections = data.get("corrections") or []
        if isinstance(corrections, str):
            corrections = [corrections]
        return cls(
            str(data["plate"]).strip(),
            str(data["description"]).strip() if data.get("description") else None,
            tuple(str(c).strip() for c in corrections if str(c).strip()),
        )


@dataclass(frozen=True)
class Category:
    """A category of vehicles"""

    name: str
    kind: str = KIND_KNOWN
    ignore: bool = False
    description: str | None = None
    icon: str | None = None
    lookup: bool = False
    plates: tuple[PlateEntry, ...] = ()

    @classmethod
    def from_data(cls, name: str, data: dict[str, Any]) -> Category:
        entries = [PlateEntry.from_data(item) for item in data.get("plates") or []]
        return cls(
            name=name,
            kind=KIND_DANGEROUS if data.get("kind") == KIND_DANGEROUS else KIND_KNOWN,
            ignore=bool(data.get("ignore")),
            description=data.get("description") or None,
            icon=data.get("icon") or None,
            lookup=bool(data.get("lookup")),
            plates=tuple(entry for entry in entries if entry is not None),
        )

    @property
    def outcome(self) -> str:
        return KIND_IGNORED if self.ignore else self.kind


@dataclass(frozen=True)
class Match:
    """A plate as read, as corrected, and the category and entry it's in, if any"""

    read: str
    plate: str
    category: Category | None = None
    entry: PlateEntry | None = None

    @property
    def kind(self) -> str:
        return self.category.outcome if self.category is not None else KIND_UNKNOWN

    @property
    def description(self) -> str | None:
        if self.entry is not None and self.entry.description:
            return self.entry.description
        return self.category.description if self.category is not None else None


@dataclass
class PlateRegister:
    """Every category, matching each plate read to one, the most specific first: an exact plate, then an expression,
    then within a character, and dangerous before known where a plate is in both"""

    categories: list[Category] = field(default_factory=list)

    def correct(self, read: str) -> str:
        """A plate read, as the plate it's really a misread of, where a correction says so"""
        plate = normalised(read)
        for category in self.categories:
            for entry in category.plates:
                if any(_matches(c, plate, fuzzy=False) for c in entry.corrections) and not is_pattern(entry.plate):
                    return normalised(entry.plate)
        return plate

    def match(self, read: str) -> Match:
        plate = self.correct(read)
        ordered = sorted(self.categories, key=lambda c: (c.outcome != KIND_IGNORED, c.kind != KIND_DANGEROUS))
        for fuzzy, patterns in ((False, False), (False, True), (True, False)):
            for category in ordered:
                for entry in category.plates:
                    if is_pattern(entry.plate) == patterns and _matches(entry.plate, plate, fuzzy):
                        # a misread within a character is the plate it's a misread of
                        return Match(read, normalised(entry.plate) if fuzzy else plate, category, entry)
        return Match(read, plate)


@dataclass(frozen=True)
class History:
    """What's known of a plate's visits, from the sightings before this one, as anpr2mqtt's tracker gives it"""

    previous_sightings: int = 0
    last_seen: str | None = None
    hourly_counts: dict[int, int] = field(default_factory=dict)
    earliest_time: str | None = None
    latest_time: str | None = None
    within_time_range: bool | None = None
    is_new_visit: bool = True
    # `daily`, `weekly`, `occasional` or `previously_seen`, by how regularly it's been seen, or none never seen
    visitor: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "previous_sightings": self.previous_sightings,
            "last_seen": self.last_seen,
            "hourly_counts": dict(self.hourly_counts),
            "earliest_time": self.earliest_time,
            "latest_time": self.latest_time,
            "within_time_range": self.within_time_range,
            "is_new_visit": self.is_new_visit,
            "visitor": self.visitor,
        }


VISITOR_DAILY = "daily"
VISITOR_WEEKLY = "weekly"
VISITOR_OCCASIONAL = "occasional"
VISITOR_PREVIOUSLY_SEEN = "previously_seen"
WEEK = timedelta(days=7)
MONTH = timedelta(days=30)


def visitor(sightings: list[datetime], now: datetime) -> str | None:
    """How regularly a plate has been seen: on 5 days of 7 in each of the last two weeks, daily; at least once in each
    of them, weekly; at least once in every 30 days back to its first sighting, a month or more ago, occasional; or
    else, seen before at all, previously seen"""
    if not sightings:
        return None
    weeks = [[seen for seen in sightings if now - (n + 1) * WEEK <= seen < now - n * WEEK] for n in range(2)]
    if all(len({seen.date() for seen in week}) >= 5 for week in weeks):
        return VISITOR_DAILY
    if all(weeks):
        return VISITOR_WEEKLY
    first = min(sightings)
    months = int((now - first) / MONTH)
    if months and all(any(now - (n + 1) * MONTH <= seen < now - n * MONTH for seen in sightings) for n in range(months)):
        return VISITOR_OCCASIONAL
    return VISITOR_PREVIOUSLY_SEEN


def analyse(sightings: list[datetime], now: datetime, min_gap: float) -> History:
    """The history of a plate from its sightings so far, before this one at the time given, which is a new visit
    unless within the minimum gap of the last"""
    times: list[time] = [seen.time() for seen in sightings]
    hourly: dict[int, int] = {}
    for seen in sightings:
        hourly[seen.hour] = hourly.get(seen.hour, 0) + 1
    earliest, latest = (min(times), max(times)) if times else (None, None)
    last = max(sightings) if sightings else None
    return History(
        previous_sightings=len(sightings),
        last_seen=last.isoformat() if last else None,
        hourly_counts=dict(sorted(hourly.items())),
        earliest_time=earliest.isoformat() if earliest else None,
        latest_time=latest.isoformat() if latest else None,
        within_time_range=(earliest <= now.time() <= latest) if earliest and latest else None,
        is_new_visit=last is None or not (timedelta(0) <= now - last < timedelta(seconds=min_gap)),
        visitor=visitor(sightings, now),
    )


def said_hours(hourly: dict[int, int]) -> str:
    """The count by hour on the 12 hour clock, `9am: 2, 1pm: 15`"""

    def hour(h: int) -> str:
        return f"{h % 12 or 12}{'am' if h < 12 else 'pm'}"

    return ", ".join(f"{hour(h)}: {count}" for h, count in sorted(hourly.items()))
