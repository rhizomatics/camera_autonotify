"""Constants for AutoNotify for Frigate"""

from typing import Final

DOMAIN: Final[str] = "frigate_autonotify"
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
# the Frigate server's entry, and the camera's or zone's name as Frigate gives it
CONF_FRIGATE_ENTRY_ID: Final[str] = "frigate_entry_id"
CONF_FRIGATE_NAME: Final[str] = "frigate_name"

# English only for the MVP
DISCOVERY_TITLE: Final[str] = "Automatic discovery"
SUPERNOTIFY_PRESENT: Final[str] = (
    "Supernotify is installed, so notifications will have the snapshot, links to the clip, and every delivery it has."
)
SUPERNOTIFY_MISSING: Final[str] = (
    "**Supernotify is not installed.** Only a plain text notification can be sent, to every phone with the Home "
    "Assistant app, with no snapshot or links. Install Supernotify from HACS for the full experience."
)
