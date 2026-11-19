"""The notification for each decision of the tracker, through Supernotify, or a plain one without it"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_ENTITY_ID, CONF_NAME, CONF_TYPE
from homeassistant.core import Context, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .actions import buttons
from .const import (
    CONF_CUSTOM_TARGET,
    CONF_DELIVERIES,
    CONF_GENAI_IMAGE,
    CONF_IMAGE,
    CONF_OBJECT,
    CONF_OBJECT_NAMES,
    CONF_SOURCE_ENTRY_ID,
    CONF_SPEED_UNIT,
    CONF_TARGET,
    CONF_TARGETS,
    CONF_THREAT_PRIORITIES,
    DEFAULT_GENAI_IMAGE,
    DEFAULT_IMAGE,
    DOMAIN,
    GENAI_IMAGE_GLOBAL,
    IMAGE_PREVIEW,
    SUBENTRY_RULE,
    SUPERNOTIFY_DOMAIN,
    THREAT_PRIORITY_DEFAULTS,
    TYPE_ZONE,
)
from .entries import global_settings
from .frigate import (
    camera_entity_id,
    camera_records,
    face_threshold,
    fact_store,
    frigate_config,
    hls_url,
    image_url,
    notifications_url,
    preferred_speed_unit,
    said_speed,
    snapshot_url,
    speed_unit,
)
from .rules import Outcome, Rule, apply_rules, rank
from .supernotify_api import fallback_urls, supernotify_available
from .texts import (
    ACTION_VIEW_SNAPSHOT,
    FACT_FACE_UNKNOWN,
    FACT_STATE,
    FACT_STATIONARY,
    HEADLINE,
    HEADLINE_ENDED,
    OBJECTS_JOINED,
    OBJECTS_NONE,
    async_load_texts,
    text,
)
from .tracker import Reason

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .tracker import Decision

_LOGGER = logging.getLogger(__name__)

MOBILE_APP_PLATFORM = "mobile_app"
# by severity, an alert to be noticed and a detection not to interrupt, both left to Supernotify to map to each
# platform, as iOS's time sensitive or Android's high importance
PRIORITY_ALERT = "high"
PRIORITY_DETECTION = "medium"
# an update with alert once, no sound or interruption, iOS's passive
PRIORITY_SILENT = "low"
# the logos of a Frigate+ model, as its labels, by the name of the brand, rather than `Dpd` or `Royal mail`
BRAND_NAMES: dict[str, str] = {
    "amazon": "Amazon",
    "an_post": "An Post",
    "canada_post": "Canada Post",
    "dhl": "DHL",
    "dpd": "DPD",
    "fedex": "FedEx",
    "gls": "GLS",
    "nzpost": "NZ Post",
    "postnl": "PostNL",
    "postnord": "PostNord",
    "purolator": "Purolator",
    "royal_mail": "Royal Mail",
    "ups": "UPS",
    "usps": "USPS",
}
# between the facts said under the headline, plain, so it reads the same in every delivery
FACTS_SEPARATOR = " - "
# a camera's or zone's own entry on the integration's page, by its entry id
HELP_PATH = f"/config/integrations/integration/{DOMAIN}#config_entry="
SEVERITY_ALERT = "alert"


def _friendly(name: str) -> str:
    """A zone or camera as Frigate writes it, `Barn_Door`, as said in a notification"""
    return name.replace("_", " ").title()


@callback
def notification_rules(hass: HomeAssistant) -> list[Rule]:
    """The rules for every notification, the subentries of the discovery entry, read as each is sent so a change
    applies straight away"""
    if (entry := global_settings(hass)) is None:
        return []
    built = [
        Rule.from_data(subentry.title, subentry.data)
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_RULE
    ]
    return [rule for rule in built if rule is not None]


@callback
def object_names(hass: HomeAssistant) -> dict[str, str]:
    """What each of Frigate's objects is called in a notification, where the global settings give it a name, read as
    each is sent so a change applies straight away, and otherwise a delivery company's logo by its brand"""
    names: dict[str, str] = dict(BRAND_NAMES)
    if (entry := global_settings(hass)) is None:
        return names
    named = entry.options.get(CONF_OBJECT_NAMES) or []
    for item in named if isinstance(named, list) else []:
        if not isinstance(item, dict):
            continue
        obj, name = str(item.get(CONF_OBJECT) or "").strip(), str(item.get(CONF_NAME) or "").strip()
        if obj and name:
            names[obj] = name
    return names


@callback
def mobile_app_targets(hass: HomeAssistant) -> list[str]:
    """Every phone with the mobile app, those told when no targets are chosen"""
    return [
        entity.entity_id
        for entity in er.async_get(hass).entities.values()
        if entity.domain == "notify" and entity.platform == MOBILE_APP_PLATFORM and not entity.disabled
    ]


