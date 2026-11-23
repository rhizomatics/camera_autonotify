"""Vehicles for any source of plates: classified, looked up, their history kept, in Frigate's notifications and
anpr2mqtt's, by an action, and imported from anpr2mqtt"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Self, cast

import pytest
from aiohttp import ClientSession
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_TYPE
from homeassistant.core import Context, HomeAssistant, State
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.camera_autonotify.anpr import AnprNotifier, Sighting
from custom_components.camera_autonotify.compat import vol
from custom_components.camera_autonotify.const import DOMAIN, SUBENTRY_PLATES, TYPE_DISCOVERY
from custom_components.camera_autonotify.facts import FactStore
from custom_components.camera_autonotify.frigate import fact_stores
from custom_components.camera_autonotify.plates import redacted
from custom_components.camera_autonotify.texts import async_load_texts
from custom_components.camera_autonotify.vehicles import (
    ISSUE_LOOKUP_REFUSED,
    NAMING,
    DvlaProvider,
    LookupResult,
    Naming,
    VehicleLookup,
    vehicle_named,
    vehicles,
)
from tests.ha_testing import MockConfigEntry, async_fire_time_changed

from .conftest import add_frigate, mock_supernotify
from .test_notifier import DETECTION, decision, notifier

if TYPE_CHECKING:
    from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

NOW = datetime(2026, 11, 19, 14, 25, tzinfo=dt_util.UTC)
FAMILY = {"plates": [{"plate": "TJ912UKL", "description": "Joe's mini", "corrections": ["J912UKL"]}]}


class FakeRegister:
    """A vehicle register, knowing the plates given"""

    name = "dvla"

    def __init__(self, known: dict[str, VehicleLookup] | None = None, refuse: bool = False) -> None:
        self.known = known or {}
        self.refuse = refuse
        self.asked: list[str] = []

    async def async_lookup(self, plate: str) -> LookupResult:
        self.asked.append(plate)
        if self.refuse:
            return LookupResult(self.name, 403, "Forbidden")
        found = self.known.get(plate)
        return LookupResult(self.name, 200 if found else 404, None if found else "Vehicle Not Found", found)


PICKUP_TRUCK = VehicleLookup(
    "dvla", "MITSUBISHI", "WHITE", 2019, "PETROL", "Taxed", "Valid", {"make": "MITSUBISHI", "colour": "WHITE"}
)


def global_settings(
    hass: HomeAssistant, categories: dict[str, dict[str, Any]] | None = None, **options: Any
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TYPE: TYPE_DISCOVERY},
        options=options,
        subentries_data=[
            ConfigSubentryData(data=data, subentry_type=SUBENTRY_PLATES, title=name, unique_id=None)
            for name, data in (categories or {}).items()
        ],
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(autouse=True)
def frozen(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def register(hass: HomeAssistant) -> FakeRegister:
    fake = FakeRegister({"PX19TVD": PICKUP_TRUCK})
    vehicles(hass).provider = fake
    return fake


# --- classified, looked up and counted


async def test_unknown_looked_up_and_cached(hass: HomeAssistant, register: FakeRegister):
    global_settings(hass, {"Family cars": FAMILY})
    found = await vehicles(hass).async_classify("px19 tvd")
    assert (found.plate, found.kind, found.lookup) == ("PX19TVD", "unknown", PICKUP_TRUCK)
    await vehicles(hass).async_classify("PX19TVD")
    assert register.asked == ["PX19TVD"]


async def test_known_not_looked_up_unless_category_says(hass: HomeAssistant, register: FakeRegister):
    global_settings(hass, {"Family cars": FAMILY, "Fleet": {"lookup": True, "plates": ["PX19TVD"]}})
    found = await vehicles(hass).async_classify("J912UKL")
    assert (found.plate, found.kind, found.match.description, found.lookup) == ("TJ912UKL", "known", "Joe's mini", None)
    assert (await vehicles(hass).async_classify("PX19TVD")).lookup == PICKUP_TRUCK
    assert register.asked == ["PX19TVD"]


async def test_lookup_cache_expires(hass: HomeAssistant, register: FakeRegister, frozen: FrozenDateTimeFactory):
    global_settings(hass, lookup_cache_hours=1)
    await vehicles(hass).async_classify("PX19TVD")
    frozen.tick(timedelta(hours=2))
    await vehicles(hass).async_classify("PX19TVD")
    assert register.asked == ["PX19TVD", "PX19TVD"]


async def test_misread_corrected_by_last_confirmed(hass: HomeAssistant, register: FakeRegister):
    """The register doesn't know a plate a character off the last it confirmed on the same camera"""
    global_settings(hass)
    await vehicles(hass).async_classify("PX19TVD", camera="driveway")
    found = await vehicles(hass).async_classify("PX19TV0", camera="driveway")
    assert (found.match.read, found.plate, found.lookup) == ("PX19TV0", "PX19TVD", PICKUP_TRUCK)
    # not on another camera
    assert (await vehicles(hass).async_classify("PX19TV0", camera="gate")).plate == "PX19TV0"


