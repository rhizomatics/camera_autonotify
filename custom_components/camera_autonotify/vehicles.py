"""Vehicles, for any source of plates: each plate read classified by the vehicle categories, its visit history kept,
and looked up with a vehicle register, the DVLA's to begin with, so Frigate's plates, anpr2mqtt's, or any other, are
treated the same, and anpr2mqtt needn't do it

The history and the lookups are kept in Home Assistant's own storage, by the object tracker, plates being one kind of
object it tracks, so a restart loses neither, and never by the plate itself. A lookup is cached,
the DVLA's for a day to begin with, and a plate the register doesn't know is cached as such too. Where it doesn't
know a plate, and it's within a character of the last plate it confirmed on the same camera, recently, it's taken as
that plate, a misread, as anpr2mqtt does.
"""

from __future__ import annotations

import logging
import re
import secrets
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
    CONF_TRACK_VISITS,
    CONF_VEHICLE_EVENTS,
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
from .objects import KIND_PLATE, ObjectTracker, Sighting
from .plates import KIND_IGNORED, KIND_KNOWN, Category, History, Match, PlateRegister, analyse, distance, normalised, redacted

if TYPE_CHECKING:
    from aiohttp import ClientResponse, ClientSession

_LOGGER = logging.getLogger(__name__)

KIND_UNREADABLE = "unreadable"

DATA_VEHICLES = "vehicles"
STORE_VERSION = 1
DVLA_URL = "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"
ISSUE_LOOKUP_REFUSED = "lookup_refused"
# the betas' stores, by plate or by a salted hash of it, the history moved into the tracker, the lookups, only a
# cache, dropped. Only for those betas, so to be removed in the release after 1.0.0
BETA_HISTORY = "plate_history"
BETA_LOOKUP = "plate_lookup"
HASHED = re.compile(r"^[0-9a-f]{64}$")
# the DVLA's own field for the plate, left out of what's kept of a lookup
DVLA_PLATE = "registrationNumber"
# a review's plate is counted once, however many notifications it has
RECORDED_FOR = 3600


# a plate made up to check the DVLA's key with, either known or not, both answers meaning the key works
DVLA_TEST_PLATE = "A123TST"
# a register's answers to a key it refuses
REFUSED = (401, 403)


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


@dataclass(frozen=True)
class LookupResult:
    """How a lookup went: what was found, if anything, the status the register gave and any error it said, whether
    it came from the cache, or that it was skipped, the plate's category not being looked up"""

    source: str | None = None
    status: int | None = None
    error: str | None = None
    found: VehicleLookup | None = None
    cached: bool = False
    skipped: bool = False
    # when a cached answer was retrieved from the register
    retrieved: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.skipped:
            return {"skipped": True}
        return {
            **(self.found.as_dict() if self.found else {"source": self.source}),
            "status": self.status,
            "error": self.error,
            "cached": self.cached,
            **({"retrieved": self.retrieved.isoformat()} if self.cached and self.retrieved else {}),
        }


class LookupProvider(Protocol):
    """A country's or region's vehicle register"""

    name: str

    async def async_lookup(self, plate: str) -> LookupResult:
        """What it knows of a plate, with the status it gave, raising only where it couldn't be asked at all"""
        ...


class DvlaProvider:
    """The UK's DVLA, by its Vehicle Enquiry Service"""

    name = "dvla"

    def __init__(self, session: ClientSession, api_key: str) -> None:
        self.session = session
        self.api_key = api_key

    async def _async_post(self, plate: str) -> tuple[int, object, str | None]:
        """The status, the JSON body, if any, and the error the DVLA said, logged, the plate redacted"""
        async with self.session.post(
            DVLA_URL,
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
            json={"registrationNumber": plate},
        ) as response:
            body = await _json_body(response)
        error = _dvla_error(body) if response.status >= 400 else None
        _LOGGER.info(
            "CAMERA_AUTONOTIFY DVLA lookup of %s: %s%s", redacted(plate), response.status, f" {error}" if error else ""
        )
        return response.status, body, error

    async def async_lookup(self, plate: str) -> LookupResult:
        status, body, error = await self._async_post(plate)
        if status != 200 or not isinstance(body, dict):
            return LookupResult(self.name, status, error or (None if status == 200 else f"HTTP {status}"))
        year = body.get("yearOfManufacture")
        found = VehicleLookup(
            source=self.name,
            make=body.get("make"),
            colour=body.get("colour"),
            year=int(year) if isinstance(year, int | str) and str(year).isdigit() else None,
            fuel=body.get("fuelType"),
            tax=body.get("taxStatus"),
            inspection=body.get("motStatus"),
            raw={key: value for key, value in body.items() if key != DVLA_PLATE},
        )
        return LookupResult(self.name, status, found=found)

    async def async_test(self) -> tuple[bool, int | None, str | None]:
        """Whether the key works, by a made up plate answered with JSON and 200 or 404, with the status and error"""
        try:
            status, body, error = await self._async_post(DVLA_TEST_PLATE)
        except Exception as failure:
            return False, None, str(failure) or type(failure).__name__
        if not isinstance(body, dict):
            return False, status, error or "No JSON in the response"
        return status in (200, 404), status, error


