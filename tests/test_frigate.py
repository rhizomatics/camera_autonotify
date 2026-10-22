from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config

from custom_components.camera_autonotify.frigate import (
    base_url,
    frigate_config,
    hls_url,
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
    assert snapshot_url(BASE, "1792602227.86265-dyoaxn") == (
        f"{BASE}/api/frigate/notifications/1792602227.86265-dyoaxn/snapshot.jpg"
    )
    assert hls_url(BASE, "1792602227.86265-dyoaxn", "courtyard") == (
        f"{BASE}/api/frigate/notifications/1792602227.86265-dyoaxn/courtyard/master.m3u8"
    )
    assert review_thumbnail_url(BASE, "1792602227.99407-wz2vj1", "courtyard") == (
        f"{BASE}/api/frigate/notifications/1792602227.99407-wz2vj1/courtyard/review_thumbnail.webp"
    )
