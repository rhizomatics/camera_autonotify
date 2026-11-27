"""Reviews, tracked objects and object descriptions from Frigate over MQTT, one subscription to each for each topic prefix, shared by
the entries that need them, and each entry's watcher, which times what its tracker holds back and sends what it
decides"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.components import mqtt
from homeassistant.const import CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import CONF_SOURCE_ENTRY_ID, CONF_SOURCE_NAME, DOMAIN, TYPE_ZONE
from .facts import FactStore
from .frigate import fact_stores, frigate_config, genai_reviews_seen, review_severity
from .notifier import Notifier
from .tracker import TYPE_GENAI, Decision, ReviewTracker, Settings, Wait

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.components.mqtt import ReceiveMessage
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

REVIEWS_TOPIC = "{prefix}/reviews"
# where Frigate sends what it adds to a tracked object: GenAI descriptions, faces, plates and classification
OBJECT_UPDATES_TOPIC = "{prefix}/tracked_object_update"
# the tracked objects themselves, and each camera's state classification, kept as facts for notifications
EVENTS_TOPIC = "{prefix}/events"
STATES_TOPIC = "{prefix}/+/classification/+"
DATA_HUBS = "hubs"


class ReviewWatcher:
    """The reviews of one camera's or zone's entry"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        settings = Settings.from_options(entry.options)
        name = entry.data[CONF_SOURCE_NAME]
        source_entry_id = entry.data.get(CONF_SOURCE_ENTRY_ID)

        def severity(camera: str, label: str, zones: tuple[str, ...]) -> str | None:
            # by Frigate's config as it now is
            return review_severity(frigate_config(hass, source_entry_id), camera, label, zones) if source_entry_id else None

        if entry.data.get(CONF_TYPE) == TYPE_ZONE:
            self.tracker = ReviewTracker(settings, zone=name, severity=severity)
        else:
            self.tracker = ReviewTracker(settings, camera=name, severity=severity)
        self.notifier = Notifier(hass, entry)
        # each review's notifications tied together, the later ones as children of the first
        self._contexts: dict[str, Context] = {}
        self._timers: dict[str, CALLBACK_TYPE] = {}

    @callback
    def async_review(self, payload: str | bytes | bytearray) -> None:
        try:
            outcome = self.tracker.on_message(payload, time.time())
        except ValueError, KeyError, TypeError:
            _LOGGER.warning("CAMERA_AUTONOTIFY Review not understood: %s", payload)
            return
        self._act(outcome)

    @callback
    def async_object_update(self, payload: str | bytes | bytearray) -> None:
        try:
            outcome = self.tracker.on_description(payload, time.time())
        except ValueError, KeyError, TypeError:
            _LOGGER.warning("CAMERA_AUTONOTIFY Object update not understood: %s", payload)
            return
        self._act(outcome)

    @callback
    def async_event(self, payload: dict[str, Any]) -> None:
        try:
            outcome = self.tracker.on_event(payload, time.time())
        except ValueError, KeyError, TypeError:
            _LOGGER.warning("CAMERA_AUTONOTIFY Event not understood: %s", payload)
            return
        self._act(outcome)

    @callback
    def async_stop(self) -> None:
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()

    @property
    def reviews(self) -> list[str]:
        return self.tracker.tracked

    def _act(self, outcome: Decision | Wait | None) -> None:
        if isinstance(outcome, Wait):
            self._wait(outcome)
        elif isinstance(outcome, Decision):
            self.entry.async_create_background_task(
                self.hass,
                self.notifier.async_notify(outcome, self._context(outcome.key)),
                f"{DOMAIN} notify {outcome.key}",
            )
        # done with, once the tracker is, or an object's description notified by itself, once its time is up
        for key in set(self._contexts) - set(self.tracker.tracked) - set(self.tracker.described):
            del self._contexts[key]

    def _wait(self, wait: Wait) -> None:
        if cancel := self._timers.pop(wait.review_id, None):
            cancel()

        @callback
        def due(now: datetime) -> None:
            self._timers.pop(wait.review_id, None)
            self._act(self.tracker.on_timer(wait.review_id, time.time()))

        self._timers[wait.review_id] = async_call_later(self.hass, max(0.0, wait.at - time.time()), due)

    def _context(self, review_id: str) -> Context:
        first = self._contexts.get(review_id)
        if first is None:
            first = self._contexts[review_id] = Context()
            return first
        return Context(parent_id=first.id)


