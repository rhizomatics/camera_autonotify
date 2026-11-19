"""Importing from anpr2mqtt: its plate targets as vehicle categories, its corrections and ignores, its DVLA settings
and its tracker's visit history, from an archive of its `config` and `data` folders uploaded in *Global Settings* or
as an anpr2mqtt source is set up, since anpr2mqtt usually runs on another server, out of Home Assistant's reach"""

from __future__ import annotations

import json
import logging
import tarfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.yaml import parse_yaml

from .const import CONF_DVLA_API_KEY, CONF_LOOKUP_CACHE_HOURS, CONF_MIN_VISIT_GAP, SUBENTRY_PLATES
from .plates import KIND_DANGEROUS, KIND_KNOWN, normalised
from .vehicles import vehicles

if TYPE_CHECKING:
    from pathlib import Path

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

IGNORED_CATEGORY = "Ignored reads"
# what the upload takes, a tar archive, compressed or not
ARCHIVE_ACCEPT = ".tar,.tar.gz,.tgz"
# anpr2mqtt's own name for its config, as in `/config/anpr2mqtt.yaml`, and the older name
CONFIG_FILES = ("anpr2mqtt.yaml", "config.yaml")
# anpr2mqtt's tracker folder for plates, `data_dir/plate`, a file for each plate, or its data folder itself
HISTORY_FOLDERS = ("plate", "data")
# the tracker's file for sightings with no plate read
UNKNOWN_PLATE = "UNKNOWN"
# larger than any config or plate's history, so anything bigger isn't read
MAX_FILE_SIZE = 5 * 1024 * 1024


class ArchiveUnreadable(Exception):
    """Not a tar archive, or none of anpr2mqtt's config in it"""


@dataclass
class Imported:
    """What anpr2mqtt has, as categories by name, the global settings it sets, its plates' sightings, and what can't
    be imported"""

    categories: dict[str, dict[str, Any]] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    history: dict[str, list[str]] = field(default_factory=dict)
    not_imported: list[str] = field(default_factory=list)


@dataclass
class Added:
    """What an import added, those already here not counted"""

    categories: int = 0
    plates: int = 0
    sightings: int = 0
    settings: list[str] = field(default_factory=list)


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


def from_anpr2mqtt(config: dict[str, Any]) -> Imported:
    """anpr2mqtt's config as categories, settings, and what can't be imported"""
    targets = ((config.get("targets") or {}).get("plate")) or {}
    found = Imported()
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
            found.not_imported.append(f"priority {group['priority']} of {name}, set by the vehicle rules instead")
        found.categories[name] = data
    # the older style, corrections for the plate corrected to, wherever it is
    for plate, reads in (targets.get("correction") or {}).items():
        entry = next(
            (p for c in found.categories.values() for p in c["plates"] if normalised(p["plate"]) == normalised(str(plate))),
            None,
        )
        if entry is None:
            found.not_imported.append(f"corrections to {plate}, in no category")
            continue
        entry["corrections"] = [*entry.get("corrections", []), *(str(r) for r in reads or [])]
    if ignore := [str(pattern) for pattern in targets.get("ignore") or []]:
        found.categories[IGNORED_CATEGORY] = {
            "kind": KIND_KNOWN,
            "ignore": True,
            "plates": [{"plate": p} for p in ignore],
        }
    dvla = config.get("dvla") or {}
    if dvla.get("api_key"):
        found.settings[CONF_DVLA_API_KEY] = str(dvla["api_key"])
    if dvla.get("cache_ttl"):
        found.settings[CONF_LOOKUP_CACHE_HOURS] = max(1, round(int(dvla["cache_ttl"]) / 3600))
    gap = (config.get("tracker") or {}).get("min_visit_gap_seconds")
    if gap is not None:
        found.settings[CONF_MIN_VISIT_GAP] = int(gap)
    return found