async def test_refused_key_repaired(hass: HomeAssistant):
    global_settings(hass)
    vehicles(hass).provider = FakeRegister(refuse=True)
    refused = await vehicles(hass).async_classify("PX19TVD")
    assert refused.as_dict()["lookup"] == {"source": "dvla", "status": 403, "error": "Forbidden", "cached": False}
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_LOOKUP_REFUSED) is not None
    vehicles(hass).provider = FakeRegister()
    await vehicles(hass).async_classify("AB12CDE")
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_LOOKUP_REFUSED) is None


async def test_failing_register_logged(hass: HomeAssistant, caplog: pytest.LogCaptureFixture):
    class Broken(FakeRegister):
        async def async_lookup(self, plate: str) -> LookupResult:
            raise OSError("timed out")

    global_settings(hass)
    vehicles(hass).provider = Broken()
    found = await vehicles(hass).async_classify("PX19TVD")
    assert found.lookup is None
    assert found.as_dict()["lookup"] == {"source": "dvla", "status": None, "error": "timed out", "cached": False}
    assert "couldn't look up PX****D: timed out" in caplog.text


async def test_no_lookup_without_a_key(hass: HomeAssistant):
    global_settings(hass)
    assert (await vehicles(hass).async_classify("PX19TVD")).lookup is None


async def test_history_counted_only_when_asked(hass: HomeAssistant, frozen: FrozenDateTimeFactory):
    global_settings(hass)
    plates = vehicles(hass)
    assert (await plates.async_classify("PX19TVD")).history.previous_sightings == 0
    await plates.async_classify("PX19TVD", record=True)
    assert (await plates.async_classify("PX19TVD")).history.previous_sightings == 1
    # within the gap between visits, the same visit, not counted again
    frozen.tick(timedelta(minutes=2))
    found = await plates.async_classify("PX19TVD", record=True)
    assert not found.history.is_new_visit
    assert (await plates.async_classify("PX19TVD")).history.previous_sightings == 1
    frozen.tick(timedelta(minutes=10))
    await plates.async_classify("PX19TVD", record=True)
    assert (await plates.async_classify("PX19TVD")).history.previous_sightings == 2


async def test_history_kept_for_a_time(hass: HomeAssistant, frozen: FrozenDateTimeFactory):
    global_settings(hass, history_days=7)
    plates = vehicles(hass)
    await plates.async_classify("PX19TVD", record=True)
    frozen.tick(timedelta(days=8))
    await plates.async_classify("PX19TVD", record=True)
    assert (await plates.async_classify("PX19TVD")).history.previous_sightings == 1


async def test_ignored_not_looked_up_or_counted(hass: HomeAssistant, register: FakeRegister):
    global_settings(hass, {"Ignored reads": {"ignore": True, "plates": ["PX19TVD"]}})
    found = await vehicles(hass).async_classify("PX19TVD", record=True)
    assert (found.kind, found.lookup, register.asked) == ("ignored", None, [])
    assert vehicles(hass).sightings("PX19TVD") == []


async def test_counted_once_for_a_review(hass: HomeAssistant):
    plates = vehicles(hass)
    assert plates.first_time_for("review:PX19TVD", 0)
    assert not plates.first_time_for("review:PX19TVD", 10)
    assert plates.first_time_for("review:PX19TVD", 4000)


# --- in Frigate's notifications


def read_plate(hass: HomeAssistant, plate: str = "PX19TVD") -> None:
    store = fact_stores(hass).setdefault("frigate", FactStore())
    store.on_event({"after": {"id": DETECTION, "camera": "courtyard", "recognized_license_plate": [plate, 0.95]}}, 1.0)


async def test_frigate_plate_classified(hass: HomeAssistant, register: FakeRegister):
    """Described, looked up, its sightings said, and the pre-defined rule's priority, once there's a category"""
    add_frigate(hass)
    global_settings(hass, {"Family cars": FAMILY})
    await async_load_texts(hass)
    read_plate(hass, "J912UKL")
    found = notifier(hass)
    vehicle = await found.async_vehicle(decision())
    _, outcome = found.ruled(decision(), vehicle)
    assert outcome.message == "Joe's mini (TJ912UKL)"
    assert outcome.priority == "medium"
    read_plate(hass)
    vehicle = await found.async_vehicle(decision())
    assert found.ruled(decision(), vehicle)[1].message == "PX19TVD - MITSUBISHI, WHITE, 2019, Taxed"
    assert found.ruled(decision(), vehicle)[1].priority == "high"


async def test_frigate_plate_priority_as_set(hass: HomeAssistant, register: FakeRegister):
    add_frigate(hass)
    global_settings(
        hass,
        {"Watch": {"kind": "dangerous", "plates": ["PX19TVD"]}},
        vehicle_priority_dangerous="critical",
        vehicle_scenarios_dangerous=["dangerous_vehicle"],
    )
    await async_load_texts(hass)
    read_plate(hass)
    found = notifier(hass)
    outcome = found.ruled(decision(), await found.async_vehicle(decision()))[1]
    assert (outcome.priority, outcome.scenarios) == ("critical", ("dangerous_vehicle",))


