"""Reviews from Frigate over MQTT, one subscription for each topic prefix, shared by the entries that need it, and
each entry's watcher, which times what its tracker holds back and sends what it decides"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.components import mqtt
from homeassistant.const import CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import CONF_FRIGATE_NAME, DOMAIN, TYPE_ZONE
from .notifier import Notifier
from .tracker import Decision, ReviewTracker, Settings, Wait

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.components.mqtt import ReceiveMessage
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

REVIEWS_TOPIC = "{prefix}/reviews"
DATA_HUBS = "hubs"


class ReviewWatcher:
    """The reviews of one camera's or zone's entry"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        settings = Settings.from_options(entry.options)
        name = entry.data[CONF_FRIGATE_NAME]
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
            _LOGGER.warning("FRIGATE_AUTONOTIFY Review not understood: %s", payload)
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
                self.notifier.async_notify(outcome, self._context(outcome.review.id)),
                f"{DOMAIN} notify {outcome.review.id}",
            )
        # done with, once the tracker is
        for review_id in set(self._contexts) - set(self.tracker.tracked):
            del self._contexts[review_id]

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
    unsubscribe: CALLBACK_TYPE
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
        def received(message: ReceiveMessage) -> None:
            for each in list(hubs[prefix].watchers):
                each.async_review(message.payload)

        unsubscribe = await mqtt.async_subscribe(hass, REVIEWS_TOPIC.format(prefix=prefix), received)
        # another entry may have subscribed while this one was waiting
        if (hub := hubs.get(prefix)) is None:
            hub = hubs[prefix] = _Hub(unsubscribe)
        else:
            unsubscribe()
    hub.watchers.append(watcher)

    @callback
    def stop() -> None:
        watcher.async_stop()
        if watcher in hub.watchers:
            hub.watchers.remove(watcher)
        if not hub.watchers and hubs.get(prefix) is hub:
            hub.unsubscribe()
            del hubs[prefix]

    return stop
