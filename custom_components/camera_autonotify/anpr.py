"""Number plates read by anpr2mqtt, notified as a camera's reviews are, with nothing of an automation

One entry for each anpr2mqtt camera and event, following the sensor anpr2mqtt makes by MQTT discovery, its state the
plate and its attributes everything else. A plate is notified only when it's a new sighting: not retained state
arriving as the sensor is followed, nor a republish, nor the same plate again in the same visit, nor the same sighting
with details added. Each kind of vehicle, dangerous, unknown, known or ignored, has its own priority, or no delivery,
and its own Supernotify scenarios.

The images and links work away from home, never anpr2mqtt's or Frigate's own LAN addresses: a Frigate sighting by the
Frigate integration's notification proxy, a filesystem one by anpr2mqtt's image entity, served by Home Assistant. The
camera it's of is the linked camera, of a primary integration such as Frigate, chosen by itself from what anpr2mqtt
says, or set, or none, when the sighting is notified by itself.

anpr2mqtt going unavailable is notified as Frigate servers are by the health checks, from the sensor's own state, with
nothing polled.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, TypeGuard

from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Context, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .actions import Action, button, chosen
from .const import (
    ACTION_KNOWN,
    CONF_ANPR_OWN_CLASSIFICATION,
    CONF_CUSTOM_TARGET,
    CONF_DELIVERIES,
    CONF_KIND_PRIORITIES,
    CONF_KIND_SCENARIOS,
    CONF_LINKED_CAMERA,
    CONF_LINKED_CAMERA_AUTO,
    CONF_SOURCE_NAME,
    CONF_TARGET,
    CONF_TARGETS,
    CONF_VEHICLE_SCENARIOS,
    DOMAIN,
    FRIGATE_DOMAIN,
    KIND_DANGEROUS,
    KIND_IGNORED,
    KIND_KNOWN,
    KIND_UNKNOWN,
    KINDS,
    SUPERNOTIFY_DOMAIN,
    VEHICLE_NO_DELIVERY,
    VEHICLE_PRIORITY_DEFAULTS,
    VEHICLE_PRIORITY_SOURCE,
)
from .entries import global_settings
from .frigate import base_url, hls_url, notifications_url, snapshot_url
from .health import HealthSettings
from .notifier import async_notify_message, mobile_app_targets
from .supernotify_api import supernotify_available
from .texts import (
    ANPR_DOWN,
    ANPR_DOWN_TITLE,
    ANPR_DVLA,
    ANPR_FIRST,
    ANPR_PLATE,
    ANPR_SEEN,
    ANPR_TITLE,
    ANPR_UP,
    ANPR_UP_TITLE,
    async_load_texts,
    said_day,
    text,
)
from .vehicles import vehicle_outcome, vehicles

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

MQTT_DOMAIN = "mqtt"
SENSOR_DOMAIN = "sensor"
IMAGE_DOMAIN = "image"
CAMERA_DOMAIN = "camera"
# the integrations a linked camera can be of, those whose events a plate belongs with, so neither anpr2mqtt's own camera
# nor one of the same camera by ONVIF or a stream, which are only pictures
PRIMARY_DOMAINS: tuple[str, ...] = (FRIGATE_DOMAIN, "unifiprotect", "viseron", "blueiris")
# the Frigate integration's unique id for a camera's entity, `{entry_id}:camera:{name}`
FRIGATE_CAMERA = ":camera:"
# seconds after the sensor is followed in which its state is what was retained, not a new sighting
STARTUP_GRACE = 10.0
# a sighting from longer ago than this isn't new, however it arrives
STALE_AFTER = 600.0
NOT_PLATES = (STATE_UNKNOWN, STATE_UNAVAILABLE, "", "None")
# anpr2mqtt's target type of a number plate, its events otherwise being of faces, lines crossed and the like
PLATE = "plate"
# the DVLA's details worth saying, in this order, as anpr2mqtt passes them on
DVLA_DETAILS = ("make", "colour", "yearOfManufacture", "fuelType", "taxStatus", "motStatus")


@dataclass(frozen=True)
class Sighting:
    """A plate as anpr2mqtt read it, with what it knows of the vehicle"""

    plate: str
    description: str | None = None
    kind: str = KIND_UNKNOWN
    # the priority anpr2mqtt gives the vehicle's target or group
    priority: str | None = None
    camera: str = ""
    # the same camera in primary integrations, by their Home Assistant domain
    linked_cameras: Mapping[str, str] = field(default_factory=dict)
    reg_info: object = None
    previous: int = 0
    last_seen: str | None = None
    new_visit: bool = True
    # `frigate` or `filesystem`
    source: str | None = None
    frigate_event_id: str | None = None
    event_time: str | None = None

    @classmethod
    def from_state(cls, state: State) -> Sighting:
        attributes = state.attributes
        history = attributes.get("history")
        history = history if isinstance(history, dict) else {}
        if attributes.get("dangerous"):
            kind = KIND_DANGEROUS
        elif attributes.get("ignore"):
            kind = KIND_IGNORED
        elif attributes.get("known"):
            kind = KIND_KNOWN
        else:
            kind = KIND_UNKNOWN
        try:
            previous = int(history.get("previous_sightings") or 0)
        except TypeError, ValueError:
            previous = 0
        linked = attributes.get("linked_cameras")
        return cls(
            plate=state.state,
            description=str(attributes["description"]) if attributes.get("description") else None,
            kind=kind,
            priority=str(attributes["priority"]) if attributes.get("priority") else None,
            camera=str(attributes.get("camera") or ""),
            linked_cameras={str(k): str(v) for k, v in linked.items() if v} if isinstance(linked, dict) else {},
            reg_info=attributes.get("reg_info"),
            previous=previous,
            last_seen=str(history["last_seen"]) if history.get("last_seen") else None,
            new_visit=bool(history.get("is_new_visit", True)),
            source=str(attributes["source"]) if attributes.get("source") else None,
            frigate_event_id=str(attributes["frigate_event_id"]) if attributes.get("frigate_event_id") else None,
            event_time=str(attributes["event_time"]) if attributes.get("event_time") else None,
        )


def is_plate(state: State | None) -> TypeGuard[State]:
    return state is not None and state.state not in NOT_PLATES


@dataclass
class PlateTracker:
    """Which changes of the sensor are new sightings, pure logic, the time passed in"""

    started: float
    last_plate: str | None = None

    def sighting(self, old: State | None, new: State | None, now: float) -> Sighting | None:
        if new is None or not is_plate(new) or "trigger" in new.attributes:
            # cleared, unavailable, or republished as Home Assistant started
            return None
        if new.attributes.get("target_type", PLATE) != PLATE:
            # another kind of detection, such as a face or a line crossed, not yet notified
            return None
        if now - self.started < STARTUP_GRACE:
            # retained, so seen before
            self.last_plate = new.state
            return None
        if old is not None and old.state == new.state and old.attributes.get("event_time") == new.attributes.get("event_time"):
            # the same sighting, with details added, such as the DVLA's
            return None
        sighting = Sighting.from_state(new)
        if sighting.event_time and (seen := dt_util.parse_datetime(sighting.event_time)) is not None:
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=dt_util.get_default_time_zone())
            if now - seen.timestamp() > STALE_AFTER:
                return None
        if sighting.plate == self.last_plate and not sighting.new_visit:
            return None
        self.last_plate = sighting.plate
        return sighting


@callback
def sensor_entity(hass: HomeAssistant, entry: ConfigEntry) -> er.RegistryEntry | None:
    """anpr2mqtt's sensor for the entry, by its unique id, so a renamed entity is still found"""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(SENSOR_DOMAIN, MQTT_DOMAIN, entry.data[CONF_SOURCE_NAME])
    return registry.async_get(entity_id) if entity_id else None