async def test_frigate_plate_priority_unchanged_without_categories(hass: HomeAssistant, register: FakeRegister):
    """No surprise for those with no vehicle categories: still looked up, but the priority is the review's own"""
    add_frigate(hass)
    global_settings(hass)
    await async_load_texts(hass)
    read_plate(hass)
    found = notifier(hass)
    outcome = found.ruled(decision(), await found.async_vehicle(decision()))[1]
    assert outcome.priority is None
    assert "MITSUBISHI" in outcome.message


async def test_frigate_plate_ignored_silenced(hass: HomeAssistant):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    global_settings(hass, {"Ignored reads": {"ignore": True, "plates": ["PX19TVD"]}})
    read_plate(hass)
    await notifier(hass).async_notify(decision(), Context())
    assert calls == []


async def test_frigate_sightings_said(hass: HomeAssistant, frozen: FrozenDateTimeFactory):
    add_frigate(hass)
    global_settings(hass)
    await async_load_texts(hass)
    read_plate(hass)
    found = notifier(hass)
    await found.async_vehicle(decision())
    frozen.tick(timedelta(hours=1))
    other = replace(decision(), review=replace(decision().review, id="another"))
    vehicle = await found.async_vehicle(other)
    assert found.ruled(other, vehicle)[1].message == "PX19TVD - Previous sightings: 1 - At an unusual time"


async def test_no_vehicle_without_a_plate(hass: HomeAssistant):
    add_frigate(hass)
    assert await notifier(hass).async_vehicle(decision()) is None


# --- in anpr2mqtt's sightings


def sighting(**given: Any) -> Sighting:
    return Sighting.from_state(
        State("sensor.anpr_driveway", given.pop("plate", "PX19TVD"), {"camera": "driveway", "known": True, **given})
    )


async def anpr_notifier(hass: HomeAssistant, **options: Any) -> AnprNotifier:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_TYPE: "anpr", "source_name": "anpr_driveway"}, options=options)
    entry.add_to_hass(hass)
    await async_load_texts(hass)
    return AnprNotifier(hass, entry)


async def test_anpr2mqtt_own_classification_to_begin_with(hass: HomeAssistant, register: FakeRegister):
    global_settings(hass, {"Watch": {"kind": "dangerous", "plates": ["PX19TVD"]}})
    found, priority, scenarios = await (await anpr_notifier(hass)).async_classified(sighting())
    assert found is not None
    assert (found.kind, priority, scenarios) == ("known", "medium", None)
    assert register.asked == []


async def test_visits_not_tracked(hass: HomeAssistant, register: FakeRegister):
    """Neither counted nor said, those already kept left as they are"""
    entry = global_settings(hass)
    await vehicles(hass).async_classify("PX19TVD", record=True)
    hass.config_entries.async_update_entry(entry, options={"track_visits": False})
    vehicle = await vehicles(hass).async_classify("PX19TVD", record=True)
    assert vehicle.history.previous_sightings == 0
    assert len(vehicles(hass).sightings("PX19TVD")) == 1


async def test_anpr2mqtt_classified_here(hass: HomeAssistant, register: FakeRegister):
    """anpr2mqtt only the source of the plate and image"""
    global_settings(
        hass,
        {"Watch": {"kind": "dangerous", "plates": [{"plate": "PX19TVD", "description": "Stolen van"}]}},
        vehicle_scenarios_dangerous=["alarm"],
    )
    found, priority, scenarios = await (await anpr_notifier(hass, anpr_own_classification=False)).async_classified(
        sighting(plate="PX19TV0")
    )
    assert found is not None
    assert (found.plate, found.kind, found.description, priority) == ("PX19TVD", "dangerous", "Stolen van", "critical")
    assert scenarios == (["alarm"], ["alarm"])
    assert found.category == "Watch"
    assert vehicles(hass).sightings("PX19TVD")


async def test_anpr2mqtt_unknown_named_by_register(hass: HomeAssistant, register: FakeRegister):
    """In no category, so by its colour and make, with the register's details as before"""
    global_settings(hass, {"Family cars": FAMILY})
    found = await anpr_notifier(hass, anpr_own_classification=False)
    classified, _, _ = await found.async_classified(sighting())
    assert classified is not None and classified.category is None
    assert found.title(classified, None).startswith("White Mitsubishi at ")
    assert "DVLA: MITSUBISHI, WHITE, 2019, Taxed" in found.message(classified).splitlines()


async def test_anpr2mqtt_ignored_here(hass: HomeAssistant):
    global_settings(hass, {"Ignored": {"ignore": True, "plates": ["PX19TVD"]}})
    found = await anpr_notifier(hass, anpr_own_classification=False)
    assert (await found.async_classified(sighting()))[0] is None


# --- the actions


async def set_up(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})


async def respond(hass: HomeAssistant, service: str, data: dict[str, Any]) -> dict[str, Any]:
    """An action's response, as a mapping to read from"""
    response = await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=True)
    return cast("dict[str, Any]", response)


