"""AutoNotify for Frigate - automatic notifications for Frigate camera reviews"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components import mqtt
from homeassistant.const import CONF_TYPE
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import CONF_FRIGATE_ENTRY_ID, DOMAIN, TYPE_DISCOVERY
from .device import async_register_device
from .discovery import async_discover, async_start_discovery
from .frigate import frigate_config, topic_prefix
from .hub import ReviewWatcher, async_watch

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type FrigateAutoNotifyConfigEntry = ConfigEntry[ReviewWatcher | None]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_start_discovery(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FrigateAutoNotifyConfigEntry) -> bool:
    entry.runtime_data = None
    if entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
        # nothing to watch, only to look again now that what's discovered may have been switched
        async_discover(hass)
        return True
    config = frigate_config(hass, entry.data[CONF_FRIGATE_ENTRY_ID])
    if config is None:
        raise ConfigEntryNotReady("Frigate isn't set up yet")
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT isn't available")
    watcher = ReviewWatcher(hass, entry)
    entry.async_on_unload(await async_watch(hass, topic_prefix(config), watcher))
    entry.runtime_data = watcher
    async_register_device(hass, entry, entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FrigateAutoNotifyConfigEntry) -> bool:
    # the subscription and timers are stopped by the entry's own unload callbacks
    return True
