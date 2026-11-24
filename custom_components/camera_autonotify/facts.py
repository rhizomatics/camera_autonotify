"""What Frigate knows of each tracked object beyond its review, kept by object id for the reviews it's in

From `{prefix}/events`, the tracked object itself, as `before` and `after`, often several times a second while it
moves, so only what's worth keeping is kept: the highest speed seen, since Frigate's own speeds at the end are of the
object slowing to a stop, the best plate read, attributes such as a delivery company's logo, whether it has stopped,
and whether Frigate has a snapshot of it. From `{prefix}/tracked_object_update`, faces and plates as Frigate
recognises them, or doesn't, with their scores, and object classification. From
`{prefix}/{camera}/classification/{model}`, the state of each camera's state classification, such as a gate open.

Pure logic, with no Home Assistant in it, the time passed in, as the tracker is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

TYPE_FACE = "face"
TYPE_LPR = "lpr"
TYPE_CLASSIFICATION = "classification"
FACE_UNKNOWN = "unknown"
# attributes that are said otherwise, a face by whether it's recognised, a plate by what's read
SAID_OTHERWISE = frozenset({"face", "license_plate"})
# an object is forgotten this long after it was last heard of
FORGET_AFTER = 3600


def _loads(payload: str | bytes | bytearray | dict[str, Any]) -> object:
    return json.loads(payload) if isinstance(payload, (str, bytes, bytearray)) else payload


def _score(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    except TypeError, ValueError:
        return 0.0


@dataclass
class ObjectFacts:
    """What's known of one tracked object"""

    label: str = ""
    camera: str = ""
    # the highest seen, in Frigate's unit, 0 without a speed zone
    speed: float = 0.0
    # the best scored plate read, recognised or not, and the name of a known plate
    plate: str | None = None
    plate_score: float = 0.0
    plate_name: str | None = None
    # Frigate's latest weighted guess at the face, which may be `unknown`, and its score
    face: str | None = None
    face_score: float = 0.0
    # attributes found on the object, such as a logo, by their best score
    attributes: dict[str, float] = field(default_factory=dict)
    stationary: bool = False
    has_snapshot: bool | None = None
    # when Frigate stopped tracking it
    end_time: float | None = None
    heard: float = 0.0


@dataclass(frozen=True)
class ReviewFacts:
    """What's known of the objects of a review, together"""

    speed: float = 0.0
    # plates read that Frigate doesn't know, a known plate being a sub label already
    plates: tuple[str, ...] = ()
    # a person whose face Frigate saw but didn't recognise, at the threshold given
    face_unknown: bool = False
    attributes: tuple[str, ...] = ()
    # every object of it has stopped
    stationary: bool = False
    # the camera's state classifications, by model
    states: tuple[tuple[str, str], ...] = ()

    def __bool__(self) -> bool:
        return bool(self.speed or self.plates or self.face_unknown or self.attributes or self.stationary or self.states)


