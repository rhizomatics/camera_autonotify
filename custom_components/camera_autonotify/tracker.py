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
# a review's summary by Frigate's generative AI, once the review has ended
TYPE_GENAI = "genai"
# an object's description by Frigate's generative AI, on `{topic_prefix}/tracked_object_update`
TYPE_DESCRIPTION = "description"
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
    SUMMARY = "summary"
    DESCRIPTION = "description"


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
    # Frigate's review summaries, below this threat level left out
    summaries: bool = True
    min_threat_level: int = 0
    # Frigate's object descriptions, and those of objects in no review this entry follows
    descriptions: bool = True
    unreviewed_descriptions: bool = False
    # seconds an ended review, or a description of an object in no review yet, is kept, for what GenAI adds later
    genai_wait: float = 120

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> Settings:
        """From a camera's options, which are named as these, and only kept where they differ from the default"""
        given = {f.name: options[f.name] for f in fields(cls) if f.name in options}
        for name in ("severities", "labels"):
            if name in given:
                given[name] = frozenset(given[name])
        if "zones" in given:
            given["zones"] = tuple(given["zones"])
        if "min_threat_level" in given:
            given["min_threat_level"] = int(given["min_threat_level"])
        return cls(**given)

    @property
    def genai(self) -> bool:
        return self.summaries or self.descriptions


def _json(value: object) -> object:
    """A value that may arrive as JSON text, as Frigate's metadata can, rather than as itself"""
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


@dataclass(frozen=True)
class Summary:
    """Frigate's GenAI summary of a review, in the review's `data.metadata`"""

    title: str
    short_summary: str
    # 0 normal, 1 suspicious, 2 critical
    threat_level: int
    # those of the camera's `additional_concerns` that were seen
    other_concerns: tuple[str, ...] = ()

    @classmethod
    def from_metadata(cls, metadata: object) -> Summary | None:
        metadata = _json(metadata)
        if not isinstance(metadata, dict):
            return None
        title = str(metadata.get("title") or "").strip()
        short_summary = str(metadata.get("shortSummary") or metadata.get("scene") or "").strip()
        if not title and not short_summary:
            return None
        try:
            threat_level = int(metadata.get("potential_threat_level") or 0)
        except TypeError, ValueError:
            threat_level = 0
        concerns = metadata.get("other_concerns") or []
        return cls(
            title,
            short_summary,
            threat_level,
            tuple(str(concern) for concern in concerns if concern) if isinstance(concerns, list) else (),
        )


