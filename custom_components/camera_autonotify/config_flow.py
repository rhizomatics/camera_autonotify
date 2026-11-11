"""Config flow for Camera AutoNotify, one config entry per camera, or zone"""

from __future__ import annotations

import re
from dataclasses import fields
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlowWithReload,
    SubentryFlowResult,
)
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
    SelectOptionDict,
    Selector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TargetSelector,
    TextSelector,
    TextSelectorConfig,
    TimeSelector,
)

from .compat import vol
from .const import (
    CONF_ALERT_ONCE,
    CONF_AUTO_DISCOVER,
    CONF_COOLDOWN,
    CONF_CUSTOM_TARGET,
    CONF_DELIVERIES,
    CONF_DESCRIPTIONS,
    CONF_DISCOVER_ZONES,
    CONF_FINAL_DELAY,
    CONF_FINAL_UPDATE,
    CONF_GENAI_WAIT,
    CONF_HEALTH_BACKOFF,
    CONF_HEALTH_CHECK,
    CONF_HEALTH_INTERVAL,
    CONF_HEALTH_RETRIES,
    CONF_INITIAL_DELAY,
    CONF_LABELS,
    CONF_MATCH,
    CONF_MIN_THREAT_LEVEL,
    CONF_PATTERN,
    CONF_POWER_ENTITY,
    CONF_POWER_GRACE,
    CONF_PRIORITY,
    CONF_REMOVE,
    CONF_SCENARIOS,
    CONF_SEVERITIES,
    CONF_SILENCE,
    CONF_SOURCE,
    CONF_SOURCE_ENTRY_ID,
    CONF_SOURCE_NAME,
    CONF_STATUS_CHECK,
    CONF_SUMMARIES,
    CONF_SUMMARY_CONCERNS,
    CONF_SUMMARY_DELIVERIES,
    CONF_SUMMARY_INTERVAL,
    CONF_SUMMARY_MODE,
    CONF_SUMMARY_TIME,
    CONF_TARGET,
    CONF_TARGETS,
    CONF_THREAT_PRIORITIES,
    CONF_TIMEOUT,
    CONF_UNREVIEWED_DESCRIPTIONS,
    CONF_UPDATE_SUB_LABEL,
    CONF_ZONE_MULTI,
    CONF_ZONE_ORDER,
    CONF_ZONES,
    DEFAULT_POWER_GRACE,
    DEFAULT_SUMMARY_INTERVAL,
    DEFAULT_SUMMARY_TIME,
    DISCOVERY_TITLE,
    DOMAIN,
    MATCH_CONTAINS,
    MATCHES,
    POWER_DOMAINS,
    PRIORITIES,
    PROXY_EXPIRES,
    PROXY_OFF,
    SEVERITIES,
    SUBENTRY_RULE,
    SUMMARY_AUTO,
    SUMMARY_INTERVALS,
    SUMMARY_MODES,
    SUPERNOTIFY_MISSING,
    SUPERNOTIFY_PRESENT,
    THREAT_PRIORITY_DEFAULTS,
    TYPE_DISCOVERY,
    TYPE_ZONE,
)
from .discovery import find_cameras
from .frigate import camera_choices, frigate_config, genai_features, proxy_problems, zone_labels
from .health import HealthSettings
from .rules import compile_pattern
from .supernotify_api import deliveries_by_transport, email_deliveries, scenario_names, supernotify_available
from .tracker import Settings

STEP_DISCOVERY = "discovery"
STEP_SETTINGS = "settings"
SECTION_TIMING = "timing"
SECTION_GENAI = "genai"
SECTION_NOTIFY = "notify"
SECTION_HEALTH = "health"
SECTION_SUMMARY = "summary"
# the daily summary without Supernotify, with nothing to set, only saying it needs Supernotify
SECTION_SUMMARY_UNAVAILABLE = "summary_unavailable"
SECTIONS = (SECTION_TIMING, SECTION_GENAI, SECTION_NOTIFY, SECTION_HEALTH, SECTION_SUMMARY, SECTION_SUMMARY_UNAVAILABLE)
# a setting left as it comes isn't stored, so it follows any better default of a later version
DEFAULTS: dict[str, Any] = (
    {f.name: sorted(value) if isinstance(value := getattr(Settings(), f.name), frozenset) else value for f in fields(Settings)}
    | dict(zip(CONF_THREAT_PRIORITIES, THREAT_PRIORITY_DEFAULTS, strict=True))
    | {CONF_STATUS_CHECK: True, CONF_POWER_GRACE: DEFAULT_POWER_GRACE}
)
SUMMARY_OPTIONS = (
    CONF_SUMMARY_MODE,
    CONF_SUMMARY_INTERVAL,
    CONF_SUMMARY_TIME,
    CONF_SUMMARY_CONCERNS,
    CONF_SUMMARY_DELIVERIES,
)
# what a rule holds, its name being the subentry's title
RULE_DATA = (CONF_MATCH, CONF_PATTERN, CONF_PRIORITY, CONF_SILENCE, CONF_SCENARIOS, CONF_REMOVE)
# what a camera or zone's entry holds, as it's found
ENTRY_DATA = (CONF_DEVICE_ID, CONF_TYPE, CONF_SOURCE, CONF_SOURCE_ENTRY_ID, CONF_SOURCE_NAME)


