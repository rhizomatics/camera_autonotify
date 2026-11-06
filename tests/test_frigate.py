from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config

from custom_components.camera_autonotify.frigate import (
    base_url,
    frigate_config,
    hls_url,
    instance_id,
    notifications_url,
    proxy_problems,
    review_thumbnail_url,
    snapshot_url,
    topic_prefix,
)

from .conftest import FRIGATE_ENTRY_ID, add_frigate

BASE = "https://example.ui.nabu.casa"


async def test_config_of_server(hass: HomeAssistant):
    assert frigate_config(hass, FRIGATE_ENTRY_ID) is None
    add_frigate(hass)
    config = frigate_config(hass, FRIGATE_ENTRY_ID)
    assert config is not None
    assert set(config["cameras"]) == {"driveway", "courtyard"}
    assert topic_prefix(config) == "frigate"


def test_topic_prefix_default():
    assert topic_prefix(None) == "frigate"
    assert topic_prefix({"mqtt": {"topic_prefix": "nvr"}}) == "nvr"


async def test_base_url_prefers_external(hass: HomeAssistant):
    assert base_url(hass) is None
    await async_process_ha_core_config(hass, {"internal_url": "http://10.0.0.2:8123", "external_url": BASE})
    assert base_url(hass) == BASE


def test_proxy_urls():
    notifications = f"{BASE}/api/frigate/notifications"
    assert snapshot_url(notifications, "1792602227.86265-dyoaxn") == (
        f"{BASE}/api/frigate/notifications/1792602227.86265-dyoaxn/snapshot.jpg"
    )
    assert hls_url(notifications, "1792602227.86265-dyoaxn", "courtyard") == (
        f"{BASE}/api/frigate/notifications/1792602227.86265-dyoaxn/courtyard/master.m3u8"
    )
    assert review_thumbnail_url(notifications, "1792602227.99407-wz2vj1", "courtyard") == (
        f"{BASE}/api/frigate/notifications/1792602227.99407-wz2vj1/courtyard/review_thumbnail.webp"
    )


def test_instance_id():
    assert instance_id(None) is None
    assert instance_id({"mqtt": {}}) is None
    assert instance_id({"mqtt": {"client_id": "barn"}}) == "barn"


async def test_notifications_url_needs_a_base(hass: HomeAssistant):
    add_frigate(hass)
    assert notifications_url(hass, FRIGATE_ENTRY_ID) is None


async def test_notifications_url_single_server_without_instance(hass: HomeAssistant):
    await async_process_ha_core_config(hass, {"external_url": BASE})
    add_frigate(hass, client_id="barn")
    assert notifications_url(hass, FRIGATE_ENTRY_ID) == f"{BASE}/api/frigate/notifications"


async def test_notifications_url_each_of_several_servers_by_instance(hass: HomeAssistant):
    await async_process_ha_core_config(hass, {"external_url": BASE})
    add_frigate(hass, client_id="house")
    add_frigate(hass, cameras={}, entry_id="02FRIGATE", client_id="barn")
    assert notifications_url(hass, FRIGATE_ENTRY_ID) == f"{BASE}/api/frigate/house/notifications"
    assert notifications_url(hass, "02FRIGATE") == f"{BASE}/api/frigate/barn/notifications"


async def test_notifications_url_server_not_loaded_without_instance(hass: HomeAssistant):
    await async_process_ha_core_config(hass, {"external_url": BASE})
    add_frigate(hass, client_id="house")
    add_frigate(hass, cameras={}, entry_id="02FRIGATE", client_id="barn")
    hass.data["frigate"].pop("02FRIGATE")
    assert notifications_url(hass, "02FRIGATE") == f"{BASE}/api/frigate/notifications"


async def test_proxy_problems(hass: HomeAssistant):
    add_frigate(hass, title="House")
    assert proxy_problems(hass) == []
    add_frigate(hass, cameras={}, entry_id="02FRIGATE", title="Barn", options={"notification_proxy_enable": False})
    add_frigate(hass, cameras={}, entry_id="03FRIGATE", title="Gate", options={"notification_proxy_expire_after_seconds": 300})
    assert proxy_problems(hass) == [("Barn", 0), ("Gate", 300)]
    assert proxy_problems(hass, "03FRIGATE") == [("Gate", 300)]
    assert proxy_problems(hass, FRIGATE_ENTRY_ID) == []
