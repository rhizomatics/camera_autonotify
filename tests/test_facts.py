"""What Frigate knows of each tracked object beyond its review, and how it's said under the headline"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from homeassistant.core import HomeAssistant

from custom_components.camera_autonotify.facts import FactStore, ReviewFacts
from custom_components.camera_autonotify.frigate import fact_stores
from custom_components.camera_autonotify.texts import async_load_texts
from custom_components.camera_autonotify.tracker import Reason

from .conftest import FakeMQTT, add_frigate
from .test_discovery import set_up_discovery
from .test_notifier import DETECTION, decision, notifier
from .test_tracker import message, review


def event(object_id: str = DETECTION, **after: Any) -> dict[str, Any]:
    return {"type": "update", "after": {"id": object_id, "camera": "courtyard", "label": "car", **after}}


def test_highest_speed_kept():
    """Frigate's speeds at the end are of the object slowing to a stop, so the highest seen is what's said"""
    store = FactStore()
    for current, average in ((12.0, 10.0), (40.2, 25.0), (0.0, 9.1)):
        store.on_event(event(current_estimated_speed=current, average_estimated_speed=average), 1.0)
    assert store.of_review("courtyard", (DETECTION,)).speed == pytest.approx(40.2)


def test_best_plate_kept():
    store = FactStore()
    store.on_event(event(recognized_license_plate=["AB12CDF", 0.90]), 1.0)
    store.on_event(event(recognized_license_plate=["AB12CDE", 0.97]), 2.0)
    store.on_update({"type": "lpr", "id": DETECTION, "plate": "AB12CDE", "score": 0.95, "name": None}, 3.0)
    assert store.of_review("courtyard", (DETECTION,)).plates == ("AB12CDE",)
    # a known plate is a sub label of the review already, so not said again
    store.on_update({"type": "lpr", "id": DETECTION, "plate": "AB12CDE", "score": 0.98, "name": "Our car"}, 4.0)
    assert store.of_review("courtyard", (DETECTION,)).plates == ()


def test_attributes_but_not_face_or_plate():
    store = FactStore()
    store.on_event(
        event(
            current_attributes=[{"label": "royal_mail", "score": 0.8}, {"label": "license_plate", "score": 0.9}],
            attributes={"face": 0.7, "amazon": 0.6},
        ),
        1.0,
    )
    store.on_update({"type": "classification", "id": DETECTION, "model": "vans", "attribute": "dhl", "score": 0.9}, 2.0)
    assert store.of_review("courtyard", (DETECTION,)).attributes == ("royal_mail", "amazon", "dhl")


def test_face_not_recognised():
    store = FactStore()
    store.on_update({"type": "face", "id": DETECTION, "name": "unknown", "score": 0.3}, 1.0)
    assert store.of_review("courtyard", (DETECTION,), 0.9).face_unknown
    # a name below Frigate's threshold isn't recognised either
    store.on_update({"type": "face", "id": DETECTION, "name": "Joe", "score": 0.7}, 2.0)
    assert store.of_review("courtyard", (DETECTION,), 0.9).face_unknown
    store.on_update({"type": "face", "id": DETECTION, "name": "Joe", "score": 0.95}, 3.0)
    assert not store.of_review("courtyard", (DETECTION,), 0.9).face_unknown


def test_no_face_seen_says_nothing():
    """A person whose face Frigate never saw can't be said to be unrecognised"""
    store = FactStore()
    store.on_event(event(label="person"), 1.0)
    assert not store.of_review("courtyard", (DETECTION,), 0.9).face_unknown


def test_stopped_and_states_and_snapshot():
    store = FactStore()
    store.on_event(event(stationary=True, has_snapshot=True), 1.0)
    store.on_state("courtyard", "gate", "open")
    store.on_state("driveway", "gate", "closed")
    found = store.of_review("courtyard", (DETECTION,))
    assert found.stationary
    assert found.states == (("gate", "open"),)
    assert store.object(DETECTION).has_snapshot  # type: ignore[union-attr]  # ty: ignore[missing-union-attribute]


def test_nothing_known():
    store = FactStore()
    store.on_event({"type": "update"}, 1.0)
    store.on_update({"type": "description", "id": DETECTION, "description": "A car"}, 1.0)
    assert not store.of_review("courtyard", (DETECTION,))
    assert not ReviewFacts()


def test_forgotten_after_an_hour():
    store = FactStore()
    store.on_event(event(current_estimated_speed=30.0), 1.0)
    store.on_event(event("other"), 3602.0)
    assert store.object(DETECTION) is None


