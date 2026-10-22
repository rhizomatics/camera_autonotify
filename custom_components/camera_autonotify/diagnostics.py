"""Diagnostics, with the settings of an entry and the reviews it's following"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_CUSTOM_TARGET, CONF_TARGET, CONF_TARGETS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

# who is told is nobody else's business
REDACT = {CONF_TARGET, CONF_CUSTOM_TARGET, CONF_TARGETS}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    watcher = getattr(entry, "runtime_data", None)
    return {
        "data": dict(entry.data),
        "options": async_redact_data(dict(entry.options), REDACT),
        "reviews": watcher.reviews if watcher is not None else [],
    }