async def async_notify_message(
    hass: HomeAssistant, title: str, message: str, priority: str, tag: str, options: Mapping[str, Any] | None = None
) -> None:
    """A notification of the integration's own, not of a review, such as a Frigate server failing its health check,
    with the rules applied to its message like any other, through Supernotify, or else to every phone, and for a
    camera, to whoever its options choose"""
    options = options or {}
    await async_load_texts(hass)
    outcome = apply_rules(notification_rules(hass), message)
    if outcome.silence:
        _LOGGER.debug("CAMERA_AUTONOTIFY Silenced %s by %s", title, ", ".join(outcome.matched))
        return
    context = Context()
    try:
        if supernotify_available(hass):
            data: dict[str, Any] = {
                "title": title,
                "message": outcome.message,
                "priority": outcome.priority or priority,
                # each with the same tag takes the place of the last, as a recovery does of its failure
                "extra_data": {"mobile_push_notification_tag": tag, "group": DOMAIN},
            }
            if deliveries := options.get(CONF_DELIVERIES):
                data["delivery"] = list(deliveries)
                data["delivery_selection"] = "explicit"
            for key in (CONF_TARGET, CONF_CUSTOM_TARGET):
                if value := options.get(key):
                    data[key] = value
            if outcome.scenarios:
                data["apply_scenarios"] = list(outcome.scenarios)
            await hass.services.async_call(SUPERNOTIFY_DOMAIN, "notify", data, blocking=True, context=context)
            return
        if not (targets := options.get(CONF_TARGETS) or mobile_app_targets(hass)):
            _LOGGER.warning("CAMERA_AUTONOTIFY Nothing to notify %s to", title)
            return
        await hass.services.async_call(
            "notify",
            "send_message",
            {ATTR_ENTITY_ID: targets, "title": title, "message": outcome.message},
            blocking=True,
            context=context,
        )
    except HomeAssistantError:
        _LOGGER.exception("CAMERA_AUTONOTIFY Notification failed: %s", title)


