"""Home Assistant actions: classifying a plate, for any other source of plates or an automation, and importing
vehicles and their history from anpr2mqtt"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util.yaml import load_yaml

from .compat import vol
from .const import (
    CONF_DVLA_API_KEY,
    CONF_LOOKUP_CACHE_HOURS,
    CONF_MIN_VISIT_GAP,
    DOMAIN,
    SUBENTRY_PLATES,
)
from .entries import global_settings
from .plates import KIND_DANGEROUS, KIND_KNOWN, normalised
from .vehicles import vehicles

_LOGGER = logging.getLogger(__name__)

SERVICE_CLASSIFY = "classify_plate"
SERVICE_IMPORT = "import_anpr2mqtt"
SERVICE_ADD = "add_plate"
SERVICE_REMOVE = "remove_plate"
IGNORED_CATEGORY = "Ignored reads"

CLASSIFY_SCHEMA = vol.Schema({
    vol.Required("plate"): cv.string,
    vol.Optional("camera"): cv.string,
    vol.Optional("record_sighting", default=False): cv.boolean,
})
ADD_SCHEMA = vol.Schema({
    vol.Required("category"): cv.string,
    vol.Required("plate"): cv.string,
    vol.Optional("description"): cv.string,
    vol.Optional("corrections"): vol.All(cv.ensure_list, [cv.string]),
})
REMOVE_SCHEMA = vol.Schema({vol.Required("plate"): cv.string, vol.Optional("category"): cv.string})
IMPORT_SCHEMA = vol.Schema({
    vol.Required("config_path"): cv.string,
    vol.Optional("history_path"): cv.string,
    vol.Optional("dry_run", default=True): cv.boolean,
})


def _members(members: object) -> list[dict[str, Any]]:
    """anpr2mqtt's group members, each a plate, or a mapping with its `id`, as plates of a category"""
    plates: list[dict[str, Any]] = []
    for member in members if isinstance(members, list) else []:
        if isinstance(member, str | int):
            plates.append({"plate": str(member)})
        elif isinstance(member, dict) and member.get("id"):
            corrections = member.get("correction") or []
            plates.append({
                "plate": str(member["id"]),
                **({"description": str(member["description"])} if member.get("description") else {}),
                **({"corrections": [str(c) for c in corrections]} if corrections else {}),
            })
    return plates


def from_anpr2mqtt(config: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[str]]:
    """anpr2mqtt's config as categories by name, the global settings it sets, and what can't be imported"""
    targets = ((config.get("targets") or {}).get("plate")) or {}
    categories: dict[str, dict[str, Any]] = {}
    not_imported: list[str] = []
    groups = list(targets.get("groups") or [])
    # the older style, `known` and `dangerous` as plates to descriptions
    for name in (KIND_KNOWN, KIND_DANGEROUS):
        if isinstance(old := targets.get(name), dict) and old:
            groups.append({"name": name, "members": [{"id": k, "description": v} for k, v in old.items()]})
    for group in groups:
        if not isinstance(group, dict) or not group.get("name"):
            continue
        name = str(group["name"])
        data: dict[str, Any] = {
            "kind": KIND_DANGEROUS if name.lower() == KIND_DANGEROUS else KIND_KNOWN,
            "plates": _members(group.get("members")),
            "lookup": bool(group.get("lookup", False)),
        }
        for key in ("icon", "entity_id"):
            if group.get(key):
                data[key] = str(group[key])
        if group.get("priority"):
            not_imported.append(f"priority {group['priority']} of {name}, priority being set by the vehicle rules")
        categories[name] = data
    # the older style, corrections for the plate corrected to, wherever it is
    for plate, reads in (targets.get("correction") or {}).items():
        entry = next(
            (p for c in categories.values() for p in c["plates"] if normalised(p["plate"]) == normalised(str(plate))), None
        )
        if entry is None:
            not_imported.append(f"corrections to {plate}, in no category")
            continue
        entry["corrections"] = [*entry.get("corrections", []), *(str(r) for r in reads or [])]
    if ignore := [str(pattern) for pattern in targets.get("ignore") or []]:
        categories[IGNORED_CATEGORY] = {"kind": KIND_KNOWN, "ignore": True, "plates": [{"plate": p} for p in ignore]}
    settings: dict[str, Any] = {}
    dvla = config.get("dvla") or {}
    if dvla.get("api_key"):
        settings[CONF_DVLA_API_KEY] = str(dvla["api_key"])
    if dvla.get("cache_ttl"):
        settings[CONF_LOOKUP_CACHE_HOURS] = max(1, round(int(dvla["cache_ttl"]) / 3600))
    gap = (config.get("tracker") or {}).get("min_visit_gap_seconds")
    if gap is not None:
        settings[CONF_MIN_VISIT_GAP] = int(gap)
    return categories, settings, not_imported


