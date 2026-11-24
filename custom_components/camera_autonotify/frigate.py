"""What's known of a Frigate server, read from the Frigate integration, and the links its notification proxy serves"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any, Protocol

from aiohttp import ClientError
from homeassistant.const import UnitOfSpeed
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import slugify
from homeassistant.util.unit_conversion import SpeedConverter
from homeassistant.util.unit_system import METRIC_SYSTEM

from .const import (
    DOMAIN,
    FRIGATE_DOMAIN,
    IMAGE_PREVIEW,
    IMAGE_SNAPSHOT,
    IMAGE_SNAPSHOT_BOX,
    IMAGE_SNAPSHOT_CROP,
    IMAGE_THUMBNAIL,
    MPH_COUNTRIES,
    SNAPSHOT_TIMEOUT,
    SPEED_KMH,
    SPEED_MPH,
)
from .facts import FactStore
from .tracker import SEVERITY_ALERT, SEVERITY_DETECTION

_LOGGER = logging.getLogger(__name__)

DEFAULT_TOPIC_PREFIX = "frigate"
# the Frigate integration keeps each server's config, as Frigate itself reports it, under its entry id
FRIGATE_CONFIG = "config"
FRIGATE_CLIENT = "client"
# what polls the server's stats every few seconds, and so knows whether it answers, and has the video of each camera
FRIGATE_COORDINATOR = "coordinator"
# served without a login, so a phone can fetch it, for as long as the Frigate entry allows
FRIGATE_API_PATH = "/api/frigate"
NOTIFICATIONS = "notifications"
# the Frigate entry's options for its notification proxy, on, and never expiring, unless changed
PROXY_ENABLE = "notification_proxy_enable"
PROXY_EXPIRE_AFTER = "notification_proxy_expire_after_seconds"
# when a review summary last came over MQTT, by topic prefix
DATA_GENAI_SEEN = "genai_seen"
# what's known of each tracked object, beyond its review, by topic prefix
DATA_FACTS = "facts"


@callback
def frigate_config(hass: HomeAssistant, source_entry_id: str) -> dict[str, Any] | None:
    """The config of a Frigate server, once its entry is set up"""
    data = hass.data.get(FRIGATE_DOMAIN, {}).get(source_entry_id)
    return data.get(FRIGATE_CONFIG) if isinstance(data, dict) else None


class FrigateApiClient(Protocol):
    """The part of the Frigate integration's API client used, raising its `FrigateApiClientError` when the server
    doesn't answer"""

    async def async_get_version(self) -> str: ...

    # only from Frigate 0.17, and the Frigate integration's releases for it
    async def async_review_summarize(self, start_time: float, end_time: float) -> dict[str, Any] | str: ...

    async def async_get_reviews(self, after: float | None = None, before: float | None = None) -> list[dict[str, Any]]: ...

    # for the actions on a notification
    async def async_retain(self, event_id: str, retain: bool) -> dict[str, Any] | str: ...

    async def async_set_reviews_viewed(self, ids: list[str], viewed: bool = True) -> dict[str, Any]: ...

    async def async_export_recording(
        self, camera: str, playback_factor: str, start_time: float, end_time: float, name: str | None = None
    ) -> dict[str, Any] | str: ...

    # anything else of Frigate's API, as submitting to Frigate+, which the client has no method for
    async def api_wrapper(self, method: str, url: str) -> dict[str, Any] | str: ...


@callback
def frigate_client(hass: HomeAssistant, source_entry_id: str) -> FrigateApiClient | None:
    """The Frigate integration's API client for a server, once its entry is set up, with its URL and login"""
    data = hass.data.get(FRIGATE_DOMAIN, {}).get(source_entry_id)
    return data.get(FRIGATE_CLIENT) if isinstance(data, dict) else None


class FrigateCoordinator(Protocol):
    """The part of the Frigate integration's coordinator used, `data` being Frigate's own `/api/stats`"""

    last_update_success: bool
    data: dict[str, Any] | None


@callback
def frigate_coordinator(hass: HomeAssistant, source_entry_id: str) -> FrigateCoordinator | None:
    """The Frigate integration's coordinator for a server, once its entry is set up"""
    data = hass.data.get(FRIGATE_DOMAIN, {}).get(source_entry_id)
    coordinator = data.get(FRIGATE_COORDINATOR) if isinstance(data, dict) else None
    return coordinator if hasattr(coordinator, "last_update_success") else None


