from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.frigate_autonotify.const import (
    CONF_AUTO_DISCOVER,
    CONF_DISCOVER_ZONES,
    DOMAIN,
    SUPERNOTIFY_MISSING,
    SUPERNOTIFY_PRESENT,
    TYPE_DISCOVERY,
)
from custom_components.frigate_autonotify.supernotify_api import deliveries_by_transport

from .conftest import add_frigate, mock_supernotify


async def test_discovery_entry_created(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {
        "supernotify": SUPERNOTIFY_MISSING,
        "found": "No Frigate cameras found yet.",
    }

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_TYPE: TYPE_DISCOVERY}
    # cameras found by default, and not zones
    assert result["options"] == {CONF_AUTO_DISCOVER: True, CONF_DISCOVER_ZONES: False}


async def test_supernotify_present(hass: HomeAssistant):
    mock_supernotify(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert (result.get("description_placeholders") or {}).get("supernotify") == SUPERNOTIFY_PRESENT


async def test_cameras_found_listed(hass: HomeAssistant):
    add_frigate(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert (result.get("description_placeholders") or {}).get("found") == "Cameras found:\n\n- Driveway\n- Courtyard"


async def test_only_one_discovery_entry(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_AUTO_DISCOVER: True})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_deliveries_by_transport(hass: HomeAssistant):
    mock_supernotify(hass)
    hass.states.async_set("switch.supernotify_delivery_chimes", "on", {"name": "chimes", "transport": "chime"})
    assert await deliveries_by_transport(hass) == {
        "chime": ["chimes"],
        "mobile_push": ["mobile_push", "phones"],
        "email": ["email"],
    }