@callback
def image_entity(hass: HomeAssistant, sensor: er.RegistryEntry) -> str | None:
    """anpr2mqtt's image entity of the same camera and event, which has the same unique id as the sensor"""
    return er.async_get(hass).async_get_entity_id(IMAGE_DOMAIN, MQTT_DOMAIN, sensor.unique_id)


def _area(hass: HomeAssistant, entity: er.RegistryEntry) -> str | None:
    if entity.area_id:
        return entity.area_id
    device = dr.async_get(hass).async_get(entity.device_id) if entity.device_id else None
    return device.area_id if device is not None else None


@callback
def find_linked_camera(
    hass: HomeAssistant, sensor: er.RegistryEntry | None, linked: Mapping[str, str], name: str
) -> str | None:
    """The camera entity of a primary integration that's the same camera, best first: one named in anpr2mqtt's
    `linked_cameras`, Frigate's first, then one in the same area, then one of the same name, taken only where there's
    one to take, and none where there's more than one, rather than a guess. Only primary integrations' cameras are
    candidates, so the same camera by ONVIF, or anpr2mqtt's own, never makes it a guess"""
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    cameras = [
        e for e in registry.entities.values() if e.domain == CAMERA_DOMAIN and not e.disabled and e.platform in PRIMARY_DOMAINS
    ]

    def named(domain: str, camera: str) -> list[er.RegistryEntry]:
        if domain == FRIGATE_DOMAIN:
            return [e for e in cameras if e.platform == domain and e.unique_id.endswith(f"{FRIGATE_CAMERA}{camera}")]
        wanted = slugify(camera)
        return [
            e
            for e in cameras
            if e.platform == domain
            and (
                slugify(e.entity_id.partition(".")[2]) == wanted
                or (
                    (device := devices.async_get(e.device_id) if e.device_id else None) and slugify(device.name or "") == wanted
                )
            )
        ]

    for domain, camera in sorted(linked.items(), key=lambda item: item[0] != FRIGATE_DOMAIN):
        if found := named(domain, camera):
            return found[0].entity_id
    area = _area(hass, sensor) if sensor is not None else None
    levels = [
        [e for e in cameras if area and _area(hass, e) == area],
        [e for e in cameras if name and e.entity_id == f"{CAMERA_DOMAIN}.{slugify(name)}"],
    ]
    for candidates in levels:
        if len(candidates) == 1:
            return candidates[0].entity_id
        if candidates:
            return None
    return None


