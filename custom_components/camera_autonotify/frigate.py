"""What's known of a Frigate server, read from the Frigate integration, and the links its notification proxy serves"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import slugify

from .const import FRIGATE_DOMAIN

DEFAULT_TOPIC_PREFIX = "frigate"
# the Frigate integration keeps each server's config, as Frigate itself reports it, under its entry id
FRIGATE_CONFIG = "config"
# served without a login, so a phone can fetch it, for as long as the Frigate entry allows
NOTIFICATIONS_PATH = "/api/frigate/notifications"


@callback
def frigate_config(hass: HomeAssistant, source_entry_id: str) -> dict[str, Any] | None:
    """The config of a Frigate server, once its entry is set up"""
    data = hass.data.get(FRIGATE_DOMAIN, {}).get(source_entry_id)
    return data.get(FRIGATE_CONFIG) if isinstance(data, dict) else None


def topic_prefix(config: dict[str, Any] | None) -> str:
    return ((config or {}).get("mqtt") or {}).get("topic_prefix") or DEFAULT_TOPIC_PREFIX


@callback
def base_url(hass: HomeAssistant) -> str | None:
    """The address a phone can reach Home Assistant at, away from home if there's one for that"""
    try:
        return get_url(hass, prefer_external=True)
    except NoURLAvailableError:
        return None


def snapshot_url(base: str, detection_id: str) -> str:
    return f"{base}{NOTIFICATIONS_PATH}/{detection_id}/snapshot.jpg"


def hls_url(base: str, detection_id: str, camera: str) -> str:
    """The clip as HLS, which iOS plays when tapped, where an attached `clip.mp4` fails to show at all"""
    return f"{base}{NOTIFICATIONS_PATH}/{detection_id}/{camera}/master.m3u8"


def review_thumbnail_url(base: str, review_id: str, camera: str) -> str:
    return f"{base}{NOTIFICATIONS_PATH}/{review_id}/{camera}/review_thumbnail.webp"


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
