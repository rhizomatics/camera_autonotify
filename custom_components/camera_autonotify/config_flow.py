"""Config flow for Camera AutoNotify, one config entry per camera, or zone"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import fields
from typing import Any

from homeassistant.components.file_upload import process_uploaded_file
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
    FileSelector,
    FileSelectorConfig,
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    ObjectSelectorConfig,
    SelectOptionDict,
    Selector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TargetSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from .actions import offered
from .anpr import PRIMARY_DOMAINS, AnprNotifier, Sighting, find_linked_camera, sensor_entity
from .compat import vol
from .const import (
    CONF_ACTIONS,
    CONF_ACTIONS_GLOBAL,
    CONF_ALERT_ONCE,
    CONF_ALPR_ENTITY,
    CONF_ALPR_VEHICLES_ONLY,
    CONF_ANPR2MQTT_ARCHIVE,
    CONF_ANPR_OWN_CLASSIFICATION,
    CONF_AUTO_DISCOVER,
    CONF_COOLDOWN,
    CONF_CUSTOM_TARGET,
    CONF_DELIVERIES,
    CONF_DESCRIPTIONS,
    CONF_DISCOVER_ZONES,
    CONF_DVLA_API_KEY,
    CONF_DVLA_API_KEY_CLEAR,
    CONF_FINAL_DELAY,
    CONF_FINAL_UPDATE,
    CONF_GENAI_IMAGE,
    CONF_GENAI_WAIT,
    CONF_HEALTH_BACKOFF,
    CONF_HEALTH_CHECK,
    CONF_HEALTH_INTERVAL,
    CONF_HEALTH_RETRIES,
    CONF_HISTORY_DAYS,
    CONF_IMAGE,
    CONF_INITIAL_DELAY,
    CONF_KIND_PRIORITIES,
    CONF_KIND_SCENARIOS,
    CONF_KNOWN_CATEGORY,
    CONF_LABELS,
    CONF_LAST_SNAPSHOT,
    CONF_LINKED_CAMERA,
    CONF_LINKED_CAMERA_AUTO,
    CONF_LOOKUP_CACHE_HOURS,
    CONF_MATCH,
    CONF_MIN_THREAT_LEVEL,
    CONF_MIN_VISIT_GAP,
    CONF_OBJECT,
    CONF_OBJECT_NAMES,
    CONF_PATTERN,
    CONF_PLATE_DESCRIPTION,
    CONF_PLATE_ICON,
    CONF_PLATE_IGNORE,
    CONF_PLATE_KIND,
    CONF_PLATE_LOOKUP,
    CONF_PLATES,
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
    CONF_SPEED_UNIT,
    CONF_STATUS_CHECK,
    CONF_SUMMARIES,
    CONF_SUMMARY_CONCERNS,
    CONF_SUMMARY_DELIVERIES,
    CONF_SUMMARY_INTERVAL,
    CONF_SUMMARY_MODE,
    CONF_SUMMARY_RETRIES,
    CONF_SUMMARY_TIME,
    CONF_TARGET,
    CONF_TARGETS,
    CONF_THREAT_PRIORITIES,
    CONF_TIMEOUT,
    CONF_UNREVIEWED_DESCRIPTIONS,
    CONF_UPDATE_SUB_LABEL,
    CONF_VEHICLE_PRIORITIES,
    CONF_VEHICLE_SCENARIOS,
    CONF_ZONE_MULTI,
    CONF_ZONE_ORDER,
    CONF_ZONES,
    DEFAULT_ACTIONS,
    DEFAULT_GENAI_IMAGE,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_IMAGE,
    DEFAULT_KNOWN_CATEGORY,
    DEFAULT_LOOKUP_CACHE_HOURS,
    DEFAULT_MIN_VISIT_GAP,
    DEFAULT_POWER_GRACE,
    DEFAULT_SUMMARY_INTERVAL,
    DEFAULT_SUMMARY_RETRIES,
    DEFAULT_SUMMARY_TIME,
    DISCOVERY_TITLE,
    DOMAIN,
    FRIGATE_DOMAIN,
    GENAI_IMAGE_GLOBAL,
    GENAI_IMAGES,
    IMAGES,
    KINDS,
    MATCH_CONTAINS,
    MATCHES,
    MAX_SUMMARY_RETRIES,
    POWER_DOMAINS,
    PRIORITIES,
    SEVERITIES,
    SOURCE_ANPR2MQTT,
    SPEED_AUTO,
    SPEED_UNITS,
    SUBENTRY_PLATES,
    SUBENTRY_RULE,
    SUMMARY_AUTO,
    SUMMARY_INTERVALS,
    SUMMARY_MODES,
    SUMMARY_OFF,
    THREAT_PRIORITY_DEFAULTS,
    TYPE_ANPR,
    TYPE_DISCOVERY,
    TYPE_ZONE,
    VEHICLE_NO_DELIVERY,
    VEHICLE_PRIORITY_DEFAULTS,
    VEHICLE_PRIORITY_SOURCE,
    VEHICLE_RULE_PRIORITIES,
)
from .discovery import find_anpr, find_cameras
from .entries import global_settings, wants_last_snapshot
from .frigate import (
    all_labels,
    camera_autotracks,
    camera_choices,
    frigate_config,
    genai_features,
    proxy_problems,
    zone_cameras,
    zone_labels,
)
from .health import HealthSettings
from .migrate import (
    ARCHIVE_ACCEPT,
    Added,
    ArchiveUnreadable,
    Imported,
    async_import,
    imported_options,
    new_plates,
    read_archive,
)
from .plates import KIND_DANGEROUS, KIND_KNOWN, is_pattern
from .rules import compile_pattern
from .supernotify_api import deliveries_by_transport, email_deliveries, scenario_names, supernotify_available
from .texts import (
    ANPR_LINKED,
    ANPR_UNLINKED,
    AUTOTRACKING,
    CAMERAS_FOUND,
    CAMERAS_NONE,
    DVLA_KEY_SET,
    DVLA_KEY_UNSET,
    IMPORT_CATEGORY,
    IMPORT_CATEGORY_EXISTING,
    IMPORT_HISTORY,
    IMPORT_NOT_IMPORTED,
    IMPORT_NOTHING,
    IMPORT_SETTING_DVLA_API_KEY,
    IMPORT_SETTING_LOOKUP_CACHE,
    IMPORT_SETTING_MIN_VISIT_GAP,
    IMPORT_SETTINGS,
    IMPORTED_CATEGORIES,
    IMPORTED_NOTHING,
    IMPORTED_PLATES,
    IMPORTED_SIGHTINGS,
    PROXY_EXPIRES,
    PROXY_OFF,
    SUPERNOTIFY_MISSING,
    SUPERNOTIFY_PRESENT,
    async_load_texts,
    text,
)
from .tracker import Settings

_LOGGER = logging.getLogger(__name__)

STEP_DISCOVERY = "discovery"
STEP_SETTINGS = "settings"
STEP_ANPR = "anpr"
STEP_CONFIRM_ANPR = "confirm_anpr"
STEP_IMPORT = "import_anpr2mqtt"
SECTION_VEHICLES = "vehicles"
SECTION_VEHICLE_LOOKUP = "vehicle_lookup"
SECTION_PLATES = "plates"
SECTION_TIMING = "timing"
SECTION_GENAI = "genai"
SECTION_NOTIFY = "notify"
SECTION_HEALTH = "health"
SECTION_SUMMARY = "summary"
SECTION_IMPORT = "anpr2mqtt_import"
# the daily summary without Supernotify, with nothing to set, only saying it needs Supernotify
SECTION_SUMMARY_UNAVAILABLE = "summary_unavailable"
SECTIONS = (
    SECTION_TIMING,
    SECTION_GENAI,
    SECTION_NOTIFY,
    SECTION_HEALTH,
    SECTION_SUMMARY,
    SECTION_SUMMARY_UNAVAILABLE,
    SECTION_VEHICLES,
    SECTION_VEHICLE_LOOKUP,
    SECTION_PLATES,
    SECTION_IMPORT,
)
# an anpr2mqtt entry's settings as they come, not stored
ANPR_DEFAULTS: dict[str, Any] = {
    CONF_LINKED_CAMERA_AUTO: True,
    **{CONF_KIND_PRIORITIES[kind]: priority for kind, priority in VEHICLE_PRIORITY_DEFAULTS.items()},
}
# a setting left as it comes isn't stored, so it follows any better default of a later version
DEFAULTS: dict[str, Any] = (
    {f.name: sorted(value) if isinstance(value := getattr(Settings(), f.name), frozenset) else value for f in fields(Settings)}
    | dict(zip(CONF_THREAT_PRIORITIES, THREAT_PRIORITY_DEFAULTS, strict=True))
    | {
        CONF_STATUS_CHECK: True,
        CONF_POWER_GRACE: DEFAULT_POWER_GRACE,
        CONF_IMAGE: DEFAULT_IMAGE,
        CONF_GENAI_IMAGE: GENAI_IMAGE_GLOBAL,
        CONF_ACTIONS_GLOBAL: True,
        CONF_ALPR_VEHICLES_ONLY: True,
    }
)
SUMMARY_OPTIONS = (
    CONF_SUMMARY_MODE,
    CONF_SUMMARY_INTERVAL,
    CONF_SUMMARY_TIME,
    CONF_SUMMARY_CONCERNS,
    CONF_SUMMARY_DELIVERIES,
    CONF_SUMMARY_RETRIES,
)
# what a rule holds, its name being the subentry's title
RULE_DATA = (CONF_MATCH, CONF_PATTERN, CONF_PRIORITY, CONF_SILENCE, CONF_SCENARIOS, CONF_REMOVE)
# what a camera or zone's entry holds, as it's found
ENTRY_DATA = (CONF_DEVICE_ID, CONF_TYPE, CONF_SOURCE, CONF_SOURCE_ENTRY_ID, CONF_SOURCE_NAME)


async def supernotify_status(hass: HomeAssistant) -> str:
    """In Home Assistant's own language, rather than the browser's, a placeholder not being translated by the
    frontend, as with the other notes"""
    await async_load_texts(hass)
    return text(hass, SUPERNOTIFY_PRESENT if supernotify_available(hass) else SUPERNOTIFY_MISSING)


async def proxy_status(hass: HomeAssistant, source_entry_id: str | None = None) -> str:
    """A warning for each Frigate server, or the one given, whose notification proxy fails some notifications, set
    apart from the text before it, or nothing"""
    await async_load_texts(hass)
    warnings = [
        text(hass, PROXY_EXPIRES, server=server, seconds=seconds) if seconds else text(hass, PROXY_OFF, server=server)
        for server, seconds in proxy_problems(hass, source_entry_id)
    ]
    return "".join(f"\n\n{warning}" for warning in warnings)


def discovery_schema(
    auto_discover: bool = True,
    discover_zones: bool = False,
    health: bool = False,
    deliveries: list[str] | None = None,
    labels: list[str] | None = None,
    actions: list[str] | None = None,
    scenarios: list[str] | None = None,
) -> vol.Schema:
    """What's found, and once set up, what every notification calls each object, the labels of every Frigate server
    being given, and the health check of each Frigate server and the daily summary, out of the way until wanted, the
    summary only to be set with Supernotify, whose deliveries are given"""
    fields_: dict[vol.Marker, Any] = {
        vol.Required(CONF_AUTO_DISCOVER, default=auto_discover): BooleanSelector(),
        vol.Required(CONF_DISCOVER_ZONES, default=discover_zones): BooleanSelector(),
    }
    if labels is not None:
        fields_[vol.Optional(CONF_OBJECT_NAMES)] = object_names_selector(labels)
        fields_[vol.Required(CONF_GENAI_IMAGE, default=DEFAULT_GENAI_IMAGE)] = SelectSelector(
            SelectSelectorConfig(options=list(IMAGES), mode=SelectSelectorMode.DROPDOWN, translation_key=CONF_IMAGE)
        )
    if actions is not None:
        # the buttons on a phone, of those Frigate can do
        fields_[vol.Optional(CONF_ACTIONS)] = _choose(actions, CONF_ACTIONS)
    if labels is not None:
        fields_[vol.Required(CONF_SPEED_UNIT, default=SPEED_AUTO)] = SelectSelector(
            SelectSelectorConfig(options=list(SPEED_UNITS), mode=SelectSelectorMode.DROPDOWN, translation_key=CONF_SPEED_UNIT)
        )
    if health:
        fields_[vol.Required(SECTION_HEALTH)] = section(vol.Schema(health_schema()), {"collapsed": True})
        if deliveries is not None:
            fields_[vol.Required(SECTION_SUMMARY)] = section(vol.Schema(summary_schema(deliveries)), {"collapsed": True})
        else:
            fields_[vol.Optional(SECTION_SUMMARY_UNAVAILABLE)] = section(vol.Schema({}), {"collapsed": True})
        fields_[vol.Optional(SECTION_VEHICLES)] = section(vol.Schema(vehicles_schema(scenarios)), {"collapsed": True})
        fields_[vol.Optional(SECTION_VEHICLE_LOOKUP)] = section(vol.Schema(lookup_schema()), {"collapsed": True})
        fields_[vol.Optional(SECTION_IMPORT)] = section(vol.Schema(archive_schema()), {"collapsed": True})
    return vol.Schema(fields_)


# the name of each setting an import can bring
IMPORT_SETTING_NAMES = {
    CONF_DVLA_API_KEY: IMPORT_SETTING_DVLA_API_KEY,
    CONF_LOOKUP_CACHE_HOURS: IMPORT_SETTING_LOOKUP_CACHE,
    CONF_MIN_VISIT_GAP: IMPORT_SETTING_MIN_VISIT_GAP,
}


def archive_schema() -> dict[vol.Marker, Any]:
    """An archive of anpr2mqtt's config and data folders, to import from"""
    return {vol.Optional(CONF_ANPR2MQTT_ARCHIVE): FileSelector(FileSelectorConfig(accept=ARCHIVE_ACCEPT))}