@dataclass(frozen=True)
class Description:
    """Frigate's GenAI description of a tracked object, which may be part of a review, and of more than one"""

    object_id: str
    camera: str
    text: str

    @classmethod
    def from_payload(cls, message: dict[str, Any]) -> Description | None:
        if message.get("type") != TYPE_DESCRIPTION:
            return None
        object_id, camera, text = message.get("id"), message.get("camera"), message.get("description")
        if not object_id or not camera or not isinstance(text, str) or not text.strip():
            return None
        return cls(str(object_id), str(camera), text.strip())


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
    summary: Summary | None = None

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
            summary=Summary.from_metadata(data.get("metadata")),
        )

    @classmethod
    def of_object(cls, description: Description) -> Review:
        """A stand-in for the review of an object described in none, so it can be notified by itself"""
        return cls(
            description.object_id,
            description.camera,
            SEVERITY_DETECTION,
            (),
            (),
            (),
            (description.object_id,),
            ended=True,
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
    # what Frigate's generative AI said of the object, the one described
    description: str | None = None
    described_id: str | None = None
    # what the notification is known by, so each takes the place of the last, the review's id unless an object's
    # description was notified first, by itself
    tag_id: str | None = None

    @property
    def key(self) -> str:
        return self.tag_id or self.review.id

    @property
    def summary(self) -> Summary | None:
        return self.review.summary if self.reason is Reason.SUMMARY else None

    @property
    def is_update(self) -> bool:
        return self.previous > 0

    @property
    def is_final(self) -> bool:
        return self.reason is Reason.FINAL

    @property
    def detection_id(self) -> str | None:
        """The detection whose snapshot shows the review, the first, which is what set it off, or the object
        described"""
        if self.described_id:
            return self.described_id
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
    # an object's description notified by itself before the review was known, so the review takes its place
    tag_id: str | None = None


@dataclass
class _Described:
    """A description of an object in no review yet, kept for a review that may come"""

    description: Description
    until: float
    # notified by itself, for a camera with descriptions without a review on
    sent: bool = False


class ReviewTracker:
    """The reviews of a camera, or of a zone on any camera, and the notifications each should give"""

    def __init__(self, settings: Settings, camera: str | None = None, zone: str | None = None) -> None:
        self.settings = settings
        self.camera = camera
        # a zone is matched by its slug, as its device has it, since reviews give it as written in the Frigate config
        self.zone = slugify(zone) if zone else None
        self._reviews: dict[str, _Tracked] = {}
        # notified and ended, kept until the time given, for what GenAI adds after
        self._ended: dict[str, tuple[_Tracked, float]] = {}
        # by object id
        self._described: dict[str, _Described] = {}
        self._last_new: float | None = None

    def on_message(self, payload: str | bytes | bytearray | dict[str, Any], now: float) -> Decision | Wait | None:
        """A message from `{topic_prefix}/reviews`"""
        message = json.loads(payload) if isinstance(payload, (str, bytes, bytearray)) else payload
        after = message.get("after")
        if not isinstance(after, dict) or not after.get("id") or not after.get("camera"):
            return None
        review = Review.from_payload(after)
        if not self._ours(review):
            return None
        self._forget_stale(now)
        if message.get("type") == TYPE_GENAI:
            return self._summary(review)
        if review.id in self._ended:
            # all there is to know once it's over is what GenAI makes of it
            return None
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
        return self._update(tracked) or self._described_since(tracked)

    def on_description(self, payload: str | bytes | bytearray | dict[str, Any], now: float) -> Decision | None:
        """A message from `{topic_prefix}/tracked_object_update`, of which only descriptions are wanted"""
        message = json.loads(payload) if isinstance(payload, (str, bytes, bytearray)) else payload
        description = Description.from_payload(message) if isinstance(message, dict) else None
        if description is None or not self.settings.descriptions:
            return None
        self._forget_stale(now)
        tracked = self._reviewing(description)
        if tracked is not None and tracked.notified_at is not None and not tracked.skipped:
            if tracked.waiting is Reason.NEW:
                # the first notification, when it goes, says what this does
                self._described[description.object_id] = _Described(description, now + self.settings.genai_wait)
                return None
            return self._decide(tracked, Reason.DESCRIPTION, description)
        if tracked is not None and tracked.skipped:
            return None
        if self.camera is not None and description.camera != self.camera:
            return None
        # a review may yet come with it, or a review not yet wanted may become so
        described = self._described[description.object_id] = _Described(description, now + self.settings.genai_wait)
        if tracked is None and self.camera is not None and self.settings.unreviewed_descriptions:
            described.sent = True
            return Decision(
                Review.of_object(description),
                Reason.DESCRIPTION,
                0,
                silent=False,
                description=description.text,
                described_id=description.object_id,
            )
        return None

    def on_timer(self, review_id: str, now: float) -> Decision | Wait | None:
        """A notification held back is due"""
        tracked = self._reviews.get(review_id)
        if tracked is None or tracked.waiting is None:
            return None
        reason, tracked.waiting = tracked.waiting, None
        if reason is Reason.FINAL:
            self._retire(tracked, now)
            return self._decide(tracked, Reason.FINAL)
        return self._first_decision(tracked, now)

    @property
    def tracked(self) -> list[str]:
        return [*self._reviews, *self._ended]

    @property
    def described(self) -> list[str]:
        """Objects described before their review, if any, was known"""
        return list(self._described)

    def _find(self, review_id: str) -> _Tracked | None:
        if (tracked := self._reviews.get(review_id)) is not None:
            return tracked
        ended = self._ended.get(review_id)
        return ended[0] if ended is not None else None

    def _summary(self, review: Review) -> Decision | None:
        tracked = self._find(review.id)
        if tracked is None or tracked.skipped or tracked.notified_at is None:
            return None
        tracked.review = review
        summary = review.summary
        if not self.settings.summaries or summary is None or tracked.waiting is not None:
            return None
        if summary.threat_level < self.settings.min_threat_level:
            return None
        return self._decide(tracked, Reason.SUMMARY)

    def _reviewing(self, description: Description) -> _Tracked | None:
        """The latest review the object is in, since one that stays put, such as a parked car, is in later ones too"""
        candidates = [
            tracked
            for tracked in [*self._reviews.values(), *(ended for ended, _ in self._ended.values())]
            if tracked.review.camera == description.camera and description.object_id in tracked.review.detections
        ]
        return max(candidates, key=lambda tracked: tracked.first_seen, default=None)

    def _take_described(self, tracked: _Tracked) -> _Described | None:
        """A description of one of the review's objects that came before the review knew of it"""
        for object_id in tracked.review.detections:
            if (described := self._described.pop(object_id, None)) is not None:
                if described.sent and tracked.tag_id is None:
                    tracked.tag_id = object_id
                return described
        return None

    def _described_since(self, tracked: _Tracked) -> Decision | None:
        if (described := self._take_described(tracked)) is None:
            return None
        return self._decide(tracked, Reason.DESCRIPTION, described.description)

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
        return self._first_decision(tracked, now)

    def _first_decision(self, tracked: _Tracked, now: float) -> Decision:
        described = self._take_described(tracked)
        decision = self._decide(tracked, Reason.NEW, described.description if described else None)
        if tracked.review.ended:
            # over before it was told at all, so told once, with only what GenAI adds to follow
            self._retire(tracked, now)
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
            self._retire(tracked, now)
            return self._described_since(tracked)
        if self.settings.final_delay > 0:
            tracked.waiting = Reason.FINAL
            return Wait(tracked.review.id, now + self.settings.final_delay, Reason.FINAL)
        self._retire(tracked, now)
        return self._decide(tracked, Reason.FINAL)

    def _retire(self, tracked: _Tracked, now: float) -> None:
        """Done with, but for what GenAI adds after, when that's wanted"""
        del self._reviews[tracked.review.id]
        if self.settings.genai:
            self._ended[tracked.review.id] = (tracked, now + self.settings.genai_wait)

    def _decide(self, tracked: _Tracked, reason: Reason, description: Description | str | None = None) -> Decision:
        review = tracked.review
        text = description.text if isinstance(description, Description) else description
        decision = Decision(
            review,
            reason,
            tracked.sent,
            silent=tracked.sent > 0 and self.settings.alert_once,
            description=text,
            described_id=description.object_id if isinstance(description, Description) else None,
            tag_id=tracked.tag_id,
        )
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
        for review_id in [r for r, (_, until) in self._ended.items() if now > until]:
            del self._ended[review_id]
        for object_id in [o for o, described in self._described.items() if now > described.until]:
            del self._described[object_id]