@callback
def frigate_camera(hass: HomeAssistant, entity_id: str | None) -> tuple[str, str] | None:
    """The Frigate entry and camera name of a camera entity, where it's Frigate's"""
    entity = er.async_get(hass).async_get(entity_id) if entity_id else None
    if entity is None or entity.platform != FRIGATE_DOMAIN:
        return None
    source_entry_id, sep, camera = entity.unique_id.partition(FRIGATE_CAMERA)
    return (source_entry_id, camera) if sep else None


class AnprNotifier:
    """Sends each sighting of an anpr2mqtt entry"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

    @callback
    def linked_camera(self, sighting: Sighting | None = None) -> str | None:
        options = self.entry.options
        if not options.get(CONF_LINKED_CAMERA_AUTO, True):
            return options.get(CONF_LINKED_CAMERA) or None
        sensor = sensor_entity(self.hass, self.entry)
        if sighting is None:
            state = self.hass.states.get(sensor.entity_id) if sensor is not None else None
            sighting = Sighting.from_state(state) if state is not None else Sighting("")
        return find_linked_camera(self.hass, sensor, sighting.linked_cameras, sighting.camera)

    def where(self, sighting: Sighting, camera: str | None) -> str:
        """The linked camera's name, or else anpr2mqtt's"""
        state = self.hass.states.get(camera) if camera else None
        if state is not None:
            return state.name
        return sighting.camera.replace("_", " ").title() or self.entry.title

    def priority(self, sighting: Sighting) -> str | None:
        """By the kind of vehicle, or nothing for no delivery"""
        chosen = self.entry.options.get(CONF_KIND_PRIORITIES[sighting.kind], VEHICLE_PRIORITY_DEFAULTS[sighting.kind])
        if chosen == VEHICLE_NO_DELIVERY:
            return None
        if chosen == VEHICLE_PRIORITY_SOURCE:
            return sighting.priority or "medium"
        return str(chosen)

    def title(self, sighting: Sighting, camera: str | None) -> str:
        return text(self.hass, ANPR_TITLE, vehicle=sighting.description or sighting.plate, where=self.where(sighting, camera))

    def message(self, sighting: Sighting) -> str:
        """The plate, the sightings before, and the DVLA's details, the same from either source, so that Supernotify's
        duplicate detection can tell the same plate read twice"""
        lines: list[str] = []
        if sighting.description:
            lines.append(text(self.hass, ANPR_PLATE, plate=sighting.plate))
        if sighting.previous and sighting.last_seen:
            lines.append(text(self.hass, ANPR_SEEN, count=sighting.previous, when=self.said_when(sighting.last_seen)))
        elif not sighting.previous:
            lines.append(text(self.hass, ANPR_FIRST))
        if details := dvla(sighting.reg_info):
            lines.append(text(self.hass, ANPR_DVLA, details=details))
        return "\n".join(lines)

    def said_when(self, when: str) -> str:
        found = dt_util.parse_datetime(when)
        if found is None:
            return when[:16]
        if found.tzinfo is None:
            found = found.replace(tzinfo=dt_util.get_default_time_zone())
        local = dt_util.as_local(found)
        return f"{said_day(self.hass, local.date())} {local:%H:%M}"

    def scenarios(self, sighting: Sighting) -> tuple[list[str], list[str]]:
        """The kind's scenarios, and those of every kind, so only the kind's are allowed"""
        options = self.entry.options
        own = list(options.get(CONF_KIND_SCENARIOS[sighting.kind]) or [])
        every = sorted({name for kind in KINDS for name in options.get(CONF_KIND_SCENARIOS[kind]) or []})
        return own, every

    def media(self, sighting: Sighting, camera: str | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The image, never a LAN address, and for a Frigate sighting, the clip when tapped"""
        media: dict[str, Any] = {}
        actions: list[dict[str, Any]] = []
        sensor = sensor_entity(self.hass, self.entry)
        image = image_entity(self.hass, sensor) if sensor is not None else None
        frigate = frigate_camera(self.hass, camera)
        if sighting.source == FRIGATE_DOMAIN and sighting.frigate_event_id and frigate is not None:
            if notifications := notifications_url(self.hass, frigate[0]):
                media["snapshot_url"] = snapshot_url(notifications, sighting.frigate_event_id)
                actions.append({
                    "level": "notification",
                    "uri": hls_url(notifications, sighting.frigate_event_id, frigate[1]),
                })
        elif image is not None and (state := self.hass.states.get(image)) is not None:
            token = state.attributes.get("access_token")
            base = base_url(self.hass)
            if token and base:
                media["snapshot_url"] = f"{base}/api/image_proxy/{image}?token={token}"
        if camera or image:
            # the same camera as its reviews, so Supernotify's camera snooze covers both
            media["camera_entity_id"] = camera or image
        return media, actions

    def supernotify_data(
        self, sighting: Sighting, priority: str, scenarios: tuple[list[str], list[str]] | None = None
    ) -> dict[str, Any]:
        camera = self.linked_camera(sighting)
        title = self.title(sighting, camera)
        data: dict[str, Any] = {
            "title": title,
            "message": self.message(sighting),
            "priority": priority,
            # the plate only where the title is the vehicle's description, not the plate already
            "spoken_message": f"{title}. {sighting.plate}" if sighting.description else title,
            "extra_data": {
                "mobile_push_notification_tag": f"anpr_{self.entry.entry_id}_{slugify(sighting.plate)}",
                "group": f"anpr_{slugify(sighting.camera) or self.entry.entry_id}",
            },
        }
        own, every = scenarios or self.scenarios(sighting)
        if own:
            data["apply_scenarios"] = own
        if every:
            data["constrain_scenarios"] = every
        media, actions = self.media(sighting, camera)
        if scenarios is not None and sighting.kind == KIND_UNKNOWN and ACTION_KNOWN in chosen(self.hass, self.entry):
            # classified here, so the plate can be added to the known vehicles here
            actions.append(button(self.hass, Action(ACTION_KNOWN, self.entry.entry_id, sighting.plate)))
        if media:
            data["media"] = media
        if actions:
            data["actions"] = actions
        if deliveries := self.entry.options.get(CONF_DELIVERIES):
            data["delivery"] = list(deliveries)
            data["delivery_selection"] = "explicit"
        for key in (CONF_TARGET, CONF_CUSTOM_TARGET):
            if value := self.entry.options.get(key):
                data[key] = value
        return data

    async def async_classified(
        self, sighting: Sighting
    ) -> tuple[Sighting | None, str | None, tuple[list[str], list[str]] | None]:
        """The sighting as anpr2mqtt classified it, as it comes, or else classified here, by the vehicle categories,
        with the history and lookup here, anpr2mqtt being only the source of the plate and image, and the pre-defined
        vehicle rules' priority and scenarios, or nothing for a vehicle ignored"""
        settings = global_settings(self.hass)
        options = dict(settings.options) if settings else {}
        if options.get(CONF_ANPR_OWN_CLASSIFICATION, True):
            return sighting, self.priority(sighting), None
        camera = self.linked_camera(sighting)
        sensor = sensor_entity(self.hass, self.entry)
        vehicle = await vehicles(self.hass).async_classify(
            sighting.plate,
            sighting.camera or None,
            record=True,
            source="anpr2mqtt",
            entity_id=camera or (image_entity(self.hass, sensor) if sensor else None),
        )
        found = vehicle_outcome(options, vehicle)
        if found.silence:
            return None, None, None
        history = vehicle.history
        classified = replace(
            sighting,
            plate=vehicle.plate,
            kind=vehicle.kind,
            description=vehicle.match.description,
            priority=None,
            previous=history.previous_sightings,
            last_seen=history.last_seen,
            new_visit=history.is_new_visit,
            reg_info=vehicle.lookup.said() if vehicle.lookup else None,
        )
        every = sorted({s for names in (options.get(k) or [] for k in CONF_VEHICLE_SCENARIOS.values()) for s in names})
        return classified, found.priority, (list(found.scenarios), every)

    async def async_notify(self, sighting: Sighting) -> None:
        await async_load_texts(self.hass)
        found, priority, scenarios = await self.async_classified(sighting)
        if found is None or priority is None:
            _LOGGER.debug("CAMERA_AUTONOTIFY No delivery for %s, a %s vehicle", sighting.plate, sighting.kind)
            return
        sighting = found
        context = Context()
        try:
            if supernotify_available(self.hass):
                data = self.supernotify_data(sighting, priority, scenarios)
                await self.hass.services.async_call(SUPERNOTIFY_DOMAIN, "notify", data, blocking=True, context=context)
                return
            camera = self.linked_camera(sighting)
            targets: list[str] = self.entry.options.get(CONF_TARGETS) or mobile_app_targets(self.hass)
            if not targets:
                return
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {ATTR_ENTITY_ID: targets, "title": self.title(sighting, camera), "message": self.message(sighting)},
                blocking=True,
                context=context,
            )
        except HomeAssistantError:
            _LOGGER.exception("CAMERA_AUTONOTIFY Notification failed for %s", sighting.plate)