async def async_read_upload(hass: HomeAssistant, file_id: str) -> Imported:
    """What's in an uploaded archive of anpr2mqtt's, the upload being removed once read"""

    def read() -> Imported:
        with process_uploaded_file(hass, file_id) as path:
            return read_archive(path)

    try:
        return await hass.async_add_executor_job(read)
    except ValueError as error:
        # the upload gone, as after a restart
        raise ArchiveUnreadable(str(error)) from error


def import_summary(hass: HomeAssistant, entry: ConfigEntry, found: Imported) -> str:
    """What an import adds, as a list: each category's new plates, the visit history, the settings, and what can't be
    imported"""
    lines = [
        text(hass, IMPORT_CATEGORY_EXISTING if existing else IMPORT_CATEGORY, name=name, count=count)
        for name, (count, existing) in new_plates(entry, found).items()
    ]
    if found.history:
        sightings = sum(len(times) for times in found.history.values())
        lines.append(text(hass, IMPORT_HISTORY, plates=len(found.history), sightings=sightings))
    if found.settings:
        named = ", ".join(text(hass, IMPORT_SETTING_NAMES[key]) for key in found.settings)
        lines.append(text(hass, IMPORT_SETTINGS, settings=named))
    lines.extend(text(hass, IMPORT_NOT_IMPORTED, item=item) for item in found.not_imported)
    return "\n".join(f"- {line}" for line in lines) if lines else text(hass, IMPORT_NOTHING)


