"""The actions on a notification, as buttons on a phone: keeping the clip from Frigate's retention, marking the review
as seen in Frigate's own UI, submitting the snapshot to Frigate+, and exporting the recording around the review

Each is offered only where Frigate can do it, as its config says, and as chosen in the global settings, or by the
camera or zone itself. A button's action names what it's for, the entry of the camera or zone it was sent for, and
the review or detection, so the Frigate server is found from the entry when it's tapped, by
`mobile_app_notification_action`, which Supernotify leaves alone, acting only on its own `SUPERNOTIFY_` actions.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback

from .const import (
    ACTION_EXPORT,
    ACTION_KEEP,
    ACTION_PLUS,
    ACTION_SEEN,
    ACTIONS,
    CONF_ACTIONS,
    CONF_ACTIONS_GLOBAL,
    CONF_SOURCE_ENTRY_ID,
    DEFAULT_ACTIONS,
    DOMAIN,
)
from .entries import global_settings
from .frigate import (
    camera_records,
    camera_snapshots,
    fact_store,
    frigate_client,
    frigate_config,
    frigate_url,
    plus_enabled,
)
from .texts import BUTTON_EXPORT, BUTTON_KEEP, BUTTON_PLUS, BUTTON_SEEN, text

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .frigate import FrigateApiClient
    from .tracker import Decision

_LOGGER = logging.getLogger(__name__)

PREFIX = "CAMERA_AUTONOTIFY_"
SEPARATOR = "|"
EVENT_ACTION = "mobile_app_notification_action"
# seconds of recording either side of a review, as exported
EXPORT_PADDING = 10
# the title of each button, by action, from the translations
TITLES = {ACTION_KEEP: BUTTON_KEEP, ACTION_SEEN: BUTTON_SEEN, ACTION_PLUS: BUTTON_PLUS, ACTION_EXPORT: BUTTON_EXPORT}


@dataclass(frozen=True)
class Action:
    """An action on a notification: what it is, the entry of the camera or zone it was sent for, and the review, or
    for submitting to Frigate+ and keeping, the detection whose snapshot was shown"""

    kind: str
    entry_id: str
    target: str

    @property
    def name(self) -> str:
        return f"{PREFIX}{self.kind.upper()}{SEPARATOR}{self.entry_id}{SEPARATOR}{self.target}"

    @classmethod
    def parse(cls, name: object) -> Action | None:
        if not isinstance(name, str) or not name.startswith(PREFIX):
            return None
        parts = name.removeprefix(PREFIX).split(SEPARATOR)
        if len(parts) != 3 or not all(parts) or (kind := parts[0].lower()) not in ACTIONS:
            return None
        return cls(kind, parts[1], parts[2])


def offered(configs: list[dict[str, Any] | None], cameras: list[str] | None = None) -> list[str]:
    """The actions Frigate can do, for the cameras given, or any camera of the servers given, so none is offered that
    can't be: Frigate+ where it's set up and a camera saves snapshots, exporting where a camera records"""

    def each(config: dict[str, Any] | None) -> list[str]:
        return list((config or {}).get("cameras") or {}) if cameras is None else cameras

    plus = any(plus_enabled(config) and any(camera_snapshots(config, c) for c in each(config)) for config in configs)
    export = any(camera_records(config, c) for config in configs for c in each(config))
    can = {ACTION_KEEP: True, ACTION_SEEN: True, ACTION_PLUS: plus, ACTION_EXPORT: export}
    return [kind for kind in ACTIONS if can[kind]]


@callback
def chosen(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """The actions chosen for a camera or zone, as the global settings unless it chooses its own"""
    if entry.options.get(CONF_ACTIONS_GLOBAL, True):
        settings = global_settings(hass)
        actions = settings.options.get(CONF_ACTIONS, list(DEFAULT_ACTIONS)) if settings else list(DEFAULT_ACTIONS)
    else:
        actions = entry.options.get(CONF_ACTIONS) or []
    return [kind for kind in ACTIONS if kind in actions]


@callback
def available(hass: HomeAssistant, entry: ConfigEntry, decision: Decision) -> list[Action]:
    """The actions chosen that Frigate can do for a notification: Frigate+ only where it's set up and the camera saves
    snapshots, exporting only where the camera records, and seen and export only for a review, not an object
    described by itself"""
    config = frigate_config(hass, entry.data[CONF_SOURCE_ENTRY_ID])
    review = decision.review
    detection = decision.detection_id
    actions: list[Action] = []
    for kind in chosen(hass, entry):
        if kind == ACTION_KEEP and detection:
            actions.append(Action(kind, entry.entry_id, detection))
        elif kind == ACTION_SEEN and not review.standalone:
            actions.append(Action(kind, entry.entry_id, review.id))
        elif (
            kind == ACTION_PLUS
            and detection
            and plus_enabled(config)
            and camera_snapshots(config, review.camera)
            and _has_snapshot(hass, entry, detection) is not False
        ):
            actions.append(Action(kind, entry.entry_id, detection))
        elif kind == ACTION_EXPORT and not review.standalone and camera_records(config, review.camera):
            actions.append(Action(kind, entry.entry_id, review.id))
    return actions


@callback
def _has_snapshot(hass: HomeAssistant, entry: ConfigEntry, detection: str) -> bool | None:
    """Whether Frigate has a snapshot of a detection, as its tracked object last said, or nothing when not known"""
    store = fact_store(hass, entry.data[CONF_SOURCE_ENTRY_ID])
    found = store.object(detection) if store is not None else None
    return found.has_snapshot if found is not None else None


@callback
def buttons(hass: HomeAssistant, entry: ConfigEntry, decision: Decision) -> list[dict[str, Any]]:
    """The buttons of a notification, as Supernotify passes them on to a phone"""
    return [{"action": action.name, "title": text(hass, TITLES[action.kind])} for action in available(hass, entry, decision)]


async def _async_review(client: FrigateApiClient, review_id: str) -> dict[str, Any] | None:
    """A review by its id, which starts with the time it started, so only the reviews around then are asked for"""
    try:
        started = float(review_id.partition("-")[0])
    except ValueError:
        return None
    reviews = await client.async_get_reviews(after=started - 1, before=started + 1)
    return next((r for r in reviews or [] if isinstance(r, dict) and r.get("id") == review_id), None)


async def async_act(hass: HomeAssistant, action: Action) -> bool:
    """Do what a button was tapped for, returning whether Frigate did it"""
    entry = hass.config_entries.async_get_entry(action.entry_id)
    if entry is None or entry.domain != DOMAIN:
        _LOGGER.warning("CAMERA_AUTONOTIFY No camera or zone for action %s", action.name)
        return False
    source = entry.data[CONF_SOURCE_ENTRY_ID]
    client = frigate_client(hass, source)
    if client is None:
        _LOGGER.warning("CAMERA_AUTONOTIFY Frigate isn't set up for action %s", action.name)
        return False
    try:
        if action.kind == ACTION_KEEP:
            await client.async_retain(action.target, True)
        elif action.kind == ACTION_SEEN:
            await client.async_set_reviews_viewed([action.target], True)
        elif action.kind == ACTION_PLUS:
            if (url := frigate_url(hass, source)) is None:
                return False
            await client.api_wrapper("post", f"{url}/api/events/{action.target}/plus")
        elif action.kind == ACTION_EXPORT:
            if (review := await _async_review(client, action.target)) is None:
                _LOGGER.warning("CAMERA_AUTONOTIFY No review %s to export", action.target)
                return False
            end = review.get("end_time") or time.time()
            await client.async_export_recording(
                review["camera"],
                "realtime",
                float(review["start_time"]) - EXPORT_PADDING,
                float(end) + EXPORT_PADDING,
            )
    except Exception as error:
        _LOGGER.warning("CAMERA_AUTONOTIFY Frigate couldn't %s %s: %s", action.kind, action.target, error)
        return False
    _LOGGER.info("CAMERA_AUTONOTIFY Frigate did %s for %s", action.kind, action.target)
    return True


@callback
def async_listen(hass: HomeAssistant) -> CALLBACK_TYPE:
    """Act on the buttons of notifications, returning what stops it"""

    @callback
    def tapped(event: Event) -> None:
        if (action := Action.parse(event.data.get("action"))) is not None:
            hass.async_create_background_task(async_act(hass, action), f"{DOMAIN} action {action.kind}")

    return hass.bus.async_listen(EVENT_ACTION, tapped)
