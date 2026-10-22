"""What to notify for the reviews of one camera or zone, as Frigate reports them over MQTT

Pure logic, with no Home Assistant in it: the time is passed in, and anything to happen later is handed back as
a `Wait` for the caller to time, and then call `on_timer` for.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import StrEnum
from typing import Any

from homeassistant.util import slugify

SEVERITY_ALERT = "alert"
SEVERITY_DETECTION = "detection"
TYPE_NEW = "new"
TYPE_UPDATE = "update"
TYPE_END = "end"
# a review that never ends, from a lost MQTT message or a restart of Frigate, is forgotten after this long
STALE_AFTER = 3600


def _slugs(zones: tuple[str, ...] | set[str]) -> set[str]:
    return {slugify(zone) for zone in zones}


class Reason(StrEnum):
    """Why a notification is sent"""

    NEW = "new"
    LABEL = "label"
    ZONE = "zone"
    SUB_LABEL = "sub_label"
    SEVERITY = "severity"
    FINAL = "final"


@dataclass(frozen=True)
class Settings:
    """The filters and timing of the Frigate blueprint, with its defaults where it has them"""

    severities: frozenset[str] = frozenset({SEVERITY_ALERT})
    # any, where empty
    labels: frozenset[str] = frozenset()
    zones: tuple[str, ...] = ()
    # every zone chosen, rather than any of them
    zone_multi: bool = False
    # and entered in the order chosen
    zone_order: bool = False
    # seconds after a review is notified before another review is
    cooldown: float = 30
    # seconds held back before the first notification of a review, for a better snapshot
    initial_delay: float = 0
    # a last notification once the review has ended, after this many seconds
    final_update: bool = False
    final_delay: float = 0
    # seconds from the first notification of a review after which nothing more is sent for it
    timeout: float = 600
    # only the first notification of a review makes a sound
    alert_once: bool = True
    # told again when a sub label, such as a face or plate, is recognised
    update_sub_label: bool = True

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> Settings:
        """From a camera's options, which are named as these, and only kept where they differ from the default"""
        given = {f.name: options[f.name] for f in fields(cls) if f.name in options}
        for name in ("severities", "labels"):
            if name in given:
                given[name] = frozenset(given[name])
        if "zones" in given:
            given["zones"] = tuple(given["zones"])
        return cls(**given)


@dataclass(frozen=True)
class Review:
    """A review as Frigate reports it, in the `after` of its MQTT message"""

    id: str
    camera: str
    severity: str
    objects: tuple[str, ...]
    sub_labels: tuple[str, ...]
    # as written in the Frigate config, in the order entered
    zones: tuple[str, ...]
    detections: tuple[str, ...]
    ended: bool

    @classmethod
    def from_payload(cls, after: dict[str, Any]) -> Review:
        data = after.get("data") or {}
        # audio, such as a scream or a bark, is as much what was seen as an object is
        objects = [*data.get("objects", []), *data.get("audio", [])]
        sub_labels = [label[0] if isinstance(label, list) else label for label in data.get("sub_labels") or []]
        return cls(
            id=after["id"],
            camera=after["camera"],
            severity=after.get("severity") or SEVERITY_DETECTION,
            objects=tuple(dict.fromkeys(objects)),
            sub_labels=tuple(dict.fromkeys(str(label) for label in sub_labels if label)),
            zones=tuple(dict.fromkeys(data.get("zones") or [])),
            detections=tuple(data.get("detections") or []),
            ended=after.get("end_time") is not None,
        )

    @property
    def label(self) -> str:
        """What was seen, as said in a notification, with whoever or whatever was recognised"""
        text = " and ".join(obj.replace("_", " ").capitalize() for obj in self.objects) or "Something"
        return f"{text} ({', '.join(self.sub_labels)})" if self.sub_labels else text


@dataclass(frozen=True)
class Decision:
    """A notification to send, with the review as it then is"""

    review: Review
    reason: Reason
    # the notifications sent for the review before this one
    previous: int
    silent: bool

    @property
    def is_update(self) -> bool:
        return self.previous > 0

    @property
    def is_final(self) -> bool:
        return self.reason is Reason.FINAL

    @property
    def detection_id(self) -> str | None:
        """The detection whose snapshot shows the review, the first, which is what set it off"""
        return self.review.detections[0] if self.review.detections else None


@dataclass(frozen=True)
class Wait:
    """A notification held back, to be looked at again with `on_timer` at `at`"""

    review_id: str
    at: float
    reason: Reason


@dataclass
class _Tracked:
    review: Review
    first_seen: float
    # when the first notification went, or is due
    notified_at: float | None = None
    sent: int = 0
    # as last notified, so an update is only for what's new since
    objects: set[str] = field(default_factory=set)
    zones: set[str] = field(default_factory=set)
    sub_labels: set[str] = field(default_factory=set)
    severity: str = ""
    # held back, the first notification by the initial delay, or the last by the final delay
    waiting: Reason | None = None
    # passed over for the cooldown, so none of its updates are sent either
    skipped: bool = False