def _read_history(folder: Path) -> dict[str, list[str]]:
    """anpr2mqtt's tracker history, a file for each plate, of the times it was seen"""
    found: dict[str, list[str]] = {}
    for file in sorted(folder.glob("*.json")):
        try:
            times = json.loads(file.read_text())
        except ValueError, OSError:
            continue
        if isinstance(times, list):
            found[normalised(file.stem)] = [str(t) for t in times]
    return found


@callback
def async_register_services(hass: HomeAssistant) -> None:
    async def classify(call: ServiceCall) -> ServiceResponse:
        vehicle = await vehicles(hass).async_classify(
            call.data["plate"], call.data.get("camera"), record=call.data["record_sighting"]
        )
        return vehicle.as_dict()

    async def import_anpr2mqtt(call: ServiceCall) -> ServiceResponse:
        entry = global_settings(hass)
        if entry is None:
            raise ServiceValidationError("Set up Camera AutoNotify's Global Settings first")
        path = Path(hass.config.path(call.data["config_path"]))
        try:
            config = await hass.async_add_executor_job(load_yaml, str(path))
        except (OSError, HomeAssistantError) as error:
            raise ServiceValidationError(f"Can't read {path}: {error}") from error
        categories, settings, not_imported = from_anpr2mqtt(config if isinstance(config, dict) else {})
        history: dict[str, list[str]] = {}
        if call.data.get("history_path"):
            folder = Path(hass.config.path(call.data["history_path"]))
            history = await hass.async_add_executor_job(_read_history, folder)
        existing = {s.title: s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_PLATES}
        summary: list[dict[str, Any]] = []
        for name, data in categories.items():
            have = existing.get(name)
            known = {normalised(p["plate"]) for p in (have.data.get("plates") or [])} if have else set()
            new = [p for p in data["plates"] if normalised(p["plate"]) not in known]
            summary.append({"category": name, "new_plates": len(new), "existing": have is not None})
            if call.data["dry_run"] or (have and not new):
                continue
            if have is None:
                hass.config_entries.async_add_subentry(
                    entry,
                    ConfigSubentry(data=MappingProxyType(data), subentry_type=SUBENTRY_PLATES, title=name, unique_id=None),
                )
            else:
                merged = {**have.data, "plates": [*have.data.get("plates", []), *new]}
                hass.config_entries.async_update_subentry(entry, have, data=merged)
        added = 0
        if not call.data["dry_run"]:
            key = settings.get(CONF_DVLA_API_KEY)
            options = {k: v for k, v in settings.items() if k != CONF_DVLA_API_KEY}
            # the key kept in the entry's data, as Home Assistant has credentials
            data = {**entry.data, CONF_DVLA_API_KEY: key} if key else dict(entry.data)
            hass.config_entries.async_update_entry(entry, data=data, options={**entry.options, **options})
            added = await vehicles(hass).async_import_history(history)
        response: dict[str, Any] = {
            "dry_run": call.data["dry_run"],
            "categories": summary,
            "settings": sorted(key for key in settings if key != CONF_DVLA_API_KEY)
            + ([CONF_DVLA_API_KEY] if CONF_DVLA_API_KEY in settings else []),
            "history": {"plates": len(history), "sightings_added": added},
            "not_imported": not_imported,
        }
        return cast("ServiceResponse", response)

    @callback
    def add_plate(call: ServiceCall) -> ServiceResponse:
        added = vehicles(hass).add_plate(
            call.data["category"], call.data["plate"], call.data.get("description"), call.data.get("corrections")
        )
        return {"added": added}

    @callback
    def remove_plate(call: ServiceCall) -> ServiceResponse:
        return {"categories": vehicles(hass).remove_plate(call.data["plate"], call.data.get("category"))}

    hass.services.async_register(DOMAIN, SERVICE_CLASSIFY, classify, CLASSIFY_SCHEMA, SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, SERVICE_ADD, add_plate, ADD_SCHEMA, SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE, remove_plate, REMOVE_SCHEMA, SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_IMPORT, import_anpr2mqtt, IMPORT_SCHEMA, SupportsResponse.ONLY)