async def test_classify_plate_lookup_said(hass: HomeAssistant, register: FakeRegister, frozen: FrozenDateTimeFactory):
    """The lookup's status and error, whether cached, skipped where the category isn't looked up, and null only
    with no register at all"""
    global_settings(hass, {"Family cars": FAMILY})
    await set_up(hass)
    found = (await respond(hass, "classify_plate", {"plate": "PX19TVD"}))["lookup"]
    assert (found["make"], found["status"], found["error"], found["cached"]) == ("MITSUBISHI", 200, None, False)
    frozen.tick(timedelta(minutes=5))
    again = (await respond(hass, "classify_plate", {"plate": "PX19TVD"}))["lookup"]
    assert again["cached"]
    assert dt_util.parse_datetime(again["retrieved"]) == NOW
    unknown = (await respond(hass, "classify_plate", {"plate": "AB12CDE"}))["lookup"]
    assert unknown == {"source": "dvla", "status": 404, "error": "Vehicle Not Found", "cached": False}
    cached = (await respond(hass, "classify_plate", {"plate": "AB12CDE"}))["lookup"]
    assert cached == {
        "source": "dvla",
        "status": 404,
        "error": "Vehicle Not Found",
        "cached": True,
        "retrieved": dt_util.as_local(NOW + timedelta(minutes=5)).isoformat(),
    }
    assert (await respond(hass, "classify_plate", {"plate": "TJ912UKL"}))["lookup"] == {"skipped": True}
    vehicles(hass).provider = None
    assert (await respond(hass, "classify_plate", {"plate": "AB12CDE"}))["lookup"] is None


async def test_classify_plate_action(hass: HomeAssistant, register: FakeRegister):
    global_settings(hass, {"Family cars": FAMILY})
    await set_up(hass)
    response = await respond(hass, "classify_plate", {"plate": "J912UKL"})
    assert response["plate"] == "TJ912UKL"
    assert response["kind"] == "known"
    assert response["category"] == "Family cars"
    assert response["history"]["previous_sightings"] == 0
    # counted only when asked
    await hass.services.async_call(
        DOMAIN, "classify_plate", {"plate": "PX19TVD", "record_sighting": True}, blocking=True, return_response=True
    )
    assert vehicles(hass).sightings("PX19TVD")
    assert not vehicles(hass).sightings("TJ912UKL")


ANPR2MQTT_CONFIG = """
targets:
  plate:
    groups:
     - name: known
       members:
        - id: TJ912UKL
          description: joe's mini conv
          correction:
            - J912UKL
        - P001PAT
     - name: Amazon Prime
       icon: "mdi:truck-delivery"
       members:
        - AM40PRM
     - name: dangerous
       priority: critical
       members:
         - id: B4DM3N
           description: Rural watch reported vehicle
    correction:
      P001PAT:
        - P0O1PAT
      UN001TST:
        - UN001TSK
    ignore:
      - ^I\\dZ$
dvla:
  api_key: placeholder
  cache_ttl: 7200
tracker:
  min_visit_gap_seconds: 60
"""


# --- the settings


async def test_plate_category_settings(hass: HomeAssistant):
    entry = global_settings(hass)
    await set_up(hass)
    result = await hass.config_entries.subentries.async_init((entry.entry_id, SUBENTRY_PLATES), context={"source": "user"})
    bad = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Fleet", "kind": "known", "ignore": False, "lookup": False, "plates": [{"plate": "AB[1"}]}
    )
    assert bad["errors"] == {"plates": "invalid_pattern"}
    done = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Fleet", "kind": "dangerous", "ignore": False, "lookup": True, "plates": [{"plate": "AB\\d{2}"}]},
    )
    assert done["type"] == "create_entry"
    subentry = next(iter(entry.subentries.values()))
    assert (subentry.title, subentry.data["kind"], subentry.data["plates"]) == ("Fleet", "dangerous", [{"plate": "AB\\d{2}"}])
    changing = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PLATES), context={"source": "reconfigure", "subentry_id": subentry.subentry_id}
    )
    changed = await hass.config_entries.subentries.async_configure(
        changing["flow_id"], {"name": "Fleet vans", "kind": "known", "ignore": False, "lookup": False}
    )
    assert changed["reason"] == "reconfigure_successful"
    assert next(iter(entry.subentries.values())).title == "Fleet vans"


async def test_vehicle_settings_in_global_settings(hass: HomeAssistant):
    mock_supernotify(hass)
    add_frigate(hass)
    from .test_discovery import set_up_discovery
    from .test_settings import fields_of

    await set_up_discovery(hass)
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_DISCOVERY)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    shown = fields_of(dict(result))
    assert {
        "vehicles.vehicle_priority_known",
        "vehicles.vehicle_scenarios_dangerous",
        "vehicles.track_visits",
        "vehicles.min_visit_gap",
        "vehicle_lookup.dvla_api_key",
    } <= set(shown)


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any] | None = None, no_json: bool = False) -> None:
        self.status = status
        self.body = body or {}
        self.no_json = no_json

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise OSError(f"status {self.status}")

    async def json(self, content_type: str | None = "application/json") -> dict[str, Any]:
        if self.no_json:
            raise ValueError("not JSON")
        return self.body


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.posted: list[dict[str, Any]] = []

    def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> FakeResponse:
        self.posted.append({"url": url, "headers": headers, "json": json})
        return self.response


