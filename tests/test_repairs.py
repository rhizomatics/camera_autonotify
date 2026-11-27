"""What can't be put right by itself is a repair, or an action's error, rather than retried or silently ignored"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir

from custom_components.camera_autonotify.const import DOMAIN

from .conftest import add_frigate
from .test_discovery import set_up_discovery
from .test_settings import entry_titled


async def test_frigate_removed(hass: HomeAssistant):
    """Its Frigate entry deleted, so a camera's entry can never be set up again, and says so, until it's removed"""
    frigate = add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    assert entry.state is ConfigEntryState.LOADED
    issue = f"source_gone_{entry.entry_id}"
    await hass.config_entries.async_remove(frigate.entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    found = ir.async_get(hass).async_get_issue(DOMAIN, issue)
    assert found is not None
    assert found.translation_placeholders == {"name": "Courtyard"}
    await hass.config_entries.async_remove(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue) is None


async def test_repair_gone_once_set_up(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"source_gone_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="source_gone",
    )
    await hass.config_entries.async_reload(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"source_gone_{entry.entry_id}") is None


@pytest.mark.parametrize(
    ("action", "data"), [("add_plate", {"category": "Family", "plate": "AB12CDE"}), ("remove_plate", {"plate": "AB12CDE"})]
)
async def test_plates_need_global_settings(hass: HomeAssistant, action: str, data: dict[str, str]):
    add_frigate(hass)
    await set_up_discovery(hass)
    settings = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get("type") == "discovery")
    await hass.config_entries.async_remove(settings.entry_id)
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(DOMAIN, action, data, blocking=True, return_response=True)
    assert raised.value.translation_key == "global_settings_missing"
