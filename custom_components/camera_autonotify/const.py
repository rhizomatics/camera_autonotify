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

# as the `target` and `custom_target` of supernotify.notify
CONF_TARGET: Final[str] = "target"
CONF_CUSTOM_TARGET: Final[str] = "custom_target"
CONF_DELIVERIES: Final[str] = "deliveries"
# notify entities, used only without Supernotify
CONF_TARGETS: Final[str] = "targets"

# English only for the MVP
DISCOVERY_TITLE: Final[str] = "Automatic discovery"
SUPERNOTIFY_PRESENT: Final[str] = (
    "Supernotify is installed, so notifications will have the snapshot, links to the clip, and every delivery it has."
)
SUPERNOTIFY_MISSING: Final[str] = (
    "**Supernotify is not installed.** Only a plain text notification can be sent, to every phone with the Home "
    "Assistant app, with no snapshot or links. Install Supernotify from HACS for the full experience."
)
# what a notification says, the title being the camera's or zone's name
MESSAGE_SEEN: Final[str] = "{label} detected"
MESSAGE_IN_ZONES: Final[str] = "{label} detected in {zones}"
MESSAGE_ON_CAMERA: Final[str] = "{label} detected on {camera}"
MESSAGE_ENDED: Final[str] = "{message}, now ended"
ACTION_VIEW_SNAPSHOT: Final[str] = "View snapshot"