def supernotify_status(hass: HomeAssistant) -> str:
    return SUPERNOTIFY_PRESENT if supernotify_available(hass) else SUPERNOTIFY_MISSING


def proxy_status(hass: HomeAssistant, source_entry_id: str | None = None) -> str:
    """A warning for each Frigate server, or the one given, whose notification proxy fails some notifications, set
    apart from the text before it, or nothing"""
    warnings = [
        PROXY_EXPIRES.format(server=server, seconds=seconds) if seconds else PROXY_OFF.format(server=server)
        for server, seconds in proxy_problems(hass, source_entry_id)
    ]
    return "".join(f"\n\n{warning}" for warning in warnings)


def discovery_schema(
    auto_discover: bool = True,
    discover_zones: bool = False,
    health: bool = False,
    deliveries: list[str] | None = None,
) -> vol.Schema:
    """What's found, and once set up, the health check of each Frigate server and the daily summary, out of the way
    until wanted, the summary only to be set with Supernotify, whose deliveries are given"""
    fields_: dict[vol.Marker, Any] = {
        vol.Required(CONF_AUTO_DISCOVER, default=auto_discover): BooleanSelector(),
        vol.Required(CONF_DISCOVER_ZONES, default=discover_zones): BooleanSelector(),
    }
    if health:
        fields_[vol.Required(SECTION_HEALTH)] = section(vol.Schema(health_schema()), {"collapsed": True})
        if deliveries is not None:
            fields_[vol.Required(SECTION_SUMMARY)] = section(vol.Schema(summary_schema(deliveries)), {"collapsed": True})
        else:
            fields_[vol.Optional(SECTION_SUMMARY_UNAVAILABLE)] = section(vol.Schema({}), {"collapsed": True})
    return vol.Schema(fields_)


def health_schema() -> dict[vol.Marker, Any]:
    default = HealthSettings()
    return {
        vol.Required(CONF_HEALTH_CHECK, default=default.enabled): BooleanSelector(),
        vol.Required(CONF_HEALTH_INTERVAL, default=default.interval): _seconds(3600, minimum=10),
        vol.Required(CONF_HEALTH_RETRIES, default=default.retries): NumberSelector(
            NumberSelectorConfig(min=0, max=10, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_HEALTH_BACKOFF, default=default.backoff): _seconds(600, minimum=1),
    }


def summary_schema(deliveries: list[str]) -> dict[vol.Marker, Any]:
    return {
        vol.Required(CONF_SUMMARY_MODE, default=SUMMARY_AUTO): SelectSelector(
            SelectSelectorConfig(
                options=list(SUMMARY_MODES), mode=SelectSelectorMode.DROPDOWN, translation_key=CONF_SUMMARY_MODE
            )
        ),
        vol.Required(CONF_SUMMARY_INTERVAL, default=str(DEFAULT_SUMMARY_INTERVAL)): SelectSelector(
            SelectSelectorConfig(
                options=[str(hours) for hours in SUMMARY_INTERVALS],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key=CONF_SUMMARY_INTERVAL,
            )
        ),
        vol.Required(CONF_SUMMARY_TIME, default=DEFAULT_SUMMARY_TIME): TimeSelector(),
        vol.Required(CONF_SUMMARY_CONCERNS, default=False): BooleanSelector(),
        # left empty, Supernotify's e-mail deliveries, as shown to begin with
        vol.Optional(CONF_SUMMARY_DELIVERIES): SelectSelector(SelectSelectorConfig(options=deliveries, multiple=True)),
    }


async def supernotify_deliveries(hass: HomeAssistant) -> list[str] | None:
    """Every Supernotify delivery by name, or nothing without Supernotify"""
    if not supernotify_available(hass):
        return None
    return sorted({name for names in (await deliveries_by_transport(hass)).values() for name in names})


# as the base class, since type checkers can't all take one registered by a decorator as a type
def _seconds(maximum: int, minimum: int = 0) -> Selector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum, max=maximum, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement=UnitOfTime.SECONDS
        )
    )


