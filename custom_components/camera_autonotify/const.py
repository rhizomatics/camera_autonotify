"""Constants for Camera AutoNotify"""

from typing import Final

DOMAIN: Final[str] = "camera_autonotify"
SUPERNOTIFY_DOMAIN: Final[str] = "supernotify"
FRIGATE_DOMAIN: Final[str] = "frigate"

# the one entry that isn't a camera, holding whether cameras found are set up without asking
TYPE_DISCOVERY: Final[str] = "discovery"
CONF_AUTO_DISCOVER: Final[str] = "auto_discover"
# whether Frigate zones are offered too, each with a device of its own like a camera's, but off to begin with, since
# a zone is part of a camera's view and so mostly covered by the camera's own notifications
CONF_DISCOVER_ZONES: Final[str] = "discover_zones"

# what each entry notifies for, a camera, or a zone, which may be in the view of more than one camera
TYPE_CAMERA: Final[str] = "camera"
TYPE_ZONE: Final[str] = "zone"
# the integration a camera comes from, its own entry for the server or system, and the camera's or zone's name
# as that integration gives it
CONF_SOURCE: Final[str] = "source"
SOURCE_FRIGATE: Final[str] = "frigate"
CONF_SOURCE_ENTRY_ID: Final[str] = "source_entry_id"
CONF_SOURCE_NAME: Final[str] = "source_name"

# the filters and timing of a camera or zone, named as the tracker's settings
CONF_SEVERITIES: Final[str] = "severities"
CONF_LABELS: Final[str] = "labels"
CONF_ZONES: Final[str] = "zones"
CONF_ZONE_MULTI: Final[str] = "zone_multi"
CONF_ZONE_ORDER: Final[str] = "zone_order"
CONF_COOLDOWN: Final[str] = "cooldown"
CONF_INITIAL_DELAY: Final[str] = "initial_delay"
CONF_FINAL_UPDATE: Final[str] = "final_update"
CONF_FINAL_DELAY: Final[str] = "final_delay"
CONF_TIMEOUT: Final[str] = "timeout"
CONF_ALERT_ONCE: Final[str] = "alert_once"
CONF_UPDATE_SUB_LABEL: Final[str] = "update_sub_label"
SEVERITIES: Final[tuple[str, ...]] = ("alert", "detection")
# what Frigate's generative AI adds, the review summaries and object descriptions, named as the tracker's settings
CONF_SUMMARIES: Final[str] = "summaries"
CONF_MIN_THREAT_LEVEL: Final[str] = "min_threat_level"
CONF_DESCRIPTIONS: Final[str] = "descriptions"
CONF_UNREVIEWED_DESCRIPTIONS: Final[str] = "unreviewed_descriptions"
CONF_GENAI_WAIT: Final[str] = "genai_wait"
# Supernotify's priorities, most urgent first
PRIORITIES: Final[tuple[str, ...]] = ("critical", "high", "medium", "low", "minimum")
# the priority of each of Frigate's threat levels, normal, suspicious and critical, by their setting
CONF_THREAT_PRIORITIES: Final[tuple[str, ...]] = ("priority_normal", "priority_suspicious", "priority_critical")
THREAT_PRIORITY_DEFAULTS: Final[tuple[str, ...]] = ("medium", "high", "critical")

# the health check of each Frigate server, a setting of the discovery entry: how often it's checked, and after a
# failed check, how many more tries, the first after the backoff and each after twice the one before, before its
# failure is notified
CONF_HEALTH_CHECK: Final[str] = "health_check"
CONF_HEALTH_INTERVAL: Final[str] = "health_interval"
CONF_HEALTH_RETRIES: Final[str] = "health_retries"
CONF_HEALTH_BACKOFF: Final[str] = "health_backoff"
# a camera's own setting, to notify when Frigate has no video from it, timed as the health check of its server
CONF_STATUS_CHECK: Final[str] = "status_check"

# a rule, a subentry of the discovery entry, that changes how any notification whose message it matches is sent
SUBENTRY_RULE: Final[str] = "rule"
CONF_MATCH: Final[str] = "match"
CONF_PATTERN: Final[str] = "pattern"
CONF_PRIORITY: Final[str] = "priority"
CONF_SILENCE: Final[str] = "silence"
CONF_SCENARIOS: Final[str] = "scenarios"
CONF_REMOVE: Final[str] = "remove"
MATCH_STARTS_WITH: Final[str] = "starts_with"
MATCH_CONTAINS: Final[str] = "contains"
MATCH_REGEX: Final[str] = "regex"
MATCHES: Final[tuple[str, ...]] = (MATCH_STARTS_WITH, MATCH_CONTAINS, MATCH_REGEX)

# as the `target` and `custom_target` of supernotify.notify
CONF_TARGET: Final[str] = "target"
CONF_CUSTOM_TARGET: Final[str] = "custom_target"
CONF_DELIVERIES: Final[str] = "deliveries"
# notify entities, used only without Supernotify
CONF_TARGETS: Final[str] = "targets"

# English only for the MVP
DISCOVERY_TITLE: Final[str] = "Global Settings"
# its title before 0.5.0, taken as not chosen by the user, so renamed
DISCOVERY_TITLE_BEFORE: Final[str] = "Automatic discovery"
SUPERNOTIFY_PRESENT: Final[str] = (
    "Supernotify is installed, so notifications will have the snapshot, links to the clip, and every delivery it has."
)
SUPERNOTIFY_MISSING: Final[str] = (
    "**Supernotify is not installed.** Only a plain text notification can be sent, to every phone with the Home "
    "Assistant app, with no snapshot or links. Install Supernotify from HACS for the full experience."
)
# a Frigate server whose notification proxy can't serve the snapshot and clip of every notification, named by its title
PROXY_OFF: Final[str] = (
    "**Frigate's notification proxy is switched off for {server}.** Notifications will have no snapshot, and tapping "
    "one won't play the clip. Switch the notification proxy back on in the Frigate integration's options."
)
PROXY_EXPIRES: Final[str] = (
    "Frigate's notification links for {server} stop working {seconds} seconds after each detection, so older "
    "notifications lose their snapshot and clip. Set the notification proxy's expiry to 0 in the Frigate "
    "integration's options to keep them."
)
# what a notification says, the title being the camera's or zone's name
HEADLINE: Final[str] = "{label} detected at {where}"
HEADLINE_ENDED: Final[str] = "{headline}, now ended"
ACTION_VIEW_SNAPSHOT: Final[str] = "View snapshot"
# a Frigate server failing its health check, and answering again, named by its title
HEALTH_DOWN_TITLE: Final[str] = "Frigate is not responding"
HEALTH_DOWN: Final[str] = "{server} has failed its health check since {since}, so camera notifications may have stopped."
HEALTH_UP_TITLE: Final[str] = "Frigate is back"
HEALTH_UP: Final[str] = "{server} is responding again, after {duration}."
# a camera Frigate has no video from, while not disabled in Frigate, and its video back, named as its entry
CAMERA_DOWN_TITLE: Final[str] = "{camera} camera is offline"
CAMERA_DOWN: Final[str] = "Frigate has had no video from {camera} since {since}."
CAMERA_UP_TITLE: Final[str] = "{camera} camera is back"
CAMERA_UP: Final[str] = "Frigate has video from {camera} again, after {duration}."
