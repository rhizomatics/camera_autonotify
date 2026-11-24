from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, section

from custom_components.camera_autonotify.const import (
    CONF_ACTIONS,
    CONF_ACTIONS_GLOBAL,
    CONF_ALERT_ONCE,
    CONF_COOLDOWN,
    CONF_DELIVERIES,
    CONF_LABELS,
    CONF_SEVERITIES,
    CONF_TARGETS,
    CONF_TIMEOUT,
    CONF_ZONES,
    DOMAIN,
)
from custom_components.camera_autonotify.entries import entry_name
from custom_components.camera_autonotify.frigate import camera_choices, genai_features, zone_labels
from custom_components.camera_autonotify.tracker import Settings

from .conftest import add_frigate, mock_supernotify
from .test_discovery import set_up_discovery


def entry_titled(hass: HomeAssistant, title: str) -> ConfigEntry:
    return next(e for e in hass.config_entries.async_entries(DOMAIN) if entry_name(e) == title)


def fields_of(result: dict[str, Any]) -> dict[str, Any]:
    """Each field of a form by name, those of its sections as `section.field`"""
    shown: dict[str, Any] = {}
    for key, value in result["data_schema"].schema.items():
        if isinstance(value, section):
            shown.update({f"{key}.{inner}": selector for inner, selector in value.schema.schema.items()})
        else:
            shown[str(key)] = value
    return shown


async def open_settings(hass: HomeAssistant, title: str = "Courtyard") -> dict[str, Any]:
    result = await hass.config_entries.options.async_init(entry_titled(hass, title).entry_id)
    assert result["step_id"] == "settings"
    return dict(result)


