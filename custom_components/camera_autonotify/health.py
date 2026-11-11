"""The health of each Frigate server, and the video of each camera, read from what the Frigate integration already
polls, so checking adds nothing to Frigate's load

A server is healthy while the Frigate integration's coordinator gets its stats, which it asks for every few seconds,
and only where there's no coordinator to read is the server itself asked for its version, as Frigate's own container
health check does. A camera is online while those stats have frames coming from it. A camera disabled in Frigate is
taken as meant to be, and isn't checked, and nor are a server's cameras while it isn't answering, since there's
nothing to tell from its stats.

Each is checked once a period. A failed check is tried again after the backoff, then after twice that, and so on,
and only once every retry has failed too is it notified, so a restart or a moment's trouble passes without a word.
Once notified, it's checked once a period again, and notified as back when it recovers, that notification taking the
place of the first.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_TYPE, STATE_OFF, STATE_ON
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CAMERA_DOWN,
    CAMERA_DOWN_TITLE,
    CAMERA_UP,
    CAMERA_UP_TITLE,
    CONF_HEALTH_BACKOFF,
    CONF_HEALTH_CHECK,
    CONF_HEALTH_INTERVAL,
    CONF_HEALTH_RETRIES,
    CONF_POWER_ENTITY,
    CONF_POWER_GRACE,
    CONF_SOURCE_ENTRY_ID,
    CONF_SOURCE_NAME,
    CONF_STATUS_CHECK,
    DEFAULT_POWER_GRACE,
    DOMAIN,
    FRIGATE_DOMAIN,
    HEALTH_DOWN,
    HEALTH_DOWN_TITLE,
    HEALTH_UP,
    HEALTH_UP_TITLE,
    TYPE_CAMERA,
)
from .frigate import (
    camera_enabled,
    camera_has_video,
    frigate_client,
    frigate_config,
    frigate_coordinator,
    topic_prefix,
)
from .notifier import async_notify_message

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from homeassistant.components.mqtt import ReceiveMessage
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

PRIORITY_DOWN = "high"
PRIORITY_UP = "low"
# a Frigate entry that can't be set up is as good as a failed check, the Frigate integration having failed to reach it
_FAILED_SETUP = (ConfigEntryState.SETUP_RETRY, ConfigEntryState.SETUP_ERROR)
# where Frigate says whether each camera is enabled, as `ON` or `OFF`, as it's switched
ENABLED_TOPIC = "{prefix}/+/enabled/state"


@dataclass(frozen=True)
class HealthSettings:
    enabled: bool = True
    interval: int = 60
    retries: int = 3
    backoff: int = 10

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> HealthSettings:
        default = cls()
        return cls(
            enabled=bool(options.get(CONF_HEALTH_CHECK, default.enabled)),
            interval=max(1, int(options.get(CONF_HEALTH_INTERVAL, default.interval))),
            retries=max(0, int(options.get(CONF_HEALTH_RETRIES, default.retries))),
            backoff=max(1, int(options.get(CONF_HEALTH_BACKOFF, default.backoff))),
        )


class Change(StrEnum):
    DOWN = "down"
    UP = "up"


class Power(StrEnum):
    """Whether what powers a camera says it should have video"""

    ON = "on"
    OFF = "off"
    STARTING = "starting"


class Kind(StrEnum):
    SERVER = "server"
    CAMERA = "camera"


@dataclass
class Health:
    """The checks of one server or camera, with no Home Assistant in it"""

    settings: HealthSettings
    failures: int = 0
    down: bool = False
    # when the first of the failures was
    failing_since: float | None = None

    def on_result(self, ok: bool, now: float) -> tuple[Change | None, float | None]:
        """What's changed with a check, if anything, and how long until the next one when it's a retry, rather
        than the next of the period"""
        if ok:
            was_down = self.down
            self.failures, self.down = 0, False
            if not was_down:
                self.failing_since = None
            return (Change.UP if was_down else None), None
        self.failures += 1
        if self.failing_since is None:
            self.failing_since = now
        if self.down:
            return None, None
        if self.failures > self.settings.retries:
            self.down = True
            return Change.DOWN, None
        return None, float(self.settings.backoff * 2 ** (self.failures - 1))


@dataclass(frozen=True)
class Subject:
    """A Frigate server, or a camera of one, as notified"""

    kind: Kind
    name: str
    server_id: str
    # the camera's name as Frigate has it, and its entry's options, for who is told
    camera: str | None = None
    options: Mapping[str, Any] = field(default_factory=dict, compare=False)


def duration(seconds: float) -> str:
    """How long, as said in a notification, to the minute after the first"""
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds} second{'' if seconds == 1 else 's'}"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'' if minutes == 1 else 's'}"
    hours, minutes = divmod(minutes, 60)
    said = f"{hours} hour{'' if hours == 1 else 's'}"
    return f"{said} {minutes} minute{'' if minutes == 1 else 's'}" if minutes else said


@dataclass
class HealthMonitor:
    """The checks of every Frigate server, unless switched off, and of each camera with its own check on, for the
    global settings entry, keyed by the server's or camera's config entry"""

    hass: HomeAssistant
    entry: ConfigEntry
    settings: HealthSettings
    states: dict[str, Health] = field(default_factory=dict)
    subjects: dict[str, Subject] = field(default_factory=dict)
    # whether each camera is enabled, by topic prefix and camera, as Frigate last said over MQTT
    enabled: dict[tuple[str, str], bool] = field(default_factory=dict)
    _retries: dict[str, CALLBACK_TYPE] = field(default_factory=dict)
    _checking: set[str] = field(default_factory=set)
    _subscribed: dict[str, CALLBACK_TYPE] = field(default_factory=dict)
    _subscribing: bool = False
    _stop_interval: CALLBACK_TYPE | None = None

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Check everything once a period, returning what stops it"""
        self._stop_interval = async_track_time_interval(
            self.hass, self._due, timedelta(seconds=self.settings.interval), name=f"{DOMAIN} health check"
        )
        self._subscribe()
        return self.async_stop

    @callback
    def async_stop(self) -> None:
        if self._stop_interval is not None:
            self._stop_interval()
            self._stop_interval = None
        for cancel in [*self._retries.values(), *self._subscribed.values()]:
            cancel()
        self._retries.clear()
        self._subscribed.clear()

    def diagnostics(self) -> dict[str, Any]:
        return {
            key: {"kind": subject.kind, "name": subject.name, "failures": health.failures, "down": health.down}
            for key, subject in self.subjects.items()
            if (health := self.states.get(key)) is not None
        }

    @callback
    def _wanted(self) -> dict[str, Subject]:
        subjects: dict[str, Subject] = {}
        if self.settings.enabled:
            for entry in self.hass.config_entries.async_entries(FRIGATE_DOMAIN, include_disabled=False):
                subjects[entry.entry_id] = Subject(Kind.SERVER, entry.title, entry.entry_id)
        for entry in self.hass.config_entries.async_entries(DOMAIN, include_disabled=False):
            if entry.data.get(CONF_TYPE) == TYPE_CAMERA and entry.options.get(CONF_STATUS_CHECK, True):
                subjects[entry.entry_id] = Subject(
                    Kind.CAMERA,
                    entry.title,
                    entry.data[CONF_SOURCE_ENTRY_ID],
                    entry.data[CONF_SOURCE_NAME],
                    dict(entry.options),
                )
        return subjects

    @callback
    def _due(self, now: datetime | None = None) -> None:
        """Each check of the period, but for one already under way or waiting on a retry"""
        self.subjects = self._wanted()
        for gone in set(self.states) - set(self.subjects):
            del self.states[gone]
        for key in set(self.subjects) - set(self._retries) - self._checking:
            self._check(key)
        self._subscribe()

    @callback
    def _check(self, key: str) -> None:
        if key not in self.subjects:
            return
        self._checking.add(key)
        self.entry.async_create_background_task(self.hass, self._async_check(key), f"{DOMAIN} health check {key}")

    async def _async_check(self, key: str) -> None:
        subject = self.subjects[key]
        try:
            if subject.kind is Kind.CAMERA:
                power = self._power(subject)
                if power is Power.OFF or not self._camera_enabled(subject):
                    # switched off on purpose, so neither offline nor back
                    self.states.pop(key, None)
                    return
                if power is Power.STARTING:
                    # still starting up, so no telling yet, and whatever was known kept
                    return
            ok = await self._async_probe(subject)
        finally:
            self._checking.discard(key)
        if self._stop_interval is None:
            return
        if ok is None:
            # no telling, as while its server isn't answering, so failures not yet notified are forgotten, rather than
            # counted with those after, and the camera given its every retry again once there's telling
            if (health := self.states.get(key)) is not None and not health.down:
                del self.states[key]
            return
        health = self.states.setdefault(key, Health(self.settings))
        now = time.time()
        change, retry_in = health.on_result(ok, now)
        if retry_in is not None:
            _LOGGER.debug("CAMERA_AUTONOTIFY %s failed its check, trying again in %ss", subject.name, retry_in)

            @callback
            def retry(_now: datetime) -> None:
                self._retries.pop(key, None)
                self._check(key)

            self._retries[key] = async_call_later(self.hass, retry_in, retry)
        if change is not None:
            await self._async_notify(key, subject, health, change, now)

    async def _async_probe(self, subject: Subject) -> bool | None:
        """Whether the server answers, or the camera has video, or nothing when there's no telling, the server's
        entry not set up yet or unloaded, or for a camera, its server not answering"""
        server = self.hass.config_entries.async_get_entry(subject.server_id)
        if server is None or server.disabled_by is not None:
            return None
        if server.state in _FAILED_SETUP:
            return False if subject.kind is Kind.SERVER else None
        if server.state is not ConfigEntryState.LOADED:
            return None
        coordinator = frigate_coordinator(self.hass, subject.server_id)
        if subject.kind is Kind.CAMERA:
            if coordinator is None or not coordinator.last_update_success or subject.camera is None:
                return None
            return camera_has_video(coordinator.data, subject.camera)
        if coordinator is not None:
            # polled by the Frigate integration anyway, every few seconds
            return coordinator.last_update_success
        if (client := frigate_client(self.hass, subject.server_id)) is None:
            return None
        try:
            await client.async_get_version()
        except Exception as error:
            # FrigateApiClientError, for a timeout, a connection refused or an error status, logged by the client itself
            _LOGGER.debug("CAMERA_AUTONOTIFY Frigate %s health check failed: %s", subject.name, error)
            return False
        return True

    @callback
    def _power(self, subject: Subject) -> Power:
        """As the entity powering the camera is, if it has one, taken as on when there's no telling, the entity
        missing, unavailable or unknown, so a fault with the switch can't hide the camera being offline"""
        entity_id = subject.options.get(CONF_POWER_ENTITY)
        if not entity_id or (state := self.hass.states.get(entity_id)) is None:
            return Power.ON
        if state.state == STATE_OFF:
            return Power.OFF
        if state.state != STATE_ON:
            return Power.ON
        grace = max(0, int(subject.options.get(CONF_POWER_GRACE, DEFAULT_POWER_GRACE)))
        if (dt_util.utcnow() - state.last_changed).total_seconds() < grace:
            return Power.STARTING
        return Power.ON

    @callback
    def _camera_enabled(self, subject: Subject) -> bool:
        """As Frigate last said over MQTT, or else as its config was when the Frigate integration read it"""
        config = frigate_config(self.hass, subject.server_id)
        camera = subject.camera or ""
        said = self.enabled.get((topic_prefix(config), camera))
        return said if said is not None else camera_enabled(config, camera)

    @callback
    def _subscribe(self) -> None:
        """To whether each camera is enabled, for every Frigate server's topic prefix not already followed"""
        if self._subscribing or self._stop_interval is None:
            return
        prefixes = {
            topic_prefix(frigate_config(self.hass, entry.entry_id))
            for entry in self.hass.config_entries.async_entries(FRIGATE_DOMAIN, include_disabled=False)
            if frigate_config(self.hass, entry.entry_id) is not None
        } - set(self._subscribed)
        if prefixes:
            self._subscribing = True
            self.entry.async_create_background_task(
                self.hass, self._async_subscribe(prefixes), f"{DOMAIN} health check subscribe"
            )

    async def _async_subscribe(self, prefixes: set[str]) -> None:
        try:
            if not await mqtt.async_wait_for_mqtt_client(self.hass):
                return
            for prefix in prefixes:

                @callback
                def said(message: ReceiveMessage, prefix: str = prefix) -> None:
                    payload = message.payload
                    text = payload.decode() if isinstance(payload, (bytes, bytearray)) else str(payload)
                    camera = message.topic.split("/")[-3]
                    self.enabled[(prefix, camera)] = text.strip().upper() == "ON"

                unsubscribe = await mqtt.async_subscribe(self.hass, ENABLED_TOPIC.format(prefix=prefix), said)
                if self._stop_interval is None:
                    unsubscribe()
                    return
                self._subscribed[prefix] = unsubscribe
        except HomeAssistantError as error:
            _LOGGER.debug("CAMERA_AUTONOTIFY Whether cameras are enabled can't be followed: %s", error)
        finally:
            self._subscribing = False

    async def _async_notify(self, key: str, subject: Subject, health: Health, change: Change, now: float) -> None:
        since = health.failing_since if health.failing_since is not None else now
        tag = f"{DOMAIN}_health_{key}"
        if change is Change.UP:
            health.failing_since = None
        if subject.kind is Kind.SERVER:
            names = {"server": subject.name}
            down_title, down, up_title, up = HEALTH_DOWN_TITLE, HEALTH_DOWN, HEALTH_UP_TITLE, HEALTH_UP
        else:
            names = {"camera": subject.name}
            down_title, down, up_title, up = CAMERA_DOWN_TITLE, CAMERA_DOWN, CAMERA_UP_TITLE, CAMERA_UP
        if change is Change.DOWN:
            _LOGGER.warning("CAMERA_AUTONOTIFY %s %s is down", subject.kind, subject.name)
            local = dt_util.as_local(dt_util.utc_from_timestamp(since)).strftime("%H:%M")
            title, message, priority = down_title.format(**names), down.format(**names, since=local), PRIORITY_DOWN
        else:
            _LOGGER.info("CAMERA_AUTONOTIFY %s %s is back", subject.kind, subject.name)
            title, message, priority = up_title.format(**names), up.format(**names, duration=duration(now - since)), PRIORITY_UP
        await async_notify_message(self.hass, title, message, priority, tag, subject.options)


@callback
def async_start_health_check(hass: HomeAssistant, entry: ConfigEntry) -> HealthMonitor:
    """The checks for the global settings entry, stopped as it unloads, of the servers unless switched off there, and
    of each camera with its own check on"""
    monitor = HealthMonitor(hass, entry, HealthSettings.from_options(entry.options))
    entry.async_on_unload(monitor.async_start())
    return monitor
