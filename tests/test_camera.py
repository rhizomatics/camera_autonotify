"""The Last notification snapshot camera, of the snapshot last notified, for a dashboard"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import ClientError
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.helpers import entity_registry as er

from custom_components.camera_autonotify.camera import LastSnapshotCamera
from custom_components.camera_autonotify.const import DOMAIN

from .conftest import FakeMQTT, add_frigate
from .test_discovery import set_up_discovery
from .test_notifier import DETECTION, ENTRY_ID, notifier
from .test_settings import entry_titled

if TYPE_CHECKING:
    from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

SNAPSHOT = f"http://10.0.0.2:8123/api/frigate/notifications/{DETECTION}/snapshot.jpg"


async def test_reads_notified_snapshot(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    await async_process_ha_core_config(hass, {"internal_url": "http://10.0.0.2:8123", "external_url": "https://x.example"})
    add_frigate(hass)
    found = notifier(hass, options={"last_snapshot": True})
    camera = LastSnapshotCamera(hass, found.entry, found, f"{ENTRY_ID}_last_snapshot")
    # nothing notified yet
    assert await camera.async_camera_image() is None
    aioclient_mock.get(SNAPSHOT, content=b"jpeg")
    found.last_snapshot = DETECTION
    # from Home Assistant itself, once for the detection
    assert await camera.async_camera_image() == b"jpeg"
    assert await camera.async_camera_image() == b"jpeg"
    assert aioclient_mock.call_count == 1


async def test_snapshot_not_fetched(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    await async_process_ha_core_config(hass, {"internal_url": "http://10.0.0.2:8123"})
    add_frigate(hass)
    found = notifier(hass, options={"last_snapshot": True})
    found.last_snapshot = DETECTION
    camera = LastSnapshotCamera(hass, found.entry, found, f"{ENTRY_ID}_last_snapshot")
    aioclient_mock.get(SNAPSHOT, exc=ClientError("refused"))
    assert await camera.async_camera_image() is None


async def test_only_where_chosen(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = entry_titled(hass, "Courtyard")
    registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_last_snapshot"
    assert registry.async_get_entity_id(Platform.CAMERA, DOMAIN, unique_id) is None

    hass.config_entries.async_update_entry(entry, options={"last_snapshot": True})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    entity_id = registry.async_get_entity_id(Platform.CAMERA, DOMAIN, unique_id)
    assert entity_id is not None
    assert hass.states.get(entity_id) is not None

    # gone again, not left unavailable
    hass.config_entries.async_update_entry(entry, options={})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_entity_id(Platform.CAMERA, DOMAIN, unique_id) is None


async def test_no_url_for_home_assistant(hass: HomeAssistant):
    add_frigate(hass)
    found = notifier(hass, options={"last_snapshot": True})
    found.last_snapshot = DETECTION
    assert await LastSnapshotCamera(hass, found.entry, found, "x").async_camera_image() is None


async def test_never_a_zones(hass: HomeAssistant, fake_mqtt: FakeMQTT):
    from .test_settings import fields_of, open_settings

    add_frigate(hass)
    await set_up_discovery(hass, discover_zones=True)
    assert "notify.last_snapshot" in fields_of(await open_settings(hass))
    assert "notify.last_snapshot" not in fields_of(await open_settings(hass, "Pend"))
