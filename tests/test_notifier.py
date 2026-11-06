from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_DEVICE_ID, CONF_TYPE
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.camera_autonotify.const import (
    CONF_CUSTOM_TARGET,
    CONF_DELIVERIES,
    CONF_SOURCE_ENTRY_ID,
    CONF_SOURCE_NAME,
    CONF_TARGET,
    CONF_TARGETS,
    DOMAIN,
    SUBENTRY_RULE,
    TYPE_CAMERA,
    TYPE_DISCOVERY,
    TYPE_ZONE,
)
from custom_components.camera_autonotify.notifier import Notifier, notification_rules
from custom_components.camera_autonotify.tracker import Decision, Reason, Review, Summary

from .conftest import FRIGATE_ENTRY_ID, add_frigate, mock_supernotify

BASE = "https://example.ui.nabu.casa"
DETECTION = "1792602227.86265-dyoaxn"
REVIEW_ID = "1792602227.99407-wz2vj1"


def decision(
    reason: Reason = Reason.NEW,
    previous: int = 0,
    silent: bool = False,
    severity: str = "alert",
    zones: tuple[str, ...] = ("Barn_Door",),
    camera: str = "courtyard",
    detections: tuple[str, ...] = (DETECTION,),
) -> Decision:
    review = Review(REVIEW_ID, camera, severity, ("person",), (), zones, detections, ended=reason is Reason.FINAL)
    return Decision(review, reason, previous, silent)


def notifier(
    hass: HomeAssistant, kind: str = TYPE_CAMERA, title: str = "Courtyard", options: dict[str, Any] | None = None
) -> Notifier:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data={CONF_DEVICE_ID: "x", CONF_TYPE: kind, CONF_SOURCE_ENTRY_ID: FRIGATE_ENTRY_ID, CONF_SOURCE_NAME: "x"},
        options=options or {},
    )
    entry.add_to_hass(hass)
    return Notifier(hass, entry)


@pytest.fixture
async def external_url(hass: HomeAssistant) -> None:
    await async_process_ha_core_config(hass, {"external_url": BASE})


async def test_new_alert(hass: HomeAssistant, external_url: None):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    await notifier(hass).async_notify(decision(), Context())
    assert len(calls) == 1
    assert calls[0].data == {
        "title": "Person detected at Barn Door",
        "message": "",
        "priority": "high",
        "extra_data": {"mobile_push_notification_tag": f"frigate_{REVIEW_ID}", "group": "frigate_courtyard"},
        "media": {
            "camera_entity_id": "camera.courtyard",
            "snapshot_url": f"{BASE}/api/frigate/notifications/{DETECTION}/snapshot.jpg",
        },
        "actions": [
            {"level": "notification", "uri": f"{BASE}/api/frigate/notifications/{DETECTION}/courtyard/master.m3u8"},
            {
                "action": "URI",
                "title": "View snapshot",
                "uri": f"{BASE}/api/frigate/notifications/{DETECTION}/snapshot.jpg",
            },
        ],
    }


@pytest.mark.parametrize(
    ("severity", "silent", "priority"),
    [("alert", False, "high"), ("detection", False, "medium"), ("alert", True, "low"), ("detection", True, "low")],
)
async def test_priority(hass: HomeAssistant, severity: str, silent: bool, priority: str):
    assert notifier(hass).supernotify_data(decision(severity=severity, silent=silent))["priority"] == priority


@pytest.mark.parametrize(
    ("kind", "zones", "reason", "title"),
    [
        (TYPE_CAMERA, (), Reason.NEW, "Person detected at Courtyard"),
        (TYPE_CAMERA, ("Barn_Door", "Back_Door"), Reason.NEW, "Person detected at Barn Door, Back Door"),
        (TYPE_CAMERA, ("Barn_Door",), Reason.FINAL, "Person detected at Barn Door, now ended"),
        (TYPE_ZONE, ("Pend",), Reason.NEW, "Person detected at Courtyard"),
    ],
)
async def test_title(hass: HomeAssistant, kind: str, zones: tuple[str, ...], reason: Reason, title: str):
    built = notifier(hass, kind)
    assert built.title(decision(reason=reason, zones=zones)) == title
    assert built.message(decision(reason=reason, zones=zones)) == ""


async def test_links_to_its_own_server(hass: HomeAssistant, external_url: None):
    add_frigate(hass, client_id="house")
    add_frigate(hass, cameras={}, entry_id="02FRIGATE", client_id="barn")
    data = notifier(hass).supernotify_data(decision())
    assert data["media"]["snapshot_url"] == f"{BASE}/api/frigate/house/notifications/{DETECTION}/snapshot.jpg"
    assert data["actions"][0]["uri"] == f"{BASE}/api/frigate/house/notifications/{DETECTION}/courtyard/master.m3u8"


async def test_no_links_without_a_url(hass: HomeAssistant):
    add_frigate(hass)
    data = notifier(hass).supernotify_data(decision())
    assert data["media"] == {"camera_entity_id": "camera.courtyard"}
    assert "actions" not in data


