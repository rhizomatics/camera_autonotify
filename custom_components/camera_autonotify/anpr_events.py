"""anpr2mqtt's events without a target, such as a face, a scene change or a line crossed: each an `event` entity on the
camera's anpr2mqtt device, from anpr2mqtt 1.4.0, notified as it fires

What's said comes with the event, in its own payload, so it's always of the event that fired, never the one before.
Nothing is of faces or of a camera maker's image names, so any event anpr2mqtt is set up for works the same way. With
no target to tell one from the next, the same source isn't notified again within its quiet period.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .anpr import IMAGE_DOMAIN, MQTT_DOMAIN, STALE_AFTER, STARTUP_GRACE, find_linked_camera, image_proxy_url
from .const import (
    CONF_LINKED_CAMERA,
    CONF_LINKED_CAMERA_AUTO,
    CONF_PRIORITY,
    CONF_QUIET_PERIOD,
    CONF_SCENARIOS,
    CONF_SOURCE_NAME,
    DEFAULT_EVENT_QUIET_PERIOD,
    DOMAIN,
    VEHICLE_NO_DELIVERY,
)
from .notifier import async_notify_message
from .texts import ANPR_TITLE, async_load_texts, text

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

EVENT_DOMAIN = "event"
DEFAULT_PRIORITY = "medium"


@dataclass(frozen=True)
class AnprEvent:
    """An event as anpr2mqtt publishes it, its details from its own payload"""

    event_type: str
    description: str | None = None
    camera: str = ""
    # the same camera in primary integrations, by their Home Assistant domain
    linked_cameras: Mapping[str, str] = field(default_factory=dict)
    event_time: str | None = None
    target_type: str | None = None
    image_event: str | None = None

    @classmethod
    def from_state(cls, state: State) -> AnprEvent:
        attributes = state.attributes
        linked = attributes.get("linked_cameras")
        return cls(
            event_type=str(attributes.get("event_type") or attributes.get("event") or ""),
            description=str(attributes["description"]) if attributes.get("description") else None,
            camera=str(attributes.get("camera") or ""),
            linked_cameras={str(k): str(v) for k, v in linked.items() if v} if isinstance(linked, dict) else {},
            event_time=str(attributes["event_time"]) if attributes.get("event_time") else None,
            target_type=str(attributes["target_type"]) if attributes.get("target_type") else None,
            image_event=str(attributes["image_event"]) if attributes.get("image_event") else None,
        )

    @property
    def said(self) -> str:
        """What it was, by anpr2mqtt's description, or else the event's own name"""
        return self.description or self.event_type.replace("_", " ").capitalize()


@dataclass
class EventTracker:
    """Which changes of the event entity are new events, pure logic, the time passed in"""

    started: float

    def event(self, old: State | None, new: State | None, now: float) -> AnprEvent | None:
        if new is None or new.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
            return None
        if old is None or old.state == new.state:
            # added, or restored as Home Assistant started, or only its attributes updated, such as its image counts
            return None
        if old.state in (STATE_UNKNOWN, STATE_UNAVAILABLE) and now - self.started < STARTUP_GRACE:
            # its last state restored once anpr2mqtt is back
            return None
        found = AnprEvent.from_state(new)
        if found.event_time and (seen := dt_util.parse_datetime(found.event_time)) is not None:
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=dt_util.get_default_time_zone())
            if now - seen.timestamp() > STALE_AFTER:
                return None
        return found


@callback
def event_entity(hass: HomeAssistant, entry: ConfigEntry) -> er.RegistryEntry | None:
    """anpr2mqtt's event entity for the entry, by its unique id, so a renamed entity is still found"""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(EVENT_DOMAIN, MQTT_DOMAIN, entry.data[CONF_SOURCE_NAME])
    return registry.async_get(entity_id) if entity_id else None