async def _json_body(response: ClientResponse) -> object:
    """A response's JSON, or nothing where it has none, as an error from a gateway in front of the register may not"""
    try:
        return await response.json(content_type=None)
    except ValueError:
        return None


def _dvla_error(body: object) -> str | None:
    """The DVLA's error, from its `errors` list, or a gateway's `message`"""
    if not isinstance(body, dict):
        return None
    errors = body.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        said = [str(errors[0][key]) for key in ("title", "detail") if errors[0].get(key)]
        return ": ".join(said) or None
    return str(body["message"]) if body.get("message") else None


@dataclass(frozen=True)
class Vehicle:
    """A plate read, classified, with its history and what its register knows"""

    match: Match
    history: History = field(default_factory=History)
    # none where there's no register to look up with at all
    looked_up: LookupResult | None = None

    @property
    def lookup(self) -> VehicleLookup | None:
        return self.looked_up.found if self.looked_up else None

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
            "lookup": self.looked_up.as_dict() if self.looked_up else None,
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
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, f"{DOMAIN}.tracker")
        # this installation's own secret, salting each object's key
        self._salt_store: Store[dict[str, str]] = Store(hass, STORE_VERSION, f"{DOMAIN}.plate_salt")
        self._tracker: ObjectTracker | None = None
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

    async def _async_load(self) -> ObjectTracker:
        if self._tracker is None:
            stored = await self._salt_store.async_load() or {}
            if not stored.get("salt"):
                # saved before anything is kept by it, since without it nothing kept could be found again
                stored = {"salt": secrets.token_hex(32)}
                await self._salt_store.async_save(stored)
            tracker = ObjectTracker(bytes.fromhex(stored["salt"]), await self._store.async_load())
            await self._async_migrate_beta(tracker)
            if self._tracker is None:
                self._tracker = tracker
        self._prune()
        return self._tracker

    async def _async_migrate_beta(self, tracker: ObjectTracker) -> None:
        """The betas' visit history moved into the tracker, and their stores removed. Only for those betas, so to be
        removed in the release after 1.0.0"""
        history_store: Store[dict[str, list[str]]] = Store(self.hass, STORE_VERSION, f"{DOMAIN}.{BETA_HISTORY}")
        history = await history_store.async_load()
        if history is None:
            return
        zone = dt_util.get_default_time_zone()
        moved = 0
        for plate, times in history.items():
            key = plate if HASHED.match(plate) else tracker.key(KIND_PLATE, normalised(plate))
            parsed = [seen for seen in (dt_util.parse_datetime(str(t)) for t in times or []) if seen is not None]
            # anpr2mqtt's may have no time zone, being its own local time
            moved += tracker.merge_key(
                key, KIND_PLATE, [Sighting(round((s if s.tzinfo else s.replace(tzinfo=zone)).timestamp())) for s in parsed]
            )
        await self._store.async_save(tracker.as_dict())
        await history_store.async_remove()
        await Store[dict[str, Any]](self.hass, STORE_VERSION, f"{DOMAIN}.{BETA_LOOKUP}").async_remove()
        _LOGGER.info(
            "CAMERA_AUTONOTIFY Visit history of %s plates, %s sightings, moved to the object tracker", len(history), moved
        )

    def _prune(self) -> None:
        """Sightings no longer kept and expired lookups dropped, when first loaded and daily after"""
        if self._tracker is None:
            return
        options = self.options
        keep = float(options.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)) * 86400
        ttl = float(options.get(CONF_LOOKUP_CACHE_HOURS, DEFAULT_LOOKUP_CACHE_HOURS)) * 3600
        if self._tracker.prune(dt_util.utcnow().timestamp(), keep, ttl):
            self._save()

    def _save(self) -> None:
        self._store.async_delay_save(lambda: self._tracker.as_dict() if self._tracker else {}, 10)

    def plate_key(self, plate: str) -> str:
        """What a plate's history and lookups are kept by, a salted hash of it, never the plate"""
        if self._tracker is None:
            raise RuntimeError("Plate keys asked for before the salt is loaded")
        return self._tracker.key(KIND_PLATE, normalised(plate))

    def sightings(self, plate: str) -> list[datetime]:
        if self._tracker is None:
            return []
        return [
            dt_util.as_local(dt_util.utc_from_timestamp(s.at)) for s in self._tracker.sightings(KIND_PLATE, normalised(plate))
        ]

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
        counted as a sighting only when asked, when it's also fired as an event, where events are wanted"""
        tracker = await self._async_load()
        now = dt_util.as_local(now or dt_util.now())
        options = self.options
        register = self.register()
        match = register.match(read)
        provider = self._provider()
        # a register to look up with, but not for this plate, ignored or in a category not looked up
        lookup = LookupResult(provider.name, skipped=True) if provider else None
        if match.kind == KIND_IGNORED:
            return Vehicle(match, looked_up=lookup)
        if provider is not None and (match.category is None or match.category.lookup):
            lookup, match = await self._async_lookup(provider, match, register, camera, now, options)
        # visits not tracked, so neither counted nor said, the history kept for when they are again
        history = History()
        if options.get(CONF_TRACK_VISITS, True):
            gap = float(options.get(CONF_MIN_VISIT_GAP, DEFAULT_MIN_VISIT_GAP))
            keep = timedelta(days=float(options.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)))
            history = analyse([seen for seen in self.sightings(match.plate) if now - seen <= keep], now, gap)
            if record and history.is_new_visit:
                tracker.record(KIND_PLATE, match.plate, Sighting(round(now.timestamp()), camera, source))
                self._save()
        vehicle = Vehicle(match, history, lookup)
        if record and options.get(CONF_VEHICLE_EVENTS, False):
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
        self,
        provider: LookupProvider,
        match: Match,
        register: PlateRegister,
        camera: str | None,
        now: datetime,
        options: dict[str, Any],
    ) -> tuple[LookupResult, Match]:
        lookup = await self._async_cached_lookup(provider, match.plate, now, options)
        ttl = timedelta(hours=float(options.get(CONF_LOOKUP_CACHE_HOURS, DEFAULT_LOOKUP_CACHE_HOURS)))
        if lookup.found is None and camera and (confirmed := self._confirmed.get(camera)):
            good, when = confirmed
            if now - when <= ttl and good != match.plate and distance(good, match.plate) <= 1:
                _LOGGER.debug("CAMERA_AUTONOTIFY Correcting %s to %s, last confirmed on %s", match.plate, good, camera)
                corrected = register.match(good)
                return await self._async_cached_lookup(provider, good, now, options), replace(corrected, read=match.read)
        if lookup.found is not None and camera:
            self._confirmed[camera] = (match.plate, now)
        return lookup, match

    async def _async_cached_lookup(
        self, provider: LookupProvider, plate: str, now: datetime, options: dict[str, Any]
    ) -> LookupResult:
        """From the cache, or the register, an answer of found or not found being cached, a failure not"""
        if self._tracker is None:
            return LookupResult(provider.name, skipped=True)
        ttl = float(options.get(CONF_LOOKUP_CACHE_HOURS, DEFAULT_LOOKUP_CACHE_HOURS)) * 3600
        if (cached := self._tracker.lookup(provider.name, KIND_PLATE, plate, now.timestamp(), ttl)) is not None:
            found = cached.get("found")
            return LookupResult(
                provider.name,
                cached.get("status") or (200 if found else 404),
                cached.get("error"),
                VehicleLookup.from_dict(found) if found else None,
                cached=True,
                retrieved=dt_util.as_local(dt_util.utc_from_timestamp(cached["at"])),
            )
        try:
            result = await provider.async_lookup(plate)
        except Exception as error:
            _LOGGER.warning("CAMERA_AUTONOTIFY %s couldn't look up %s: %s", provider.name, redacted(plate), error)
            return LookupResult(provider.name, error=str(error) or type(error).__name__)
        if result.status in REFUSED:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_LOOKUP_REFUSED,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_LOOKUP_REFUSED,
                translation_placeholders={"provider": provider.name.upper()},
            )
            return result
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_LOOKUP_REFUSED)
        if result.status in (200, 404):
            self._tracker.remember(
                provider.name,
                KIND_PLATE,
                plate,
                round(now.timestamp()),
                {"found": result.found.as_dict() if result.found else None, "status": result.status, "error": result.error},
            )
            self._save()
        return result

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

    async def async_reset_sightings(self, plate: str | None = None) -> int:
        """A plate's visit history forgotten, or every plate's where none is given, returning how many sightings"""
        tracker = await self._async_load()
        removed = tracker.forget(KIND_PLATE, normalised(plate) if plate else None)
        self._save()
        return removed

    async def async_import_history(self, sightings: dict[str, list[str]]) -> int:
        """Sightings from elsewhere, such as anpr2mqtt's tracker, merged with those here, returning how many were new"""
        tracker = await self._async_load()
        zone = dt_util.get_default_time_zone()
        added = 0
        for plate, times in sightings.items():
            # anpr2mqtt's may have no time zone, being its own local time
            parsed = [seen for seen in (dt_util.parse_datetime(t) for t in times) if seen is not None]
            found = [
                Sighting(round((s if s.tzinfo else s.replace(tzinfo=zone)).timestamp()), source="anpr2mqtt") for s in parsed
            ]
            added += tracker.merge(KIND_PLATE, normalised(plate), found)
        self._save()
        return added


@callback
def vehicles(hass: HomeAssistant) -> Vehicles:
    data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    if DATA_VEHICLES not in data:
        data[DATA_VEHICLES] = Vehicles(hass)
    return data[DATA_VEHICLES]