async def test_no_media_without_camera_or_detection(hass: HomeAssistant, external_url: None):
    data = notifier(hass).supernotify_data(decision(detections=()))
    assert "media" not in data
    assert "actions" not in data


async def test_deliveries_and_targets(hass: HomeAssistant):
    data = notifier(
        hass,
        options={
            CONF_DELIVERIES: ["mobile_push"],
            CONF_TARGET: {"entity_id": ["person.jeff"]},
            CONF_CUSTOM_TARGET: ["x@y.z"],
        },
    ).supernotify_data(decision())
    assert data["delivery"] == ["mobile_push"]
    assert data["delivery_selection"] == "explicit"
    assert data[CONF_TARGET] == {"entity_id": ["person.jeff"]}
    assert data[CONF_CUSTOM_TARGET] == ["x@y.z"]


async def test_supernotify_failure_logged(hass: HomeAssistant, caplog: pytest.LogCaptureFixture):
    mock_supernotify(hass)

    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("down")

    hass.services.async_register("supernotify", "notify", fail)
    await notifier(hass).async_notify(decision(), Context())
    assert "Supernotify notification failed for Courtyard" in caplog.text


def add_phone(hass: HomeAssistant, name: str = "jeffs_iphone") -> str:
    return er.async_get(hass).async_get_or_create("notify", "mobile_app", name, suggested_object_id=name).entity_id


async def test_without_supernotify_every_phone_told(hass: HomeAssistant):
    phone = add_phone(hass)
    calls = async_mock_service(hass, "notify", "send_message")
    await notifier(hass).async_notify(decision(), Context())
    assert len(calls) == 1
    assert calls[0].data == {"entity_id": [phone], "title": "Person detected at Barn Door", "message": ""}


async def test_without_supernotify_targets_chosen(hass: HomeAssistant):
    add_phone(hass)
    calls = async_mock_service(hass, "notify", "send_message")
    await notifier(hass, options={CONF_TARGETS: ["notify.kitchen"]}).async_notify(decision(), Context())
    assert calls[0].data["entity_id"] == ["notify.kitchen"]


async def test_without_supernotify_no_updates(hass: HomeAssistant):
    add_phone(hass)
    calls = async_mock_service(hass, "notify", "send_message")
    await notifier(hass).async_notify(decision(reason=Reason.LABEL, previous=1), Context())
    assert calls == []


async def test_without_supernotify_nobody_to_tell(hass: HomeAssistant, caplog: pytest.LogCaptureFixture):
    calls = async_mock_service(hass, "notify", "send_message")
    await notifier(hass).async_notify(decision(), Context())
    assert calls == []
    assert "Nothing to notify for Courtyard" in caplog.text


async def test_without_supernotify_failure_logged(hass: HomeAssistant, caplog: pytest.LogCaptureFixture):
    add_phone(hass)

    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("down")

    hass.services.async_register("notify", "send_message", fail)
    await notifier(hass).async_notify(decision(), Context())
    assert "Notification failed for Courtyard" in caplog.text


def summarised(level: int, concerns: tuple[str, ...] = (), previous: int = 1, silent: bool = True) -> Decision:
    review = Review(
        REVIEW_ID,
        "courtyard",
        "alert",
        ("person",),
        (),
        ("Barn_Door",),
        (DETECTION,),
        ended=True,
        summary=Summary("A person entering a barn", "A person walks to the barn.", level, concerns),
    )
    return Decision(review, Reason.SUMMARY, previous, silent)


def described(text: str, severity: str = "alert", silent: bool = True, tag_id: str | None = None) -> Decision:
    review = Review(REVIEW_ID, "courtyard", severity, ("person",), (), (), (DETECTION,), ended=True)
    return Decision(review, Reason.DESCRIPTION, 1, silent, description=text, described_id="object-1", tag_id=tag_id)


def add_rules(hass: HomeAssistant, *rules: dict[str, Any]) -> None:
    """The discovery entry, with a subentry for each rule"""
    MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TYPE: TYPE_DISCOVERY},
        subentries_data=[
            ConfigSubentryData(
                data={k: v for k, v in rule.items() if k != "name"},
                subentry_type=SUBENTRY_RULE,
                title=rule["name"],
                unique_id=None,
            )
            for rule in rules
        ],
    ).add_to_hass(hass)


@pytest.mark.parametrize(
    ("level", "priority"),
    # silent updates sound again once a summary is suspicious or worse
    [(0, "low"), (1, "high"), (2, "critical")],
)
async def test_summary(hass: HomeAssistant, level: int, priority: str):
    data = notifier(hass).supernotify_data(summarised(level, ("visitors entering barn",)))
    assert data["title"] == "A person entering a barn"
    assert data["message"] == "A person walks to the barn. (visitors entering barn)"
    assert data["priority"] == priority
    assert data["extra_data"]["mobile_push_notification_tag"] == f"frigate_{REVIEW_ID}"


