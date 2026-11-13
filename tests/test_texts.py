"""The translations: every text of a notification and of the setup screens, object names, and the exceptions"""

from __future__ import annotations

import json
import string
from datetime import date
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant

from custom_components.camera_autonotify import texts
from custom_components.camera_autonotify.const import (
    CONF_AUTO_DISCOVER,
    CONF_DISCOVER_ZONES,
    CONF_IMAGE,
    CONF_OBJECT_NAMES,
    DOMAIN,
    TYPE_DISCOVERY,
)
from custom_components.camera_autonotify.frigate import all_labels, image_url
from custom_components.camera_autonotify.notifier import object_names
from custom_components.camera_autonotify.texts import async_load_texts, text
from custom_components.camera_autonotify.tracker import Review
from tests.ha_testing import MockConfigEntry

from .conftest import EN_JSON, FakeMQTT, add_frigate
from .test_discovery import set_up_discovery
from .test_notifier import BASE, DETECTION, REVIEW_ID, decision, external_url, notifier  # noqa: F401
from .test_settings import entry_titled, fields_of, open_settings

COMMON: dict[str, str] = json.loads(EN_JSON.read_text())["common"]


def test_every_text_translated():
    keys = {
        value
        for name, value in vars(texts).items()
        if name.isupper() and isinstance(value, str) and name not in {"CATEGORY", "PREFIX", "DOMAIN"}
    }
    keys |= {*texts.WEEKDAYS, *texts.MONTHS}
    assert keys == set(COMMON)


async def test_text_before_loaded_is_its_key(hass: HomeAssistant):
    hass.config.language = "xx"
    assert text(hass, texts.HEADLINE, label="Person", where="Gate") == texts.HEADLINE


async def test_english_where_not_translated(hass: HomeAssistant):
    # no translation of the language, so English
    hass.config.language = "cy"
    await async_load_texts(hass)
    assert text(hass, texts.HEADLINE, label="Person", where="Gate") == "Person detected at Gate"


async def test_text_with_placeholders_missing(hass: HomeAssistant):
    await async_load_texts(hass)
    assert text(hass, texts.HEADLINE) == COMMON[texts.HEADLINE]


@pytest.mark.parametrize(
    ("objects", "names", "said"),
    [
        (("person",), {}, "Person"),
        (("person", "car"), {}, "Person and Car"),
        (("person", "car", "dog"), {}, "Person and Car and Dog"),
        (("car",), {"car": "Vehicle"}, "Vehicle"),
        # named the same, so said once
        (("car", "motorcycle", "person"), {"car": "Vehicle", "motorcycle": "Vehicle"}, "Vehicle and Person"),
        ((), {}, "Something"),
    ],
)
def test_review_said(objects: tuple[str, ...], names: dict[str, str], said: str):
    review = Review(REVIEW_ID, "gate", "alert", objects, (), (), (), ended=False)
    assert review.said(names) == said


def test_review_said_in_another_language():
    review = Review(REVIEW_ID, "gate", "alert", ("person", "car"), ("Jeff",), (), (), ended=False)
    assert review.said({"person": "Personne", "car": "Voiture"}, "{first} et {second}") == "Personne et Voiture (Jeff)"
    assert Review(REVIEW_ID, "gate", "alert", (), (), (), (), ended=False).said(nothing="Quelque chose") == "Quelque chose"


def add_global_settings(hass: HomeAssistant, options: dict[str, Any]) -> None:
    MockConfigEntry(domain=DOMAIN, data={CONF_TYPE: TYPE_DISCOVERY}, options=options).add_to_hass(hass)


async def test_object_names(hass: HomeAssistant):
    assert object_names(hass) == {}
    add_global_settings(
        hass,
        {
            CONF_OBJECT_NAMES: [
                {"object": "car", "name": " Vehicle "},
                {"object": "dog", "name": ""},
                {"object": "", "name": "Nothing"},
                "not a mapping",
            ]
        },
    )
    assert object_names(hass) == {"car": "Vehicle"}