class FactStore:
    """The facts of every tracked object of one Frigate server, and its cameras' states"""

    def __init__(self) -> None:
        self._objects: dict[str, ObjectFacts] = {}
        # by camera, then model
        self._states: dict[str, dict[str, str]] = {}

    def _object(self, object_id: str, now: float) -> ObjectFacts:
        facts = self._objects.get(object_id)
        if facts is None:
            self._forget(now)
            facts = self._objects[object_id] = ObjectFacts()
        facts.heard = now
        return facts

    def _forget(self, now: float) -> None:
        for object_id in [o for o, facts in self._objects.items() if now - facts.heard > FORGET_AFTER]:
            del self._objects[object_id]

    def on_event(self, payload: str | bytes | bytearray | dict[str, Any], now: float) -> None:
        """A message from `{prefix}/events`, the tracked object as it now is"""
        message = _loads(payload)
        after = message.get("after") if isinstance(message, dict) else None
        if not isinstance(after, dict) or not after.get("id"):
            return
        facts = self._object(str(after["id"]), now)
        facts.label = str(after.get("label") or facts.label)
        facts.camera = str(after.get("camera") or facts.camera)
        speed = max(_score(after.get("current_estimated_speed")), _score(after.get("average_estimated_speed")))
        facts.speed = max(facts.speed, speed)
        plate = after.get("recognized_license_plate")
        if isinstance(plate, list) and plate and plate[0]:
            self._plate(facts, str(plate[0]), _score(plate[1]) if len(plate) > 1 else 0.0)
        for attribute in after.get("current_attributes") or []:
            if isinstance(attribute, dict) and attribute.get("label"):
                self._attribute(facts, str(attribute["label"]), _score(attribute.get("score")))
        attributes = after.get("attributes")
        if isinstance(attributes, dict):
            for label, score in attributes.items():
                self._attribute(facts, str(label), _score(score))
        facts.stationary = bool(after.get("stationary"))
        if "has_snapshot" in after:
            facts.has_snapshot = bool(after["has_snapshot"])
        if after.get("end_time") is not None:
            facts.end_time = _score(after["end_time"]) or None

    def ended(self, object_id: str) -> float | None:
        """When Frigate stopped tracking an object, if it has, and it's still known"""
        facts = self._objects.get(object_id)
        return facts.end_time if facts is not None else None

    def on_update(self, payload: str | bytes | bytearray | dict[str, Any], now: float) -> None:
        """A message from `{prefix}/tracked_object_update`: a face, a plate, or object classification"""
        message = _loads(payload)
        if not isinstance(message, dict) or not message.get("id"):
            return
        kind = message.get("type")
        if kind not in (TYPE_FACE, TYPE_LPR, TYPE_CLASSIFICATION):
            return
        facts = self._object(str(message["id"]), now)
        facts.camera = str(message.get("camera") or facts.camera)
        score = _score(message.get("score"))
        if kind == TYPE_FACE:
            facts.face, facts.face_score = str(message.get("name") or FACE_UNKNOWN), score
        elif kind == TYPE_LPR:
            if message.get("plate"):
                self._plate(facts, str(message["plate"]), score)
            if message.get("name"):
                facts.plate_name = str(message["name"])
        elif message.get("attribute"):
            # a sub label from classification already reaches the review
            self._attribute(facts, str(message["attribute"]), score)

    def on_state(self, camera: str, model: str, state: str) -> None:
        """A camera's state classification, such as `gate` being `open`"""
        if camera and model and state:
            self._states.setdefault(camera, {})[model] = state

    @staticmethod
    def _plate(facts: ObjectFacts, plate: str, score: float) -> None:
        if facts.plate is None or score >= facts.plate_score:
            facts.plate, facts.plate_score = plate, score

    @staticmethod
    def _attribute(facts: ObjectFacts, label: str, score: float) -> None:
        if label not in SAID_OTHERWISE:
            facts.attributes[label] = max(score, facts.attributes.get(label, 0.0))

    def object(self, object_id: str) -> ObjectFacts | None:
        return self._objects.get(object_id)

    def best_plate(self, detections: tuple[str, ...]) -> tuple[str, float] | None:
        """The best scored plate read of a review's objects, and its score, whether Frigate knows it or not"""
        read = [facts for object_id in detections if (facts := self._objects.get(object_id)) and facts.plate]
        if not read:
            return None
        best = max(read, key=lambda facts: facts.plate_score)
        return str(best.plate), best.plate_score

    def of_review(self, camera: str, detections: tuple[str, ...], face_threshold: float = 0.0) -> ReviewFacts:
        """The facts of a review's objects together, a face taken as recognised only at the threshold given, as
        Frigate's own `face_recognition.recognition_threshold`"""
        objects = [facts for object_id in detections if (facts := self._objects.get(object_id)) is not None]
        faces = [facts for facts in objects if facts.face is not None]
        plates = [facts.plate for facts in objects if facts.plate and not facts.plate_name]
        return ReviewFacts(
            speed=max((facts.speed for facts in objects), default=0.0),
            plates=tuple(dict.fromkeys(plate for plate in plates if plate)),
            face_unknown=bool(faces)
            and all(facts.face == FACE_UNKNOWN or facts.face_score < face_threshold for facts in faces),
            attributes=tuple(dict.fromkeys(label for facts in objects for label in facts.attributes)),
            stationary=bool(objects) and all(facts.stationary for facts in objects),
            states=tuple(sorted(self._states.get(camera, {}).items())),
        )