def camera_has_video(stats: dict[str, Any] | None, camera: str) -> bool | None:
    """Whether Frigate is getting frames from a camera, by its stats, or nothing when they don't have the camera"""
    found = ((stats or {}).get("cameras") or {}).get(camera)
    if not isinstance(found, dict) or found.get("camera_fps") is None:
        return None
    return float(found["camera_fps"]) > 0


def _camera(config: dict[str, Any] | None, camera: str) -> dict[str, Any]:
    return (((config or {}).get("cameras") or {}).get(camera)) or {}


def plus_enabled(config: dict[str, Any] | None) -> bool:
    """Whether Frigate+ is set up, by its API key, with or without a Frigate+ model, for submitting to it"""
    return bool(((config or {}).get("plus") or {}).get("enabled"))


def camera_snapshots(config: dict[str, Any] | None, camera: str) -> bool:
    """Whether Frigate saves snapshots for a camera, which Frigate+ needs to submit one"""
    return bool((_camera(config, camera).get("snapshots") or {}).get("enabled"))


def camera_autotracks(config: dict[str, Any] | None, camera: str) -> bool:
    """Whether a camera follows what it sees, moving, so that zones drawn on its frame stop meaning what they say"""
    return bool(((_camera(config, camera).get("onvif") or {}).get("autotracking") or {}).get("enabled_in_config"))


def frigate_url(hass: HomeAssistant, source_entry_id: str) -> str | None:
    """The address the Frigate integration reaches a server at, for what its client has no method for"""
    entry = hass.config_entries.async_get_entry(source_entry_id)
    url = entry.data.get("url") if entry is not None else None
    return str(url).rstrip("/") if url else None


def camera_records(config: dict[str, Any] | None, camera: str) -> bool:
    """Whether Frigate records a camera, by its config as the Frigate integration last read it, which has each camera's
    settings with Frigate's own merged in, so not when that isn't known"""
    return bool(((((config or {}).get("cameras") or {}).get(camera) or {}).get("record") or {}).get("enabled"))


def camera_enabled(config: dict[str, Any] | None, camera: str) -> bool:
    """Whether a camera is enabled in Frigate's config, as the Frigate integration last read it"""
    return bool((((config or {}).get("cameras") or {}).get(camera) or {}).get("enabled", True))


def review_severity(config: dict[str, Any] | None, camera: str, label: str, zones: Iterable[str]) -> str | None:
    """The severity of the review an object in these zones would be in, by the camera's `review` config, as Frigate's
    `get_review_severity` gives it, but for having moved, or nothing where it would be in none, or the camera isn't
    known"""
    review = _camera(config, camera).get("review")
    if not isinstance(review, dict):
        return None
    zones = set(zones)
    for severity, key in ((SEVERITY_ALERT, "alerts"), (SEVERITY_DETECTION, "detections")):
        found = review.get(key) or {}
        labels = found.get("labels")
        required = found.get("required_zones") or []
        if (
            found.get("enabled", True)
            # an alert's labels are always given, a detection's being any where they aren't
            and (label in labels if labels is not None else key == "detections")
            and (not required or zones & set(required))
        ):
            return severity
    return None


def topic_prefix(config: dict[str, Any] | None) -> str:
    return ((config or {}).get("mqtt") or {}).get("topic_prefix") or DEFAULT_TOPIC_PREFIX


@callback
def base_url(hass: HomeAssistant, internal: bool = False) -> str | None:
    """The address a phone can reach Home Assistant at, away from home if there's one for that, or else Home Assistant
    reaches itself at"""
    try:
        return get_url(hass, prefer_external=not internal)
    except NoURLAvailableError:
        return None


def instance_id(config: dict[str, Any] | None) -> str | None:
    """How the Frigate integration tells its servers apart in a proxy link, the server's MQTT client id"""
    return ((config or {}).get("mqtt") or {}).get("client_id") or None


@callback
def notifications_url(hass: HomeAssistant, source_entry_id: str, internal: bool = False) -> str | None:
    """Where a Frigate server's notification proxy is, with the server's instance id only when there's more than
    one server, since without it the Frigate integration serves the first"""
    base = base_url(hass, internal)
    if base is None:
        return None
    instance = instance_id(frigate_config(hass, source_entry_id))
    if instance and len(hass.config_entries.async_entries(FRIGATE_DOMAIN)) > 1:
        return f"{base}{FRIGATE_API_PATH}/{instance}/{NOTIFICATIONS}"
    return f"{base}{FRIGATE_API_PATH}/{NOTIFICATIONS}"


def snapshot_url(notifications: str, detection_id: str) -> str:
    return f"{notifications}/{detection_id}/snapshot.jpg"


