"""What's known of a Frigate server, read from the Frigate integration, and the links its notification proxy serves"""

from __future__ import annotations

from typing import Any, Protocol

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import slugify

from .const import DOMAIN, FRIGATE_DOMAIN

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


def camera_enabled(config: dict[str, Any] | None, camera: str) -> bool:
    """Whether a camera is enabled in Frigate's config, as the Frigate integration last read it"""
    return bool((((config or {}).get("cameras") or {}).get(camera) or {}).get("enabled", True))


def topic_prefix(config: dict[str, Any] | None) -> str:
    return ((config or {}).get("mqtt") or {}).get("topic_prefix") or DEFAULT_TOPIC_PREFIX


@callback
def base_url(hass: HomeAssistant) -> str | None:
    """The address a phone can reach Home Assistant at, away from home if there's one for that"""
    try:
        return get_url(hass, prefer_external=True)
    except NoURLAvailableError:
        return None


def instance_id(config: dict[str, Any] | None) -> str | None:
    """How the Frigate integration tells its servers apart in a proxy link, the server's MQTT client id"""
    return ((config or {}).get("mqtt") or {}).get("client_id") or None


@callback
def notifications_url(hass: HomeAssistant, source_entry_id: str) -> str | None:
    """Where a Frigate server's notification proxy is, with the server's instance id only when there's more than
    one server, since without it the Frigate integration serves the first"""
    base = base_url(hass)
    if base is None:
        return None
    instance = instance_id(frigate_config(hass, source_entry_id))
    if instance and len(hass.config_entries.async_entries(FRIGATE_DOMAIN)) > 1:
        return f"{base}{FRIGATE_API_PATH}/{instance}/{NOTIFICATIONS}"
    return f"{base}{FRIGATE_API_PATH}/{NOTIFICATIONS}"


def snapshot_url(notifications: str, detection_id: str) -> str:
    return f"{notifications}/{detection_id}/snapshot.jpg"


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


def concerning(review: dict[str, Any]) -> bool:
    """Whether GenAI's summary of a review saw a threat, or something else of concern"""
    metadata = (review.get("data") or {}).get("metadata") or {}
    try:
        level = int(metadata.get("potential_threat_level") or 0)
    except TypeError, ValueError:
        level = 0
    return level > 0 or bool(metadata.get("other_concerns"))