def _choose(options: list[str], translation_key: str | None = None) -> Selector:
    config = SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.DROPDOWN)
    if translation_key:
        config["translation_key"] = translation_key
    else:
        # what's typed is kept too, for a label or zone Frigate's config doesn't list, such as one added since
        config["custom_value"] = True
    return SelectSelector(config)


def _priority() -> Selector:
    return SelectSelector(
        SelectSelectorConfig(options=list(PRIORITIES), mode=SelectSelectorMode.DROPDOWN, translation_key=CONF_PRIORITY)
    )


def genai_schema(summaries: bool, descriptions: bool, camera: bool) -> dict[vol.Marker, Any]:
    """What Frigate's generative AI adds, as far as Frigate makes it for the camera, or zone"""
    genai: dict[vol.Marker, Any] = {}
    if summaries:
        genai[vol.Required(CONF_SUMMARIES, default=DEFAULTS[CONF_SUMMARIES])] = BooleanSelector()
        genai[vol.Required(CONF_MIN_THREAT_LEVEL, default=DEFAULTS[CONF_MIN_THREAT_LEVEL])] = NumberSelector(
            NumberSelectorConfig(min=0, max=2, step=1, mode=NumberSelectorMode.SLIDER)
        )
        for key in CONF_THREAT_PRIORITIES:
            genai[vol.Required(key, default=DEFAULTS[key])] = _priority()
    if descriptions:
        genai[vol.Required(CONF_DESCRIPTIONS, default=DEFAULTS[CONF_DESCRIPTIONS])] = BooleanSelector()
        if camera:
            # a description has no zone, so a zone only has those of its reviews
            genai[vol.Required(CONF_UNREVIEWED_DESCRIPTIONS, default=DEFAULTS[CONF_UNREVIEWED_DESCRIPTIONS])] = (
                BooleanSelector()
            )
    if genai:
        genai[vol.Required(CONF_GENAI_WAIT, default=DEFAULTS[CONF_GENAI_WAIT])] = _seconds(600)
    return genai


async def settings_schema(
    hass: HomeAssistant, labels: list[str], zones: list[str] | None, genai: dict[vol.Marker, Any] | None = None
) -> vol.Schema:
    """The blueprint's filters, then its timing, what GenAI adds and who is told, out of the way until wanted. Zones
    only for a camera, since a zone's entry is the zone"""
    fields_: dict[vol.Marker, Any] = {
        vol.Required(CONF_SEVERITIES, default=DEFAULTS[CONF_SEVERITIES]): _choose(list(SEVERITIES), CONF_SEVERITIES),
        vol.Optional(CONF_LABELS): _choose(labels),
    }
    if zones is not None:
        fields_[vol.Optional(CONF_ZONES)] = _choose(zones)
        fields_[vol.Required(CONF_ZONE_MULTI, default=False)] = BooleanSelector()
        fields_[vol.Required(CONF_ZONE_ORDER, default=False)] = BooleanSelector()
        # a camera's own, a zone having no video of its own
        fields_[vol.Required(CONF_STATUS_CHECK, default=DEFAULTS[CONF_STATUS_CHECK])] = BooleanSelector()
        fields_[vol.Optional(CONF_POWER_ENTITY)] = EntitySelector(EntitySelectorConfig(domain=list(POWER_DOMAINS)))
        fields_[vol.Required(CONF_POWER_GRACE, default=DEFAULTS[CONF_POWER_GRACE])] = _seconds(1800)
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
        deliveries = await supernotify_deliveries(hass) or []
        notify[vol.Optional(CONF_DELIVERIES)] = SelectSelector(SelectSelectorConfig(options=deliveries, multiple=True))
    else:
        notify[vol.Optional(CONF_TARGETS)] = EntitySelector(EntitySelectorConfig(domain="notify", multiple=True))
    fields_[vol.Required(SECTION_TIMING)] = section(vol.Schema(timing), {"collapsed": True})
    if genai:
        fields_[vol.Required(SECTION_GENAI)] = section(vol.Schema(genai), {"collapsed": True})
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
        settings.update(value if isinstance(value, dict) and name in SECTIONS else {name: value})
    return settings


class CameraAutoNotifyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._found: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CameraAutoNotifyOptionsFlow:
        return CameraAutoNotifyOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        """Rules, for every notification, on the discovery entry, the one entry that isn't a camera's or zone's"""
        if config_entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            return {SUBENTRY_RULE: RuleSubentryFlow}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The global settings, chiefly automatic discovery, the cameras themselves set up as they're found"""
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
            description_placeholders={
                "found": found_text,
                "supernotify": supernotify_status(self.hass),
                "proxy": proxy_status(self.hass),
            },
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
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._found[CONF_NAME],
                "supernotify": supernotify_status(self.hass),
                "proxy": proxy_status(self.hass, self._found.get(CONF_SOURCE_ENTRY_ID)),
            },
        )


class CameraAutoNotifyOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            return await self.async_step_discovery()
        return await self.async_step_settings()

    async def async_step_discovery(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # the daily summary's settings kept while they can't be shown, without Supernotify
            kept = (
                {}
                if SECTION_SUMMARY in user_input
                else {key: value for key, value in self.config_entry.options.items() if key in SUMMARY_OPTIONS}
            )
            return self.async_create_entry(data=kept | flattened(user_input))
        options = self.config_entry.options
        schema = discovery_schema(
            options.get(CONF_AUTO_DISCOVER, True),
            options.get(CONF_DISCOVER_ZONES, False),
            health=True,
            deliveries=await supernotify_deliveries(self.hass),
        )
        shown = dict(options)
        if not shown.get(CONF_SUMMARY_DELIVERIES) and supernotify_available(self.hass):
            shown[CONF_SUMMARY_DELIVERIES] = await email_deliveries(self.hass)
        return self.async_show_form(
            step_id=STEP_DISCOVERY, data_schema=self.add_suggested_values_to_schema(schema, sectioned(schema, shown))
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
        config = frigate_config(self.hass, data[CONF_SOURCE_ENTRY_ID])
        if is_zone := data.get(CONF_TYPE) == TYPE_ZONE:
            labels, zones = zone_labels(config, data[CONF_SOURCE_NAME]), None
            summaries, descriptions = genai_features(config, zone=data[CONF_SOURCE_NAME])
        else:
            labels, zones = camera_choices(config, data[CONF_SOURCE_NAME])
            summaries, descriptions = genai_features(config, camera=data[CONF_SOURCE_NAME])
        genai = genai_schema(summaries, descriptions, camera=not is_zone)
        schema = await settings_schema(self.hass, labels, zones, genai)
        return self.async_show_form(
            step_id=STEP_SETTINGS,
            data_schema=self.add_suggested_values_to_schema(schema, sectioned(schema, dict(self.config_entry.options))),
            description_placeholders={
                "name": self.config_entry.title,
                "supernotify": supernotify_status(self.hass),
                "proxy": proxy_status(self.hass, data[CONF_SOURCE_ENTRY_ID]),
            },
        )


async def rule_schema(hass: HomeAssistant) -> vol.Schema:
    fields_: dict[vol.Marker, Any] = {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Required(CONF_MATCH, default=MATCH_CONTAINS): SelectSelector(
            SelectSelectorConfig(options=list(MATCHES), mode=SelectSelectorMode.LIST, translation_key=CONF_MATCH)
        ),
        vol.Required(CONF_PATTERN): TextSelector(),
        vol.Optional(CONF_PRIORITY): _priority(),
        vol.Required(CONF_SILENCE, default=False): BooleanSelector(),
        vol.Required(CONF_REMOVE, default=False): BooleanSelector(),
    }
    if supernotify_available(hass):
        scenarios = [SelectOptionDict(value=name, label=name) for name in await scenario_names(hass)]
        fields_[vol.Optional(CONF_SCENARIOS)] = SelectSelector(
            SelectSelectorConfig(options=scenarios, multiple=True, custom_value=True, mode=SelectSelectorMode.DROPDOWN)
        )
    return vol.Schema(fields_)


class RuleSubentryFlow(ConfigSubentryFlow):
    """A rule, matching the message of any notification, to change its priority, silence it, apply Supernotify
    scenarios, or take out the text matched"""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._rule("user", user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._rule("reconfigure", user_input)

    async def _rule(self, step_id: str, user_input: dict[str, Any] | None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                compile_pattern(user_input[CONF_MATCH], user_input[CONF_PATTERN])
            except re.error:
                errors[CONF_PATTERN] = "invalid_pattern"
            else:
                title = str(user_input[CONF_NAME]).strip() or str(user_input[CONF_PATTERN])
                data = {key: user_input[key] for key in RULE_DATA if user_input.get(key) not in (None, [], "")}
                if step_id == "user":
                    return self.async_create_entry(title=title, data=data)
                return self.async_update_and_abort(self._get_entry(), self._get_reconfigure_subentry(), title=title, data=data)
            suggested = user_input
        elif step_id == "reconfigure":
            subentry = self._get_reconfigure_subentry()
            suggested = {CONF_NAME: subentry.title, **subentry.data}
        else:
            suggested = {}
        schema = await rule_schema(self.hass)
        return self.async_show_form(
            step_id=step_id, data_schema=self.add_suggested_values_to_schema(schema, suggested), errors=errors
        )
