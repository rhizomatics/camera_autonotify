"""An image processing entity of Home Assistant's, such as OpenALPR's, as a source of its own: its own scans of its own
camera notified, as they come, with the image of the camera chosen for it

By the Core interface alone, the events the entity fires: `image_processing.found_plate` for an ANPR/ALPR entity, and
`image_processing.detect_face` for a face entity. A plate is classified, looked up and its visit counted, as Frigate's
are, its priority by the vehicle rules; a face has the priority chosen. The same plate or face isn't notified again
within the quiet period. The entity's own camera isn't in its state, so the camera whose image is notified is chosen in
the entry's settings.

To have another camera, such as Frigate's, scanned too, set up the entity with that camera as its source.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.util import slugify

from .const import (
    CONF_CAMERA_ENTITY,
    CONF_IMAGE_PROCESSING_CONFIDENCE,
    CONF_IMAGE_PROCESSING_EVENTS,
    CONF_PRIORITY,
    CONF_QUIET_PERIOD,
    CONF_SOURCE_NAME,
    DEFAULT_IMAGE_PROCESSING_CONFIDENCE,
    DEFAULT_QUIET_PERIOD,
    DOMAIN,
)
from .entries import entry_name
from .imaging import EVENTS, KIND_FACES, KIND_PLATES, UNNAMED, platform_name
from .notifier import FACTS_SEPARATOR, _friendly, async_notify_message, object_names, said_vehicle
from .texts import ANPR_TITLE, FACT_FACE_UNKNOWN, HEADLINE, async_load_texts, text
from .vehicles import vehicle_outcome, vehicles

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# what a face no one is named for is said as, before the camera
FACE = "face"


class ImageSourceWatcher:
    """The sightings of one image processing entity"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.entity_id: str = entry.data[CONF_SOURCE_NAME]
        # when each plate or face was last notified
        self._notified: dict[str, float] = {}
        self._stop: list[CALLBACK_TYPE] = []

    @property
    def minimum(self) -> float:
        return float(self.entry.options.get(CONF_IMAGE_PROCESSING_CONFIDENCE, DEFAULT_IMAGE_PROCESSING_CONFIDENCE))

    @property
    def camera(self) -> str | None:
        """The camera whose image is notified, as chosen"""
        return self.entry.options.get(CONF_CAMERA_ENTITY) or None

    @property
    def priority(self) -> str:
        return str(self.entry.options.get(CONF_PRIORITY, "medium"))

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        @callback
        def of_entity(data: Mapping[str, object]) -> bool:
            return bool(data.get("entity_id") == self.entity_id)

        handlers = {KIND_PLATES: self._plate, KIND_FACES: self._face}
        for kind in self.entry.data.get(CONF_IMAGE_PROCESSING_EVENTS) or []:
            if kind in handlers:
                self._stop.append(self.hass.bus.async_listen(EVENTS[kind], handlers[kind], event_filter=of_entity))
        return self.async_stop

    @callback
    def async_stop(self) -> None:
        for stop in self._stop:
            stop()
        self._stop.clear()

    def quiet(self, key: str) -> bool:
        """Whether the same was notified within the quiet period, and if not, it's now"""
        now = time.monotonic()
        last = self._notified.get(key)
        if last is not None and now - last < float(self.entry.options.get(CONF_QUIET_PERIOD, DEFAULT_QUIET_PERIOD)):
            return True
        self._notified[key] = now
        return False

    def where(self) -> str:
        state = self.hass.states.get(self.camera) if self.camera else None
        return state.name if state is not None else entry_name(self.entry)

    def _found(self, data: Mapping[str, Any]) -> float | None:
        """The confidence of what the entity found, as a fraction, or nothing where it's not sure enough. One with no
        confidence of its own names only what it's sure of"""
        confidence = data.get("confidence")
        score = float(confidence) if isinstance(confidence, int | float) else 100.0
        return score / 100 if score >= self.minimum else None

    def _background(self, work: Callable[[], Any], name: str) -> None:
        self.entry.async_create_background_task(self.hass, work(), f"{DOMAIN} image processing {name}")

    @callback
    def _plate(self, event: Event[dict[str, Any]]) -> None:
        if (score := self._found(event.data)) is not None and (plate := str(event.data.get("plate") or "")):
            self._background(lambda: self.async_plate(plate, score), plate)

    @callback
    def _face(self, event: Event[dict[str, Any]]) -> None:
        if self._found(event.data) is not None:
            name = str(event.data.get("name") or "")
            self._background(lambda: self.async_face(name if name.lower() not in UNNAMED else None), name or FACE)

    async def async_plate(self, plate: str, score: float) -> None:
        """Classified, looked up and its visit counted, as Frigate's are, with the vehicle rules' priority"""
        await async_load_texts(self.hass)
        found = vehicles(self.hass)
        vehicle = await found.async_classify(
            plate,
            self.camera,
            record=True,
            source=platform_name(self.hass, self.entity_id),
            entity_id=self.camera,
            confidence=score,
        )
        outcome = vehicle_outcome(found.options, vehicle)
        if outcome.silence or self.quiet(f"plate:{vehicle.plate}"):
            return
        title = text(self.hass, ANPR_TITLE, vehicle=vehicle.match.description or vehicle.plate, where=self.where())
        message = FACTS_SEPARATOR.join(said_vehicle(self.hass, vehicle))
        extra = self.extra()
        if outcome.scenarios:
            extra["apply_scenarios"] = list(outcome.scenarios)
        await self.async_send(title, message, outcome.priority or "medium", f"plate_{vehicle.plate}", extra)

    async def async_face(self, name: str | None) -> None:
        await async_load_texts(self.hass)
        if self.quiet(f"face:{name or ''}"):
            return
        label = name or _friendly(object_names(self.hass).get(FACE) or FACE)
        title = text(self.hass, HEADLINE, label=label, where=self.where())
        message = "" if name else text(self.hass, FACT_FACE_UNKNOWN)
        await self.async_send(title, message, self.priority, f"face_{name or ''}", self.extra())

    def extra(self) -> dict[str, Any]:
        """The camera's image, by Supernotify, so its camera snooze covers it too"""
        return {"media": {"camera_entity_id": self.camera}} if self.camera else {}

    async def async_send(self, title: str, message: str, priority: str, tag: str, extra: dict[str, Any]) -> None:
        await async_notify_message(
            self.hass,
            title,
            message,
            priority,
            f"{DOMAIN}_imaging_{self.entry.entry_id}_{slugify(tag)}",
            self.entry.options,
            extra,
        )
