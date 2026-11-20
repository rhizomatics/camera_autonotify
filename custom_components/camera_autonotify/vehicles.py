"""Vehicles, for any source of plates: each plate read classified by the vehicle categories, its visit history kept,
and looked up with a vehicle register, the DVLA's to begin with, so Frigate's plates, anpr2mqtt's, or any other, are
treated the same, and anpr2mqtt needn't do it

The history and the lookups are kept in Home Assistant's own storage, so a restart loses neither. A lookup is cached,
the DVLA's for a day to begin with, and a plate the register doesn't know is cached as such too. Where it doesn't
know a plate, and it's within a character of the last plate it confirmed on the same camera, recently, it's taken as
that plate, a misread, as anpr2mqtt does.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DVLA_API_KEY,
    CONF_HISTORY_DAYS,
    CONF_LOOKUP_CACHE_HOURS,
    CONF_MIN_VISIT_GAP,
    CONF_VEHICLE_PRIORITIES,
    CONF_VEHICLE_SCENARIOS,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_LOOKUP_CACHE_HOURS,
    DEFAULT_MIN_VISIT_GAP,
    DOMAIN,
    EVENT_VEHICLE,
    SUBENTRY_PLATES,
    VEHICLE_RULE_PRIORITIES,
)
from .entries import global_settings
from .plates import KIND_IGNORED, KIND_KNOWN, Category, History, Match, PlateRegister, analyse, distance, normalised, visitor

if TYPE_CHECKING:
    from aiohttp import ClientSession

_LOGGER = logging.getLogger(__name__)

KIND_UNREADABLE = "unreadable"

DATA_VEHICLES = "vehicles"
STORE_VERSION = 1
DVLA_URL = "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"
ISSUE_LOOKUP_REFUSED = "lookup_refused"
# a review's plate is counted once, however many notifications it has
RECORDED_FOR = 3600


class LookupRefused(Exception):
    """The register refused the key"""


@dataclass(frozen=True)
class VehicleLookup:
    """What a vehicle register knows of a plate, in a schema common to every register, with what it gave as it came"""

    source: str
    make: str | None = None
    colour: str | None = None
    year: int | None = None
    fuel: str | None = None
    tax: str | None = None
    inspection: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def said(self) -> str:
        return ", ".join(str(v) for v in (self.make, self.colour, self.year, self.tax) if v)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "make": self.make,
            "colour": self.colour,
            "year": self.year,
            "fuel": self.fuel,
            "tax": self.tax,
            "inspection": self.inspection,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VehicleLookup:
        return cls(
            source=str(data.get("source") or ""),
            make=data.get("make"),
            colour=data.get("colour"),
            year=data.get("year"),
            fuel=data.get("fuel"),
            tax=data.get("tax"),
            inspection=data.get("inspection"),
            raw=data.get("raw") or {},
        )


class LookupProvider(Protocol):
    """A country's or region's vehicle register"""

    name: str

    async def async_lookup(self, plate: str) -> VehicleLookup | None:
        """What it knows of a plate, or nothing when it doesn't know it, raising LookupRefused for a refused key"""
        ...


class DvlaProvider:
    """The UK's DVLA, by its Vehicle Enquiry Service"""

    name = "dvla"

    def __init__(self, session: ClientSession, api_key: str) -> None:
        self.session = session
        self.api_key = api_key

    async def async_lookup(self, plate: str) -> VehicleLookup | None:
        async with self.session.post(
            DVLA_URL,
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
            json={"registrationNumber": plate},
        ) as response:
            if response.status == 404:
                return None
            if response.status in (401, 403):
                raise LookupRefused
            response.raise_for_status()
            found: dict[str, Any] = await response.json()
        year = found.get("yearOfManufacture")
        return VehicleLookup(
            source=self.name,
            make=found.get("make"),
            colour=found.get("colour"),
            year=int(year) if isinstance(year, int | str) and str(year).isdigit() else None,
            fuel=found.get("fuelType"),
            tax=found.get("taxStatus"),
            inspection=found.get("motStatus"),
            raw=found,
        )