async def test_summary_priorities_chosen(hass: HomeAssistant):
    options = {"priority_normal": "minimum", "priority_suspicious": "critical"}
    assert notifier(hass, options=options).supernotify_data(summarised(1))["priority"] == "critical"
    # sounding, without alert once
    assert notifier(hass, options=options).supernotify_data(summarised(0, silent=False))["priority"] == "minimum"
    assert notifier(hass).supernotify_data(summarised(0, silent=False))["priority"] == "medium"
    # a threat level beyond those known taken as the highest
    assert notifier(hass).supernotify_data(summarised(5))["priority"] == "critical"


async def test_summary_raised_by_rule_only(hass: HomeAssistant):
    add_rules(
        hass,
        {"name": "barn", "match": "contains", "pattern": "barn", "priority": "critical"},
        {"name": "person", "match": "contains", "pattern": "person", "priority": "minimum"},
    )
    assert notifier(hass).supernotify_data(summarised(1))["priority"] == "critical"


async def test_summary_not_lowered_by_rule(hass: HomeAssistant):
    add_rules(hass, {"name": "person", "match": "contains", "pattern": "person", "priority": "minimum"})
    assert notifier(hass).supernotify_data(summarised(1))["priority"] == "high"


async def test_description_ruled(hass: HomeAssistant):
    add_rules(
        hass,
        {"name": "High risk", "match": "regex", "pattern": r"^high risk\W*", "priority": "critical", "remove": True},
        {"name": "Scenario", "match": "contains", "pattern": "hoodies", "scenarios": ["high_alert", "noisy"]},
    )
    data = notifier(hass).supernotify_data(described("HIGH RISK. Two men in hoodies are in the courtyard."))
    assert data["title"] == "Person detected at Courtyard"
    assert data["message"] == "Two men in hoodies are in the courtyard."
    # raised above the alert's own, so it sounds despite alert once
    assert data["priority"] == "critical"
    assert data["apply_scenarios"] == ["high_alert", "noisy"]


async def test_headline_ruled_without_message(hass: HomeAssistant):
    """With no message, rules read the title"""
    add_rules(
        hass,
        {"name": "Barn", "match": "contains", "pattern": "barn", "priority": "critical"},
        {"name": "Detected", "match": "regex", "pattern": r"\s+detected\b", "remove": True},
    )
    data = notifier(hass).supernotify_data(decision(severity="detection"))
    assert data["title"] == "Person at Barn Door"
    assert data["message"] == ""
    assert data["priority"] == "critical"


async def test_headline_silenced(hass: HomeAssistant):
    add_rules(hass, {"name": "Barn", "match": "contains", "pattern": "barn door", "silence": True})
    calls = mock_supernotify(hass)
    await notifier(hass).async_notify(decision(), Context())
    assert calls == []


async def test_description_unruled_stays_silent(hass: HomeAssistant):
    data = notifier(hass).supernotify_data(described("A person is walking"))
    assert data["message"] == "A person is walking"
    assert data["priority"] == "low"
    assert "apply_scenarios" not in data


async def test_description_rule_below_own_priority(hass: HomeAssistant):
    """A rule sets the priority of a description, even below the review's own"""
    add_rules(hass, {"name": "Birds", "match": "starts_with", "pattern": "bird identified", "priority": "minimum"})
    data = notifier(hass).supernotify_data(described("BIRD IDENTIFIED blackbird", silent=False))
    assert data["priority"] == "minimum"


async def test_description_by_itself_tagged_by_object(hass: HomeAssistant, external_url: None):
    add_frigate(hass)
    data = notifier(hass).supernotify_data(described("A person", tag_id="object-1"))
    assert data["extra_data"]["mobile_push_notification_tag"] == "frigate_object-1"
    # the snapshot of the object described
    assert data["media"]["snapshot_url"] == f"{BASE}/api/frigate/notifications/object-1/snapshot.jpg"


async def test_silenced(hass: HomeAssistant):
    add_rules(hass, {"name": "No risk", "match": "regex", "pattern": r"^(no|low) risk\b", "silence": True})
    calls = mock_supernotify(hass)
    await notifier(hass).async_notify(described("NO RISK. Wendy in the barn."), Context())
    await notifier(hass).async_notify(described("LOW RISK. A van."), Context())
    assert calls == []
    await notifier(hass).async_notify(described("MEDIUM RISK. A van."), Context())
    assert len(calls) == 1


async def test_silenced_without_supernotify(hass: HomeAssistant):
    add_rules(hass, {"name": "No risk", "match": "starts_with", "pattern": "no risk", "silence": True})
    calls = async_mock_service(hass, "notify", "send_message")
    options = {CONF_TARGETS: ["notify.phone"]}
    first = Decision(Review(REVIEW_ID, "courtyard", "alert", (), (), (), (), ended=False), Reason.NEW, 0, False, "NO RISK")
    await notifier(hass, options=options).async_notify(first, Context())
    assert calls == []


async def test_unusable_rule_left_out(hass: HomeAssistant):
    add_rules(hass, {"name": "bad", "match": "regex", "pattern": "(", "silence": True})
    assert notification_rules(hass) == []
    assert notifier(hass).ruled(described("Anything"))[1].silence is False
