"""A summary of the hours before, from each Frigate server, made by Frigate's generative AI from their reviews, as the
`frigate.review_summarize` action does, sent every so many hours, once a day to begin with, as set in the global
settings

Sent automatically when Frigate makes review summaries for any of a server's cameras, or a review summary has come
over MQTT in the hours summarised, or else always or never, as chosen. It can be kept for when there's something to
worry about: Frigate is always asked for the summary, but it's only sent when one of the reviews in those hours was
given a threat level, or other concerns, by GenAI. A summary Frigate can't make is logged and nothing sent.

Too long for a phone's notification or a voice assistant, so only sent through Supernotify, by one of its e-mail
deliveries unless others are chosen, such as Telegram, and not at all when it has none.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DELIVERIES,
    CONF_SUMMARY_CONCERNS,
    CONF_SUMMARY_DELIVERIES,
    CONF_SUMMARY_INTERVAL,
    CONF_SUMMARY_MODE,
    CONF_SUMMARY_TIME,
    DEFAULT_SUMMARY_INTERVAL,
    DEFAULT_SUMMARY_TIME,
    DOMAIN,
    FRIGATE_DOMAIN,
    SUMMARY_AUTO,
    SUMMARY_INTERVALS,
    SUMMARY_MODES,
    SUMMARY_OFF,
    SUMMARY_ON,
)
from .frigate import (
    FrigateApiClient,
    concerning,
    frigate_client,
    frigate_config,
    genai_reviews_seen,
    makes_summaries,
    topic_prefix,
)
from .notifier import async_notify_message
from .supernotify_api import email_deliveries, supernotify_available
from .texts import (
    PERIOD_DAYS,
    PERIOD_SAME_DAY,
    PERIOD_TO_MIDNIGHT,
    SUMMARY_SERVER_TITLE,
    SUMMARY_TITLE,
    async_load_texts,
    said_day,
    text,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

PRIORITY = "medium"
DEFAULT_TIME = time.fromisoformat(DEFAULT_SUMMARY_TIME)


@dataclass(frozen=True)
class SummarySettings:
    mode: str = SUMMARY_AUTO
    at: time = DEFAULT_TIME
    # hours between summaries, from the time set
    interval: int = DEFAULT_SUMMARY_INTERVAL
    concerns_only: bool = False
    deliveries: tuple[str, ...] = ()

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> SummarySettings:
        default = cls()
        mode = options.get(CONF_SUMMARY_MODE, default.mode)
        try:
            at = time.fromisoformat(str(options.get(CONF_SUMMARY_TIME, DEFAULT_SUMMARY_TIME)))
        except ValueError:
            at = default.at
        try:
            interval = int(options.get(CONF_SUMMARY_INTERVAL, default.interval))
        except TypeError, ValueError:
            interval = default.interval
        return cls(
            mode=mode if mode in SUMMARY_MODES else default.mode,
            at=at,
            interval=interval if interval in SUMMARY_INTERVALS else default.interval,
            concerns_only=bool(options.get(CONF_SUMMARY_CONCERNS, default.concerns_only)),
            deliveries=tuple(options.get(CONF_SUMMARY_DELIVERIES) or ()),
        )

    def due(self, now: datetime) -> bool:
        """Whether a summary is due in the hour given, one of every so many from the time set"""
        return (dt_util.as_local(now).hour - self.at.hour) % self.interval == 0

    def period(self, now: datetime) -> tuple[datetime, datetime]:
        """The hours a summary at the time given covers, up to the hour"""
        end = dt_util.as_local(now).replace(minute=0, second=0, microsecond=0)
        return end - timedelta(hours=self.interval), end


@callback
def said_period(hass: HomeAssistant, start: datetime, end: datetime) -> str:
    """The hours summarised, as said in a title, a day by its name alone when the summary is of all of it"""
    if start.time() == end.time() == time() and end - start == timedelta(days=1):
        return said_day(hass, start)
    if end.time() == time() and end - start <= timedelta(days=1):
        return text(hass, PERIOD_TO_MIDNIGHT, day=said_day(hass, start), start=f"{start:%H:%M}")
    if start.date() == end.date():
        return text(hass, PERIOD_SAME_DAY, day=said_day(hass, start), start=f"{start:%H:%M}", end=f"{end:%H:%M}")
    return text(
        hass,
        PERIOD_DAYS,
        start_day=said_day(hass, start),
        start=f"{start:%H:%M}",
        end_day=said_day(hass, end),
        end=f"{end:%H:%M}",
    )


def summary_text(response: dict[str, Any] | str | None) -> str | None:
    """The summary Frigate made, from what it answered, or nothing when it made none"""
    if isinstance(response, dict):
        summary = response.get("summary")
        return summary.strip() or None if isinstance(summary, str) else None
    return None


@dataclass
class Summaries:
    hass: HomeAssistant
    entry: ConfigEntry
    settings: SummarySettings

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Every hour at the minute set, for those hours a summary is due in, returning what stops it, or nothing to
        stop when switched off"""
        if self.settings.mode == SUMMARY_OFF:
            return lambda: None
        at = self.settings.at
        return async_track_time_change(self.hass, self._due, minute=at.minute, second=at.second)

    @callback
    def _due(self, now: datetime) -> None:
        if self.settings.due(now):
            self.entry.async_create_background_task(self.hass, self.async_send(now), f"{DOMAIN} summary")

    @callback
    def wanted(self, server_id: str, start: datetime) -> bool:
        """Whether a server's summary of the hours from the start given is sent"""
        if self.settings.mode != SUMMARY_AUTO:
            return self.settings.mode == SUMMARY_ON
        config = frigate_config(self.hass, server_id)
        if makes_summaries(config):
            return True
        seen = genai_reviews_seen(self.hass).get(topic_prefix(config))
        return seen is not None and seen >= start.timestamp()

    async def async_send(self, now: datetime) -> None:
        """The summary of the hours before the time given, from each Frigate server it's wanted for"""
        if not supernotify_available(self.hass):
            _LOGGER.debug("CAMERA_AUTONOTIFY No summary without Supernotify")
            return
        deliveries = list(self.settings.deliveries) or await email_deliveries(self.hass)
        if not deliveries:
            _LOGGER.warning("CAMERA_AUTONOTIFY No summary, Supernotify having no e-mail delivery and none chosen")
            return
        await async_load_texts(self.hass)
        start, end = self.settings.period(now)
        said = said_period(self.hass, start, end)
        servers = [
            entry
            for entry in self.hass.config_entries.async_entries(FRIGATE_DOMAIN, include_disabled=False)
            if entry.state is ConfigEntryState.LOADED
        ]
        for server in servers:
            if not self.wanted(server.entry_id, start):
                continue
            client = frigate_client(self.hass, server.entry_id)
            if client is None or not hasattr(client, "async_review_summarize"):
                _LOGGER.warning("CAMERA_AUTONOTIFY Frigate %s can't summarise, needing Frigate 0.17", server.title)
                continue
            try:
                response = await client.async_review_summarize(start.timestamp(), end.timestamp())
            except Exception as error:
                # FrigateApiClientError, for a timeout, a refusal, or Frigate or its GenAI provider failing to make it
                _LOGGER.warning("CAMERA_AUTONOTIFY Frigate %s couldn't summarise %s: %s", server.title, said, error)
                continue
            if (report := summary_text(response)) is None:
                _LOGGER.warning("CAMERA_AUTONOTIFY Frigate %s made no summary of %s: %s", server.title, said, response)
                continue
            if self.settings.concerns_only and not await self._async_concerned(client, server.title, start, end):
                continue
            names = {"period": said, "server": server.title}
            title = text(self.hass, SUMMARY_SERVER_TITLE if len(servers) > 1 else SUMMARY_TITLE, **names)
            await async_notify_message(
                self.hass, title, report, PRIORITY, f"{DOMAIN}_summary_{server.entry_id}", {CONF_DELIVERIES: deliveries}
            )

    async def _async_concerned(self, client: FrigateApiClient, server: str, start: datetime, end: datetime) -> bool:
        """Whether any review starting in the hours given raised a concern, by what GenAI made of it"""
        try:
            reviews = await client.async_get_reviews(after=start.timestamp(), before=end.timestamp())
        except Exception as error:
            _LOGGER.warning("CAMERA_AUTONOTIFY Frigate %s couldn't give its reviews: %s", server, error)
            return False
        found = any(
            concerning(review) and start.timestamp() <= float(review.get("start_time") or 0) < end.timestamp()
            for review in reviews or []
            if isinstance(review, dict)
        )
        if not found:
            _LOGGER.debug("CAMERA_AUTONOTIFY Nothing of concern from Frigate %s, so summary not sent", server)
        return found


@callback
def async_start_summaries(hass: HomeAssistant, entry: ConfigEntry) -> Summaries:
    """The summaries of the global settings entry, stopped as it unloads"""
    summaries = Summaries(hass, entry, SummarySettings.from_options(entry.options))
    entry.async_on_unload(summaries.async_start())
    return summaries
