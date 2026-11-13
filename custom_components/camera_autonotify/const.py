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
# the image of each notification, served by Frigate through the Frigate integration's notification proxy, the snapshot
# to begin with, which Frigate can draw the object's box on, or crop to the object, or else the smaller thumbnail
CONF_IMAGE: Final[str] = "image"
IMAGE_SNAPSHOT: Final[str] = "snapshot"
IMAGE_SNAPSHOT_BOX: Final[str] = "snapshot_box"
IMAGE_SNAPSHOT_CROP: Final[str] = "snapshot_crop"
IMAGE_THUMBNAIL: Final[str] = "thumbnail"
IMAGES: Final[tuple[str, ...]] = (IMAGE_SNAPSHOT, IMAGE_SNAPSHOT_BOX, IMAGE_SNAPSHOT_CROP, IMAGE_THUMBNAIL)
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
# what each of Frigate's objects is called in a notification, a setting of the discovery entry, for every camera and
# zone, as a list of the object as Frigate names it and what to call it instead, such as `car` as `Vehicle`
CONF_OBJECT_NAMES: Final[str] = "object_names"
CONF_OBJECT: Final[str] = "object"
# a camera's own setting, to notify when Frigate has no video from it, timed as the health check of its server
CONF_STATUS_CHECK: Final[str] = "status_check"
# what powers a camera, such as its PoE port or smart plug, or a schedule of when it's meant to be on, so it's only
# checked while that's on, and not until the grace has passed since it came on, for the camera to start up
CONF_POWER_ENTITY: Final[str] = "power_entity"
CONF_POWER_GRACE: Final[str] = "power_grace"
POWER_DOMAINS: Final[tuple[str, ...]] = ("switch", "binary_sensor", "input_boolean", "schedule")
DEFAULT_POWER_GRACE: Final[int] = 180

# a summary of the hours before, made by Frigate's GenAI from their reviews, a setting of the discovery entry: sent
# automatically when Frigate makes review summaries, or always, or never, every so many hours from a time of day, to
# the deliveries chosen, and if chosen, only when a review in those hours raised a concern
CONF_SUMMARY_MODE: Final[str] = "summary_mode"
CONF_SUMMARY_TIME: Final[str] = "summary_time"
CONF_SUMMARY_INTERVAL: Final[str] = "summary_interval"
CONF_SUMMARY_CONCERNS: Final[str] = "summary_concerns_only"
CONF_SUMMARY_DELIVERIES: Final[str] = "summary_deliveries"
SUMMARY_AUTO: Final[str] = "auto"
SUMMARY_ON: Final[str] = "on"
SUMMARY_OFF: Final[str] = "off"
SUMMARY_MODES: Final[tuple[str, ...]] = (SUMMARY_AUTO, SUMMARY_ON, SUMMARY_OFF)
DEFAULT_SUMMARY_TIME: Final[str] = "00:05:00"
# hours between summaries, each dividing a day, so they fall at the same times every day
SUMMARY_INTERVALS: Final[tuple[int, ...]] = (1, 2, 3, 4, 6, 8, 12, 24)
DEFAULT_SUMMARY_INTERVAL: Final[int] = 24

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

# the global settings entry's title, which the user can change, entry titles not being translated
DISCOVERY_TITLE: Final[str] = "Global Settings"
# its title before 0.5.0, taken as not chosen by the user, so renamed
DISCOVERY_TITLE_BEFORE: Final[str] = "Automatic discovery"
