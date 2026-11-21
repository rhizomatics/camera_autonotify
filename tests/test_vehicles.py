"""Vehicles for any source of plates: classified, looked up, their history kept, in Frigate's notifications and
anpr2mqtt's, by an action, and imported from anpr2mqtt"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Self, cast

import pytest
from aiohttp import ClientSession
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_TYPE
from homeassistant.core import Context, HomeAssistant, ServiceCall, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.camera_autonotify.anpr import AnprNotifier, Sighting
from custom_components.camera_autonotify.compat import vol
from custom_components.camera_autonotify.const import DOMAIN, SUBENTRY_PLATES, TYPE_DISCOVERY
from custom_components.camera_autonotify.facts import FactStore
from custom_components.camera_autonotify.frigate import fact_stores
from custom_components.camera_autonotify.texts import async_load_texts
from custom_components.camera_autonotify.vehicles import (
    ISSUE_LOOKUP_REFUSED,
    DvlaProvider,
    LookupRefused,
    VehicleLookup,
    vehicles,
)
from tests.ha_testing import MockConfigEntry, async_fire_time_changed

from .conftest import add_frigate, mock_supernotify
from .test_notifier import DETECTION, decision, notifier

NOW = datetime(2026, 11, 19, 14, 25, tzinfo=dt_util.UTC)
FAMILY = {"plates": [{"plate": "TJ912UKL", "description": "Joe's mini", "corrections": ["J912UKL"]}]}


class FakeRegister:
    """A vehicle register, knowing the plates given"""

    name = "dvla"

    def __init__(self, known: dict[str, VehicleLookup] | None = None, refuse: bool = False) -> None:
        self.known = known or {}
        self.refuse = refuse
        self.asked: list[str] = []

    async def async_lookup(self, plate: str) -> VehicleLookup | None:
        self.asked.append(plate)
        if self.refuse:
            raise LookupRefused
        return self.known.get(plate)


PICKUP_TRUCK = VehicleLookup("dvla", "MITSUBISHI", "WHITE", 2019, "PETROL", "Taxed", "Valid", {"make": "MITSUBISHI"})


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
    assert (await vehicles(hass).async_classify("PX19TVD")).lookup is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_LOOKUP_REFUSED) is not None
    vehicles(hass).provider = FakeRegister()
    await vehicles(hass).async_classify("AB12CDE")
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_LOOKUP_REFUSED) is None


async def test_failing_register_logged(hass: HomeAssistant, caplog: pytest.LogCaptureFixture):
    class Broken(FakeRegister):
        async def async_lookup(self, plate: str) -> VehicleLookup | None:
            raise OSError("timed out")

    global_settings(hass)
    vehicles(hass).provider = Broken()
    assert (await vehicles(hass).async_classify("PX19TVD")).lookup is None
    assert "couldn't look up PX19TVD: timed out" in caplog.text


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
    assert vehicles(hass).sightings("PX19TVD")


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
    def __init__(self, status: int, body: dict[str, Any] | None = None) -> None:
        self.status = status
        self.body = body or {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise OSError(f"status {self.status}")

    async def json(self) -> dict[str, Any]:
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
    assert looked_up == VehicleLookup("dvla", "MITSUBISHI", "WHITE", 2019, "PETROL", "Taxed", "Valid", raw)
    assert session.posted[0]["headers"]["x-api-key"] == "key"
    assert session.posted[0]["json"] == {"registrationNumber": "PX19TVD"}
    assert await DvlaProvider(as_session(FakeSession(FakeResponse(404))), "key").async_lookup("X") is None
    with pytest.raises(LookupRefused):
        await DvlaProvider(as_session(FakeSession(FakeResponse(403))), "key").async_lookup("X")
    with pytest.raises(OSError, match="status 500"):
        await DvlaProvider(as_session(FakeSession(FakeResponse(500))), "key").async_lookup("X")


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


async def test_event_for_each_sighting(hass: HomeAssistant, register: FakeRegister):
    """As OpenALPR's, plate, entity and confidence first, then what's known here"""
    add_frigate(hass)
    global_settings(hass, {"Family cars": FAMILY})
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


async def test_history_kept_by_salted_hash(
    hass: HomeAssistant, hass_storage: dict[str, Any], frozen: FrozenDateTimeFactory, register: FakeRegister
):
    """Never by the plate, history or lookups, the betas' history, kept by plate, rewritten by hash and merged, and
    their lookups, by plate, dropped"""
    hashed = salted("PX19TVD")
    hass_storage["camera_autonotify.plate_salt"] = stored("plate_salt", {"salt": SALT})
    hass_storage["camera_autonotify.plate_history"] = stored(
        "plate_history", {"PX19TVD": ["2026-11-01T08:00:00+00:00"], hashed: ["2026-11-02T08:00:00+00:00"]}
    )
    hass_storage["camera_autonotify.plate_lookup"] = stored(
        "plate_lookup", {"dvla:AB12CDE": {"at": NOW.isoformat(), "found": None}}
    )
    global_settings(hass)
    assert vehicles(hass).sightings("PX19TVD") == []
    vehicle = await vehicles(hass).async_classify("PX19TVD", record=True)
    assert vehicle.history is not None and vehicle.history.previous_sightings == 2
    assert vehicle.lookup == PICKUP_TRUCK
    await vehicles(hass).async_classify("AB12CDE", record=True)
    # looked up again, the beta's cached lookup being dropped
    assert register.asked == ["PX19TVD", "AB12CDE"]
    # once saved, after the store's delay
    frozen.tick(11)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    history = hass_storage["camera_autonotify.plate_history"]["data"]
    assert set(history) == {hashed, salted("AB12CDE")}
    lookups = hass_storage["camera_autonotify.plate_lookup"]["data"]
    assert set(lookups) == {f"dvla:{hashed}", f"dvla:{salted('AB12CDE')}"}
    for data in (history, lookups):
        assert "PX19TVD" not in str(data) and "AB12CDE" not in str(data)


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


async def test_visitor_said(hass: HomeAssistant):
    from custom_components.camera_autonotify.plates import History, Match
    from custom_components.camera_autonotify.vehicles import Vehicle

    add_frigate(hass)
    await async_load_texts(hass)
    regular = Vehicle(Match("PX19TVD", "PX19TVD"), History(previous_sightings=12, visitor="daily"))
    assert notifier(hass).said_vehicle(regular) == ["PX19TVD", "Previous sightings: 12", "Daily visitor"]


# --- plates read by an image processing ANPR/ALPR entity, such as OpenALPR's

ALPR = "image_processing.openalpr_courtyard"


def openalpr(hass: HomeAssistant, plates: dict[str, float], fail: bool = False) -> list[ServiceCall]:
    """OpenALPR's entity, its scan setting its plates, by confidence as a percentage, or failing"""
    hass.states.async_set(ALPR, "unknown", {"device_class": "alpr", "plates": {}})
    scans: list[ServiceCall] = []

    async def scan(call: ServiceCall) -> None:
        scans.append(call)
        if fail:
            raise HomeAssistantError("OpenALPR not answering")
        best = max(plates, key=plates.__getitem__) if plates else None
        hass.states.async_set(ALPR, best or "unknown", {"device_class": "alpr", "plates": plates})

    hass.services.async_register("image_processing", "scan", scan)
    return scans