class ReviewTracker:
    """The reviews of a camera, or of a zone on any camera, and the notifications each should give"""

    def __init__(self, settings: Settings, camera: str | None = None, zone: str | None = None) -> None:
        self.settings = settings
        self.camera = camera
        # a zone is matched by its slug, as its device has it, since reviews give it as written in the Frigate config
        self.zone = slugify(zone) if zone else None
        self._reviews: dict[str, _Tracked] = {}
        self._last_new: float | None = None

    def on_message(self, payload: str | bytes | dict[str, Any], now: float) -> Decision | Wait | None:
        """A message from `{topic_prefix}/reviews`"""
        message = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
        after = message.get("after")
        if not isinstance(after, dict) or not after.get("id") or not after.get("camera"):
            return None
        review = Review.from_payload(after)
        if not self._ours(review):
            return None
        self._forget_stale(now)
        tracked = self._reviews.get(review.id)
        if tracked is None:
            if message.get("type") == TYPE_END and not self._wanted(review):
                return None
            tracked = self._reviews[review.id] = _Tracked(review, first_seen=now)
        tracked.review = review
        if tracked.skipped:
            self._drop_if_ended(tracked)
            return None
        if tracked.notified_at is None:
            return self._first(tracked, now)
        if tracked.waiting is not None:
            # held back, and sent as it is once it's due, with whatever has changed
            return None
        if now - tracked.notified_at > self.settings.timeout:
            del self._reviews[review.id]
            return None
        if review.ended:
            return self._ending(tracked, now)
        return self._update(tracked)

    def on_timer(self, review_id: str, now: float) -> Decision | Wait | None:
        """A notification held back is due"""
        tracked = self._reviews.get(review_id)
        if tracked is None or tracked.waiting is None:
            return None
        reason, tracked.waiting = tracked.waiting, None
        if reason is Reason.FINAL:
            del self._reviews[review_id]
            return self._decide(tracked, Reason.FINAL)
        return self._first_decision(tracked)

    @property
    def tracked(self) -> list[str]:
        return list(self._reviews)

    def _ours(self, review: Review) -> bool:
        if self.zone is not None:
            return self.zone in {slugify(zone) for zone in review.zones}
        return review.camera == self.camera

    def _wanted(self, review: Review) -> bool:
        settings = self.settings
        if review.severity not in settings.severities:
            return False
        if settings.labels and not settings.labels & set(review.objects):
            return False
        if settings.zones:
            chosen = [slugify(zone) for zone in settings.zones]
            entered = [slugify(zone) for zone in review.zones]
            matched = [zone for zone in chosen if zone in entered]
            if not matched or (settings.zone_multi and len(matched) < len(chosen)):
                return False
            # Frigate lists the zones of a review in the order they were entered
            positions = [entered.index(zone) for zone in matched]
            if settings.zone_order and positions != sorted(positions):
                return False
        return True

    def _first(self, tracked: _Tracked, now: float) -> Decision | Wait | None:
        if not self._wanted(tracked.review):
            # may yet be, as the review goes on
            self._drop_if_ended(tracked)
            return None
        if self._last_new is not None and now - self._last_new < self.settings.cooldown:
            tracked.skipped = True
            self._drop_if_ended(tracked)
            return None
        self._last_new = tracked.notified_at = now
        if self.settings.initial_delay > 0:
            tracked.waiting = Reason.NEW
            return Wait(tracked.review.id, now + self.settings.initial_delay, Reason.NEW)
        return self._first_decision(tracked)

    def _first_decision(self, tracked: _Tracked) -> Decision:
        decision = self._decide(tracked, Reason.NEW)
        if tracked.review.ended:
            # over before it was told at all, so told once, with nothing to follow
            del self._reviews[tracked.review.id]
        return decision

    def _update(self, tracked: _Tracked) -> Decision | None:
        review = tracked.review
        settings = self.settings
        reason: Reason | None = None
        if review.severity == SEVERITY_ALERT and tracked.severity != SEVERITY_ALERT:
            reason = Reason.SEVERITY
        elif (new := set(review.objects) - tracked.objects) and (not settings.labels or new & settings.labels):
            reason = Reason.LABEL
        elif settings.update_sub_label and set(review.sub_labels) - tracked.sub_labels:
            reason = Reason.SUB_LABEL
        elif settings.zones and (_slugs(review.zones) - _slugs(tracked.zones)) & _slugs(settings.zones):
            reason = Reason.ZONE
        return self._decide(tracked, reason) if reason is not None else None

    def _ending(self, tracked: _Tracked, now: float) -> Decision | Wait | None:
        if not self.settings.final_update:
            del self._reviews[tracked.review.id]
            return None
        if self.settings.final_delay > 0:
            tracked.waiting = Reason.FINAL
            return Wait(tracked.review.id, now + self.settings.final_delay, Reason.FINAL)
        del self._reviews[tracked.review.id]
        return self._decide(tracked, Reason.FINAL)

    def _decide(self, tracked: _Tracked, reason: Reason) -> Decision:
        review = tracked.review
        decision = Decision(review, reason, tracked.sent, silent=tracked.sent > 0 and self.settings.alert_once)
        tracked.sent += 1
        tracked.objects = set(review.objects)
        tracked.zones = set(review.zones)
        tracked.sub_labels = set(review.sub_labels)
        tracked.severity = review.severity
        return decision

    def _drop_if_ended(self, tracked: _Tracked) -> None:
        if tracked.review.ended:
            del self._reviews[tracked.review.id]

    def _forget_stale(self, now: float) -> None:
        for review_id in [r for r, tracked in self._reviews.items() if now - tracked.first_seen > STALE_AFTER]:
            del self._reviews[review_id]