class Notifier:
    """Sends each notification for a camera's or a zone's entry"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.name: str = entry.title
        self.is_zone: bool = entry.data.get(CONF_TYPE) == TYPE_ZONE
        self.source_entry_id: str = entry.data[CONF_SOURCE_ENTRY_ID]

    def headline(self, decision: Decision) -> str:
        """What was seen and where, `Person detected at Barn Door`, the zone's own name for a zone, or else the
        zones the review entered, or the camera's name when none"""
        review = decision.review
        if self.is_zone or not review.zones:
            where = self.name
        else:
            where = ", ".join(_friendly(zone) for zone in review.zones)
        label = review.said(object_names(self.hass), text(self.hass, OBJECTS_JOINED), text(self.hass, OBJECTS_NONE))
        headline = text(self.hass, HEADLINE, label=label, where=where)
        return text(self.hass, HEADLINE_ENDED, headline=headline) if decision.is_final else headline

    def title(self, decision: Decision) -> str:
        summary = decision.summary
        return summary.title if summary is not None and summary.title else self.headline(decision)

    def message(self, decision: Decision) -> str:
        """What the notification says under its title, before rules, with nothing more to say than the headline
        without a summary or description"""
        if (summary := decision.summary) is not None:
            message = summary.short_summary or summary.title
            if summary.other_concerns:
                message = f"{message} ({', '.join(summary.other_concerns)})"
            return message
        return decision.description or ""

    def ruled(self, decision: Decision) -> tuple[str, Outcome]:
        """The title, and the outcome of the rules for the message, or for the headline when that's all there is,
        so a rule can still match what was seen"""
        rules = notification_rules(self.hass)
        if message := self.message(decision):
            return self.title(decision), apply_rules(rules, message)
        outcome = apply_rules(rules, self.headline(decision))
        return outcome.message, replace(outcome, message=self.facts(decision))

    def facts(self, decision: Decision) -> str:
        """What Frigate knows of the review's objects beyond the review, as a line under the headline: the highest
        speed, plates read that Frigate doesn't know, attributes such as a delivery company, a face seen but not
        recognised, whether it has stopped, and the camera's state classifications"""
        store = fact_store(self.hass, self.source_entry_id)
        if store is None:
            return ""
        review = decision.review
        config = frigate_config(self.hass, self.source_entry_id)
        found = store.of_review(review.camera, review.detections, face_threshold(config))
        names = object_names(self.hass)
        said: list[str] = []
        if found.speed >= 1:
            settings = global_settings(self.hass)
            unit = preferred_speed_unit(self.hass, settings.options.get(CONF_SPEED_UNIT) if settings else None)
            said.append(said_speed(found.speed, speed_unit(config), unit))
        said.extend(found.plates)
        # not one already said in the headline, such as a van that's also a DPD logo
        said.extend(names.get(label) or _friendly(label) for label in found.attributes if label not in review.objects)
        if found.face_unknown:
            said.append(text(self.hass, FACT_FACE_UNKNOWN))
        if found.stationary:
            said.append(text(self.hass, FACT_STATIONARY))
        said.extend(text(self.hass, FACT_STATE, model=_friendly(m), state=s.replace("_", " ")) for m, s in found.states)
        return FACTS_SEPARATOR.join(said)

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

    def image(self, decision: Decision) -> str:
        """The image chosen, the GenAI image for what GenAI adds, except the animated preview falls back to the
        camera's own image, or the snapshot with its box, where Frigate can't make it yet: for a camera that doesn't
        record, since it's made from the frames kept for the recordings, and for the first notification of a review,
        which may come before Frigate has any frames of the event. An update takes the first notification's place, so
        the preview follows as soon as there's one, and GenAI only adds to an event Frigate has frames of"""
        own: str = self.entry.options.get(CONF_IMAGE) or DEFAULT_IMAGE
        genai = decision.reason in (Reason.SUMMARY, Reason.DESCRIPTION)
        image = self.genai_image() if genai else own
        if image != IMAGE_PREVIEW:
            return image
        records = camera_records(frigate_config(self.hass, self.source_entry_id), decision.review.camera)
        if records and (genai or decision.is_update):
            return image
        return self.still_image()

    def still_image(self) -> str:
        """The camera's own image where it isn't the animated preview, or else the snapshot with its box, for when
        the preview can't be had"""
        own: str = self.entry.options.get(CONF_IMAGE) or DEFAULT_IMAGE
        return own if own != IMAGE_PREVIEW else DEFAULT_IMAGE

    def genai_image(self) -> str:
        """The camera's own image for what GenAI adds, or else the global settings'"""
        chosen: str | None = self.entry.options.get(CONF_GENAI_IMAGE)
        if chosen and chosen != GENAI_IMAGE_GLOBAL:
            return chosen
        entry = global_settings(self.hass)
        return (entry.options.get(CONF_GENAI_IMAGE) if entry else None) or DEFAULT_GENAI_IMAGE

    def spoken(self, decision: Decision, title: str, outcome: Outcome) -> str:
        """What a voice assistant or speaker says: the headline, and GenAI's summary or description where there's
        one, being written to be read, but never the facts under the headline, which are for reading, not hearing"""
        if self.message(decision) and outcome.message:
            return f"{title}. {outcome.message}"
        return title

    def supernotify_data(
        self, decision: Decision, ruled: tuple[str, Outcome] | None = None, fallback: bool = False
    ) -> dict[str, Any]:
        """The `supernotify.notify` call: the snapshot, tapped for the clip as HLS, and never `clip_url`, which iOS
        fails to show, even the image"""
        review = decision.review
        title, outcome = ruled or self.ruled(decision)
        data: dict[str, Any] = {
            "title": title,
            "message": outcome.message,
            "spoken_message": self.spoken(decision, title, outcome),
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
            # the image chosen, though the button is always for the whole snapshot
            image = self.image(decision)
            url = image_url(notifications, decision.detection_id, image)
            if image == IMAGE_PREVIEW and fallback:
                # tried in order, the still image behind the preview for when Frigate can't make it, and the GIF not
                # redrawn, which would keep only its first frame, while the still image is as usual
                still = image_url(notifications, decision.detection_id, self.still_image())
                media["snapshot_url"] = [{"url": url, "reprocess": "never"}, still]
            else:
                media["snapshot_url"] = url
                if image == IMAGE_PREVIEW:
                    # Supernotify otherwise redraws the image it attaches, keeping only a GIF's first frame
                    media["reprocess"] = "never"
            if fallback:
                # where to change the image, linked from Supernotify's repair when none of it can be had
                media["help_url"] = f"{HELP_PATH}{self.entry.entry_id}"
            data["actions"] = [
                {"level": "notification", "uri": hls_url(notifications, decision.detection_id, review.camera)},
                {
                    "action": "URI",
                    "title": text(self.hass, ACTION_VIEW_SNAPSHOT),
                    "uri": snapshot_url(notifications, decision.detection_id),
                },
            ]
        if more := buttons(self.hass, self.entry, decision):
            data.setdefault("actions", []).extend(more)
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
        await async_load_texts(self.hass)
        title, outcome = self.ruled(decision)
        if outcome.silence:
            _LOGGER.debug("CAMERA_AUTONOTIFY Silenced for %s by %s", self.name, ", ".join(outcome.matched))
            return
        if not supernotify_available(self.hass):
            await self._send_message(decision, title, outcome.message, context)
            return
        try:
            data = self.supernotify_data(decision, (title, outcome), fallback=fallback_urls(self.hass))
            await self.hass.services.async_call(SUPERNOTIFY_DOMAIN, "notify", data, blocking=True, context=context)
        except HomeAssistantError:
            _LOGGER.exception("CAMERA_AUTONOTIFY Supernotify notification failed for %s", self.name)

    async def _send_message(self, decision: Decision, title: str, message: str, context: Context) -> None:
        """Plain text only, with no snapshot or link, Supernotify being what's needed for those"""
        if decision.is_update:
            # each would be a new notification, with nothing to take the place of the last
            return
        targets: list[str] = self.entry.options.get(CONF_TARGETS) or mobile_app_targets(self.hass)
        if not targets:
            _LOGGER.warning("CAMERA_AUTONOTIFY Nothing to notify for %s, choose targets in its settings", self.name)
            return
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {ATTR_ENTITY_ID: targets, "title": title, "message": message},
                blocking=True,
                context=context,
            )
        except HomeAssistantError:
            _LOGGER.exception("CAMERA_AUTONOTIFY Notification failed for %s", self.name)
