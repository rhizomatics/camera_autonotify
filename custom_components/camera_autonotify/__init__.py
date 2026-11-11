"""Camera AutoNotify - automatic notifications for Frigate camera reviews"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components import mqtt
from homeassistant.const import CONF_TYPE
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import CONF_SOURCE_ENTRY_ID, DISCOVERY_TITLE, DISCOVERY_TITLE_BEFORE, DOMAIN, TYPE_DISCOVERY
from .device import async_register_device
from .discovery import async_discover, async_start_discovery
from .frigate import frigate_config, topic_prefix
from .health import HealthMonitor, async_start_health_check
from .hub import ReviewWatcher, async_watch

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# a camera's or zone's reviews, or the health checks of the discovery entry, unless switched off
type CameraAutoNotifyConfigEntry = ConfigEntry[ReviewWatcher | HealthMonitor | None]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_start_discovery(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CameraAutoNotifyConfigEntry) -> bool:
    entry.runtime_data = None
    if entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
        # no reviews to watch, only to look again now that what's discovered may have been switched, and the health
        # of each Frigate server
        if entry.title == DISCOVERY_TITLE_BEFORE:
            hass.config_entries.async_update_entry(entry, title=DISCOVERY_TITLE)
        async_discover(hass)
        entry.runtime_data = async_start_health_check(hass, entry)
        return True
    config = frigate_config(hass, entry.data[CONF_SOURCE_ENTRY_ID])
    if config is None:
        raise ConfigEntryNotReady("Frigate isn't set up yet")
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT isn't available")
    watcher = ReviewWatcher(hass, entry)
    entry.async_on_unload(await async_watch(hass, topic_prefix(config), watcher))
    entry.runtime_data = watcher
    async_register_device(hass, entry, entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CameraAutoNotifyConfigEntry) -> bool:
    # the subscription and timers are stopped by the entry's own unload callbacks
    return True
