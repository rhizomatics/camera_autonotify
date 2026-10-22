"""Config flow for AutoNotify for Frigate, one config entry per camera, or zone"""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME, CONF_TYPE, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    Selector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TargetSelector,
    TextSelector,
    TextSelectorConfig,
)

from .compat import vol
from .const import (
    CONF_ALERT_ONCE,
    CONF_AUTO_DISCOVER,
    CONF_COOLDOWN,
    CONF_CUSTOM_TARGET,
    CONF_DELIVERIES,
    CONF_DISCOVER_ZONES,
    CONF_FINAL_DELAY,
    CONF_FINAL_UPDATE,
    CONF_FRIGATE_ENTRY_ID,
    CONF_FRIGATE_NAME,
    CONF_INITIAL_DELAY,
    CONF_LABELS,
    CONF_SEVERITIES,
    CONF_TARGET,
    CONF_TARGETS,
    CONF_TIMEOUT,
    CONF_UPDATE_SUB_LABEL,
    CONF_ZONE_MULTI,
    CONF_ZONE_ORDER,
    CONF_ZONES,
    DISCOVERY_TITLE,
    DOMAIN,
    SEVERITIES,
    SUPERNOTIFY_MISSING,
    SUPERNOTIFY_PRESENT,
    TYPE_DISCOVERY,
    TYPE_ZONE,
)
from .discovery import find_cameras
from .frigate import camera_choices, frigate_config, zone_labels
from .supernotify_api import deliveries_by_transport, supernotify_available
from .tracker import Settings

STEP_DISCOVERY = "discovery"
STEP_SETTINGS = "settings"
SECTION_TIMING = "timing"
SECTION_NOTIFY = "notify"
# a setting left as it comes isn't stored, so it follows any better default of a later version
DEFAULTS: dict[str, Any] = {
    f.name: sorted(value) if isinstance(value := getattr(Settings(), f.name), frozenset) else value for f in fields(Settings)
}
# what a camera or zone's entry holds, as it's found
ENTRY_DATA = (CONF_DEVICE_ID, CONF_TYPE, CONF_FRIGATE_ENTRY_ID, CONF_FRIGATE_NAME)


def supernotify_status(hass: HomeAssistant) -> str:
    return SUPERNOTIFY_PRESENT if supernotify_available(hass) else SUPERNOTIFY_MISSING


def discovery_schema(auto_discover: bool = True, discover_zones: bool = False) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_AUTO_DISCOVER, default=auto_discover): BooleanSelector(),
        vol.Required(CONF_DISCOVER_ZONES, default=discover_zones): BooleanSelector(),
    })


# as the base class, since type checkers can't all take one registered by a decorator as a type
def _seconds(maximum: int) -> Selector:
    return NumberSelector(
        NumberSelectorConfig(min=0, max=maximum, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement=UnitOfTime.SECONDS)
    )


def _choose(options: list[str], translation_key: str | None = None) -> Selector:
    config = SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.DROPDOWN)
    if translation_key:
        config["translation_key"] = translation_key
    else:
        # what's typed is kept too, for a label or zone Frigate's config doesn't list, such as one added since
        config["custom_value"] = True
    return SelectSelector(config)


async def settings_schema(hass: HomeAssistant, labels: list[str], zones: list[str] | None) -> vol.Schema:
    """The blueprint's filters, then its timing and who is told, out of the way until wanted. Zones only for a
    camera, since a zone's entry is the zone"""
    fields_: dict[vol.Marker, Any] = {
        vol.Required(CONF_SEVERITIES, default=DEFAULTS[CONF_SEVERITIES]): _choose(list(SEVERITIES), CONF_SEVERITIES),
        vol.Optional(CONF_LABELS): _choose(labels),
    }
    if zones is not None:
        fields_[vol.Optional(CONF_ZONES)] = _choose(zones)
        fields_[vol.Required(CONF_ZONE_MULTI, default=False)] = BooleanSelector()
        fields_[vol.Required(CONF_ZONE_ORDER, default=False)] = BooleanSelector()
    timing: dict[vol.Marker, Any] = {
        vol.Required(CONF_COOLDOWN, default=DEFAULTS[CONF_COOLDOWN]): _seconds(3600),
        vol.Required(CONF_INITIAL_DELAY, default=DEFAULTS[CONF_INITIAL_DELAY]): _seconds(60),
        vol.Required(CONF_FINAL_UPDATE, default=DEFAULTS[CONF_FINAL_UPDATE]): BooleanSelector(),
        vol.Required(CONF_FINAL_DELAY, default=DEFAULTS[CONF_FINAL_DELAY]): _seconds(300),
        vol.Required(CONF_TIMEOUT, default=DEFAULTS[CONF_TIMEOUT]): _seconds(3600),
        vol.Required(CONF_ALERT_ONCE, default=DEFAULTS[CONF_ALERT_ONCE]): BooleanSelector(),
        vol.Required(CONF_UPDATE_SUB_LABEL, default=DEFAULTS[CONF_UPDATE_SUB_LABEL]): BooleanSelector(),
    }
    notify: dict[vol.Marker, Any] = {}
    if supernotify_available(hass):
        # the same pair of target fields as supernotify.notify itself
        notify[vol.Optional(CONF_TARGET)] = TargetSelector()
        notify[vol.Optional(CONF_CUSTOM_TARGET)] = TextSelector(TextSelectorConfig(multiple=True))
        deliveries = sorted({name for names in (await deliveries_by_transport(hass)).values() for name in names})
        notify[vol.Optional(CONF_DELIVERIES)] = SelectSelector(SelectSelectorConfig(options=deliveries, multiple=True))
    else:
        notify[vol.Optional(CONF_TARGETS)] = EntitySelector(EntitySelectorConfig(domain="notify", multiple=True))
    fields_[vol.Required(SECTION_TIMING)] = section(vol.Schema(timing), {"collapsed": True})
    fields_[vol.Required(SECTION_NOTIFY)] = section(vol.Schema(notify), {"collapsed": True})
    return vol.Schema(fields_)


