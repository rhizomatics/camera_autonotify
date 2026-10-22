from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.frigate_autonotify.const import CONF_INITIAL_DELAY, CONF_LABELS, DOMAIN
from custom_components.frigate_autonotify.diagnostics import async_get_config_entry_diagnostics

from .conftest import FakeMQTT, add_frigate, mock_supernotify
from .test_discovery import set_up_discovery
from .test_settings import entry_titled
from .test_tracker import message, review

TOPIC = "frigate/reviews"


async def test_review_notified(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up_discovery(hass)
    # one subscription, for both cameras
    assert len(fake_mqtt.subscriptions[TOPIC]) == 1

    fake_mqtt.publish(TOPIC, message("new", review("courtyard", zones=["Barn_Door"])))
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data["title"] == "Courtyard"
    assert calls[0].data["message"] == "Person detected in Barn Door"


async def test_updates_tied_to_first(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up_discovery(hass)
    fake_mqtt.publish(TOPIC, message("new", review("courtyard", objects=["person"])))
    fake_mqtt.publish(TOPIC, message("update", review("courtyard", objects=["person", "car"])))
    await hass.async_block_till_done()
    assert [call.data["priority"] for call in calls] == ["high", "low"]
    assert calls[1].context.parent_id == calls[0].context.id

    fake_mqtt.publish(TOPIC, message("end", review("courtyard")))
    await hass.async_block_till_done()
    assert entry_titled(hass, "Courtyard").runtime_data.reviews == []


async def test_initial_delay_timed(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    hass.config_entries.async_update_entry(entry, options={CONF_INITIAL_DELAY: 5})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    fake_mqtt.publish(TOPIC, message("new", review("courtyard", objects=["person"])))
    fake_mqtt.publish(TOPIC, message("update", review("courtyard", objects=["person", "car"])))
    await hass.async_block_till_done()
    assert calls == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data["message"] == "Person and Car detected in Barn Door"


async def test_unload_stops_everything(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    hass.config_entries.async_update_entry(entry, options={CONF_INITIAL_DELAY: 5})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    fake_mqtt.publish(TOPIC, message("new", review("courtyard")))

    for each in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(each.entry_id)
    await hass.async_block_till_done()
    assert fake_mqtt.subscriptions[TOPIC] == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert calls == []


async def test_settings_applied(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    hass.config_entries.async_update_entry(entry, options={CONF_LABELS: ["car"]})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    fake_mqtt.publish(TOPIC, message("new", review("courtyard", objects=["person"])))
    await hass.async_block_till_done()
    assert calls == []


async def test_zone_hears_every_camera(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up_discovery(hass, discover_zones=True)
    # the driveway camera, and the pend zone it's in, and not the courtyard camera
    fake_mqtt.publish(TOPIC, message("new", review("driveway", zones=["Driveway", "Pend"])))
    await hass.async_block_till_done()
    assert sorted(call.data["title"] for call in calls) == ["Driveway", "Pend"]
    assert next(call for call in calls if call.data["title"] == "Pend").data["message"] == "Car detected on Driveway"


async def test_review_not_understood(hass: HomeAssistant, fake_mqtt: FakeMQTT, caplog: pytest.LogCaptureFixture):
    add_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up_discovery(hass)
    fake_mqtt.publish(TOPIC, "not json")
    await hass.async_block_till_done()
    assert calls == []
    assert "Review not understood" in caplog.text


async def test_waits_for_frigate(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    hass.data["frigate"].clear()
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_waits_for_mqtt(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    fake_mqtt.available = False
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    mock_supernotify(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    hass.config_entries.async_update_entry(entry, options={"target": {"entity_id": ["person.jeff"]}})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    fake_mqtt.publish(TOPIC, message("new", review("courtyard")))
    await hass.async_block_till_done()
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["options"] == {"target": "**REDACTED**"}
    assert diagnostics["reviews"] == [review("courtyard")["id"]]
    discovery = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.title == "Automatic discovery")
    assert (await async_get_config_entry_diagnostics(hass, discovery))["reviews"] == []
