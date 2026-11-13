from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from custom_components.camera_autonotify.const import (
    CONF_AUTO_DISCOVER,
    CONF_DISCOVER_ZONES,
    CONF_HEALTH_BACKOFF,
    CONF_HEALTH_CHECK,
    CONF_HEALTH_INTERVAL,
    CONF_HEALTH_RETRIES,
    CONF_MATCH,
    CONF_PATTERN,
    CONF_PRIORITY,
    CONF_SILENCE,
    CONF_SOURCE_ENTRY_ID,
    CONF_SOURCE_NAME,
    CONF_TARGETS,
    DISCOVERY_TITLE,
    DISCOVERY_TITLE_BEFORE,
    DOMAIN,
    TYPE_CAMERA,
    TYPE_DISCOVERY,
)
from custom_components.camera_autonotify.diagnostics import async_get_config_entry_diagnostics
from custom_components.camera_autonotify.health import (
    Change,
    Health,
    HealthMonitor,
    HealthSettings,
)
from custom_components.camera_autonotify.notifier import async_notify_message
from custom_components.camera_autonotify.texts import async_load_texts, said_duration
from tests.ha_testing import MockConfigEntry, async_fire_time_changed, async_mock_service

from .conftest import FakeFrigate, FakeMQTT, add_frigate, english, mock_supernotify

HEALTH_DOWN_TITLE = english("health_down_title")
HEALTH_UP_TITLE = english("health_up_title")
from .test_notifier import add_phone, add_rules

FRIGATE = "01FRIGATE"
TAG = f"camera_autonotify_health_{FRIGATE}"


def test_retries_back_off_before_failure_notified():
    health = Health(HealthSettings(retries=3, backoff=10))
    # each retry after twice the wait of the one before, and only the last failure notified
    assert [health.on_result(False, 100 + n) for n in range(4)] == [
        (None, 10.0),
        (None, 20.0),
        (None, 40.0),
        (Change.DOWN, None),
    ]
    # still down, checked again with the period, and not notified again
    assert health.on_result(False, 200) == (None, None)
    assert health.failing_since == 100
    assert health.on_result(True, 300) == (Change.UP, None)
    assert health.on_result(True, 360) == (None, None)
    assert (health.failures, health.down) == (0, False)


def test_answer_during_retries_forgets_failure():
    health = Health(HealthSettings(retries=2, backoff=5))
    assert health.on_result(False, 0) == (None, 5.0)
    assert health.on_result(True, 5) == (None, None)
    assert health.failing_since is None
    # counted from the start again
    assert health.on_result(False, 60) == (None, 5.0)
    assert health.failing_since == 60


def test_no_retries_notifies_first_failure():
    assert Health(HealthSettings(retries=0)).on_result(False, 0) == (Change.DOWN, None)


@pytest.mark.parametrize(
    ("seconds", "said"),
    [(1, "1 second"), (45, "45 seconds"), (60, "1 minute"), (190, "3 minutes"), (3600, "1 hour"), (7380, "2 hours 3 minutes")],
)
async def test_duration(hass: HomeAssistant, seconds: float, said: str):
    await async_load_texts(hass)
    assert said_duration(hass, seconds) == said


def test_settings_from_options():
    assert HealthSettings.from_options({}) == HealthSettings(enabled=True, interval=60, retries=3, backoff=10)
    # numbers come from the form as floats
    assert HealthSettings.from_options({
        CONF_HEALTH_CHECK: False,
        CONF_HEALTH_INTERVAL: 30.0,
        CONF_HEALTH_RETRIES: 0.0,
        CONF_HEALTH_BACKOFF: 0,
    }) == HealthSettings(enabled=False, interval=30, retries=0, backoff=1)


def loaded_frigate(hass: HomeAssistant, coordinator: bool = True) -> tuple[FakeFrigate, SimpleNamespace, AsyncMock]:
    """A Frigate server set up, with the Frigate integration's coordinator, polling its stats, and its API client"""
    frigate = add_frigate(hass)
    frigate.entry.mock_state(hass, ConfigEntryState.LOADED)
    stats = SimpleNamespace(
        last_update_success=True,
        data={"cameras": {"driveway": {"camera_fps": 5.0}, "courtyard": {"camera_fps": 6.1}}},
    )
    client = AsyncMock()
    client.async_get_version.return_value = "0.18.2"
    hass.data["frigate"][FRIGATE]["client"] = client
    if coordinator:
        hass.data["frigate"][FRIGATE]["coordinator"] = stats
    return frigate, stats, client


