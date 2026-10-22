"""What's known of a Frigate server, read from the Frigate integration, and the links its notification proxy serves"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import FRIGATE_DOMAIN

DEFAULT_TOPIC_PREFIX = "frigate"
# the Frigate integration keeps each server's config, as Frigate itself reports it, under its entry id
FRIGATE_CONFIG = "config"
# served without a login, so a phone can fetch it, for as long as the Frigate entry allows
NOTIFICATIONS_PATH = "/api/frigate/notifications"


@callback
def frigate_config(hass: HomeAssistant, frigate_entry_id: str) -> dict[str, Any] | None:
    """The config of a Frigate server, once its entry is set up"""
    data = hass.data.get(FRIGATE_DOMAIN, {}).get(frigate_entry_id)
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