def as_session(fake: FakeSession) -> ClientSession:
    return cast("ClientSession", fake)


async def test_dvla_provider():
    """The DVLA's Vehicle Enquiry Service, its details in the common schema, the plate left out of what it gave"""
    found = {
        "registrationNumber": "PX19TVD",
        "make": "MITSUBISHI",
        "colour": "WHITE",
        "yearOfManufacture": 2019,
        "fuelType": "PETROL",
        "taxStatus": "Taxed",
        "motStatus": "Valid",
    }
    session = FakeSession(FakeResponse(200, found))
    looked_up = await DvlaProvider(as_session(session), "key").async_lookup("PX19TVD")
    raw = {key: value for key, value in found.items() if key != "registrationNumber"}
    assert looked_up == LookupResult(
        "dvla", 200, found=VehicleLookup("dvla", "MITSUBISHI", "WHITE", 2019, "PETROL", "Taxed", "Valid", raw)
    )
    assert session.posted[0]["headers"]["x-api-key"] == "key"
    assert session.posted[0]["json"] == {"registrationNumber": "PX19TVD"}
    not_found = {"errors": [{"status": "404", "title": "Vehicle Not Found", "detail": "Record for vehicle not found"}]}
    assert await DvlaProvider(as_session(FakeSession(FakeResponse(404, not_found))), "key").async_lookup("X") == (
        LookupResult("dvla", 404, "Vehicle Not Found: Record for vehicle not found")
    )
    assert await DvlaProvider(as_session(FakeSession(FakeResponse(500))), "key").async_lookup("X") == LookupResult(
        "dvla", 500, "HTTP 500"
    )


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (FakeResponse(404, {"errors": [{"title": "Vehicle Not Found"}]}), (True, 404, "Vehicle Not Found")),
        (FakeResponse(200, {"make": "FORD"}), (True, 200, None)),
        (FakeResponse(403, {"message": "Forbidden"}), (False, 403, "Forbidden")),
        (FakeResponse(404, no_json=True), (False, 404, "No JSON in the response")),
    ],
)
async def test_dvla_key_test(response: FakeResponse, expected: tuple[bool, int | None, str | None]):
    """A made up plate, answered with JSON and 200 or 404 by a key that works"""
    session = FakeSession(response)
    assert await DvlaProvider(as_session(session), "key").async_test() == expected
    assert session.posted[0]["json"] == {"registrationNumber": "A123TST"}


async def test_dvla_lookup_logged(caplog: pytest.LogCaptureFixture):
    """Every call logged at info, the plate partly redacted, with the status and the DVLA's error where it gives one"""
    caplog.set_level(logging.INFO)
    await DvlaProvider(as_session(FakeSession(FakeResponse(200, {"make": "FORD"}))), "key").async_lookup("PX19 TVD")
    assert "DVLA lookup of PX****D: 200" in caplog.text
    assert "PX19TVD" not in caplog.text
    errors = {"errors": [{"status": "400", "title": "Bad Request", "detail": "Invalid format for field - vrn"}]}
    await DvlaProvider(as_session(FakeSession(FakeResponse(400, errors))), "key").async_lookup("X1")
    assert "DVLA lookup of X*: 400 Bad Request: Invalid format for field - vrn" in caplog.text
    await DvlaProvider(as_session(FakeSession(FakeResponse(403, {"message": "Forbidden"}))), "key").async_lookup("AB12CDE")
    assert "DVLA lookup of AB****E: 403 Forbidden" in caplog.text


def test_redacted():
    assert redacted("px19 tvd") == "PX****D"
    assert redacted("A1") == "A*"


async def test_dvla_provider_from_key(hass: HomeAssistant):
    """The key in the entry's data, as Home Assistant keeps credentials, not its options"""
    entry = global_settings(hass, dvla_api_key="in the options")
    assert vehicles(hass)._provider() is None
    hass.config_entries.async_update_entry(entry, data={**entry.data, "dvla_api_key": "key"})
    assert isinstance(vehicles(hass)._provider(), DvlaProvider)


# --- 1.0.0: unreadable, the event, Known vehicle, plates by action, and the key as a credential


async def test_unreadable_vehicle(hass: HomeAssistant):
    """A car with no plate read is unreadable, high to begin with, once there's a category"""
    add_frigate(hass)
    found = notifier(hass)
    car = replace(decision(), review=replace(decision().review, objects=("car",)))
    # no vehicle category yet
    assert found.ruled(car, None)[1].priority is None
    global_settings(hass, {"Family cars": FAMILY})
    assert found.ruled(car, None)[1].priority == "high"
    # a person isn't a vehicle
    assert found.ruled(decision(), None)[1].priority is None


async def test_no_event_unless_asked(hass: HomeAssistant, register: FakeRegister):
    """Off to begin with, since it carries the plate, which the recorder would keep"""
    global_settings(hass)
    fired: list[dict[str, Any]] = []
    hass.bus.async_listen("camera_autonotify_vehicle", lambda event: fired.append(dict(event.data)))
    await vehicles(hass).async_classify("PX19TVD", record=True)
    await hass.async_block_till_done()
    assert fired == []