async def test_camera_settings_offer_its_labels_and_zones(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    result = await open_settings(hass)
    shown = fields_of(result)
    assert shown["labels"].config["options"] == ["bark", "car", "cat", "person"]
    assert shown["zones"].config["options"] == ["Barn_Door", "Pend"]
    assert shown["severities"].config["translation_key"] == "severities"
    assert {"zone_multi", "zone_order", "timing.cooldown", "timing.alert_once", "notify.targets"} <= set(shown)


async def test_zone_settings_offer_labels_of_its_cameras(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass, discover_zones=True)
    shown = fields_of(await open_settings(hass, "Pend"))
    # pend is on both cameras, so the detections of each
    assert shown["labels"].config["options"] == ["bark", "car", "cat", "fox", "person"]
    assert "zones" not in shown
    # a zone has no video of its own to check
    assert "status_check" not in shown


async def test_camera_offline_check_on_to_begin_with(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    shown = fields_of(await open_settings(hass))
    status_check = next(key for key in shown if key == "status_check")
    assert status_check == "status_check"
    form = await open_settings(hass)
    marker = next(key for key in form["data_schema"].schema if str(key) == "status_check")
    assert marker.default() is True


async def test_settings_stored_flat_without_defaults(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    form = await open_settings(hass)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            CONF_SEVERITIES: ["alert"],
            CONF_LABELS: ["person"],
            CONF_ZONES: [],
            "zone_multi": False,
            "zone_order": False,
            "timing": {
                CONF_COOLDOWN: 0,
                "initial_delay": 0,
                "final_update": False,
                "final_delay": 0,
                CONF_TIMEOUT: 120,
                CONF_ALERT_ONCE: True,
                "update_sub_label": True,
            },
            "notify": {CONF_TARGETS: []},
            "advanced": {"notify_from": "events", "review_wait": 2},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert dict(entry.options) == {CONF_LABELS: ["person"], CONF_COOLDOWN: 0, CONF_TIMEOUT: 120}


async def test_settings_shown_as_saved(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    hass.config_entries.async_update_entry(entry, options={CONF_LABELS: ["car"], CONF_COOLDOWN: 10})
    await hass.async_block_till_done()
    result = await open_settings(hass)
    suggested: dict[str, Any] = {}
    for key, value in result["data_schema"].schema.items():
        keys = {f"{key}.{inner}": inner for inner in value.schema.schema} if isinstance(value, section) else {str(key): key}
        for name, marker in keys.items():
            if marker.description and "suggested_value" in marker.description:
                suggested[name] = marker.description["suggested_value"]
    # the Last notification snapshot camera shown as it is, off without an ANPR/ALPR entity
    assert suggested == {"labels": ["car"], "timing.cooldown": 10, "notify.last_snapshot": False}


async def test_supernotify_targets(hass: HomeAssistant):
    add_frigate(hass)
    mock_supernotify(hass)
    await set_up_discovery(hass)
    shown = fields_of(await open_settings(hass))
    assert {"notify.target", "notify.custom_target", "notify.deliveries"} <= set(shown)
    assert "notify.targets" not in shown
    assert shown["notify.deliveries"].config["options"] == ["email", "mobile_push", "phones"]


async def test_settings_without_frigate_config(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    hass.data["frigate"].clear()
    shown = fields_of(await open_settings(hass))
    assert shown["labels"].config["options"] == []
    assert shown["labels"].config["custom_value"] is True


def test_choices_without_config():
    assert camera_choices(None, "courtyard") == ([], [])
    assert zone_labels(None, "pend") == []


def test_settings_from_options():
    assert Settings.from_options({}) == Settings()
    settings = Settings.from_options({
        CONF_SEVERITIES: ["alert", "detection"],
        CONF_LABELS: ["car"],
        CONF_ZONES: ["Pend"],
        CONF_COOLDOWN: 0,
        CONF_DELIVERIES: ["mobile_push"],
    })
    assert settings.severities == frozenset({"alert", "detection"})
    assert settings.labels == frozenset({"car"})
    assert settings.zones == ("Pend",)
    assert settings.cooldown == 0


async def test_settings_warn_of_expiring_proxy(hass: HomeAssistant):
    add_frigate(hass, title="House", options={"notification_proxy_expire_after_seconds": 120})
    await set_up_discovery(hass)
    result = await open_settings(hass)
    assert "for House stop working 120 seconds" in result["description_placeholders"]["proxy"]


async def test_genai_settings_only_where_frigate_has_it(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    assert not any(name.startswith("genai.") for name in fields_of(await open_settings(hass)))


async def test_genai_settings(hass: HomeAssistant):
    add_frigate(hass, genai=True)
    await set_up_discovery(hass, discover_zones=True)
    shown = [name for name in fields_of(await open_settings(hass)) if name.startswith("genai.")]
    assert shown == [
        "genai.summaries",
        "genai.min_threat_level",
        "genai.priority_normal",
        "genai.priority_suspicious",
        "genai.priority_critical",
        "genai.descriptions",
        "genai.unreviewed_descriptions",
        "genai.genai_wait",
        "genai.genai_image",
    ]
    # a zone can't tell which descriptions are of it, without a review
    zone = [name for name in fields_of(await open_settings(hass, "Pend")) if name.startswith("genai.")]
    assert "genai.unreviewed_descriptions" not in zone
    assert "genai.summaries" in zone


async def test_genai_settings_stored(hass: HomeAssistant):
    add_frigate(hass, genai=True)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    form = await open_settings(hass)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            "timing": {},
            "notify": {},
            "advanced": {},
            "genai": {
                "summaries": True,
                "min_threat_level": 1.0,
                "priority_normal": "medium",
                "priority_suspicious": "critical",
                "priority_critical": "critical",
                "descriptions": True,
                "unreviewed_descriptions": True,
                "genai_wait": 120,
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert dict(entry.options) == {
        "min_threat_level": 1.0,
        "priority_suspicious": "critical",
        "unreviewed_descriptions": True,
    }
    settings = Settings.from_options(entry.options)
    assert settings.min_threat_level == 1
    assert settings.unreviewed_descriptions


def test_genai_features():
    config = {
        "cameras": {
            "a": {"review": {"genai": {"enabled": True}}, "zones": {"Pend": {}}},
            "b": {"objects": {"genai": {"enabled": True}}, "zones": {"Pend": {}, "Gate": {}}},
        }
    }
    assert genai_features(config, camera="a") == (True, False)
    assert genai_features(config, camera="b") == (False, True)
    assert genai_features(config, camera="c") == (False, False)
    assert genai_features(config, zone="pend") == (True, True)
    assert genai_features(config, zone="gate") == (False, True)
    assert genai_features(None, camera="a") == (False, False)


def suggested(result: dict[str, Any]) -> dict[str, Any]:
    """The value shown in each field of a form, by name, those of its sections as `section.field`"""
    shown: dict[str, Any] = {}
    for key, value in result["data_schema"].schema.items():
        inner = value.schema.schema.items() if isinstance(value, section) else [(key, value)]
        prefix = f"{key}." if isinstance(value, section) else ""
        for marker, _ in inner:
            if (wanted := (marker.description or {}).get("suggested_value")) is not None:
                shown[f"{prefix}{marker}"] = wanted
    return shown


async def test_actions_offered_for_the_camera(hass: HomeAssistant):
    """Only those Frigate can do for it, Frigate+ where it's set up and the camera saves snapshots"""
    mock_supernotify(hass)
    add_frigate(hass, plus=True, snapshots=True)
    await set_up_discovery(hass)
    shown = fields_of(await open_settings(hass))
    assert shown["notify.actions"].config["options"] == ["keep", "seen", "plus", "known_vehicle"]
    assert "notify.actions_global" in shown


async def test_actions_shown_only_where_still_offered(hass: HomeAssistant):
    mock_supernotify(hass)
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    hass.config_entries.async_update_entry(entry, options={CONF_ACTIONS_GLOBAL: False, CONF_ACTIONS: ["plus", "seen"]})
    assert suggested(await open_settings(hass))["notify.actions"] == ["seen"]


async def test_no_actions_without_supernotify(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    assert not {"notify.actions", "notify.actions_global"} & set(fields_of(await open_settings(hass)))


async def test_actions_switched_off_for_a_camera(hass: HomeAssistant):
    mock_supernotify(hass)
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    form = await open_settings(hass)
    await hass.config_entries.options.async_configure(
        form["flow_id"], {"severities": ["alert"], "timing": {}, "notify": {CONF_ACTIONS_GLOBAL: False}, "advanced": {}}
    )
    await hass.async_block_till_done()
    assert dict(entry.options) == {CONF_ACTIONS_GLOBAL: False}


@pytest.mark.parametrize(("title", "warned"), [("Driveway", True), ("Courtyard", False), ("Turning Circle", True)])
async def test_autotracking_warned(hass: HomeAssistant, title: str, warned: bool):
    """For a camera that follows what it sees, or a zone on one, since zones are drawn on its frame"""
    add_frigate(hass, autotracking=True)
    await set_up_discovery(hass, discover_zones=True)
    placeholders = (await open_settings(hass, title))["description_placeholders"]
    assert ("driveway follows what it sees" in placeholders["autotracking"]) is warned


async def test_global_actions(hass: HomeAssistant):
    """Offered where any server can do them, keep, seen and Frigate+ shown to begin with, of those"""
    mock_supernotify(hass)
    add_frigate(hass, plus=True, snapshots=True, record=True)
    await set_up_discovery(hass)
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get("type") == "discovery")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert fields_of(dict(result))["actions"].config["options"] == ["keep", "seen", "plus", "export", "known_vehicle"]
    assert suggested(dict(result))["actions"] == ["keep", "seen", "plus", "known_vehicle"]