def read_archive(path: Path) -> Imported:
    """anpr2mqtt's `anpr2mqtt.yaml` and its tracker's plate files, wherever they are in a tar archive, read from it
    without unpacking anything, so nothing in the archive is written anywhere"""
    config: Any = None
    history: dict[str, list[str]] = {}
    try:
        with tarfile.open(path) as archive:
            for member in archive:
                if not member.isfile() or member.size > MAX_FILE_SIZE:
                    continue
                parts = PurePosixPath(member.name).parts
                # macOS's tar adds `._` files of its own metadata beside each file, binary whatever their name
                if parts[-1].startswith("._"):
                    continue
                is_config = parts[-1] in CONFIG_FILES and config is None
                is_history = (
                    len(parts) > 1
                    and parts[-2] in HISTORY_FOLDERS
                    and parts[-1].endswith(".json")
                    and PurePosixPath(parts[-1]).stem.upper() != UNKNOWN_PLATE
                )
                if not is_config and not is_history:
                    continue
                file = archive.extractfile(member)
                raw = file.read() if file is not None else b""
                try:
                    content = raw.decode()
                except UnicodeDecodeError:
                    if is_config:
                        raise
                    # a plate's file that isn't text is skipped, not the whole archive
                    continue
                if is_config:
                    config = parse_yaml(content)
                    continue
                try:
                    times = json.loads(content)
                except ValueError:
                    continue
                if isinstance(times, list):
                    history[normalised(PurePosixPath(parts[-1]).stem)] = [str(t) for t in times]
    except (tarfile.TarError, OSError, UnicodeDecodeError, HomeAssistantError) as error:
        raise ArchiveUnreadable(str(error)) from error
    if not isinstance(config, dict):
        raise ArchiveUnreadable(f"no {' or '.join(CONFIG_FILES)} in the archive")
    found = from_anpr2mqtt(config)
    found.history = history
    return found


def new_plates(entry: ConfigEntry, found: Imported) -> dict[str, tuple[int, bool]]:
    """How many plates of each category are new, and whether the category is already here"""
    existing = {s.title: s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_PLATES}
    counts: dict[str, tuple[int, bool]] = {}
    for name, data in found.categories.items():
        have = existing.get(name)
        known = {normalised(p["plate"]) for p in (have.data.get("plates") or [])} if have else set()
        counts[name] = (sum(1 for p in data["plates"] if normalised(p["plate"]) not in known), have is not None)
    return counts


async def async_import(hass: HomeAssistant, entry: ConfigEntry, found: Imported) -> Added:
    """Into the global settings: new categories added, new plates added to those already here, the DVLA's key kept
    in the entry's data, as Home Assistant has credentials, the other settings in its options, and the visit history
    merged with that here, returning what was added"""
    added = Added(settings=list(found.settings))
    existing = {s.title: s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_PLATES}
    for name, data in found.categories.items():
        have = existing.get(name)
        if have is None:
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(data=MappingProxyType(data), subentry_type=SUBENTRY_PLATES, title=name, unique_id=None),
            )
            added.categories += 1
            added.plates += len(data["plates"])
            continue
        known = {normalised(p["plate"]) for p in (have.data.get("plates") or [])}
        if new := [p for p in data["plates"] if normalised(p["plate"]) not in known]:
            hass.config_entries.async_update_subentry(
                entry, have, data={**have.data, "plates": [*(have.data.get("plates") or []), *new]}
            )
            added.plates += len(new)
    key = found.settings.get(CONF_DVLA_API_KEY)
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_DVLA_API_KEY: key} if key else dict(entry.data),
        options={**entry.options, **imported_options(found)},
    )
    added.sightings = await vehicles(hass).async_import_history(found.history)
    _LOGGER.info(
        "CAMERA_AUTONOTIFY Imported from anpr2mqtt: %s categories, %s plates, %s sightings, settings %s",
        added.categories,
        added.plates,
        added.sightings,
        added.settings,
    )
    return added


def imported_options(found: Imported) -> dict[str, Any]:
    """The settings imported that are options, the DVLA's key being kept in the entry's data instead"""
    return {key: value for key, value in found.settings.items() if key != CONF_DVLA_API_KEY}