def add_camera_entry(hass: HomeAssistant, name: str = "courtyard", **options: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=name.title(),
        data={CONF_TYPE: TYPE_CAMERA, CONF_SOURCE_ENTRY_ID: FRIGATE, CONF_SOURCE_NAME: name},
        options=options,
        unique_id=name,
    )
    entry.add_to_hass(hass)
    return entry


async def set_up(
    hass: HomeAssistant, options: dict[str, Any] | None = None, title: str = DISCOVERY_TITLE
) -> config_entries.ConfigEntry:
    """The global settings entry, with the health check settings given"""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data={CONF_TYPE: TYPE_DISCOVERY},
        options={CONF_AUTO_DISCOVER: False, **(options or {})},
        unique_id=TYPE_DISCOVERY,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def monitor(entry: config_entries.ConfigEntry) -> HealthMonitor:
    assert isinstance(entry.runtime_data, HealthMonitor)
    return entry.runtime_data


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_old_title_renamed(hass: HomeAssistant):
    entry = await set_up(hass, title=DISCOVERY_TITLE_BEFORE)
    assert entry.title == "Global Settings"


async def test_server_failure_and_recovery_notified(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    _, stats, client = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    entry = await set_up(hass)

    await advance(hass, freezer, 60)
    assert calls == []

    stats.last_update_success = False
    await advance(hass, freezer, 60)
    # retried after 10, 20, then 40 seconds, only the last failure notified
    for wait in (10, 20, 39):
        await advance(hass, freezer, wait)
        assert calls == []
    await advance(hass, freezer, 1)
    assert len(calls) == 1
    assert calls[0].data["title"] == HEALTH_DOWN_TITLE
    assert calls[0].data["message"].startswith("frigate:5000 has failed its health check since ")
    assert calls[0].data["priority"] == "high"
    assert calls[0].data["extra_data"]["mobile_push_notification_tag"] == TAG

    # once a period while down, with nothing more said
    await advance(hass, freezer, 50)
    assert len(calls) == 1

    stats.last_update_success = True
    await advance(hass, freezer, 60)
    assert len(calls) == 2
    assert calls[1].data["title"] == HEALTH_UP_TITLE
    assert calls[1].data["message"] == "frigate:5000 is responding again, after 3 minutes."
    assert calls[1].data["priority"] == "low"
    # taking the place of the failure's notification
    assert calls[1].data["extra_data"]["mobile_push_notification_tag"] == TAG
    # read from what the Frigate integration polls, with nothing asked of Frigate itself
    assert client.async_get_version.await_count == 0

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["health"] == {FRIGATE: {"kind": "server", "name": "frigate:5000", "failures": 0, "down": False}}


async def test_server_asked_without_coordinator(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    _, _, client = loaded_frigate(hass, coordinator=False)
    calls = mock_supernotify(hass)
    client.async_get_version.side_effect = Exception("Connection refused")
    await set_up(hass, {CONF_HEALTH_RETRIES: 1})
    await advance(hass, freezer, 60)
    # the retry of the first failure, after the backoff, the check of the period skipped while it waits
    await advance(hass, freezer, 10)
    assert client.async_get_version.await_count == 2
    assert [call.data["title"] for call in calls] == [HEALTH_DOWN_TITLE]
    client.async_get_version.side_effect = None
    await advance(hass, freezer, 50)
    assert [call.data["title"] for call in calls] == [HEALTH_DOWN_TITLE, HEALTH_UP_TITLE]


async def test_frigate_failing_setup_counts_as_failure(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    frigate = add_frigate(hass)
    frigate.entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    add_camera_entry(hass)
    calls = mock_supernotify(hass)
    await set_up(hass, {CONF_HEALTH_RETRIES: 0})
    await advance(hass, freezer, 60)
    # its cameras left out, with nothing to tell of them
    assert [call.data["title"] for call in calls] == [HEALTH_DOWN_TITLE]


async def test_frigate_not_set_up_yet_not_checked(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    entry = await set_up(hass, {CONF_HEALTH_RETRIES: 0})
    await advance(hass, freezer, 60)
    assert calls == []
    assert monitor(entry).states == {}


async def test_period_and_retries_as_set(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    stats.last_update_success = False
    entry = await set_up(hass, {CONF_HEALTH_INTERVAL: 300, CONF_HEALTH_RETRIES: 1, CONF_HEALTH_BACKOFF: 30})
    await advance(hass, freezer, 299)
    assert monitor(entry).states == {}
    await advance(hass, freezer, 1)
    assert monitor(entry).states[FRIGATE].failures == 1
    await advance(hass, freezer, 30)
    assert [call.data["title"] for call in calls] == [HEALTH_DOWN_TITLE]


async def test_server_check_switched_off(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    stats.last_update_success = False
    entry = await set_up(hass, {CONF_HEALTH_CHECK: False, CONF_HEALTH_RETRIES: 0})
    await advance(hass, freezer, 600)
    assert calls == []
    assert monitor(entry).states == {}


async def test_unload_stops_checks(hass: HomeAssistant, freezer: FrozenDateTimeFactory, fake_mqtt: FakeMQTT):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    stats.last_update_success = False
    entry = await set_up(hass)
    assert fake_mqtt.subscriptions["frigate/+/enabled/state"]
    await advance(hass, freezer, 60)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert fake_mqtt.subscriptions["frigate/+/enabled/state"] == []
    # neither the retry waiting nor the period
    await advance(hass, freezer, 600)
    assert calls == []


async def test_server_removed_forgotten(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    frigate, _, _ = loaded_frigate(hass)
    entry = await set_up(hass)
    await advance(hass, freezer, 60)
    assert set(monitor(entry).states) == {FRIGATE}
    await hass.config_entries.async_remove(frigate.entry.entry_id)
    await advance(hass, freezer, 60)
    assert monitor(entry).states == {}


async def test_camera_offline_and_back(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    camera = add_camera_entry(hass, target={"entity_id": ["person.jeff"]})
    entry = await set_up(hass, {CONF_HEALTH_RETRIES: 1})

    stats.data["cameras"]["courtyard"]["camera_fps"] = 0
    await advance(hass, freezer, 60)
    assert calls == []
    await advance(hass, freezer, 10)
    assert len(calls) == 1
    assert calls[0].data["title"] == "Courtyard camera is offline"
    assert calls[0].data["message"].startswith("Frigate has had no video from Courtyard since ")
    # to whoever the camera's own notifications go to
    assert calls[0].data["target"] == {"entity_id": ["person.jeff"]}
    assert calls[0].data["extra_data"]["mobile_push_notification_tag"] == f"camera_autonotify_health_{camera.entry_id}"

    stats.data["cameras"]["courtyard"]["camera_fps"] = 5.9
    await advance(hass, freezer, 50)
    assert calls[1].data["title"] == "Courtyard camera is back"
    assert calls[1].data["message"] == "Frigate has video from Courtyard again, after 1 minute."
    assert monitor(entry).diagnostics()[camera.entry_id]["kind"] == "camera"


async def test_camera_disabled_in_frigate_not_notified(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, fake_mqtt: FakeMQTT
):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    hass.data["frigate"][FRIGATE]["config"]["cameras"]["courtyard"]["enabled"] = False
    add_camera_entry(hass)
    await set_up(hass, {CONF_HEALTH_RETRIES: 0})
    stats.data["cameras"]["courtyard"]["camera_fps"] = 0
    await advance(hass, freezer, 60)
    assert calls == []

    # enabled again, as Frigate says once switched
    fake_mqtt.publish("frigate/courtyard/enabled/state", "ON")
    await advance(hass, freezer, 60)
    assert [call.data["title"] for call in calls] == ["Courtyard camera is offline"]

    # disabled once offline, forgotten with nothing more said, even once its video is back
    fake_mqtt.publish("frigate/courtyard/enabled/state", "OFF")
    await advance(hass, freezer, 60)
    stats.data["cameras"]["courtyard"]["camera_fps"] = 6
    fake_mqtt.publish("frigate/courtyard/enabled/state", "ON")
    await advance(hass, freezer, 60)
    assert len(calls) == 1


async def test_camera_powered_off_not_notified(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set("switch.courtyard_poe", "on")
    camera = add_camera_entry(hass, power_entity="switch.courtyard_poe", power_grace=120)
    entry = await set_up(hass, {CONF_HEALTH_RETRIES: 0})
    await advance(hass, freezer, 60)

    # its PoE switched off for the day, so no video, and nothing said
    hass.states.async_set("switch.courtyard_poe", "off")
    stats.data["cameras"]["courtyard"]["camera_fps"] = 0
    await advance(hass, freezer, 60)
    await advance(hass, freezer, 60)
    assert calls == []
    assert camera.entry_id not in monitor(entry).states

    # switched on again, and given time to start up before it's checked
    hass.states.async_set("switch.courtyard_poe", "on")
    await advance(hass, freezer, 60)
    assert calls == []
    # still no video once started, so offline after all
    await advance(hass, freezer, 60)
    assert [call.data["title"] for call in calls] == ["Courtyard camera is offline"]


async def test_camera_powered_on_in_grace_keeps_offline(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    """An offline camera powered off and on between checks still says when it's back"""
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set("switch.courtyard_poe", "on")
    add_camera_entry(hass, power_entity="switch.courtyard_poe")
    await set_up(hass, {CONF_HEALTH_RETRIES: 0})
    # past the grace of it having come on
    await advance(hass, freezer, 180)
    stats.data["cameras"]["courtyard"]["camera_fps"] = 0
    await advance(hass, freezer, 60)
    assert [call.data["title"] for call in calls] == ["Courtyard camera is offline"]

    hass.states.async_set("switch.courtyard_poe", "off")
    hass.states.async_set("switch.courtyard_poe", "on")
    stats.data["cameras"]["courtyard"]["camera_fps"] = 5
    await advance(hass, freezer, 60)
    assert len(calls) == 1
    await advance(hass, freezer, 180)
    assert [call.data["title"] for call in calls][1:] == ["Courtyard camera is back"]


@pytest.mark.parametrize("power", ["unavailable", "unknown", None])
async def test_camera_checked_when_power_unknown(hass: HomeAssistant, freezer: FrozenDateTimeFactory, power: str | None):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    if power is not None:
        hass.states.async_set("switch.courtyard_poe", power)
    add_camera_entry(hass, power_entity="switch.courtyard_poe", power_grace=0)
    await set_up(hass, {CONF_HEALTH_RETRIES: 0})
    stats.data["cameras"]["courtyard"]["camera_fps"] = 0
    await advance(hass, freezer, 60)
    assert [call.data["title"] for call in calls] == ["Courtyard camera is offline"]


async def test_camera_check_switched_off(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    add_camera_entry(hass, status_check=False)
    entry = await set_up(hass, {CONF_HEALTH_RETRIES: 0})
    stats.data["cameras"]["courtyard"]["camera_fps"] = 0
    await advance(hass, freezer, 60)
    assert calls == []
    assert set(monitor(entry).states) == {FRIGATE}


async def test_cameras_not_checked_while_server_failing(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    add_camera_entry(hass)
    await set_up(hass, {CONF_HEALTH_RETRIES: 0})
    stats.last_update_success = False
    await advance(hass, freezer, 60)
    assert [call.data["title"] for call in calls] == [HEALTH_DOWN_TITLE]


async def test_camera_failures_forgotten_while_server_failing(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    """A camera failing its retries as its server stops answering starts its retries over once it's back"""
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    camera = add_camera_entry(hass)
    entry = await set_up(hass, {CONF_HEALTH_CHECK: False, CONF_HEALTH_RETRIES: 2})
    stats.data["cameras"]["courtyard"]["camera_fps"] = 0
    await advance(hass, freezer, 60)
    await advance(hass, freezer, 10)
    assert monitor(entry).states[camera.entry_id].failures == 2

    # its retry while the server isn't answering, with no telling
    stats.last_update_success = False
    await advance(hass, freezer, 20)
    assert camera.entry_id not in monitor(entry).states

    # answering again, but the camera with no video yet, so its first failure, not its last
    stats.last_update_success = True
    await advance(hass, freezer, 30)
    assert monitor(entry).states[camera.entry_id].failures == 1
    assert calls == []


async def test_camera_offline_kept_while_server_failing(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    add_camera_entry(hass)
    await set_up(hass, {CONF_HEALTH_CHECK: False, CONF_HEALTH_RETRIES: 0})
    stats.data["cameras"]["courtyard"]["camera_fps"] = 0
    await advance(hass, freezer, 60)
    stats.last_update_success = False
    await advance(hass, freezer, 60)
    stats.last_update_success = True
    stats.data["cameras"]["courtyard"]["camera_fps"] = 5
    await advance(hass, freezer, 60)
    assert [call.data["title"] for call in calls] == ["Courtyard camera is offline", "Courtyard camera is back"]


async def test_camera_checked_with_server_check_off(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    add_camera_entry(hass)
    await set_up(hass, {CONF_HEALTH_CHECK: False, CONF_HEALTH_RETRIES: 0})
    stats.data["cameras"]["courtyard"]["camera_fps"] = 0
    await advance(hass, freezer, 60)
    assert [call.data["title"] for call in calls] == ["Courtyard camera is offline"]


async def test_camera_not_in_stats_not_checked(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    _, stats, _ = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    add_camera_entry(hass, "garden")
    await set_up(hass, {CONF_HEALTH_RETRIES: 0})
    stats.data = None
    await advance(hass, freezer, 60)
    assert calls == []


async def test_settings_in_global_options(hass: HomeAssistant):
    entry = await set_up(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "discovery"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_AUTO_DISCOVER: True,
            CONF_DISCOVER_ZONES: False,
            "health": {CONF_HEALTH_CHECK: True, CONF_HEALTH_INTERVAL: 120, CONF_HEALTH_RETRIES: 2, CONF_HEALTH_BACKOFF: 15},
        },
    )
    await hass.async_block_till_done()
    # stored flat, the section only for display
    assert dict(entry.options) == {
        CONF_AUTO_DISCOVER: True,
        CONF_DISCOVER_ZONES: False,
        CONF_HEALTH_CHECK: True,
        CONF_HEALTH_INTERVAL: 120,
        CONF_HEALTH_RETRIES: 2,
        CONF_HEALTH_BACKOFF: 15,
    }
    assert monitor(entry).settings == HealthSettings(interval=120, retries=2, backoff=15)
    # shown again as stored
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"] is not None
    health = next(field for key, field in result["data_schema"].schema.items() if str(key) == "health")
    suggested = {str(key): key.description["suggested_value"] for key in health.schema.schema}
    assert suggested[CONF_HEALTH_INTERVAL] == 120


async def test_message_without_supernotify_to_every_phone(hass: HomeAssistant):
    phone = add_phone(hass)
    calls = async_mock_service(hass, "notify", "send_message")
    await async_notify_message(hass, "Frigate is not responding", "frigate:5000 has failed", "high", TAG)
    assert [call.data for call in calls] == [
        {"entity_id": [phone], "title": "Frigate is not responding", "message": "frigate:5000 has failed"}
    ]


async def test_message_without_supernotify_to_camera_targets(hass: HomeAssistant):
    add_phone(hass)
    calls = async_mock_service(hass, "notify", "send_message")
    options = {CONF_TARGETS: ["notify.kitchen"]}
    await async_notify_message(hass, "Courtyard camera is offline", "No video", "high", TAG, options)
    assert [call.data["entity_id"] for call in calls] == [["notify.kitchen"]]


async def test_message_to_camera_deliveries(hass: HomeAssistant):
    calls = mock_supernotify(hass)
    options = {"deliveries": ["phones"], "custom_target": ["jeff@example.com"]}
    await async_notify_message(hass, "Courtyard camera is offline", "No video", "high", TAG, options)
    assert calls[0].data["delivery"] == ["phones"]
    assert calls[0].data["delivery_selection"] == "explicit"
    assert calls[0].data["custom_target"] == ["jeff@example.com"]


async def test_message_without_supernotify_or_phones(hass: HomeAssistant, caplog: pytest.LogCaptureFixture):
    calls = async_mock_service(hass, "notify", "send_message")
    await async_notify_message(hass, "Frigate is not responding", "frigate:5000 has failed", "high", TAG)
    assert calls == []
    assert "Nothing to notify Frigate is not responding to" in caplog.text


async def test_message_ruled(hass: HomeAssistant):
    calls = mock_supernotify(hass)
    add_rules(
        hass,
        {
            "name": "Frigate urgent",
            CONF_MATCH: "contains",
            CONF_PATTERN: "failed",
            CONF_PRIORITY: "critical",
            "scenarios": ["high_alert"],
        },
        {"name": "Quiet recovery", CONF_MATCH: "contains", CONF_PATTERN: "responding again", CONF_SILENCE: True},
    )
    await async_notify_message(hass, HEALTH_DOWN_TITLE, "frigate:5000 has failed its health check", "high", TAG)
    await async_notify_message(hass, HEALTH_UP_TITLE, "frigate:5000 is responding again", "low", TAG)
    assert [call.data["priority"] for call in calls] == ["critical"]
    assert calls[0].data["apply_scenarios"] == ["high_alert"]


async def test_message_failure_logged(hass: HomeAssistant, caplog: pytest.LogCaptureFixture):
    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("down")

    mock_supernotify(hass)
    hass.services.async_register("supernotify", "notify", fail)
    await async_notify_message(hass, HEALTH_DOWN_TITLE, "frigate:5000 has failed", "high", TAG)
    assert "Notification failed: Frigate is not responding" in caplog.text