# the success dialog's text once imported from anpr2mqtt
IMPORTED = "anpr2mqtt_imported"


def added_summary(hass: HomeAssistant, added: Added) -> dict[str, str]:
    """What an import added, as a list, for the success dialog's placeholders"""
    lines = [
        text(hass, key, count=count)
        for key, count in (
            (IMPORTED_CATEGORIES, added.categories),
            (IMPORTED_PLATES, added.plates),
            (IMPORTED_SIGHTINGS, added.sightings),
        )
        if count
    ]
    if added.settings:
        named = ", ".join(text(hass, IMPORT_SETTING_NAMES[key]) for key in added.settings)
        lines.append(text(hass, IMPORT_SETTINGS, settings=named))
    return {"imported": "\n".join(f"- {line}" for line in lines) if lines else text(hass, IMPORTED_NOTHING)}


def vehicles_schema(scenarios: list[str] | None) -> dict[vol.Marker, Any]:
    """The pre-defined vehicle rules, their condition fixed, a priority and scenarios for each, whether anpr2mqtt's
    sightings keep its own classification, and the visit history"""
    fields_: dict[vol.Marker, Any] = {}
    for kind, key in CONF_VEHICLE_PRIORITIES.items():
        fields_[vol.Required(key, default=VEHICLE_RULE_PRIORITIES[kind])] = _priority()
        if scenarios is not None:
            fields_[vol.Optional(CONF_VEHICLE_SCENARIOS[kind])] = SelectSelector(
                SelectSelectorConfig(options=scenarios, multiple=True, custom_value=True, mode=SelectSelectorMode.DROPDOWN)
            )
    fields_[vol.Required(CONF_KNOWN_CATEGORY, default=DEFAULT_KNOWN_CATEGORY)] = TextSelector()
    fields_[vol.Required(CONF_ANPR_OWN_CLASSIFICATION, default=True)] = BooleanSelector()
    fields_[vol.Required(CONF_MIN_VISIT_GAP, default=DEFAULT_MIN_VISIT_GAP)] = _seconds(86400)
    fields_[vol.Required(CONF_HISTORY_DAYS, default=DEFAULT_HISTORY_DAYS)] = NumberSelector(
        NumberSelectorConfig(min=1, max=3650, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement=UnitOfTime.DAYS)
    )
    return fields_


