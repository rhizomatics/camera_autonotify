"""A summary of the hours before, from each Frigate server, made by Frigate's generative AI from their reviews, as the
`frigate.review_summarize` action does, sent every so many hours, once a day to begin with, as set in the global
settings

Sent automatically when Frigate makes review summaries for any of a server's cameras, or a review summary has come
over MQTT in the hours summarised, or else always or never, as chosen. It can be kept for when there's something to
worry about: Frigate is always asked for the summary, but it's only sent when one of the reviews in those hours was
given a threat level, or other concerns, by GenAI. A summary Frigate can't make is logged and nothing sent.

The reviews are chosen as Frigate chooses them for its summary: those overlapping the hours, over by their end, with a
GenAI review summary. With none of concern, Frigate answers with a fixed sentence in English instead of a summary, so
that's said here in Home Assistant's language instead. The reviews are asked for after the summary, so there can only be
more of them than Frigate saw, and a summary it did make is never taken for one of those sentences.

A summary Frigate fails to make, by an error or by answering without one, is asked for again so many times, a quarter
of an hour apart, and if it still fails, that's notified in its place, by the same deliveries, saying why as far as can
be told, with links to Home Assistant's logs, the Frigate integration's page for its diagnostics, and Frigate's own
GenAI troubleshooting.

Too long for a phone's notification or a voice assistant, so only sent through Supernotify, by one of its e-mail
deliveries unless others are chosen, such as Telegram, and not at all when it has none.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DELIVERIES,
    CONF_SUMMARY_CONCERNS,
    CONF_SUMMARY_DELIVERIES,
    CONF_SUMMARY_INTERVAL,
    CONF_SUMMARY_MODE,
    CONF_SUMMARY_RETRIES,
    CONF_SUMMARY_TIME,
    DEFAULT_SUMMARY_INTERVAL,
    DEFAULT_SUMMARY_RETRIES,
    DEFAULT_SUMMARY_TIME,
    DOMAIN,
    FRIGATE_DOMAIN,
    MAX_SUMMARY_RETRIES,
    SUMMARY_AUTO,
    SUMMARY_INTERVALS,
    SUMMARY_MODES,
    SUMMARY_OFF,
    SUMMARY_ON,
)
from .frigate import (
    FrigateApiClient,
    base_url,
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
    SUMMARY_FAILED,
    SUMMARY_FAILED_AUTH,
    SUMMARY_FAILED_NONE,
    SUMMARY_FAILED_OTHER,
    SUMMARY_FAILED_STATUS,
    SUMMARY_FAILED_TIMEOUT,
    SUMMARY_FAILED_TITLE,
    SUMMARY_FAILED_UNREACHABLE,
    SUMMARY_NO_ACTIVITY,
    SUMMARY_NO_CONCERNS,
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
# a quarter of an hour between each time Frigate is asked again for a summary it failed to make
RETRY_DELAY = 900
# where to look further, Home Assistant's own pages by its address, Frigate's GenAI troubleshooting by its docs
LOGS_PATH = "/config/logs"
FRIGATE_PATH = f"/config/integrations/integration/{FRIGATE_DOMAIN}"
GENAI_HELP = "https://docs.frigate.video/configuration/genai/genai_config#how-do-i-debug-genai-issues"
DEFAULT_TIME = time.fromisoformat(DEFAULT_SUMMARY_TIME)


@dataclass(frozen=True)
class SummarySettings:
    mode: str = SUMMARY_AUTO
    at: time = DEFAULT_TIME
    # hours between summaries, from the time set
    interval: int = DEFAULT_SUMMARY_INTERVAL
    concerns_only: bool = False
    deliveries: tuple[str, ...] = ()
    # how many more times a summary Frigate failed to make is asked for
    retries: int = DEFAULT_SUMMARY_RETRIES

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
        try:
            retries = min(max(int(options.get(CONF_SUMMARY_RETRIES, default.retries)), 0), MAX_SUMMARY_RETRIES)
        except TypeError, ValueError:
            retries = default.retries
        return cls(
            mode=mode if mode in SUMMARY_MODES else default.mode,
            at=at,
            interval=interval if interval in SUMMARY_INTERVALS else default.interval,
            concerns_only=bool(options.get(CONF_SUMMARY_CONCERNS, default.concerns_only)),
            deliveries=tuple(options.get(CONF_SUMMARY_DELIVERIES) or ()),
            retries=retries,
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


def failure(hass: HomeAssistant, error: BaseException) -> str:
    """Why Frigate couldn't make a summary, as far as can be told, the Frigate integration's own error mostly saying
    nothing itself, raised from what went wrong"""
    cause = error.__cause__ or error
    if isinstance(cause, TimeoutError):
        return text(hass, SUMMARY_FAILED_TIMEOUT)
    status = getattr(cause, "status", None)
    if status in (401, 403):
        return text(hass, SUMMARY_FAILED_AUTH)
    if isinstance(status, int):
        return text(hass, SUMMARY_FAILED_STATUS, status=status)
    if isinstance(cause, aiohttp.ClientError | OSError):
        return text(hass, SUMMARY_FAILED_UNREACHABLE)
    return text(hass, SUMMARY_FAILED_OTHER, error=str(error) or type(cause).__name__)


def unmade(hass: HomeAssistant, response: dict[str, Any] | str | None) -> str:
    """Why Frigate answered without a summary, by its own message where it gave one"""
    message = response.get("message") if isinstance(response, dict) else response
    return text(hass, SUMMARY_FAILED_NONE, message=str(message or "")[:200])


@dataclass(frozen=True)
class Found:
    """How many of the reviews in the hours summarised GenAI summarised, and how many of those were of concern"""

    summarised: int
    concerns: int


def found(reviews: list[dict[str, Any]] | None, start: datetime, end: datetime) -> Found:
    """The reviews as Frigate chooses them for its summary: overlapping the hours, over by their end, and summarised by
    GenAI, an ongoing one being left out"""
    chosen = [
        review
        for review in reviews or []
        if isinstance(review, dict)
        and review.get("end_time") is not None
        and float(review.get("start_time") or 0) < end.timestamp()
        and float(review["end_time"]) > start.timestamp()
        and (review.get("data") or {}).get("metadata")
    ]
    return Found(len(chosen), sum(1 for review in chosen if concerning(review)))


@dataclass(frozen=True)
class Report:
    """A summary to ask a Frigate server for, and where it goes"""

    server_id: str
    server: str
    start: datetime
    end: datetime
    # titled by the server, there being more than one
    several: bool
    deliveries: list[str]

    def title_key(self, several: str, one: str) -> str:
        return several if self.several else one


@dataclass
class Summaries:
    hass: HomeAssistant
    entry: ConfigEntry
    settings: SummarySettings
    # each summary to be asked for again, by its server and the start of its hours, to be cancelled when stopped
    _retries: dict[tuple[str, float], CALLBACK_TYPE] = field(default_factory=dict)

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Every hour at the minute set, for those hours a summary is due in, returning what stops it, and any retry
        waiting, or nothing to stop when switched off"""
        if self.settings.mode == SUMMARY_OFF:
            return lambda: None
        at = self.settings.at
        stop_due = async_track_time_change(self.hass, self._due, minute=at.minute, second=at.second)

        @callback
        def stop() -> None:
            stop_due()
            for cancel in self._retries.values():
                cancel()
            self._retries.clear()

        return stop

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
        start, end = self.settings.period(now)
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
            await self._async_report(Report(server.entry_id, server.title, start, end, len(servers) > 1, deliveries))

    async def _async_report(self, report: Report, attempt: int = 1) -> None:
        """A server's summary of its hours, asked for again if it fails, so many times, then its failure notified"""
        await async_load_texts(self.hass)
        said = said_period(self.hass, report.start, report.end)
        client = frigate_client(self.hass, report.server_id)
        why: str | None = None
        made: str | None = None
        if client is None:
            # the Frigate entry unloaded since the first try
            why = text(self.hass, SUMMARY_FAILED_UNREACHABLE)
        else:
            try:
                response = await client.async_review_summarize(report.start.timestamp(), report.end.timestamp())
            except Exception as error:
                # FrigateApiClientError, for a timeout, a refusal, or Frigate or its GenAI provider failing to make it
                _LOGGER.warning(
                    "CAMERA_AUTONOTIFY Frigate %s couldn't summarise %s: %s",
                    report.server,
                    said,
                    str(error) or repr(error.__cause__ or error),
                )
                why = failure(self.hass, error)
            else:
                if (made := summary_text(response)) is None:
                    _LOGGER.warning("CAMERA_AUTONOTIFY Frigate %s made no summary of %s: %s", report.server, said, response)
                    why = unmade(self.hass, response)
        if client is None or made is None:
            await self._async_failed(report, attempt, said, why or "")
            return
        seen = await self._async_found(client, report.server, report.start, report.end)
        if seen is None and self.settings.concerns_only:
            return
        if seen is not None and not seen.concerns:
            if self.settings.concerns_only:
                _LOGGER.debug("CAMERA_AUTONOTIFY Nothing of concern from Frigate %s, so summary not sent", report.server)
                return
            made = text(self.hass, SUMMARY_NO_CONCERNS if seen.summarised else SUMMARY_NO_ACTIVITY)
        title = text(self.hass, report.title_key(SUMMARY_SERVER_TITLE, SUMMARY_TITLE), period=said, server=report.server)
        await async_notify_message(
            self.hass, title, made, PRIORITY, f"{DOMAIN}_summary_{report.server_id}", {CONF_DELIVERIES: report.deliveries}
        )

    async def _async_failed(self, report: Report, attempt: int, said: str, why: str) -> None:
        """Asked for again in a while, or else, once asked for as many times as set, its failure notified, whether or
        not only concerns are sent, since a failed summary can't say there were none"""
        if attempt <= self.settings.retries:
            _LOGGER.info(
                "CAMERA_AUTONOTIFY Asking Frigate %s again for %s in %s seconds, retry %s of %s",
                report.server,
                said,
                RETRY_DELAY,
                attempt,
                self.settings.retries,
            )
            key = (report.server_id, report.start.timestamp())

            @callback
            def again(_now: datetime) -> None:
                self._retries.pop(key, None)
                self.entry.async_create_background_task(
                    self.hass, self._async_report(report, attempt + 1), f"{DOMAIN} summary retry"
                )

            self._retries[key] = async_call_later(self.hass, RETRY_DELAY, again)
            return
        base = base_url(self.hass) or ""
        message = text(
            self.hass,
            SUMMARY_FAILED,
            server=report.server,
            attempts=attempt,
            reason=why,
            logs=f"{base}{LOGS_PATH}",
            diagnostics=f"{base}{FRIGATE_PATH}",
            help=GENAI_HELP,
        )
        title = text(self.hass, SUMMARY_FAILED_TITLE, period=said, server=report.server)
        await async_notify_message(
            self.hass,
            title,
            message,
            PRIORITY,
            f"{DOMAIN}_summary_{report.server_id}",
            {CONF_DELIVERIES: report.deliveries},
        )

    async def _async_found(self, client: FrigateApiClient, server: str, start: datetime, end: datetime) -> Found | None:
        """What GenAI made of the reviews in the hours given, or nothing when Frigate couldn't give them"""
        try:
            reviews = await client.async_get_reviews(after=start.timestamp(), before=end.timestamp())
        except Exception as error:
            _LOGGER.warning("CAMERA_AUTONOTIFY Frigate %s couldn't give its reviews: %s", server, error)
            return None
        return found(reviews, start, end)


@callback
def async_start_summaries(hass: HomeAssistant, entry: ConfigEntry) -> Summaries:
    """The summaries of the global settings entry, stopped as it unloads"""
    summaries = Summaries(hass, entry, SummarySettings.from_options(entry.options))
    entry.async_on_unload(summaries.async_start())
    return summaries