@callback
def event_images(hass: HomeAssistant, entity: er.RegistryEntry) -> list[str]:
    """The event's image entities, its own first, such as a face, then any more, such as the whole scene, each with
    the event's unique id and the image event after it"""
    registry = er.async_get(hass)
    own = registry.async_get_entity_id(IMAGE_DOMAIN, MQTT_DOMAIN, entity.unique_id)
    more = sorted(
        e.entity_id
        for e in registry.entities.values()
        if e.domain == IMAGE_DOMAIN and e.platform == MQTT_DOMAIN and e.unique_id.startswith(f"{entity.unique_id}_")
    )
    return [own, *more] if own else more


class AnprEventWatcher:
    """The events of one of anpr2mqtt's event entities"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.tracker = EventTracker(time.time())
        self._notified: float | None = None
        self._stop: list[CALLBACK_TYPE] = []

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        entity = event_entity(self.hass, self.entry)
        if entity is None:
            _LOGGER.warning("CAMERA_AUTONOTIFY No anpr2mqtt event entity for %s", self.entry.title)
            return self.async_stop
        self._stop.append(async_track_state_change_event(self.hass, entity.entity_id, self._changed))
        return self.async_stop

    @callback
    def async_stop(self) -> None:
        for stop in self._stop:
            stop()
        self._stop.clear()

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        found = self.tracker.event(event.data["old_state"], event.data["new_state"], time.time())
        if found is None or self.quiet():
            return
        self.entry.async_create_background_task(self.hass, self.async_notify(found), f"{DOMAIN} anpr event {found.event_type}")

    def quiet(self) -> bool:
        """Whether one was notified within the quiet period, and if not, it's now"""
        now = time.monotonic()
        period = float(self.entry.options.get(CONF_QUIET_PERIOD, DEFAULT_EVENT_QUIET_PERIOD))
        if self._notified is not None and now - self._notified < period:
            return True
        self._notified = now
        return False

    @property
    def priority(self) -> str | None:
        """As chosen, or nothing for no delivery"""
        chosen = str(self.entry.options.get(CONF_PRIORITY, DEFAULT_PRIORITY))
        return None if chosen == VEHICLE_NO_DELIVERY else chosen

    @callback
    def linked_camera(self, found: AnprEvent) -> str | None:
        options = self.entry.options
        if not options.get(CONF_LINKED_CAMERA_AUTO, True):
            return options.get(CONF_LINKED_CAMERA) or None
        return find_linked_camera(self.hass, event_entity(self.hass, self.entry), found.linked_cameras, found.camera)

    def where(self, found: AnprEvent, camera: str | None) -> str:
        """The linked camera's name, or else anpr2mqtt's"""
        state = self.hass.states.get(camera) if camera else None
        if state is not None:
            return state.name
        return found.camera.replace("_", " ").title() or self.entry.title

    def notification_data(self, found: AnprEvent, camera: str | None) -> dict[str, Any]:
        """The event's image, the camera for Supernotify's camera snooze, its scenarios, and each event its own tag"""
        entity = event_entity(self.hass, self.entry)
        images = event_images(self.hass, entity) if entity is not None else []
        media: dict[str, Any] = {}
        if images and (url := image_proxy_url(self.hass, images[0])):
            media["snapshot_url"] = url
        if camera or images:
            media["camera_entity_id"] = camera or images[0]
        extra: dict[str, Any] = {
            "extra_data": {
                "mobile_push_notification_tag": f"anpr_event_{self.entry.entry_id}_{slugify(found.event_time or '')}",
                "group": f"anpr_{slugify(found.camera) or self.entry.entry_id}",
            }
        }
        if media:
            extra["media"] = media
        if scenarios := self.entry.options.get(CONF_SCENARIOS):
            extra["apply_scenarios"] = list(scenarios)
        return extra

    async def async_notify(self, found: AnprEvent) -> None:
        if (priority := self.priority) is None:
            return
        await async_load_texts(self.hass)
        camera = self.linked_camera(found)
        title = text(self.hass, ANPR_TITLE, vehicle=found.said, where=self.where(found, camera))
        extra = self.notification_data(found, camera)
        tag = extra["extra_data"]["mobile_push_notification_tag"]
        await async_notify_message(self.hass, title, "", priority, tag, self.entry.options, extra)
