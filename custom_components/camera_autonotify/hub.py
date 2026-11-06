"""Reviews and object descriptions from Frigate over MQTT, one subscription to each for each topic prefix, shared by
the entries that need them, and each entry's watcher, which times what its tracker holds back and sends what it
decides"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.components import mqtt
from homeassistant.const import CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import CONF_SOURCE_NAME, DOMAIN, TYPE_ZONE
from .notifier import Notifier
from .tracker import Decision, ReviewTracker, Settings, Wait

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.components.mqtt import ReceiveMessage
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

REVIEWS_TOPIC = "{prefix}/reviews"
# where Frigate sends what it adds to a tracked object, of which only GenAI descriptions are wanted
OBJECT_UPDATES_TOPIC = "{prefix}/tracked_object_update"
DATA_HUBS = "hubs"


class ReviewWatcher:
    """The reviews of one camera's or zone's entry"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        settings = Settings.from_options(entry.options)
        name = entry.data[CONF_SOURCE_NAME]
        if entry.data.get(CONF_TYPE) == TYPE_ZONE:
            self.tracker = ReviewTracker(settings, zone=name)
        else:
            self.tracker = ReviewTracker(settings, camera=name)
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


def _hubs(hass: HomeAssistant) -> dict[str, _Hub]:
    data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    return data.setdefault(DATA_HUBS, {})


async def async_watch(hass: HomeAssistant, prefix: str, watcher: ReviewWatcher) -> CALLBACK_TYPE:
    """Start the watcher on the reviews of a Frigate server, returning what stops it"""
    hubs = _hubs(hass)
    hub = hubs.get(prefix)
    if hub is None:

        @callback
        def review(message: ReceiveMessage) -> None:
            for each in list(hubs[prefix].watchers):
                each.async_review(message.payload)

        @callback
        def object_update(message: ReceiveMessage) -> None:
            for each in list(hubs[prefix].watchers):
                each.async_object_update(message.payload)

        unsubscribe = [
            await mqtt.async_subscribe(hass, REVIEWS_TOPIC.format(prefix=prefix), review),
            await mqtt.async_subscribe(hass, OBJECT_UPDATES_TOPIC.format(prefix=prefix), object_update),
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

    return stop