async def test_event_for_each_sighting(hass: HomeAssistant, register: FakeRegister):
    """As OpenALPR's, plate, entity and confidence first, then what's known here"""
    add_frigate(hass)
    global_settings(hass, {"Family cars": FAMILY}, vehicle_events=True)
    fired: list[dict[str, Any]] = []
    hass.bus.async_listen("camera_autonotify_vehicle", lambda event: fired.append(dict(event.data)))
    read_plate(hass, "J912UKL")
    found = notifier(hass)
    await found.async_vehicle(decision())
    # once for the review, however many notifications it has
    await found.async_vehicle(decision())
    await hass.async_block_till_done()
    assert len(fired) == 1
    event = fired[0]
    assert (event["plate"], event["confidence"], event["source"], event["camera"]) == ("TJ912UKL", 0.95, "frigate", "courtyard")
    assert event["entity_id"] == "camera.courtyard"
    assert (event["kind"], event["category"], event["description"], event["read"]) == (
        "known",
        "Family cars",
        "Joe's mini",
        "J912UKL",
    )
    # not for a plate only classified, not seen
    await vehicles(hass).async_classify("PX19TVD")
    await hass.async_block_till_done()
    assert len(fired) == 1


async def test_known_vehicle_button(hass: HomeAssistant, register: FakeRegister):
    """On an unknown plate, typed into on the phone, adding it to the known vehicles"""
    from custom_components.camera_autonotify.actions import Action, async_act, available, button

    add_frigate(hass)
    entry = global_settings(hass, {"Family cars": FAMILY})
    await async_load_texts(hass)
    found = notifier(hass)
    unknown = await vehicles(hass).async_classify("PX19TVD")
    offered = [a for a in available(hass, found.entry, decision(), unknown) if a.kind == "known_vehicle"]
    assert offered == [Action("known_vehicle", found.entry.entry_id, "PX19TVD")]
    assert button(hass, offered[0])["behavior"] == "textInput"
    known = await vehicles(hass).async_classify("TJ912UKL")
    assert not [a for a in available(hass, found.entry, decision(), known) if a.kind == "known_vehicle"]
    assert await async_act(hass, offered[0], "The postman")
    category = next(s for s in entry.subentries.values() if s.title == "Known vehicles")
    assert category.data["plates"] == [{"plate": "PX19TVD", "description": "The postman"}]
    assert (await vehicles(hass).async_classify("PX19TVD")).kind == "known"
    # again, already there
    assert not await async_act(hass, offered[0])


async def test_anpr2mqtt_known_vehicle_button(hass: HomeAssistant, register: FakeRegister):
    global_settings(hass, {"Family cars": FAMILY})
    found = await anpr_notifier(hass, anpr_own_classification=False)
    classified, priority, scenarios = await found.async_classified(sighting())
    assert classified is not None and priority is not None
    data = found.supernotify_data(classified, priority, scenarios)
    assert [a["title"] for a in data["actions"]] == ["Known vehicle"]


async def test_add_and_remove_plate_actions(hass: HomeAssistant):
    entry = global_settings(hass, {"Family cars": FAMILY})
    await set_up(hass)
    added = await respond(hass, "add_plate", {"category": "Family cars", "plate": "MY13CAR", "description": "Old pickup"})
    assert added == {"added": True}
    again = await respond(hass, "add_plate", {"category": "Family cars", "plate": "my13 car"})
    assert again == {"added": False}
    await respond(hass, "add_plate", {"category": "Watch list", "plate": "B4DM3N", "corrections": ["B4DM8N"]})
    titles = sorted(s.title for s in entry.subentries.values())
    assert titles == ["Family cars", "Watch list"]
    assert (await vehicles(hass).async_classify("B4DM8N")).plate == "B4DM3N"
    removed = await respond(hass, "remove_plate", {"plate": "MY13CAR"})
    assert removed == {"categories": 1}
    assert (await vehicles(hass).async_classify("MY13CAR")).kind == "unknown"
    assert await respond(hass, "remove_plate", {"plate": "B4DM3N", "category": "Family cars"}) == {"categories": 0}


async def test_list_categories_and_sightings_actions(hass: HomeAssistant):
    global_settings(hass, {"Family cars": FAMILY})
    await set_up(hass)
    listed = await respond(hass, "list_vehicle_categories", {})
    family = listed["categories"][0]
    assert family["name"] == "Family cars"
    assert family["kind"] == "known"
    assert family["plates"][0]["plate"] == "TJ912UKL"
    assert await respond(hass, "list_vehicle_categories", {"category": "Nothing"}) == {"categories": []}

    await vehicles(hass).async_classify("PX19TVD", record=True)
    await vehicles(hass).async_classify("J912UKL", record=True)
    assert await respond(hass, "reset_sightings", {"plate": "px19 tvd"}) == {"sightings": 1}
    assert not vehicles(hass).sightings("PX19TVD")
    assert vehicles(hass).sightings("TJ912UKL")
    # every plate only when asked for outright, and not with a plate too
    for wrong in ({}, {"plate": "TJ912UKL", "all": True}):
        with pytest.raises(vol.Invalid):
            await respond(hass, "reset_sightings", wrong)
    assert await respond(hass, "reset_sightings", {"all": True}) == {"sightings": 1}
    assert not vehicles(hass).sightings("TJ912UKL")


