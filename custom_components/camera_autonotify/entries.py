"""The integration's own entries: the discovery entry, holding the global settings, beside an entry for each camera
and zone"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant, callback

from .const import CONF_ALPR_ENTITY, CONF_LAST_SNAPSHOT, DOMAIN, TYPE_ANPR, TYPE_DISCOVERY, TYPE_ZONE

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


# what a Frigate camera or zone's entry title says after its name, so the entries list shows where each is from, as an
# anpr2mqtt source's name already says
FRIGATE_SUFFIX = " (Frigate)"


def entry_title(name: str, entry_type: str | None) -> str:
    """A new entry's title: its name, and for Frigate's cameras and zones, that they're Frigate's"""
    return name if entry_type == TYPE_ANPR else f"{name}{FRIGATE_SUFFIX}"


def entry_name(entry: ConfigEntry) -> str:
    """What an entry's camera or zone is called, as notifications say it: its title, renamed or not, without where
    it's from"""
    return entry.title.removesuffix(FRIGATE_SUFFIX)


@callback
def global_settings(hass: HomeAssistant) -> ConfigEntry | None:
    """The discovery entry, holding what applies to every camera and zone, unless deleted or disabled"""
    for entry in hass.config_entries.async_entries(DOMAIN, include_disabled=False):
        if entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            return entry
    return None


def wants_last_snapshot(entry: ConfigEntry) -> bool:
    """Whether a camera's entry has its Last notification snapshot camera, never a zone's, whose reviews are of several
    cameras: where chosen, and otherwise where an ANPR/ALPR entity is, for it to read the snapshot notified"""
    if entry.data.get(CONF_TYPE) == TYPE_ZONE:
        return False
    return bool(entry.options.get(CONF_LAST_SNAPSHOT, bool(entry.options.get(CONF_ALPR_ENTITY))))
