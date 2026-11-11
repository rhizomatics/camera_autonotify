"""Diagnostics, with the settings of an entry and the reviews it's following, or for the discovery entry, the health of
each Frigate server"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_CUSTOM_TARGET, CONF_TARGET, CONF_TARGETS
from .health import HealthMonitor
from .hub import ReviewWatcher

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

# who is told is nobody else's business
REDACT = {CONF_TARGET, CONF_CUSTOM_TARGET, CONF_TARGETS}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    runtime = getattr(entry, "runtime_data", None)
    diagnostics: dict[str, Any] = {
        "data": dict(entry.data),
        "options": async_redact_data(dict(entry.options), REDACT),
    }
    if isinstance(runtime, HealthMonitor):
        diagnostics["health"] = runtime.diagnostics()
    else:
        diagnostics["reviews"] = runtime.reviews if isinstance(runtime, ReviewWatcher) else []
    return diagnostics