async def test_facts_from_mqtt_said_under_headline(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    await set_up_discovery(hass)
    await async_load_texts(hass)
    fake_mqtt.publish("frigate/events", event(current_estimated_speed=48.4, recognized_license_plate=["AB12CDE", 0.97]))
    fake_mqtt.publish("frigate/events", event(attributes={"royal_mail": 0.8}, stationary=True))
    fake_mqtt.publish("frigate/tracked_object_update", {"type": "face", "id": DETECTION, "name": "unknown", "score": 0.2})
    fake_mqtt.publish("frigate/courtyard/classification/gate", "open")
    assert fact_stores(hass)["frigate"].object(DETECTION) is not None
    title, outcome = notifier(hass).ruled(decision())
    # rules still match the headline, the facts going under it
    assert title == "Person detected at Barn Door"
    assert outcome.message == "48 km/h - AB12CDE - Royal Mail - Face not recognised - Not moving - Gate: open"


@pytest.mark.parametrize(
    ("frigate_units", "country", "chosen", "said"),
    [
        # Frigate's own unit converted to Home Assistant's, metric with no country here
        ("imperial", None, None, "49 km/h"),
        ("metric", None, None, "48 km/h"),
        # miles an hour where roads are signed in them, though Home Assistant is metric
        ("metric", "GB", None, "30 mph"),
        ("imperial", "GB", None, "30 mph"),
        # or as chosen in the global settings
        ("metric", "GB", "kmh", "48 km/h"),
        ("metric", "FR", "mph", "30 mph"),
    ],
)
async def test_speed_in_preferred_unit(
    hass: HomeAssistant, fake_mqtt: FakeMQTT, frigate_units: str, country: str | None, chosen: str | None, said: str
):
    add_frigate(hass)
    hass.data["frigate"]["01FRIGATE"]["config"]["ui"] = {"unit_system": frigate_units}
    await hass.config.async_update(country=country)
    await set_up_discovery(hass)
    if chosen:
        settings = next(e for e in hass.config_entries.async_entries("camera_autonotify") if e.data.get("type") == "discovery")
        hass.config_entries.async_update_entry(settings, options={**settings.options, "speed_unit": chosen})
    await async_load_texts(hass)
    speed = 30.2 if frigate_units == "imperial" else 48.4
    fake_mqtt.publish("frigate/events", event(current_estimated_speed=speed))
    assert notifier(hass).ruled(decision())[1].message == said


async def test_speed_in_mph_with_us_units(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    await hass.config.async_update(unit_system="us_customary")
    await set_up_discovery(hass)
    await async_load_texts(hass)
    fake_mqtt.publish("frigate/events", event(current_estimated_speed=48.4))
    assert notifier(hass).ruled(decision())[1].message == "30 mph"


async def test_genai_text_without_facts(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    """GenAI says more than the facts, so they're left out of its notifications"""
    add_frigate(hass)
    await set_up_discovery(hass)
    await async_load_texts(hass)
    fake_mqtt.publish("frigate/events", event(current_estimated_speed=48.0))
    found = decision()
    described = type(found)(found.review, found.reason, 1, False, description="A red van")
    assert notifier(hass).ruled(described)[1].message == "A red van"


async def test_no_facts_without_a_followed_camera(hass: HomeAssistant):
    add_frigate(hass)
    await async_load_texts(hass)
    assert notifier(hass).facts(decision()) == ""


async def test_facts_store_dropped_with_last_camera(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    await set_up_discovery(hass)
    assert "frigate" in fact_stores(hass)
    for entry in hass.config_entries.async_entries("camera_autonotify"):
        await hass.config_entries.async_unload(entry.entry_id)
    assert "frigate" not in fact_stores(hass)


async def test_odd_messages_ignored(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    await set_up_discovery(hass)
    fake_mqtt.publish("frigate/events", "not json")
    fake_mqtt.publish("frigate/tracked_object_update", "[1, 2]")
    fake_mqtt.publish("frigate/courtyard/classification", "open")
    fake_mqtt.publish("frigate/reviews", message("new", review("courtyard")))
    assert fact_stores(hass)["frigate"].object(DETECTION) is None


async def test_delivery_van_announced(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    """Issue #26: a DPD van, its logo both the object and an attribute, said as the brand, once, and spoken as the
    headline alone, not the facts read out like bullet points"""
    add_frigate(hass)
    await set_up_discovery(hass)
    await async_load_texts(hass)
    fake_mqtt.publish(
        "frigate/events",
        event(
            current_estimated_speed=33.8, recognized_license_plate=["MF98VNA", 0.95], attributes={"dpd": 0.8}, stationary=True
        ),
    )
    found = decision()
    van = type(found)(replace(found.review, objects=("dpd",)), found.reason, 0, False)
    data = notifier(hass).supernotify_data(van)
    assert data["title"] == "DPD detected at Barn Door"
    assert data["message"] == "34 km/h - MF98VNA - Not moving"
    assert data["spoken_message"] == "DPD detected at Barn Door"


async def test_genai_spoken_with_its_summary(hass: HomeAssistant):
    """What GenAI writes is for reading out, so it's said after the headline"""
    add_frigate(hass)
    await async_load_texts(hass)
    found = decision()
    described = type(found)(found.review, Reason.DESCRIPTION, 1, False, description="A courier leaves a parcel")
    data = notifier(hass).supernotify_data(described)
    assert data["spoken_message"] == "Person detected at Barn Door. A courier leaves a parcel"
