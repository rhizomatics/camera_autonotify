from __future__ import annotations

from typing import Any

import pytest
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
    TYPE_CAMERA,
    TYPE_ZONE,
)
from custom_components.camera_autonotify.notifier import Notifier
from custom_components.camera_autonotify.tracker import Decision, Reason, Review

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
        "title": "Courtyard",
        "message": "Person detected in Barn Door",
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
    ("kind", "zones", "reason", "message"),
    [
        (TYPE_CAMERA, (), Reason.NEW, "Person detected"),
        (TYPE_CAMERA, ("Barn_Door", "Back_Door"), Reason.NEW, "Person detected in Barn Door, Back Door"),
        (TYPE_CAMERA, ("Barn_Door",), Reason.FINAL, "Person detected in Barn Door, now ended"),
        (TYPE_ZONE, ("Pend",), Reason.NEW, "Person detected on Courtyard"),
    ],
)
async def test_message(hass: HomeAssistant, kind: str, zones: tuple[str, ...], reason: Reason, message: str):
    assert notifier(hass, kind).message(decision(reason=reason, zones=zones)) == message


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
    assert calls[0].data == {"entity_id": [phone], "title": "Courtyard", "message": "Person detected in Barn Door"}


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