SALT = "00" * 32


def stored(key: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "key": f"camera_autonotify.{key}", "data": data}


def salted(plate: str) -> str:
    import hashlib
    import hmac

    return hmac.new(bytes.fromhex(SALT), plate.encode(), hashlib.sha256).hexdigest()


async def test_kept_by_salted_hash(
    hass: HomeAssistant, hass_storage: dict[str, Any], frozen: FrozenDateTimeFactory, register: FakeRegister
):
    """One store, objects and lookups both kept by a salted hash of the plate's kind and itself, never the plate, with
    each sighting's camera and source"""
    hashed = salted("PX19TVD")
    hass_storage["camera_autonotify.plate_salt"] = stored("plate_salt", {"salt": SALT})
    earlier = round((NOW - timedelta(days=1)).timestamp())
    hass_storage["camera_autonotify.tracker"] = stored(
        "tracker", {"objects": {hashed: {"kind": "plate", "sightings": [[earlier, "gate", "frigate"]]}}, "lookups": {}}
    )
    global_settings(hass)
    vehicle = await vehicles(hass).async_classify("PX19TVD", "drive", record=True, source="frigate")
    assert vehicle.history.previous_sightings == 1
    assert vehicle.lookup == PICKUP_TRUCK
    await vehicles(hass).async_classify("AB12CDE", record=True)
    # once saved, after the store's delay
    frozen.tick(11)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    data = hass_storage["camera_autonotify.tracker"]["data"]
    assert set(data["objects"]) == {hashed, salted("AB12CDE")}
    assert data["objects"][hashed] == {
        "kind": "plate",
        "sightings": [[earlier, "gate", "frigate"], [round(NOW.timestamp()), "drive", "frigate"]],
    }
    assert set(data["lookups"]) == {f"dvla:{hashed}", f"dvla:{salted('AB12CDE')}"}
    assert "PX19TVD" not in str(data) and "AB12CDE" not in str(data)


async def test_beta_history_moved(
    hass: HomeAssistant, hass_storage: dict[str, Any], frozen: FrozenDateTimeFactory, register: FakeRegister
):
    """The betas' history, by plate or by hash, moved into the tracker, merged, and their stores removed, their lookups
    dropped and looked up again"""
    hashed = salted("PX19TVD")
    hass_storage["camera_autonotify.plate_salt"] = stored("plate_salt", {"salt": SALT})
    hass_storage["camera_autonotify.plate_history"] = stored(
        "plate_history", {"PX19TVD": ["2026-11-01T08:00:00+00:00"], hashed: ["2026-11-02T08:00:00+00:00"]}
    )
    hass_storage["camera_autonotify.plate_lookup"] = stored(
        "plate_lookup", {"dvla:AB12CDE": {"at": NOW.isoformat(), "found": None}}
    )
    global_settings(hass)
    vehicle = await vehicles(hass).async_classify("PX19TVD", record=True)
    assert vehicle.history.previous_sightings == 2
    await vehicles(hass).async_classify("AB12CDE")
    assert register.asked == ["PX19TVD", "AB12CDE"]
    assert "camera_autonotify.plate_history" not in hass_storage
    assert "camera_autonotify.plate_lookup" not in hass_storage
    objects = hass_storage["camera_autonotify.tracker"]["data"]["objects"]
    assert set(objects) == {hashed}
    assert "PX19TVD" not in str(objects)


async def test_pruned_when_loaded(
    hass: HomeAssistant, hass_storage: dict[str, Any], frozen: FrozenDateTimeFactory, register: FakeRegister
):
    """A plate seen once, long ago, and an expired lookup, dropped, though the plate isn't seen again"""
    hass_storage["camera_autonotify.plate_salt"] = stored("plate_salt", {"salt": SALT})
    old = round((NOW - timedelta(days=30)).timestamp())
    hass_storage["camera_autonotify.tracker"] = stored(
        "tracker",
        {
            "objects": {salted("AB12CDE"): {"kind": "plate", "sightings": [[old, None, None]]}},
            "lookups": {f"dvla:{salted('AB12CDE')}": {"at": old, "found": None}},
        },
    )
    global_settings(hass, history_days=7)
    await vehicles(hass).async_classify("PX19TVD")
    frozen.tick(11)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    data = hass_storage["camera_autonotify.tracker"]["data"]
    assert salted("AB12CDE") not in data["objects"]
    assert f"dvla:{salted('AB12CDE')}" not in data["lookups"]


