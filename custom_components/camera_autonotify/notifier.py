"""The notification for each decision of the tracker, through Supernotify, or a plain one without it"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_ENTITY_ID, CONF_TYPE
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import (
    ACTION_VIEW_SNAPSHOT,
    CONF_CUSTOM_TARGET,
    CONF_DELIVERIES,
    CONF_SOURCE_ENTRY_ID,
    CONF_TARGET,
    CONF_TARGETS,
    CONF_THREAT_PRIORITIES,
    DOMAIN,
    MESSAGE_ENDED,
    MESSAGE_IN_ZONES,
    MESSAGE_ON_CAMERA,
    MESSAGE_SEEN,
    SUBENTRY_RULE,
    SUPERNOTIFY_DOMAIN,
    THREAT_PRIORITY_DEFAULTS,
    TYPE_DISCOVERY,
    TYPE_ZONE,
)
from .frigate import camera_entity_id, hls_url, notifications_url, snapshot_url
from .rules import Outcome, Rule, apply_rules, rank
from .supernotify_api import supernotify_available

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Context, HomeAssistant

    from .tracker import Decision

_LOGGER = logging.getLogger(__name__)

MOBILE_APP_PLATFORM = "mobile_app"
# by severity, an alert to be noticed and a detection not to interrupt, both left to Supernotify to map to each
# platform, as iOS's time sensitive or Android's high importance
PRIORITY_ALERT = "high"
PRIORITY_DETECTION = "medium"
# an update with alert once, no sound or interruption, iOS's passive
PRIORITY_SILENT = "low"
SEVERITY_ALERT = "alert"


def _friendly(name: str) -> str:
    """A zone or camera as Frigate writes it, `Barn_Door`, as said in a notification"""
    return name.replace("_", " ").title()


@callback
def notification_rules(hass: HomeAssistant) -> list[Rule]:
    """The rules for every notification, the subentries of the discovery entry, read as each is sent so a change
    applies straight away"""
    for entry in hass.config_entries.async_entries(DOMAIN, include_disabled=False):
        if entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            built = [
                Rule.from_data(subentry.title, subentry.data)
                for subentry in entry.subentries.values()
                if subentry.subentry_type == SUBENTRY_RULE
            ]
            return [rule for rule in built if rule is not None]
    return []


class Notifier:
    """Sends each notification for a camera's or a zone's entry"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.name: str = entry.title
        self.is_zone: bool = entry.data.get(CONF_TYPE) == TYPE_ZONE
        self.source_entry_id: str = entry.data[CONF_SOURCE_ENTRY_ID]

    def title(self, decision: Decision) -> str:
        summary = decision.summary
        return summary.title if summary is not None and summary.title else self.name

    def message(self, decision: Decision) -> str:
        """What the notification says, before rules"""
        review = decision.review
        if (summary := decision.summary) is not None:
            message = summary.short_summary or summary.title
            if summary.other_concerns:
                message = f"{message} ({', '.join(summary.other_concerns)})"
            return message
        if decision.description:
            return decision.description
        if self.is_zone:
            message = MESSAGE_ON_CAMERA.format(label=review.label, camera=_friendly(review.camera))
        elif review.zones:
            message = MESSAGE_IN_ZONES.format(label=review.label, zones=", ".join(_friendly(z) for z in review.zones))
        else:
            message = MESSAGE_SEEN.format(label=review.label)
        return MESSAGE_ENDED.format(message=message) if decision.is_final else message

    def ruled(self, decision: Decision) -> Outcome:
        return apply_rules(notification_rules(self.hass), self.message(decision))

    def priority(self, decision: Decision, outcome: Outcome) -> str:
        """By the review's severity, or a summary's threat level, raised by a rule, and only sounding again for an
        update with alert once when raised"""
        review = decision.review
        own = PRIORITY_ALERT if review.severity == SEVERITY_ALERT else PRIORITY_DETECTION
        priority = own
        raised = False
        if (summary := decision.summary) is not None:
            level = min(max(summary.threat_level, 0), len(CONF_THREAT_PRIORITIES) - 1)
            priority = self.entry.options.get(CONF_THREAT_PRIORITIES[level]) or THREAT_PRIORITY_DEFAULTS[level]
            raised = summary.threat_level > 0
        if rank(outcome.priority) > rank(priority) or (outcome.priority and summary is None):
            priority = outcome.priority or priority
        raised = raised or rank(priority) > rank(own)
        if decision.silent and not raised:
            return PRIORITY_SILENT
        return priority

    def supernotify_data(self, decision: Decision, outcome: Outcome | None = None) -> dict[str, Any]:
        """The `supernotify.notify` call: the snapshot, tapped for the clip as HLS, and never `clip_url`, which iOS
        fails to show, even the image"""
        review = decision.review
        outcome = outcome or self.ruled(decision)
        data: dict[str, Any] = {
            "title": self.title(decision),
            "message": outcome.message,
            "priority": self.priority(decision, outcome),
            "extra_data": {
                # each update of a review takes the place of its last notification
                "mobile_push_notification_tag": f"frigate_{decision.key}",
                "group": f"frigate_{review.camera}",
            },
        }
        media: dict[str, Any] = {}
        if camera := camera_entity_id(self.hass, self.source_entry_id, review.camera):
            # for Supernotify's camera snooze, the snapshot still being the image
            media["camera_entity_id"] = camera
        notifications = notifications_url(self.hass, self.source_entry_id)
        if notifications and decision.detection_id:
            snapshot = snapshot_url(notifications, decision.detection_id)
            media["snapshot_url"] = snapshot
            data["actions"] = [
                {"level": "notification", "uri": hls_url(notifications, decision.detection_id, review.camera)},
                {"action": "URI", "title": ACTION_VIEW_SNAPSHOT, "uri": snapshot},
            ]
        if media:
            data["media"] = media
        if deliveries := self.entry.options.get(CONF_DELIVERIES):
            data["delivery"] = list(deliveries)
            data["delivery_selection"] = "explicit"
        for key in (CONF_TARGET, CONF_CUSTOM_TARGET):
            if value := self.entry.options.get(key):
                data[key] = value
        if outcome.scenarios:
            data["apply_scenarios"] = list(outcome.scenarios)
        return data

    async def async_notify(self, decision: Decision, context: Context) -> None:
        outcome = self.ruled(decision)
        if outcome.silence:
            _LOGGER.debug("CAMERA_AUTONOTIFY Silenced for %s by %s", self.name, ", ".join(outcome.matched))
            return
        if not supernotify_available(self.hass):
            await self._send_message(decision, outcome, context)
            return
        try:
            await self.hass.services.async_call(
                SUPERNOTIFY_DOMAIN, "notify", self.supernotify_data(decision, outcome), blocking=True, context=context
            )
        except HomeAssistantError:
            _LOGGER.exception("CAMERA_AUTONOTIFY Supernotify notification failed for %s", self.name)

    async def _send_message(self, decision: Decision, outcome: Outcome, context: Context) -> None:
        """Plain text only, with no snapshot or link, Supernotify being what's needed for those"""
        if decision.is_update:
            # each would be a new notification, with nothing to take the place of the last
            return
        # with none chosen, every phone with the mobile app is told
        targets: list[str] = self.entry.options.get(CONF_TARGETS) or [
            entity.entity_id
            for entity in er.async_get(self.hass).entities.values()
            if entity.domain == "notify" and entity.platform == MOBILE_APP_PLATFORM and not entity.disabled
        ]
        if not targets:
            _LOGGER.warning("CAMERA_AUTONOTIFY Nothing to notify for %s, choose targets in its settings", self.name)
            return
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {ATTR_ENTITY_ID: targets, "title": self.title(decision), "message": outcome.message},
                blocking=True,
                context=context,
            )
        except HomeAssistantError:
            _LOGGER.exception("CAMERA_AUTONOTIFY Notification failed for %s", self.name)