async def test_alpr_read(hass: HomeAssistant, register: FakeRegister):
    add_frigate(hass)
    global_settings(hass, {"Family cars": FAMILY})
    scans = openalpr(hass, {"PX19TVD": 92.5, "PX19TV0": 60.0})
    fired: list[dict[str, Any]] = []
    hass.bus.async_listen("camera_autonotify_vehicle", lambda event: fired.append(dict(event.data)))
    found = notifier(hass, options={"alpr_entity": ALPR})
    car = replace(decision(), review=replace(decision().review, objects=("car",)))
    vehicle = await found.async_vehicle(car)
    assert vehicle is not None
    assert (vehicle.plate, vehicle.lookup) == ("PX19TVD", PICKUP_TRUCK)
    # once for the review
    await found.async_vehicle(car)
    await hass.async_block_till_done()
    assert len(scans) == 1
    assert (fired[0]["source"], fired[0]["confidence"]) == ("openalpr", 0.925)


async def test_alpr_only_for_vehicles(hass: HomeAssistant):
    add_frigate(hass)
    scans = openalpr(hass, {"PX19TVD": 92.5})
    assert await notifier(hass, options={"alpr_entity": ALPR}).async_vehicle(decision()) is None
    assert scans == []
    # unless chosen otherwise
    found = notifier(hass, options={"alpr_entity": ALPR, "alpr_vehicles_only": False})
    assert await found.async_vehicle(decision()) is not None


async def test_alpr_not_sure_enough(hass: HomeAssistant):
    add_frigate(hass)
    openalpr(hass, {"PX19TVD": 70.0})
    car = replace(decision(), review=replace(decision().review, objects=("car",)))
    assert await notifier(hass, options={"alpr_entity": ALPR}).async_vehicle(car) is None


async def test_alpr_failing(hass: HomeAssistant, caplog: pytest.LogCaptureFixture):
    add_frigate(hass)
    openalpr(hass, {"PX19TVD": 92.5}, fail=True)
    car = replace(decision(), review=replace(decision().review, objects=("car",)))
    assert await notifier(hass, options={"alpr_entity": ALPR}).async_vehicle(car) is None
    assert "couldn't read a plate: OpenALPR not answering" in caplog.text


async def test_alpr_before_frigate_plate(hass: HomeAssistant):
    """Chosen where Frigate's own reading is poor, so read first, Frigate's plate only where it reads none"""
    add_frigate(hass)
    scans = openalpr(hass, {"AB12CDE": 99.0})
    read_plate(hass)
    car = replace(decision(), review=replace(decision().review, objects=("car",)))
    vehicle = await notifier(hass, options={"alpr_entity": ALPR}).async_vehicle(car)
    assert vehicle is not None and vehicle.plate == "AB12CDE"
    assert len(scans) == 1
    # nothing read by it, so Frigate's
    openalpr(hass, {})
    other = replace(car, review=replace(car.review, id="another_review"))
    vehicle = await notifier(hass, options={"alpr_entity": ALPR}).async_vehicle(other)
    assert vehicle is not None and vehicle.plate == "PX19TVD"


async def test_alpr_setting_offered_for_every_camera(hass: HomeAssistant):
    """Even before there's an ANPR/ALPR entity, so it can be found, there being no telling which cameras see vehicles"""
    from .test_discovery import set_up_discovery
    from .test_settings import fields_of, open_settings

    add_frigate(hass)
    await set_up_discovery(hass, discover_zones=True)
    assert {"plates.alpr_entity", "plates.alpr_vehicles_only"} <= set(fields_of(await open_settings(hass)))
    # not for a zone, which has no camera of its own
    assert "plates.alpr_entity" not in fields_of(await open_settings(hass, "Pend"))