# the path of each image under the notification proxy, which passes the query on to Frigate's own events API, so
# Frigate draws the box or crops the snapshot itself
IMAGE_PATHS = {
    IMAGE_SNAPSHOT: "snapshot.jpg",
    IMAGE_SNAPSHOT_BOX: "snapshot.jpg?bbox=1",
    IMAGE_SNAPSHOT_CROP: "snapshot.jpg?crop=1",
    IMAGE_THUMBNAIL: "thumbnail.jpg",
    # Frigate's animated GIF of the event's first 20 seconds, made from the frames it keeps for its recordings, so
    # only where the camera records, and never with the box or crop
    IMAGE_PREVIEW: "event_preview.gif",
}


async def async_snapshot(hass: HomeAssistant, source_entry_id: str, detection_id: str) -> bytes | None:
    """Frigate's snapshot of a detection, by the notification proxy on Home Assistant's own address"""
    notifications = notifications_url(hass, source_entry_id, internal=True)
    if notifications is None:
        return None
    try:
        async with asyncio.timeout(SNAPSHOT_TIMEOUT):
            response = await async_get_clientsession(hass).get(snapshot_url(notifications, detection_id))
            response.raise_for_status()
            return await response.read()
    except (TimeoutError, ClientError) as error:
        _LOGGER.warning("CAMERA_AUTONOTIFY No snapshot of %s: %s", detection_id, error)
        return None


def image_url(notifications: str, detection_id: str, image: str | None = None) -> str:
    """The image chosen for a notification, the snapshot unless another is"""
    return f"{notifications}/{detection_id}/{IMAGE_PATHS.get(image or IMAGE_SNAPSHOT, IMAGE_PATHS[IMAGE_SNAPSHOT])}"


def hls_url(notifications: str, detection_id: str, camera: str) -> str:
    """The clip as HLS, which iOS plays when tapped, where an attached `clip.mp4` fails to show at all"""
    return f"{notifications}/{detection_id}/{camera}/master.m3u8"


def review_thumbnail_url(notifications: str, review_id: str, camera: str) -> str:
    return f"{notifications}/{review_id}/{camera}/review_thumbnail.webp"


@callback
def proxy_problems(hass: HomeAssistant, source_entry_id: str | None = None) -> list[tuple[str, int]]:
    """The Frigate servers, or the one given, whose notification proxy is off, given as `0`, or whose links expire,
    given as the seconds they last, by title"""
    problems: list[tuple[str, int]] = []
    for entry in hass.config_entries.async_entries(FRIGATE_DOMAIN):
        if source_entry_id is not None and entry.entry_id != source_entry_id:
            continue
        if not entry.options.get(PROXY_ENABLE, True):
            problems.append((entry.title, 0))
        elif expire := int(entry.options.get(PROXY_EXPIRE_AFTER) or 0):
            problems.append((entry.title, expire))
    return problems


@callback
def camera_entity_id(hass: HomeAssistant, source_entry_id: str, camera: str) -> str | None:
    """The camera entity the Frigate integration has for a camera, by the unique id it gives it"""
    return er.async_get(hass).async_get_entity_id("camera", FRIGATE_DOMAIN, f"{source_entry_id}:camera:{camera}")


def _labels(camera: dict[str, Any]) -> set[str]:
    """What a camera can see or hear, and what its reviews are made of"""
    review = camera.get("review") or {}
    return {
        *((camera.get("objects") or {}).get("track") or []),
        *((camera.get("audio") or {}).get("listen") or []),
        *((review.get("alerts") or {}).get("labels") or []),
        *((review.get("detections") or {}).get("labels") or []),
    }


def camera_choices(config: dict[str, Any] | None, camera: str) -> tuple[list[str], list[str]]:
    """The labels and zones of a camera, as its config has them, to choose from"""
    settings = ((config or {}).get("cameras") or {}).get(camera) or {}
    return sorted(_labels(settings)), list(settings.get("zones") or {})


@callback
def all_labels(hass: HomeAssistant) -> list[str]:
    """The labels of every camera of every Frigate server, for naming each in the global settings"""
    return sorted({
        label
        for entry in hass.config_entries.async_entries(FRIGATE_DOMAIN)
        for camera in ((frigate_config(hass, entry.entry_id) or {}).get("cameras") or {}).values()
        if isinstance(camera, dict)
        for label in _labels(camera)
    })