async def test_salt_made_once(hass: HomeAssistant, hass_storage: dict[str, Any]):
    """Its own to each installation, made and saved the first time, then kept"""
    global_settings(hass)
    await vehicles(hass).async_classify("PX19TVD")
    salt = hass_storage["camera_autonotify.plate_salt"]["data"]["salt"]
    assert len(bytes.fromhex(salt)) == 32
    assert vehicles(hass).plate_key("PX19TVD") != salted("PX19TVD")
    from custom_components.camera_autonotify.vehicles import Vehicles

    again = Vehicles(hass)
    await again.async_classify("PX19TVD")
    assert again.plate_key("PX19TVD") == vehicles(hass).plate_key("PX19TVD")
    assert hass_storage["camera_autonotify.plate_salt"]["data"]["salt"] == salt


async def test_key_kept_as_a_credential(hass: HomeAssistant):
    """In the entry's data, never its options, not shown again, kept when left empty, and forgotten when asked"""
    from homeassistant.components.diagnostics import REDACTED

    from custom_components.camera_autonotify.diagnostics import async_get_config_entry_diagnostics

    from .test_discovery import set_up_discovery

    mock_supernotify(hass)
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_DISCOVERY)

    async def key_said() -> str:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        hass.config_entries.options.async_abort(result["flow_id"])
        return str((result["description_placeholders"] or {})["dvla_key"])

    async def save(lookup: dict[str, Any]) -> None:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"auto_discover": True, "discover_zones": False, "health": {}, "summary": {}, "vehicle_lookup": lookup},
        )
        await hass.async_block_till_done()

    assert await key_said() == "No key is set."
    await save({"dvla_api_key": "secret"})
    assert entry.data["dvla_api_key"] == "secret"
    # never shown, but said to be set
    assert (await key_said()).startswith("A key is set")
    assert "dvla_api_key" not in entry.options
    assert (await async_get_config_entry_diagnostics(hass, entry))["data"]["dvla_api_key"] == REDACTED
    await save({})
    assert entry.data["dvla_api_key"] == "secret"
    await save({"dvla_api_key_clear": True})
    assert "dvla_api_key" not in entry.data
    assert "dvla_api_key_clear" not in entry.options


async def test_dvla_key_tested(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    """The key typed tried, the result shown, then the settings again, nothing saved, or the key set where none's
    typed"""
    from .test_discovery import set_up_discovery

    mock_supernotify(hass)
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_DISCOVERY)
    form = {"auto_discover": True, "discover_zones": False, "health": {}, "summary": {}}

    async def tested(lookup: dict[str, Any]) -> str:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**form, "vehicle_lookup": {**lookup, "dvla_api_key_test": True}}
        )
        assert result["step_id"] == "dvla_test"
        said = str((result["description_placeholders"] or {})["result"])
        result = await hass.config_entries.options.async_configure(result["flow_id"], {})
        assert result["step_id"] == "discovery"
        hass.config_entries.options.async_abort(result["flow_id"])
        return said

    assert await tested({}) == "There's no key to test: type one first."
    aioclient_mock.post(
        "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles",
        status=404,
        json={"errors": [{"title": "Vehicle Not Found"}]},
    )
    said = await tested({"dvla_api_key": "typed"})
    assert said == "The DVLA answered as expected for A123TST: 404 Vehicle Not Found."
    assert aioclient_mock.mock_calls[-1][3]["x-api-key"] == "typed"
    assert "dvla_api_key" not in entry.data
    aioclient_mock.clear_requests()
    aioclient_mock.post(
        "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles", status=403, json={"message": "Forbidden"}
    )
    hass.config_entries.async_update_entry(entry, data={**entry.data, "dvla_api_key": "set"})
    said = await tested({})
    assert said.startswith("The DVLA didn't answer as expected for A123TST: 403 Forbidden.")
    assert aioclient_mock.mock_calls[-1][3]["x-api-key"] == "set"


async def test_visitor_said(hass: HomeAssistant):
    from custom_components.camera_autonotify.plates import History, Match
    from custom_components.camera_autonotify.vehicles import Vehicle

    add_frigate(hass)
    await async_load_texts(hass)
    regular = Vehicle(Match("PX19TVD", "PX19TVD"), History(previous_sightings=12, visitor="daily"))
    assert notifier(hass).said_vehicle(regular) == ["PX19TVD", "Previous sightings: 12", "Daily visitor"]


def test_named_by_each_registers_own_fields(monkeypatch: pytest.MonkeyPatch):
    """By the register's own fields, one set for a known vehicle and one for an unknown, and nothing for a register
    with no naming yet"""
    dvla = {"make": "LAND ROVER", "colour": "RED"}
    assert vehicle_named("dvla", dvla, "unknown") == "Red Land Rover"
    assert vehicle_named("dvla", {"make": "BMW", "colour": "BLACK"}, "known") == "Black BMW"
    assert vehicle_named("dvla", {}, "unknown") is None
    assert vehicle_named("rdw", {"merk": "PEUGEOT"}, "unknown") is None
    monkeypatch.setitem(NAMING, "rdw", Naming(known=("merk",), unknown=("eerste_kleur", "merk")))
    rdw = {"merk": "PEUGEOT", "eerste_kleur": "ROOD"}
    assert (vehicle_named("rdw", rdw, "known"), vehicle_named("rdw", rdw, "unknown")) == ("Peugeot", "Rood Peugeot")
