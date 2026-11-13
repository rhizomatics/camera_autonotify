"""The words of each notification, and of the notes on the setup screens, from the `common` section of the
translations, in Home Assistant's own language, English where a translation lacks one

A notification goes to people, not to the browser of whoever set it up, so it's in the language set for Home
Assistant itself. The translations are loaded once, as the integration is set up, and again before each notification
in case the language has changed, being cached by Home Assistant after the first time.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.translation import async_get_cached_translations, async_get_translations

from .const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.core import HomeAssistant

CATEGORY = "common"
PREFIX = f"component.{DOMAIN}.{CATEGORY}."

# what a notification says, the title being the camera's or zone's name
HEADLINE = "headline"
HEADLINE_ENDED = "headline_ended"
# the objects of a review, as said in its headline, and when it has none
OBJECTS_JOINED = "objects_joined"
OBJECTS_NONE = "objects_none"
ACTION_VIEW_SNAPSHOT = "action_view_snapshot"
# a Frigate server failing its health check, and answering again, named by its title
HEALTH_DOWN_TITLE = "health_down_title"
HEALTH_DOWN = "health_down"
HEALTH_UP_TITLE = "health_up_title"
HEALTH_UP = "health_up"
# a camera Frigate has no video from, while not disabled in Frigate, and its video back, named as its entry
CAMERA_DOWN_TITLE = "camera_down_title"
CAMERA_DOWN = "camera_down"
CAMERA_UP_TITLE = "camera_up_title"
CAMERA_UP = "camera_up"
# a summary, named by the hours it covers, and by the server's title when there's more than one
SUMMARY_TITLE = "summary_title"
SUMMARY_SERVER_TITLE = "summary_server_title"
PERIOD_TO_MIDNIGHT = "period_to_midnight"
PERIOD_SAME_DAY = "period_same_day"
PERIOD_DAYS = "period_days"
DAY = "day"
# by `date.weekday()`, Monday first, and by month, January first
WEEKDAYS = tuple(f"weekday_{n}" for n in range(7))
MONTHS = tuple(f"month_{n}" for n in range(1, 13))
# how long, in whole seconds, minutes, or hours and minutes, each one or more than one
SECONDS_ONE, SECONDS_OTHER = "seconds_one", "seconds_other"
MINUTES_ONE, MINUTES_OTHER = "minutes_one", "minutes_other"
HOURS_ONE, HOURS_OTHER = "hours_one", "hours_other"
HOURS_MINUTES = "hours_minutes"
# the notes on the setup screens, by what's installed, and each Frigate server whose notification proxy fails some
# notifications, by its title
SUPERNOTIFY_PRESENT = "supernotify_present"
SUPERNOTIFY_MISSING = "supernotify_missing"
PROXY_OFF = "proxy_off"
PROXY_EXPIRES = "proxy_expires"
CAMERAS_FOUND = "cameras_found"
CAMERAS_NONE = "cameras_none"


async def async_load_texts(hass: HomeAssistant) -> None:
    """Cached by Home Assistant once loaded, so quick after the first time"""
    await async_get_translations(hass, hass.config.language, CATEGORY, {DOMAIN})


@callback
def texts(hass: HomeAssistant) -> Mapping[str, str]:
    """Every text, by key, in Home Assistant's language, empty until loaded"""
    cached = async_get_cached_translations(hass, hass.config.language, CATEGORY, DOMAIN)
    return {key.removeprefix(PREFIX): value for key, value in cached.items() if key.startswith(PREFIX)}


@callback
def text(hass: HomeAssistant, key: str, **placeholders: object) -> str:
    """A text, with its placeholders filled in, or the key itself if the translations haven't been loaded"""
    template = async_get_cached_translations(hass, hass.config.language, CATEGORY, DOMAIN).get(PREFIX + key)
    if template is None:
        return key
    try:
        return template.format(**placeholders)
    except KeyError, IndexError, ValueError:
        # a translation with a placeholder it shouldn't have, which Home Assistant should have left out
        return template


@callback
def said_duration(hass: HomeAssistant, seconds: float) -> str:
    """How long, as said in a notification, to the minute after the first"""
    seconds = round(seconds)
    if seconds < 60:
        return text(hass, SECONDS_ONE if seconds == 1 else SECONDS_OTHER, count=seconds)
    minutes = seconds // 60
    if minutes < 60:
        return text(hass, MINUTES_ONE if minutes == 1 else MINUTES_OTHER, count=minutes)
    hours, minutes = divmod(minutes, 60)
    said = text(hass, HOURS_ONE if hours == 1 else HOURS_OTHER, count=hours)
    if not minutes:
        return said
    return text(
        hass, HOURS_MINUTES, hours=said, minutes=text(hass, MINUTES_ONE if minutes == 1 else MINUTES_OTHER, count=minutes)
    )


@callback
def said_day(hass: HomeAssistant, day: date) -> str:
    """A day by its name, date and month, `Sunday 1 November`"""
    return text(hass, DAY, weekday=text(hass, WEEKDAYS[day.weekday()]), day=day.day, month=text(hass, MONTHS[day.month - 1]))
