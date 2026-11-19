"""The integration's own entries: the discovery entry, holding the global settings, beside an entry for each camera
and zone"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant, callback

from .const import CONF_ALPR_ENTITY, CONF_LAST_SNAPSHOT, DOMAIN, TYPE_DISCOVERY, TYPE_ZONE

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


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