def dvla(reg_info: object) -> str | None:
    """The DVLA's details, as anpr2mqtt passes them on, the ones worth saying"""
    if isinstance(reg_info, dict):
        said = [str(reg_info[key]) for key in DVLA_DETAILS if reg_info.get(key) not in (None, "")]
        return ", ".join(said) or None
    return str(reg_info) if reg_info else None


class AnprWatcher:
    """The sightings of one anpr2mqtt camera and event, and its health"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.notifier = AnprNotifier(hass, entry)
        self.tracker = PlateTracker(time.time())
        self._stop: list[CALLBACK_TYPE] = []
        self._down_check: CALLBACK_TYPE | None = None
        self._down_notified = False

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        sensor = sensor_entity(self.hass, self.entry)
        if sensor is None:
            _LOGGER.warning("CAMERA_AUTONOTIFY No anpr2mqtt sensor for %s", self.entry.title)
            return self.async_stop
        if is_plate(state := self.hass.states.get(sensor.entity_id)):
            self.tracker.last_plate = state.state
        self._stop.append(async_track_state_change_event(self.hass, sensor.entity_id, self._changed))
        return self.async_stop

    @callback
    def async_stop(self) -> None:
        for stop in self._stop:
            stop()
        self._stop.clear()
        if self._down_check:
            self._down_check()
            self._down_check = None

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        self._health(new)
        if (sighting := self.tracker.sighting(old, new, time.time())) is not None:
            self.entry.async_create_background_task(
                self.hass, self.notifier.async_notify(sighting), f"{DOMAIN} anpr {sighting.plate}"
            )

    def _health(self, new: State | None) -> None:
        """anpr2mqtt down once the sensor has been unavailable for as long as a Frigate server's retries take, and
        back as soon as it isn't, by the global health check settings"""
        unavailable = new is not None and new.state == STATE_UNAVAILABLE
        if unavailable and self._down_check is None and not self._down_notified:
            settings = global_settings(self.hass)
            health = HealthSettings.from_options(settings.options if settings else {})
            if not health.enabled:
                return
            self._down_check = async_call_later(self.hass, health.interval * (health.retries + 1), self._still_down)
        elif not unavailable:
            if self._down_check:
                self._down_check()
                self._down_check = None
            if self._down_notified:
                self._down_notified = False
                self._notify_health(ANPR_UP_TITLE, ANPR_UP, "low")

    @callback
    def _still_down(self, _now: object) -> None:
        self._down_check = None
        sensor = sensor_entity(self.hass, self.entry)
        state = self.hass.states.get(sensor.entity_id) if sensor is not None else None
        if state is not None and state.state == STATE_UNAVAILABLE:
            self._down_notified = True
            self._notify_health(ANPR_DOWN_TITLE, ANPR_DOWN, "high")

    def _notify_health(self, title: str, message: str, priority: str) -> None:
        names = {"camera": self.entry.title}
        self.entry.async_create_background_task(
            self.hass,
            async_notify_message(
                self.hass,
                text(self.hass, title, **names),
                text(self.hass, message, **names),
                priority,
                f"{DOMAIN}_anpr_health_{self.entry.entry_id}",
                self.entry.options,
            ),
            f"{DOMAIN} anpr health",
        )