def zone_cameras(config: dict[str, Any] | None, zone: str) -> list[str]:
    """The cameras a zone is on, the zone as slugified for its device"""
    cameras = (config or {}).get("cameras") or {}
    return [name for name, camera in cameras.items() if zone in {slugify(z) for z in camera.get("zones") or {}}]


def zone_labels(config: dict[str, Any] | None, zone: str) -> list[str]:
    """The labels of every camera a zone is on, the zone as slugified for its device"""
    cameras = ((config or {}).get("cameras") or {}).values()
    return sorted({
        label for camera in cameras if zone in {slugify(z) for z in camera.get("zones") or {}} for label in _labels(camera)
    })


def _genai(camera: dict[str, Any]) -> tuple[bool, bool]:
    return (
        bool(((camera.get("review") or {}).get("genai") or {}).get("enabled")),
        bool(((camera.get("objects") or {}).get("genai") or {}).get("enabled")),
    )


def genai_features(config: dict[str, Any] | None, camera: str | None = None, zone: str | None = None) -> tuple[bool, bool]:
    """Whether Frigate makes review summaries, and object descriptions, for a camera, or for any camera a zone is on,
    the zone as slugified for its device"""
    cameras = (config or {}).get("cameras") or {}
    if camera is not None:
        chosen = [cameras.get(camera) or {}]
    else:
        chosen = [settings for settings in cameras.values() if zone in {slugify(z) for z in settings.get("zones") or {}}]
    found = [_genai(settings) for settings in chosen]
    return any(summaries for summaries, _ in found), any(descriptions for _, descriptions in found)


def makes_summaries(config: dict[str, Any] | None) -> bool:
    """Whether Frigate makes review summaries for any of its cameras"""
    return any(summaries for summaries, _ in map(_genai, ((config or {}).get("cameras") or {}).values()))


@callback
def genai_reviews_seen(hass: HomeAssistant) -> dict[str, float]:
    """When a review summary last came from each Frigate server over MQTT, as a timestamp, by its topic prefix, since
    Home Assistant started"""
    data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    return data.setdefault(DATA_GENAI_SEEN, {})


@callback
def fact_stores(hass: HomeAssistant) -> dict[str, FactStore]:
    """What's known of each Frigate server's tracked objects, by topic prefix, kept while any camera is followed"""
    data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    return data.setdefault(DATA_FACTS, {})


@callback
def fact_store(hass: HomeAssistant, source_entry_id: str) -> FactStore | None:
    """What's known of a Frigate server's tracked objects, once a camera of it is followed"""
    return fact_stores(hass).get(topic_prefix(frigate_config(hass, source_entry_id)))


def speed_unit(config: dict[str, Any] | None) -> str:
    """Frigate's unit for speed, by its own unit system"""
    return (
        UnitOfSpeed.MILES_PER_HOUR
        if ((config or {}).get("ui") or {}).get("unit_system") == "imperial"
        else UnitOfSpeed.KILOMETERS_PER_HOUR
    )


@callback
def preferred_speed_unit(hass: HomeAssistant, chosen: str | None = None) -> str:
    """The unit speeds are said in: as chosen in the global settings, or else miles an hour where roads are signed in
    them, by Home Assistant's country, or where its unit system isn't metric, and kilometres an hour otherwise"""
    if chosen == SPEED_MPH:
        return UnitOfSpeed.MILES_PER_HOUR
    if chosen == SPEED_KMH:
        return UnitOfSpeed.KILOMETERS_PER_HOUR
    if hass.config.country in MPH_COUNTRIES or hass.config.units is not METRIC_SYSTEM:
        return UnitOfSpeed.MILES_PER_HOUR
    return UnitOfSpeed.KILOMETERS_PER_HOUR


def said_speed(speed: float, frigate_unit: str, unit: str) -> str:
    """A speed in Frigate's unit, said in the unit given, as a whole number"""
    return f"{round(SpeedConverter.convert(speed, frigate_unit, unit))} {unit}"


def face_threshold(config: dict[str, Any] | None) -> float:
    """The score at which Frigate takes a face as recognised, its own default where not set"""
    try:
        return float(((config or {}).get("face_recognition") or {}).get("recognition_threshold") or 0.9)
    except TypeError, ValueError:
        return 0.9


def concerning(review: dict[str, Any]) -> bool:
    """Whether GenAI's summary of a review saw a threat, or something else of concern"""
    metadata = (review.get("data") or {}).get("metadata") or {}
    try:
        level = int(metadata.get("potential_threat_level") or 0)
    except TypeError, ValueError:
        level = 0
    return level > 0 or bool(metadata.get("other_concerns"))
