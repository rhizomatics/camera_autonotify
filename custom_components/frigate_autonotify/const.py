"""Constants for Frigate Auto Notify"""

from typing import Final

DOMAIN: Final[str] = "frigate_autonotify"
SUPERNOTIFY_DOMAIN: Final[str] = "supernotify"
FRIGATE_DOMAIN: Final[str] = "frigate"

# the one entry that isn't a camera, holding whether cameras found are set up without asking
TYPE_DISCOVERY: Final[str] = "discovery"
CONF_AUTO_DISCOVER: Final[str] = "auto_discover"

# English only for the MVP
DISCOVERY_TITLE: Final[str] = "Automatic discovery"
SUPERNOTIFY_PRESENT: Final[str] = (
    "Supernotify is installed, so notifications will have the snapshot, links to the clip, and every delivery it has."
)
SUPERNOTIFY_MISSING: Final[str] = (
    "**Supernotify is not installed.** Only a plain text notification can be sent, to every phone with the Home "
    "Assistant app, with no snapshot or links. Install Supernotify from HACS for the full experience."
)
