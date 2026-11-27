"""Camera AutoNotify - automatic notifications for Frigate camera reviews"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components import mqtt
from homeassistant.const import CONF_TYPE, Platform
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir

from .actions import async_listen
from .anpr import AnprWatcher, sensor_entity
from .anpr_events import AnprEventWatcher, event_entity
from .const import (
    CONF_SOURCE_ENTRY_ID,
    DISCOVERY_TITLE,
    DISCOVERY_TITLE_BEFORE,
    DOMAIN,
    TYPE_ANPR,
    TYPE_ANPR_EVENT,
    TYPE_CAMERA,
    TYPE_DISCOVERY,
    TYPE_IMAGE_PROCESSING,
    TYPE_ZONE,
)
from .device import async_register_device
from .discovery import async_discover, async_start_discovery
from .entries import entry_name
from .frigate import frigate_config, topic_prefix
from .health import HealthMonitor, async_start_health_check
from .hub import ReviewWatcher, async_watch
from .image_source import ImageSourceWatcher
from .services import async_register_services
from .summary import async_start_summaries
from .texts import async_load_texts

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# of a camera's or zone's entry, the Last snapshot camera only where an ANPR/ALPR entity is chosen
PLATFORMS: list[Platform] = [Platform.CAMERA]

# a camera's or zone's reviews, or the health checks of the discovery entry, unless switched off
type CameraAutoNotifyConfigEntry = ConfigEntry[
    ReviewWatcher | AnprWatcher | AnprEventWatcher | ImageSourceWatcher | HealthMonitor | None
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await async_load_texts(hass)
    async_start_discovery(hass)
    # the buttons of notifications, for as long as Home Assistant runs
    async_listen(hass)
    async_register_services(hass)
    return True


# an entry whose source has gone for good, its Frigate entry deleted, or anpr2mqtt's entity for it removed, one repair
# for each such entry, until the entry is removed
ISSUE_SOURCE_GONE = "source_gone"


def _source_gone(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Whether the entry's source has gone for good, not only not ready yet. An image processing entity, often set up
    from YAML with no registry entry, may only turn up after starting, so isn't judged"""
    kind = entry.data.get(CONF_TYPE)
    if kind in (TYPE_CAMERA, TYPE_ZONE, None):
        return hass.config_entries.async_get_entry(entry.data.get(CONF_SOURCE_ENTRY_ID, "")) is None
    if kind == TYPE_ANPR:
        return sensor_entity(hass, entry) is None
    if kind == TYPE_ANPR_EVENT:
        return event_entity(hass, entry) is None
    return False


def _issue_id(entry: ConfigEntry) -> str:
    return f"{ISSUE_SOURCE_GONE}_{entry.entry_id}"


async def async_setup_entry(hass: HomeAssistant, entry: CameraAutoNotifyConfigEntry) -> bool:
    entry.runtime_data = None
    if _source_gone(hass, entry):
        ir.async_create_issue(
            hass,
            DOMAIN,
            _issue_id(entry),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_SOURCE_GONE,
            translation_placeholders={"name": entry_name(entry)},
        )
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key=ISSUE_SOURCE_GONE, translation_placeholders={"name": entry_name(entry)}
        )
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
    if entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
        # no reviews to watch, only to look again now that what's discovered may have been switched, the health
        # of each Frigate server, and its daily summary
        if entry.title == DISCOVERY_TITLE_BEFORE:
            hass.config_entries.async_update_entry(entry, title=DISCOVERY_TITLE)
        async_discover(hass)
        entry.runtime_data = async_start_health_check(hass, entry)
        async_start_summaries(hass, entry)
        return True
    if entry.data.get(CONF_TYPE) == TYPE_IMAGE_PROCESSING:
        # an image processing entity's own scans of its own camera, needing neither Frigate nor MQTT
        source = ImageSourceWatcher(hass, entry)
        entry.async_on_unload(source.async_start())
        entry.runtime_data = source
        return True
    if entry.data.get(CONF_TYPE) == TYPE_ANPR:
        # plates read by anpr2mqtt, from its sensor's state, needing neither Frigate nor MQTT here
        anpr = AnprWatcher(hass, entry)
        entry.async_on_unload(anpr.async_start())
        entry.runtime_data = anpr
        async_register_device(hass, entry, entry.title)
        return True
    if entry.data.get(CONF_TYPE) == TYPE_ANPR_EVENT:
        # another of anpr2mqtt's events, such as a face, from its event entity
        events = AnprEventWatcher(hass, entry)
        entry.async_on_unload(events.async_start())
        entry.runtime_data = events
        async_register_device(hass, entry, entry.title)
        return True
    config = frigate_config(hass, entry.data[CONF_SOURCE_ENTRY_ID])
    if config is None:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="frigate_not_ready", translation_placeholders={"name": entry_name(entry)}
        )
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady(translation_domain=DOMAIN, translation_key="mqtt_not_ready")
    watcher = ReviewWatcher(hass, entry)
    entry.async_on_unload(await async_watch(hass, topic_prefix(config), watcher))
    entry.runtime_data = watcher
    async_register_device(hass, entry, entry_name(entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: CameraAutoNotifyConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))


async def async_unload_entry(hass: HomeAssistant, entry: CameraAutoNotifyConfigEntry) -> bool:
    # the subscription and timers are stopped by the entry's own unload callbacks
    if isinstance(entry.runtime_data, ReviewWatcher):
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True