def lookup_schema() -> dict[vol.Marker, Any]:
    """Looking a plate up with a vehicle register, the DVLA's for UK plates"""
    return {
        vol.Optional(CONF_DVLA_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
        vol.Required(CONF_DVLA_API_KEY_CLEAR, default=False): BooleanSelector(),
        vol.Required(CONF_LOOKUP_CACHE_HOURS, default=DEFAULT_LOOKUP_CACHE_HOURS): NumberSelector(
            NumberSelectorConfig(min=1, max=720, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement=UnitOfTime.HOURS)
        ),
    }


def plate_category_schema() -> vol.Schema:
    """A category of vehicles, by its plates, each a plate or a regular expression, with its own corrections"""
    return vol.Schema({
        vol.Required(CONF_NAME): TextSelector(),
        vol.Required(CONF_PLATE_KIND, default=KIND_KNOWN): SelectSelector(
            SelectSelectorConfig(
                options=[KIND_KNOWN, KIND_DANGEROUS], mode=SelectSelectorMode.DROPDOWN, translation_key=CONF_PLATE_KIND
            )
        ),
        vol.Optional(CONF_PLATE_DESCRIPTION): TextSelector(),
        vol.Optional(CONF_PLATE_ICON): IconSelector(),
        vol.Required(CONF_PLATE_IGNORE, default=False): BooleanSelector(),
        vol.Required(CONF_PLATE_LOOKUP, default=False): BooleanSelector(),
        vol.Optional(CONF_PLATES): ObjectSelector(
            ObjectSelectorConfig(
                fields={
                    "plate": {"required": True, "selector": {"text": {}}},
                    "description": {"required": False, "selector": {"text": {}}},
                    "corrections": {"required": False, "selector": {"text": {"multiple": True}}},
                },
                multiple=True,
                label_field="plate",
                description_field="description",
            )
        ),
    })


def invalid_patterns(plates: object) -> bool:
    """Whether any plate, or correction of one, is a regular expression that can't be used"""
    for item in plates if isinstance(plates, list) else []:
        texts = [item.get("plate"), *(item.get("corrections") or [])] if isinstance(item, dict) else [item]
        for each in texts:
            if each and is_pattern(str(each)):
                try:
                    re.compile(str(each))
                except re.error:
                    return True
    return False


class PlateCategorySubentryFlow(ConfigSubentryFlow):
    """A category of vehicles, a single vehicle, every family car, or a delivery company's vans, by their plates"""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._category("user", user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._category("reconfigure", user_input)

    async def _category(self, step_id: str, user_input: dict[str, Any] | None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if invalid_patterns(user_input.get(CONF_PLATES)):
                errors[CONF_PLATES] = "invalid_pattern"
            else:
                title = str(user_input[CONF_NAME]).strip()
                data = {k: v for k, v in user_input.items() if k != CONF_NAME and v not in (None, [], "")}
                if step_id == "user":
                    return self.async_create_entry(title=title, data=data)
                return self.async_update_and_abort(self._get_entry(), self._get_reconfigure_subentry(), title=title, data=data)
            suggested = user_input
        elif step_id == "reconfigure":
            subentry = self._get_reconfigure_subentry()
            suggested = {CONF_NAME: subentry.title, **subentry.data}
        else:
            suggested = {}
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(plate_category_schema(), suggested),
            errors=errors,
        )


def object_names_selector(labels: list[str]) -> Selector:
    """A list of Frigate's objects, each with what to call it, the object chosen from those Frigate has, or typed"""
    return ObjectSelector(
        ObjectSelectorConfig(
            fields={
                CONF_OBJECT: {
                    "required": True,
                    "selector": {"select": {"options": labels, "custom_value": True, "mode": "dropdown"}},
                },
                CONF_NAME: {"required": True, "selector": {"text": {}}},
            },
            multiple=True,
            label_field=CONF_OBJECT,
            description_field=CONF_NAME,
            translation_key=CONF_OBJECT_NAMES,
        )
    )


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
        vol.Required(CONF_SUMMARY_RETRIES, default=DEFAULT_SUMMARY_RETRIES): NumberSelector(
            NumberSelectorConfig(min=0, max=MAX_SUMMARY_RETRIES, step=1, mode=NumberSelectorMode.BOX)
        ),
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
        # as the global settings unless chosen here
        genai[vol.Required(CONF_GENAI_IMAGE, default=DEFAULTS[CONF_GENAI_IMAGE])] = SelectSelector(
            SelectSelectorConfig(options=list(GENAI_IMAGES), mode=SelectSelectorMode.DROPDOWN, translation_key=CONF_GENAI_IMAGE)
        )
    return genai


async def settings_schema(
    hass: HomeAssistant,
    labels: list[str],
    zones: list[str] | None,
    genai: dict[vol.Marker, Any] | None = None,
    actions: list[str] | None = None,
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
    notify: dict[vol.Marker, Any] = {
        vol.Required(CONF_IMAGE, default=DEFAULTS[CONF_IMAGE]): SelectSelector(
            SelectSelectorConfig(options=list(IMAGES), mode=SelectSelectorMode.DROPDOWN, translation_key=CONF_IMAGE)
        )
    }
    if zones is not None:
        # a camera's own, shown as it is, which is on where an ANPR/ALPR entity is chosen until switched off
        notify[vol.Optional(CONF_LAST_SNAPSHOT)] = BooleanSelector()
    if supernotify_available(hass) and actions:
        # the buttons on a phone, as the global settings unless chosen here, of those Frigate can do for the camera
        notify[vol.Required(CONF_ACTIONS_GLOBAL, default=DEFAULTS[CONF_ACTIONS_GLOBAL])] = BooleanSelector()
        notify[vol.Optional(CONF_ACTIONS)] = _choose(actions, CONF_ACTIONS)
    notify.update(await target_fields(hass))
    fields_[vol.Required(SECTION_TIMING)] = section(vol.Schema(timing), {"collapsed": True})
    if genai:
        fields_[vol.Required(SECTION_GENAI)] = section(vol.Schema(genai), {"collapsed": True})
    if zones is not None:
        # for any camera, there being no telling which see vehicles, an image processing ANPR/ALPR entity, such as OpenALPR's, reading plates instead of Frigate
        plates = {
            vol.Optional(CONF_ALPR_ENTITY): EntitySelector(
                EntitySelectorConfig(filter=[{"domain": "image_processing", "device_class": "alpr"}])
            ),
            vol.Required(CONF_ALPR_VEHICLES_ONLY, default=DEFAULTS[CONF_ALPR_VEHICLES_ONLY]): BooleanSelector(),
        }
        fields_[vol.Optional(SECTION_PLATES)] = section(vol.Schema(plates), {"collapsed": True})
    fields_[vol.Required(SECTION_NOTIFY)] = section(vol.Schema(notify), {"collapsed": True})
    return vol.Schema(fields_)


async def target_fields(hass: HomeAssistant) -> dict[vol.Marker, Any]:
    """Who and what is notified: with Supernotify, the same pair of target fields as supernotify.notify itself, and
    its deliveries, or else notify entities"""
    if not supernotify_available(hass):
        return {vol.Optional(CONF_TARGETS): EntitySelector(EntitySelectorConfig(domain="notify", multiple=True))}
    deliveries = await supernotify_deliveries(hass) or []
    return {
        vol.Optional(CONF_TARGET): TargetSelector(),
        vol.Optional(CONF_CUSTOM_TARGET): TextSelector(TextSelectorConfig(multiple=True)),
        vol.Optional(CONF_DELIVERIES): SelectSelector(SelectSelectorConfig(options=deliveries, multiple=True)),
    }


async def anpr_schema(hass: HomeAssistant) -> vol.Schema:
    """An anpr2mqtt entry's linked camera, a priority and scenarios for each kind of vehicle, and who is told"""
    vehicles: dict[vol.Marker, Any] = {}
    scenarios = await scenario_names(hass) if supernotify_available(hass) else None
    priorities = [VEHICLE_PRIORITY_SOURCE, *PRIORITIES, VEHICLE_NO_DELIVERY]
    for kind in KINDS:
        vehicles[vol.Required(CONF_KIND_PRIORITIES[kind], default=VEHICLE_PRIORITY_DEFAULTS[kind])] = SelectSelector(
            SelectSelectorConfig(options=priorities, mode=SelectSelectorMode.DROPDOWN, translation_key="vehicle_priority")
        )
        if scenarios is not None:
            # chosen from Supernotify's, or typed, for one not made yet
            vehicles[vol.Optional(CONF_KIND_SCENARIOS[kind])] = SelectSelector(
                SelectSelectorConfig(options=scenarios, multiple=True, custom_value=True, mode=SelectSelectorMode.DROPDOWN)
            )
    return vol.Schema({
        vol.Required(CONF_LINKED_CAMERA_AUTO, default=True): BooleanSelector(),
        # only the cameras of primary integrations, not anpr2mqtt's own, nor the same camera by ONVIF
        vol.Optional(CONF_LINKED_CAMERA): EntitySelector(
            EntitySelectorConfig(filter=[{"integration": domain, "domain": "camera"} for domain in PRIMARY_DOMAINS])
        ),
        vol.Required(SECTION_VEHICLES): section(vol.Schema(vehicles), {"collapsed": False}),
        vol.Required(SECTION_NOTIFY): section(vol.Schema(await target_fields(hass)), {"collapsed": True}),
    })


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


def _unique_id(found: Mapping[str, Any]) -> str:
    """A camera's or zone's device, or for anpr2mqtt, whose cameras each have one device for all their events, the
    sensor's unique id"""
    if found.get(CONF_TYPE) == TYPE_ANPR:
        return f"{SOURCE_ANPR2MQTT}:{found[CONF_SOURCE_NAME]}"
    return str(found[CONF_DEVICE_ID])


class CameraAutoNotifyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._found: dict[str, Any] = {}
        self._imported = Imported()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CameraAutoNotifyOptionsFlow:
        return CameraAutoNotifyOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        """Rules, for every notification, on the discovery entry, the one entry that isn't a camera's or zone's"""
        if config_entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            return {SUBENTRY_RULE: RuleSubentryFlow, SUBENTRY_PLATES: PlateCategorySubentryFlow}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The global settings, chiefly automatic discovery, the cameras themselves set up as they're found"""
        await self.async_set_unique_id(TYPE_DISCOVERY)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            # the cameras are set up as this entry is, each as its own entry to change or delete
            return self.async_create_entry(title=DISCOVERY_TITLE, data={CONF_TYPE: TYPE_DISCOVERY}, options=user_input)
        found = [camera.name for camera in find_cameras(self.hass) + find_anpr(self.hass)]
        await async_load_texts(self.hass)
        if found:
            found_text = text(self.hass, CAMERAS_FOUND) + "\n\n" + "\n".join(f"- {name}" for name in found)
        else:
            found_text = text(self.hass, CAMERAS_NONE)
        return self.async_show_form(
            step_id="user",
            data_schema=discovery_schema(),
            description_placeholders={
                "found": found_text,
                "supernotify": await supernotify_status(self.hass),
                "proxy": await proxy_status(self.hass),
            },
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """A camera found with automatic discovery on, so set up without asking"""
        # a discovery of the same camera may be waiting, and goes once this entry exists
        await self.async_set_unique_id(_unique_id(import_data), raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=import_data[CONF_NAME], data={k: v for k, v in import_data.items() if k in ENTRY_DATA}
        )

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        """A camera found with automatic discovery off, a zone, or an anpr2mqtt source, so offered to be added"""
        self._found = dict(discovery_info)
        await self.async_set_unique_id(_unique_id(discovery_info))
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": discovery_info[CONF_NAME]}
        if discovery_info.get(CONF_TYPE) == TYPE_ANPR:
            return await self.async_step_confirm_anpr()
        return await self.async_step_confirm()

    def _create_found(self, added: Added | None = None) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._found[CONF_NAME],
            data={k: v for k, v in self._found.items() if k in ENTRY_DATA},
            description=IMPORTED if added is not None else None,
            description_placeholders=added_summary(self.hass, added) if added is not None else None,
        )

    async def async_step_confirm_anpr(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """An anpr2mqtt source, offering to import from anpr2mqtt itself until there are vehicle categories"""
        settings = global_settings(self.hass)
        upload = settings is not None and not any(
            subentry.subentry_type == SUBENTRY_PLATES for subentry in settings.subentries.values()
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            if not (archive := user_input.get(CONF_ANPR2MQTT_ARCHIVE)):
                return self._create_found()
            try:
                self._imported = await async_read_upload(self.hass, archive)
            except ArchiveUnreadable as error:
                _LOGGER.warning("CAMERA_AUTONOTIFY Can't import from anpr2mqtt's archive: %s", error)
                errors["base"] = "archive_unreadable"
            else:
                return await self.async_step_import_anpr2mqtt()
        return self.async_show_form(
            step_id=STEP_CONFIRM_ANPR,
            data_schema=vol.Schema(archive_schema() if upload else {}),
            errors=errors,
            description_placeholders={"name": self._found[CONF_NAME], "supernotify": await supernotify_status(self.hass)},
        )

    async def async_step_import_anpr2mqtt(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """What's imported from anpr2mqtt into the global settings, to confirm, then the source set up"""
        settings = global_settings(self.hass)
        if settings is None:
            return self.async_abort(reason="global_settings_missing")
        if user_input is not None:
            added = await async_import(self.hass, settings, self._imported)
            await async_load_texts(self.hass)
            return self._create_found(added)
        await async_load_texts(self.hass)
        return self.async_show_form(
            step_id=STEP_IMPORT, description_placeholders={"found": import_summary(self.hass, settings, self._imported)}
        )

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._create_found()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._found[CONF_NAME],
                "supernotify": await supernotify_status(self.hass),
                "proxy": await proxy_status(self.hass, self._found.get(CONF_SOURCE_ENTRY_ID)),
            },
        )


class CameraAutoNotifyOptionsFlow(OptionsFlowWithReload):
    # warned once that summaries have no delivery, saved as they are if sent again
    _undeliverable_warned: bool = False
    # an anpr2mqtt archive read, and the global settings to save once it's imported
    _imported: Imported
    _settings: dict[str, Any]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            return await self.async_step_discovery()
        if self.config_entry.data.get(CONF_TYPE) == TYPE_ANPR:
            return await self.async_step_anpr()
        return await self.async_step_settings()

    async def async_step_anpr(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """An anpr2mqtt entry's settings, saying which camera is linked, as found by itself"""
        if user_input is not None:
            settings = {
                key: value
                for key, value in flattened(user_input).items()
                if (value or value is False or value == 0) and value != ANPR_DEFAULTS.get(key)
            }
            return self.async_create_entry(data=settings)
        schema = await anpr_schema(self.hass)
        await async_load_texts(self.hass)
        found = AnprNotifier(self.hass, self.config_entry)
        sensor = sensor_entity(self.hass, self.config_entry)
        state = self.hass.states.get(sensor.entity_id) if sensor is not None else None
        sighting = Sighting.from_state(state) if state is not None else Sighting("")
        camera = find_linked_camera(self.hass, sensor, sighting.linked_cameras, sighting.camera)
        linked = (
            text(self.hass, ANPR_LINKED, camera=found.where(sighting, camera)) if camera else text(self.hass, ANPR_UNLINKED)
        )
        return self.async_show_form(
            step_id=STEP_ANPR,
            data_schema=self.add_suggested_values_to_schema(schema, sectioned(schema, dict(self.config_entry.options))),
            description_placeholders={
                "name": self.config_entry.title,
                "supernotify": await supernotify_status(self.hass),
                "linked": linked,
            },
        )

    async def async_step_discovery(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None and not self._undeliverable_warned and await self._summary_undeliverable(user_input):
            self._undeliverable_warned = True
            return await self._show_discovery(
                dict(self.config_entry.options) | flattened(user_input),
                shown_as_is=True,
                errors={"base": "summary_undeliverable"},
            )
        if user_input is not None:
            # the daily summary's settings kept while they can't be shown, without Supernotify
            kept = (
                {}
                if SECTION_SUMMARY in user_input
                else {key: value for key, value in self.config_entry.options.items() if key in SUMMARY_OPTIONS}
            )
            settings = kept | flattened(user_input)
            archive = settings.pop(CONF_ANPR2MQTT_ARCHIVE, None)
            self._keep_credentials(settings)
            if archive:
                try:
                    self._imported = await async_read_upload(self.hass, archive)
                except ArchiveUnreadable as error:
                    _LOGGER.warning("CAMERA_AUTONOTIFY Can't import from anpr2mqtt's archive: %s", error)
                    shown = dict(self.config_entry.options) | settings
                    return await self._show_discovery(shown, shown_as_is=True, errors={"base": "archive_unreadable"})
                self._settings = settings
                return await self.async_step_import_anpr2mqtt()
            return self.async_create_entry(data=settings)
        return await self._show_discovery(dict(self.config_entry.options))

    async def async_step_import_anpr2mqtt(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """What's imported from anpr2mqtt, to confirm, then imported and the global settings saved with it"""
        if user_input is not None:
            added = await async_import(self.hass, self.config_entry, self._imported)
            await async_load_texts(self.hass)
            return self.async_create_entry(
                data=self._settings | imported_options(self._imported),
                description=IMPORTED,
                description_placeholders=added_summary(self.hass, added),
            )
        await async_load_texts(self.hass)
        return self.async_show_form(
            step_id=STEP_IMPORT,
            description_placeholders={"found": import_summary(self.hass, self.config_entry, self._imported)},
        )

    async def _show_discovery(
        self, shown: dict[str, Any], shown_as_is: bool = False, errors: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        servers = self.hass.config_entries.async_entries(FRIGATE_DOMAIN)
        actions = offered([frigate_config(self.hass, server.entry_id) for server in servers])
        schema = discovery_schema(
            shown.get(CONF_AUTO_DISCOVER, True),
            shown.get(CONF_DISCOVER_ZONES, False),
            health=True,
            deliveries=await supernotify_deliveries(self.hass),
            labels=all_labels(self.hass),
            actions=actions,
            scenarios=await scenario_names(self.hass) if supernotify_available(self.hass) else None,
        )
        # only those still offered, so the form can be saved as shown
        shown[CONF_ACTIONS] = [kind for kind in shown.get(CONF_ACTIONS, DEFAULT_ACTIONS) if kind in actions]
        if not shown_as_is and not shown.get(CONF_SUMMARY_DELIVERIES) and supernotify_available(self.hass):
            shown[CONF_SUMMARY_DELIVERIES] = await email_deliveries(self.hass)
        await async_load_texts(self.hass)
        key_set = bool(self.config_entry.data.get(CONF_DVLA_API_KEY))
        return self.async_show_form(
            step_id=STEP_DISCOVERY,
            data_schema=self.add_suggested_values_to_schema(schema, sectioned(schema, shown)),
            errors=errors,
            # the key's never shown, so whether there's one is said instead
            description_placeholders={"dvla_key": text(self.hass, DVLA_KEY_SET if key_set else DVLA_KEY_UNSET)},
        )

    def _keep_credentials(self, settings: dict[str, Any]) -> None:
        """The DVLA's key kept in the entry's data, as Home Assistant has credentials, never in its options, and never
        shown again: one typed replaces it, none leaves it as it is, and *Forget the key* takes it away"""
        key = settings.pop(CONF_DVLA_API_KEY, None)
        forget = bool(settings.pop(CONF_DVLA_API_KEY_CLEAR, False))
        if not forget and not key:
            return
        data = {k: v for k, v in self.config_entry.data.items() if k != CONF_DVLA_API_KEY}
        if key and not forget:
            data[CONF_DVLA_API_KEY] = str(key)
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)

    async def _summary_undeliverable(self, user_input: dict[str, Any]) -> bool:
        """Whether the summary is switched on with no deliveries chosen, and Supernotify has no e-mail delivery to
        send it by instead, so it would never be delivered"""
        summary = user_input.get(SECTION_SUMMARY)
        if not isinstance(summary, dict) or summary.get(CONF_SUMMARY_MODE, SUMMARY_AUTO) == SUMMARY_OFF:
            return False
        return not summary.get(CONF_SUMMARY_DELIVERIES) and not await email_deliveries(self.hass)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            settings = {
                key: value
                for key, value in flattened(user_input).items()
                if (value or value is False or value == 0) and value != DEFAULTS.get(key)
            }
            if settings.get(CONF_ALPR_ENTITY) and not self.config_entry.options.get(CONF_ALPR_ENTITY):
                # for the ANPR/ALPR entity to read the snapshot notified, chosen as its source
                settings[CONF_LAST_SNAPSHOT] = True
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
        name = data[CONF_SOURCE_NAME]
        cameras = zone_cameras(config, name) if is_zone else [name]
        actions = offered([config], cameras)
        schema = await settings_schema(self.hass, labels, zones, genai, actions)
        await async_load_texts(self.hass)
        shown = dict(self.config_entry.options)
        if not is_zone:
            shown[CONF_LAST_SNAPSHOT] = wants_last_snapshot(self.config_entry)
        if CONF_ACTIONS in shown:
            shown[CONF_ACTIONS] = [kind for kind in shown[CONF_ACTIONS] if kind in actions]
        moving = [camera for camera in cameras if camera_autotracks(config, camera)]
        autotracking = f"\n\n{text(self.hass, AUTOTRACKING, cameras=', '.join(moving))}" if moving else ""
        return self.async_show_form(
            step_id=STEP_SETTINGS,
            data_schema=self.add_suggested_values_to_schema(schema, sectioned(schema, shown)),
            description_placeholders={
                "name": self.config_entry.title,
                "supernotify": await supernotify_status(self.hass),
                "proxy": await proxy_status(self.hass, data[CONF_SOURCE_ENTRY_ID]),
                "autotracking": autotracking,
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
