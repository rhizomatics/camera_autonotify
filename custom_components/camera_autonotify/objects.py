"""Objects recognised, of any kind, a plate being one, with their sightings and what's been looked up of them

Pure logic, with no Home Assistant in it, the time passed in. Each object is kept by a hash of its kind and identity,
salted with a secret of the installation's own, never by the identity itself, so what's kept says when an object
was seen, or what it is, only to whoever already knows it.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

KIND_PLATE = "plate"
DAY = 86400


@dataclass(frozen=True)
class Sighting:
    """When, in epoch seconds, and where an object was seen, and what saw it"""

    at: float
    camera: str | None = None
    source: str | None = None

    def as_list(self) -> list[Any]:
        return [self.at, self.camera, self.source]

    @classmethod
    def from_list(cls, data: object) -> Sighting | None:
        if not isinstance(data, list) or not data or not isinstance(data[0], int | float):
            return None
        camera, source = (*data[1:3], None, None)[:2]
        return cls(float(data[0]), str(camera) if camera else None, str(source) if source else None)


class ObjectTracker:
    """Every object's sightings, and the cached lookups of them, as kept in one store"""

    def __init__(self, salt: bytes, data: dict[str, Any] | None = None) -> None:
        self.salt = salt
        data = data or {}
        self._objects: dict[str, dict[str, Any]] = dict(data.get("objects") or {})
        self._lookups: dict[str, dict[str, Any]] = dict(data.get("lookups") or {})
        self._pruned: float | None = None

    def key(self, kind: str, identity: str) -> str:
        """A plate's by itself, as the betas kept it, any other kind's prefixed, which a plate, being only letters and
        digits, can't collide with"""
        keyed = identity if kind == KIND_PLATE else f"{kind}:{identity}"
        return hmac.new(self.salt, keyed.encode(), hashlib.sha256).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {"objects": self._objects, "lookups": self._lookups}

    def sightings(self, kind: str, identity: str) -> list[Sighting]:
        return self._sightings(self.key(kind, identity))

    def _sightings(self, key: str) -> list[Sighting]:
        found = self._objects.get(key) or {}
        return sorted((s for s in (Sighting.from_list(item) for item in found.get("sightings") or []) if s), key=lambda s: s.at)

    def record(self, kind: str, identity: str, sighting: Sighting) -> None:
        tracked = self._objects.setdefault(self.key(kind, identity), {"kind": kind, "sightings": []})
        tracked["sightings"].append(sighting.as_list())

    def merge(self, kind: str, identity: str, sightings: list[Sighting]) -> int:
        """Sightings from elsewhere, those not already kept, returning how many were new"""
        return self.merge_key(self.key(kind, identity), kind, sightings)

    def merge_key(self, key: str, kind: str, sightings: list[Sighting]) -> int:
        """As `merge`, by a key already hashed, such as the betas kept"""
        known = {s.at for s in self._sightings(key)}
        new = sorted({s.at: s for s in sightings if s.at not in known}.values(), key=lambda s: s.at)
        if new:
            tracked = self._objects.setdefault(key, {"kind": kind, "sightings": []})
            tracked["sightings"] = [s.as_list() for s in sorted([*self._sightings(key), *new], key=lambda s: s.at)]
        return len(new)

    def forget(self, kind: str, identity: str | None = None) -> int:
        """An object's sightings, or those of every object of the kind, returning how many"""
        keys = (
            [self.key(kind, identity)]
            if identity is not None
            else [key for key, tracked in self._objects.items() if tracked.get("kind") == kind]
        )
        return sum(len((self._objects.pop(key, None) or {}).get("sightings") or []) for key in keys)

    def lookup(self, provider: str, kind: str, identity: str, now: float, ttl: float) -> dict[str, Any] | None:
        """A cached lookup still fresh, as remembered, or none"""
        cached = self._lookups.get(f"{provider}:{self.key(kind, identity)}")
        if cached and isinstance(cached.get("at"), int | float) and now - cached["at"] <= ttl:
            return cached
        return None

    def remember(self, provider: str, kind: str, identity: str, now: float, answer: dict[str, Any]) -> None:
        self._lookups[f"{provider}:{self.key(kind, identity)}"] = {"at": now, **answer}

    def prune(self, now: float, keep: float, ttl: float, force: bool = False) -> bool:
        """Sightings older than kept, objects with none left, and expired lookups, dropped, at most once a day
        unless forced, returning whether anything was"""
        if not force and self._pruned is not None and now - self._pruned < DAY:
            return False
        self._pruned = now
        changed = False
        for key, tracked in list(self._objects.items()):
            sightings = tracked.get("sightings") or []
            kept = [item for item in sightings if (s := Sighting.from_list(item)) and now - s.at <= keep]
            if not kept:
                del self._objects[key]
                changed = True
            elif len(kept) != len(sightings):
                tracked["sightings"] = kept
                changed = True
        for key in [k for k, cached in self._lookups.items() if not now - (cached.get("at") or 0) <= ttl]:
            del self._lookups[key]
            changed = True
        return changed