@dataclass(frozen=True)
class Vehicle:
    """A plate read, classified, with its history and what its register knows"""

    match: Match
    history: History = field(default_factory=History)
    lookup: VehicleLookup | None = None

    @property
    def kind(self) -> str:
        return self.match.kind

    @property
    def plate(self) -> str:
        return self.match.plate

    def as_dict(self) -> dict[str, Any]:
        category = self.match.category
        return {
            "plate": self.plate,
            "read": self.match.read,
            "kind": self.kind,
            "category": category.name if category else None,
            "description": self.match.description,
            "icon": category.icon if category else None,
            "history": self.history.as_dict(),
            "lookup": self.lookup.as_dict() if self.lookup else None,
        }


@dataclass(frozen=True)
class VehicleOutcome:
    """What the pre-defined vehicle rules make of a vehicle: a priority and scenarios, or silence for the ignored"""

    priority: str | None = None
    silence: bool = False
    scenarios: tuple[str, ...] = ()


def vehicle_outcome(options: dict[str, Any], vehicle: Vehicle | None) -> VehicleOutcome:
    """The pre-defined rule for the vehicle's kind, its condition fixed, its priority and scenarios as set, a vehicle
    with no plate read being unreadable"""
    if vehicle is not None and vehicle.kind == KIND_IGNORED:
        return VehicleOutcome(silence=True)
    kind = vehicle.kind if vehicle is not None else KIND_UNREADABLE
    priority = options.get(CONF_VEHICLE_PRIORITIES[kind]) or VEHICLE_RULE_PRIORITIES[kind]
    return VehicleOutcome(priority, False, tuple(options.get(CONF_VEHICLE_SCENARIOS[kind]) or ()))


