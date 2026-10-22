"""The notification for each decision of the tracker, through Supernotify, or a plain one without it"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_ENTITY_ID, CONF_TYPE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import (
    ACTION_VIEW_SNAPSHOT,
    CONF_CUSTOM_TARGET,
    CONF_DELIVERIES,
    CONF_FRIGATE_ENTRY_ID,
    CONF_TARGET,
    CONF_TARGETS,
    MESSAGE_ENDED,
    MESSAGE_IN_ZONES,
    MESSAGE_ON_CAMERA,
    MESSAGE_SEEN,
    SUPERNOTIFY_DOMAIN,
    TYPE_ZONE,
)
from .frigate import base_url, camera_entity_id, hls_url, snapshot_url
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


class Notifier:
    """Sends each notification for a camera's or a zone's entry"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.name: str = entry.title
        self.is_zone: bool = entry.data.get(CONF_TYPE) == TYPE_ZONE
        self.frigate_entry_id: str = entry.data[CONF_FRIGATE_ENTRY_ID]

    def message(self, decision: Decision) -> str:
        review = decision.review
        if self.is_zone:
            message = MESSAGE_ON_CAMERA.format(label=review.label, camera=_friendly(review.camera))
        elif review.zones:
            message = MESSAGE_IN_ZONES.format(label=review.label, zones=", ".join(_friendly(z) for z in review.zones))
        else:
            message = MESSAGE_SEEN.format(label=review.label)
        return MESSAGE_ENDED.format(message=message) if decision.is_final else message

    def supernotify_data(self, decision: Decision) -> dict[str, Any]:
        """The `supernotify.notify` call: the snapshot, tapped for the clip as HLS, and never `clip_url`, which iOS
        fails to show, even the image"""
        review = decision.review
        if decision.silent:
            priority = PRIORITY_SILENT
        else:
            priority = PRIORITY_ALERT if review.severity == SEVERITY_ALERT else PRIORITY_DETECTION
        data: dict[str, Any] = {
            "title": self.name,
            "message": self.message(decision),
            "priority": priority,
            "extra_data": {
                # each update of a review takes the place of its last notification
                "mobile_push_notification_tag": f"frigate_{review.id}",
                "group": f"frigate_{review.camera}",
            },
        }
        media: dict[str, Any] = {}
        if camera := camera_entity_id(self.hass, self.frigate_entry_id, review.camera):
            # for Supernotify's camera snooze, the snapshot still being the image
            media["camera_entity_id"] = camera
        base = base_url(self.hass)
        if base and decision.detection_id:
            snapshot = snapshot_url(base, decision.detection_id)
            media["snapshot_url"] = snapshot
            data["actions"] = [
                {"level": "notification", "uri": hls_url(base, decision.detection_id, review.camera)},
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
        return data

    async def async_notify(self, decision: Decision, context: Context) -> None:
        if not supernotify_available(self.hass):
            await self._send_message(decision, context)
            return
        try:
            await self.hass.services.async_call(
                SUPERNOTIFY_DOMAIN, "notify", self.supernotify_data(decision), blocking=True, context=context
            )
        except HomeAssistantError:
            _LOGGER.exception("FRIGATE_AUTONOTIFY Supernotify notification failed for %s", self.name)

    async def _send_message(self, decision: Decision, context: Context) -> None:
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
            _LOGGER.warning("FRIGATE_AUTONOTIFY Nothing to notify for %s, choose targets in its settings", self.name)
            return
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {ATTR_ENTITY_ID: targets, "title": self.name, "message": self.message(decision)},
                blocking=True,
                context=context,
            )
        except HomeAssistantError:
            _LOGGER.exception("FRIGATE_AUTONOTIFY Notification failed for %s", self.name)