def sectioned(schema: vol.Schema, values: dict[str, Any]) -> dict[str, Any]:
    """Settings are stored flat, the sections are only for display"""
    shown: dict[str, Any] = {}
    for name, field in schema.schema.items():
        if isinstance(field, section):
            shown[str(name)] = {str(key): values[key] for key in field.schema.schema if key in values}
        elif name in values:
            shown[str(name)] = values[name]
    return shown


def flattened(user_input: dict[str, Any]) -> dict[str, Any]:
    """The settings of a form, with those in sections alongside the rest"""
    settings: dict[str, Any] = {}
    for name, value in user_input.items():
        settings.update(value if isinstance(value, dict) and name in (SECTION_TIMING, SECTION_NOTIFY) else {name: value})
    return settings


class FrigateAutoNotifyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._found: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FrigateAutoNotifyOptionsFlow:
        return FrigateAutoNotifyOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Automatic discovery, the cameras themselves set up as they're found"""
        await self.async_set_unique_id(TYPE_DISCOVERY)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            # the cameras are set up as this entry is, each as its own entry to change or delete
            return self.async_create_entry(title=DISCOVERY_TITLE, data={CONF_TYPE: TYPE_DISCOVERY}, options=user_input)
        found = [camera.name for camera in find_cameras(self.hass)]
        if found:
            found_text = "Cameras found:\n\n" + "\n".join(f"- {name}" for name in found)
        else:
            found_text = "No Frigate cameras found yet."
        return self.async_show_form(
            step_id="user",
            data_schema=discovery_schema(),
            description_placeholders={"found": found_text, "supernotify": supernotify_status(self.hass)},
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """A camera found with automatic discovery on, so set up without asking"""
        # a discovery of the same camera may be waiting, and goes once this entry exists
        await self.async_set_unique_id(import_data[CONF_DEVICE_ID], raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=import_data[CONF_NAME], data={k: v for k, v in import_data.items() if k in ENTRY_DATA}
        )

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        """A camera found with automatic discovery off, or a zone, so offered to be added"""
        self._found = dict(discovery_info)
        await self.async_set_unique_id(discovery_info[CONF_DEVICE_ID])
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": discovery_info[CONF_NAME]}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._found[CONF_NAME], data={k: v for k, v in self._found.items() if k in ENTRY_DATA}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._found[CONF_NAME], "supernotify": supernotify_status(self.hass)},
        )


class FrigateAutoNotifyOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            return await self.async_step_discovery()
        return await self.async_step_settings()

    async def async_step_discovery(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id=STEP_DISCOVERY,
            data_schema=discovery_schema(options.get(CONF_AUTO_DISCOVER, True), options.get(CONF_DISCOVER_ZONES, False)),
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            settings = {
                key: value
                for key, value in flattened(user_input).items()
                if (value or value is False or value == 0) and value != DEFAULTS.get(key)
            }
            return self.async_create_entry(data=settings)
        data = self.config_entry.data
        config = frigate_config(self.hass, data[CONF_FRIGATE_ENTRY_ID])
        if data.get(CONF_TYPE) == TYPE_ZONE:
            labels, zones = zone_labels(config, data[CONF_FRIGATE_NAME]), None
        else:
            labels, zones = camera_choices(config, data[CONF_FRIGATE_NAME])
        schema = await settings_schema(self.hass, labels, zones)
        return self.async_show_form(
            step_id=STEP_SETTINGS,
            data_schema=self.add_suggested_values_to_schema(schema, sectioned(schema, dict(self.config_entry.options))),
            description_placeholders={"name": self.config_entry.title, "supernotify": supernotify_status(self.hass)},
        )
