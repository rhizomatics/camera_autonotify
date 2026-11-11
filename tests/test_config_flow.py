from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.camera_autonotify.config_flow import CameraAutoNotifyConfigFlow, RuleSubentryFlow
from custom_components.camera_autonotify.const import (
    CONF_AUTO_DISCOVER,
    CONF_DISCOVER_ZONES,
    DOMAIN,
    PROXY_EXPIRES,
    PROXY_OFF,
    SUBENTRY_RULE,
    SUPERNOTIFY_MISSING,
    SUPERNOTIFY_PRESENT,
    TYPE_DISCOVERY,
)
from custom_components.camera_autonotify.notifier import notification_rules
from custom_components.camera_autonotify.supernotify_api import deliveries_by_transport
from tests.ha_testing import MockConfigEntry

from .conftest import add_frigate, mock_supernotify


async def test_discovery_entry_created(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {
        "supernotify": SUPERNOTIFY_MISSING,
        "found": "No Frigate cameras found yet.",
        "proxy": "",
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


async def test_proxy_warnings(hass: HomeAssistant):
    add_frigate(hass, title="House", options={"notification_proxy_enable": False})
    add_frigate(hass, cameras={}, entry_id="02FRIGATE", title="Barn", options={"notification_proxy_expire_after_seconds": 60})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert (result.get("description_placeholders") or {}).get("proxy") == (
        f"\n\n{PROXY_OFF.format(server='House')}\n\n{PROXY_EXPIRES.format(server='Barn', seconds=60)}"
    )


async def discovery_entry(hass: HomeAssistant) -> config_entries.ConfigEntry:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    return result["result"]


async def test_rule_added(hass: HomeAssistant):
    mock_supernotify(hass)
    entry = await discovery_entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_RULE), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"] is not None
    scenarios = next(value for key, value in result["data_schema"].schema.items() if str(key) == "scenarios")
    assert [option["value"] for option in scenarios.config["options"]] == ["high_alert", "noisy"]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "High risk",
            "match": "regex",
            "pattern": r"^high risk\W*",
            "priority": "high",
            "silence": False,
            "remove": True,
            "scenarios": ["high_alert"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.title == "High risk"
    assert dict(subentry.data) == {
        "match": "regex",
        "pattern": r"^high risk\W*",
        "priority": "high",
        "silence": False,
        "remove": True,
        "scenarios": ["high_alert"],
    }
    assert [rule.name for rule in notification_rules(hass)] == ["High risk"]


async def test_rule_pattern_checked(hass: HomeAssistant):
    entry = await discovery_entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_RULE), context={"source": config_entries.SOURCE_USER}
    )
    # no scenarios to choose from without Supernotify
    assert result["data_schema"] is not None
    assert not any(str(key) == "scenarios" for key in result["data_schema"].schema)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Bad", "match": "regex", "pattern": "(risk", "silence": True, "remove": False}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"pattern": "invalid_pattern"}
    # the same text is fine to look for as it is
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": " ", "match": "contains", "pattern": "(risk", "silence": True, "remove": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.title == "(risk"


async def test_rule_changed(hass: HomeAssistant):
    entry = await discovery_entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_RULE), context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Birds", "match": "starts_with", "pattern": "bird", "silence": True, "remove": False}
    )
    (subentry,) = entry.subentries.values()
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_RULE),
        context={"source": config_entries.SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Birds",
            "match": "starts_with",
            "pattern": "bird identified",
            "priority": "minimum",
            "silence": False,
            "remove": True,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    (subentry,) = entry.subentries.values()
    assert dict(subentry.data) == {
        "match": "starts_with",
        "pattern": "bird identified",
        "priority": "minimum",
        "silence": False,
        "remove": True,
    }


async def test_rules_only_on_discovery_entry(hass: HomeAssistant):
    entry = await discovery_entry(hass)
    assert CameraAutoNotifyConfigFlow.async_get_supported_subentry_types(entry) == {SUBENTRY_RULE: RuleSubentryFlow}
    camera = MockConfigEntry(domain=DOMAIN, data={CONF_TYPE: "camera"})
    assert CameraAutoNotifyConfigFlow.async_get_supported_subentry_types(camera) == {}