class Vehicles:
    """Classifying, history and lookups, one for Home Assistant, set from the global settings as each is asked"""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._history_store: Store[dict[str, list[str]]] = Store(hass, STORE_VERSION, f"{DOMAIN}.plate_history")
        self._lookup_store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, f"{DOMAIN}.plate_lookup")
        self._history: dict[str, list[str]] | None = None
        self._lookups: dict[str, Any] | None = None
        # the last plate the register confirmed on each camera, and when
        self._confirmed: dict[str, tuple[str, datetime]] = {}
        # reviews whose plate is already counted, and when
        self._recorded: dict[str, float] = {}
        self.provider: LookupProvider | None = None

    @property
    def options(self) -> dict[str, Any]:
        entry = global_settings(self.hass)
        return dict(entry.options) if entry else {}

    @callback
    def register(self) -> PlateRegister:
        entry = global_settings(self.hass)
        if entry is None:
            return PlateRegister()
        return PlateRegister([
            Category.from_data(subentry.title, dict(subentry.data))
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_PLATES
        ])

    def _provider(self) -> LookupProvider | None:
        if self.provider is not None:
            return self.provider
        entry = global_settings(self.hass)
        # a credential, so kept in the entry's data, not its options, as Home Assistant has it
        key = entry.data.get(CONF_DVLA_API_KEY) if entry else None
        return DvlaProvider(async_get_clientsession(self.hass), str(key)) if key else None

    async def _async_load(self) -> None:
        if self._history is None:
            self._history = await self._history_store.async_load() or {}
        if self._lookups is None:
            self._lookups = await self._lookup_store.async_load() or {}

    def sightings(self, plate: str) -> list[datetime]:
        found = [dt_util.parse_datetime(seen) for seen in (self._history or {}).get(plate, [])]
        zone = dt_util.get_default_time_zone()
        # anpr2mqtt's may have no time zone, being its own local time
        return sorted(dt_util.as_local(seen if seen.tzinfo else seen.replace(tzinfo=zone)) for seen in found if seen)

    async def async_classify(
        self,
        read: str,
        camera: str | None = None,
        record: bool = False,
        now: datetime | None = None,
        source: str | None = None,
        entity_id: str | None = None,
        confidence: float | None = None,
    ) -> Vehicle:
        """A plate read, corrected, classified, looked up where its category says, or it's in none, and its history,
        counted as a sighting only when asked, when it's also fired as an event"""
        await self._async_load()
        now = dt_util.as_local(now or dt_util.now())
        options = self.options
        register = self.register()
        match = register.match(read)
        if match.kind == KIND_IGNORED:
            return Vehicle(match)
        lookup: VehicleLookup | None = None
        if match.category is None or match.category.lookup:
            lookup, match = await self._async_lookup(match, register, camera, now, options)
        history = analyse(self.sightings(match.plate), now, float(options.get(CONF_MIN_VISIT_GAP, DEFAULT_MIN_VISIT_GAP)))
        if record and history.is_new_visit:
            self._record(match.plate, now, options)
        vehicle = Vehicle(match, history, lookup)
        if record:
            self.hass.bus.async_fire(
                EVENT_VEHICLE,
                {
                    # as OpenALPR's `image_processing.found_plate`, so what's written for it reads this the same
                    "plate": vehicle.plate,
                    "entity_id": entity_id,
                    "confidence": confidence,
                    "camera": camera,
                    "source": source,
                    **vehicle.as_dict(),
                },
            )
        return vehicle

    async def _async_lookup(
        self, match: Match, register: PlateRegister, camera: str | None, now: datetime, options: dict[str, Any]
    ) -> tuple[VehicleLookup | None, Match]:
        lookup = await self._async_cached_lookup(match.plate, now, options)
        ttl = timedelta(hours=float(options.get(CONF_LOOKUP_CACHE_HOURS, DEFAULT_LOOKUP_CACHE_HOURS)))
        if lookup is None and camera and (confirmed := self._confirmed.get(camera)):
            good, when = confirmed
            if now - when <= ttl and good != match.plate and distance(good, match.plate) <= 1:
                _LOGGER.debug("CAMERA_AUTONOTIFY Correcting %s to %s, last confirmed on %s", match.plate, good, camera)
                corrected = register.match(good)
                return await self._async_cached_lookup(good, now, options), replace(corrected, read=match.read)
        if lookup is not None and camera:
            self._confirmed[camera] = (match.plate, now)
        return lookup, match

    async def _async_cached_lookup(self, plate: str, now: datetime, options: dict[str, Any]) -> VehicleLookup | None:
        provider = self._provider()
        if provider is None or self._lookups is None:
            return None
        ttl = timedelta(hours=float(options.get(CONF_LOOKUP_CACHE_HOURS, DEFAULT_LOOKUP_CACHE_HOURS)))
        cached = self._lookups.get(f"{provider.name}:{plate}")
        if cached and (when := dt_util.parse_datetime(cached.get("at", ""))) and now - when <= ttl:
            return VehicleLookup.from_dict(cached["found"]) if cached.get("found") else None
        try:
            found = await provider.async_lookup(plate)
        except LookupRefused:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_LOOKUP_REFUSED,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_LOOKUP_REFUSED,
                translation_placeholders={"provider": provider.name.upper()},
            )
            return None
        except Exception as error:
            _LOGGER.warning("CAMERA_AUTONOTIFY %s couldn't look up %s: %s", provider.name, plate, error)
            return None
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_LOOKUP_REFUSED)
        self._lookups[f"{provider.name}:{plate}"] = {"at": now.isoformat(), "found": found.as_dict() if found else None}
        self._lookup_store.async_delay_save(lambda: self._lookups or {}, 10)
        return found

    def _record(self, plate: str, now: datetime, options: dict[str, Any]) -> None:
        if self._history is None:
            return
        keep = timedelta(days=float(options.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)))
        kept = [seen for seen in self.sightings(plate) if now - seen <= keep]
        self._history[plate] = [seen.isoformat() for seen in [*kept, now]]
        self._history_store.async_delay_save(lambda: self._history or {}, 10)

    def first_time_for(self, key: str, now: float) -> bool:
        """Whether a review's plate is yet to be counted, so it's counted once however many notifications it has"""
        for old in [k for k, when in self._recorded.items() if now - when > RECORDED_FOR]:
            del self._recorded[old]
        if key in self._recorded:
            return False
        self._recorded[key] = now
        return True

    @callback
    def add_plate(
        self, category: str, plate: str, description: str | None = None, corrections: list[str] | None = None
    ) -> bool:
        """A plate added to a category, made, as known, if it isn't there, returning whether it was new"""
        entry = global_settings(self.hass)
        if entry is None:
            return False
        item: dict[str, Any] = {"plate": plate}
        if description:
            item["description"] = description
        if corrections:
            item["corrections"] = list(corrections)
        existing = next(
            (s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_PLATES and s.title == category), None
        )
        if existing is None:
            self.hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=MappingProxyType({"kind": KIND_KNOWN, "plates": [item]}),
                    subentry_type=SUBENTRY_PLATES,
                    title=category,
                    unique_id=None,
                ),
            )
            return True
        plates = list(existing.data.get("plates") or [])
        if any(normalised(str(p.get("plate") if isinstance(p, dict) else p)) == normalised(plate) for p in plates):
            return False
        self.hass.config_entries.async_update_subentry(entry, existing, data={**existing.data, "plates": [*plates, item]})
        return True

    @callback
    def remove_plate(self, plate: str, category: str | None = None) -> int:
        """A plate taken out of every category, or the one given, returning from how many"""
        entry = global_settings(self.hass)
        if entry is None:
            return 0
        removed = 0
        for subentry in list(entry.subentries.values()):
            if subentry.subentry_type != SUBENTRY_PLATES or (category and subentry.title != category):
                continue
            plates = list(subentry.data.get("plates") or [])
            kept = [p for p in plates if normalised(str(p.get("plate") if isinstance(p, dict) else p)) != normalised(plate)]
            if len(kept) != len(plates):
                removed += 1
                self.hass.config_entries.async_update_subentry(entry, subentry, data={**subentry.data, "plates": kept})
        return removed

    @callback
    def categories(self, name: str | None = None) -> list[dict[str, Any]]:
        """Every vehicle category, or the one named, with its plates"""
        return [
            {
                "name": category.name,
                "kind": category.kind,
                "ignore": category.ignore,
                "lookup": category.lookup,
                **{key: value for key in ("description", "icon") if (value := getattr(category, key))},
                "plates": [
                    {
                        "plate": entry.plate,
                        **({"description": entry.description} if entry.description else {}),
                        **({"corrections": list(entry.corrections)} if entry.corrections else {}),
                    }
                    for entry in category.plates
                ],
            }
            for category in self.register().categories
            if name is None or category.name == name
        ]

    async def async_sightings(self, plate: str | None = None) -> list[dict[str, Any]]:
        """Every plate seen, or the one given, with when, and how regularly it's seen"""
        await self._async_load()
        now = dt_util.now()
        wanted = normalised(plate) if plate else None
        found = []
        for seen in sorted(self._history or {}):
            if wanted is not None and seen != wanted:
                continue
            times = self.sightings(seen)
            found.append({
                "plate": seen,
                "count": len(times),
                "last_seen": times[-1].isoformat() if times else None,
                "visitor": visitor(times, now),
                "sightings": [t.isoformat() for t in times],
            })
        return found

    async def async_import_history(self, sightings: dict[str, list[str]]) -> int:
        """Sightings from elsewhere, such as anpr2mqtt's tracker, merged with those here, returning how many were new"""
        await self._async_load()
        if self._history is None:
            return 0
        added = 0
        for plate, times in sightings.items():
            known = set(self._history.get(plate, []))
            new = [t for t in times if t not in known and dt_util.parse_datetime(t) is not None]
            if new:
                self._history[plate] = sorted([*known, *new])
                added += len(new)
        self._history_store.async_delay_save(lambda: self._history or {}, 10)
        return added


@callback
def vehicles(hass: HomeAssistant) -> Vehicles:
    data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    if DATA_VEHICLES not in data:
        data[DATA_VEHICLES] = Vehicles(hass)
    return data[DATA_VEHICLES]