@dataclass
class _Hub:
    unsubscribe: list[CALLBACK_TYPE]
    watchers: list[ReviewWatcher] = field(default_factory=list)


def _is_summary(payload: str | bytes | bytearray) -> bool:
    """Whether a review message is GenAI's summary of the review, read only when it might be"""
    text = payload.decode(errors="replace") if isinstance(payload, (bytes, bytearray)) else payload
    if TYPE_GENAI not in text:
        return False
    try:
        message = json.loads(text)
    except ValueError:
        return False
    return isinstance(message, dict) and message.get("type") == TYPE_GENAI


def _safely(handle: Callable[[Any, float], None], message: ReceiveMessage, parsed: dict[str, Any] | None = None) -> None:
    """A message kept as facts, one not understood logged, and not passed on"""
    try:
        handle(parsed if parsed is not None else message.payload, time.time())
    except ValueError, KeyError, TypeError, AttributeError:
        _LOGGER.debug("CAMERA_AUTONOTIFY %s not understood: %s", message.topic, message.payload)


def _hubs(hass: HomeAssistant) -> dict[str, _Hub]:
    data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    hubs: dict[str, _Hub] = data.setdefault(DATA_HUBS, {})
    return hubs


async def async_watch(hass: HomeAssistant, prefix: str, watcher: ReviewWatcher) -> CALLBACK_TYPE:
    """Start the watcher on the reviews of a Frigate server, returning what stops it"""
    hubs = _hubs(hass)
    hub = hubs.get(prefix)
    if hub is None:

        @callback
        def review(message: ReceiveMessage) -> None:
            if _is_summary(message.payload):
                # so the daily summary is sent, even where Frigate's config doesn't say it makes them
                genai_reviews_seen(hass)[prefix] = time.time()
            for each in list(hubs[prefix].watchers):
                each.async_review(message.payload)

        facts = fact_stores(hass).setdefault(prefix, FactStore())

        @callback
        def object_update(message: ReceiveMessage) -> None:
            _safely(facts.on_update, message)
            for each in list(hubs[prefix].watchers):
                each.async_object_update(message.payload)

        @callback
        def event(message: ReceiveMessage) -> None:
            # read once, for the facts and every watcher, there being many of these
            try:
                parsed = json.loads(message.payload)
            except ValueError:
                _LOGGER.debug("CAMERA_AUTONOTIFY %s not understood: %s", message.topic, message.payload)
                return
            if not isinstance(parsed, dict):
                return
            _safely(facts.on_event, message, parsed)
            for each in list(hubs[prefix].watchers):
                each.async_event(parsed)

        @callback
        def state(message: ReceiveMessage) -> None:
            # `{prefix}/{camera}/classification/{model}`, the prefix possibly of more than one level
            parts = message.topic.removeprefix(f"{prefix}/").split("/")
            payload = message.payload
            value = payload.decode(errors="replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
            if len(parts) == 3:
                facts.on_state(parts[0], parts[2], value.strip())

        unsubscribe = [
            await mqtt.async_subscribe(hass, REVIEWS_TOPIC.format(prefix=prefix), review),
            await mqtt.async_subscribe(hass, OBJECT_UPDATES_TOPIC.format(prefix=prefix), object_update),
            await mqtt.async_subscribe(hass, EVENTS_TOPIC.format(prefix=prefix), event),
            await mqtt.async_subscribe(hass, STATES_TOPIC.format(prefix=prefix), state),
        ]
        # another entry may have subscribed while this one was waiting
        if (hub := hubs.get(prefix)) is None:
            hub = hubs[prefix] = _Hub(unsubscribe)
        else:
            for each in unsubscribe:
                each()
    hub.watchers.append(watcher)

    @callback
    def stop() -> None:
        watcher.async_stop()
        if watcher in hub.watchers:
            hub.watchers.remove(watcher)
        if not hub.watchers and hubs.get(prefix) is hub:
            for each in hub.unsubscribe:
                each()
            del hubs[prefix]
            fact_stores(hass).pop(prefix, None)

    return stop
