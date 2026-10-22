from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, section

from custom_components.frigate_autonotify.const import (
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
from custom_components.frigate_autonotify.frigate import camera_choices, zone_labels
from custom_components.frigate_autonotify.tracker import Settings

from .conftest import add_frigate, mock_supernotify
from .test_discovery import set_up_discovery


def entry_titled(hass: HomeAssistant, title: str) -> ConfigEntry:
    return next(e for e in hass.config_entries.async_entries(DOMAIN) if e.title == title)


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


async def test_settings_stored_flat_without_defaults(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    result = await open_settings(hass)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
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
    assert suggested == {"labels": ["car"], "timing.cooldown": 10}


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