async def test_object_names_in_headline(hass: HomeAssistant):
    add_global_settings(hass, {CONF_OBJECT_NAMES: [{"object": "person", "name": "Visitor"}]})
    await async_load_texts(hass)
    assert notifier(hass).title(decision(zones=())) == "Visitor detected at Courtyard"


@pytest.mark.parametrize(
    ("image", "path"),
    [
        (None, "snapshot.jpg"),
        ("snapshot", "snapshot.jpg"),
        ("snapshot_box", "snapshot.jpg?bbox=1"),
        ("snapshot_crop", "snapshot.jpg?crop=1"),
        ("thumbnail", "thumbnail.jpg"),
        ("unknown", "snapshot.jpg"),
    ],
)
def test_image_url(image: str | None, path: str):
    assert image_url("https://ha/api/frigate/notifications", "abc", image) == f"https://ha/api/frigate/notifications/abc/{path}"


async def test_image_chosen(hass: HomeAssistant, external_url: None):  # noqa: F811
    await async_load_texts(hass)
    data = notifier(hass, options={CONF_IMAGE: "snapshot_crop"}).supernotify_data(decision())
    notifications = f"{BASE}/api/frigate/notifications/{DETECTION}"
    assert data["media"]["snapshot_url"] == f"{notifications}/snapshot.jpg?crop=1"
    # the button still shows the whole snapshot
    assert data["actions"][1] == {"action": "URI", "title": "View snapshot", "uri": f"{notifications}/snapshot.jpg"}


async def test_image_offered_and_stored(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    form = await open_settings(hass)
    image = fields_of(form)["notify.image"]
    assert image.config["options"] == ["snapshot", "snapshot_box", "snapshot_crop", "thumbnail"]
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {"severities": ["alert"], "timing": {}, "notify": {CONF_IMAGE: "thumbnail"}}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert dict(entry.options) == {CONF_IMAGE: "thumbnail"}


async def test_object_names_in_global_settings(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    discovery = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data[CONF_TYPE] == TYPE_DISCOVERY)
    result = await hass.config_entries.options.async_init(discovery.entry_id)
    shown = fields_of(dict(result))
    named = shown[CONF_OBJECT_NAMES].config
    assert named["multiple"] is True
    assert named["fields"]["object"]["selector"]["select"]["options"] == ["bark", "car", "cat", "fox", "person"]
    names = [{"object": "car", "name": "Vehicle"}]
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_AUTO_DISCOVER: True, CONF_DISCOVER_ZONES: False, CONF_OBJECT_NAMES: names, "health": {}}
    )
    await hass.async_block_till_done()
    assert object_names(hass) == {"car": "Vehicle"}


async def test_all_labels(hass: HomeAssistant):
    assert all_labels(hass) == []
    add_frigate(hass)
    add_frigate(hass, cameras={"gate": []}, entry_id="02FRIGATE")
    assert all_labels(hass) == ["bark", "car", "cat", "fox", "person"]


async def test_retry_reasons_translated(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    hass.data["frigate"].clear()
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason == "Frigate isn't set up yet, so Courtyard can't be followed until it is"
    add_frigate(hass)
    fake_mqtt.available = False
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason == "MQTT isn't available, so Frigate's reviews can't be followed until it is"


def _flat(node: object, path: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        return {key: value for name, inner in node.items() for key, value in _flat(inner, f"{path}.{name}").items()}
    return {path: str(node)}


def _placeholders(value: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(value) if name}


@pytest.mark.parametrize("language", ["fr", "de", "it"])
def test_translation_complete(language: str):
    english = _flat(json.loads(EN_JSON.read_text()))
    translated = _flat(json.loads((EN_JSON.parent / f"{language}.json").read_text()))
    assert set(translated) == set(english)
    assert {key for key, value in translated.items() if _placeholders(value) != _placeholders(english[key])} == set()


async def test_notification_in_home_assistants_language(hass: HomeAssistant):
    hass.config.language = "fr"
    await async_load_texts(hass)
    assert notifier(hass).title(decision(zones=())) == "Détection : Person à Courtyard"
    assert texts.said_day(hass, date(2026, 11, 1)) == "dimanche 1 novembre"
    assert texts.said_duration(hass, 7380) == "2 heures 3 minutes"
