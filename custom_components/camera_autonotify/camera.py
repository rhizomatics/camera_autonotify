"""The Last notification snapshot camera of a camera's entry, Frigate's snapshot of the detection last notified, for a
dashboard, or for an image processing ANPR/ALPR entity, such as OpenALPR's, to read as its source, since a scan reads
only its source camera. An option of any camera, on to begin with where such an entity is chosen"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiohttp import ClientError
from homeassistant.components.camera import Camera
from homeassistant.const import CONF_DEVICE_ID, Platform
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo

from .compat import LINKED_DEVICES
from .const import ALPR_TIMEOUT, CONF_SOURCE_ENTRY_ID, DOMAIN
from .entries import wants_last_snapshot
from .frigate import notifications_url, snapshot_url
from .hub import ReviewWatcher

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .notifier import Notifier

_LOGGER = logging.getLogger(__name__)

LAST_SNAPSHOT = "last_snapshot"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    unique_id = f"{entry.entry_id}_{LAST_SNAPSHOT}"
    watcher = entry.runtime_data
    if not wants_last_snapshot(entry) or not isinstance(watcher, ReviewWatcher):
        # no longer wanted, so not left behind as unavailable
        registry = er.async_get(hass)
        if entity_id := registry.async_get_entity_id(Platform.CAMERA, DOMAIN, unique_id):
            registry.async_remove(entity_id)
        return
    async_add_entities([LastSnapshotCamera(hass, entry, watcher.notifier, unique_id)])


class LastSnapshotCamera(Camera):
    """Frigate's whole snapshot of the detection last notified, without the box, which may hide a plate, fetched
    through the Frigate integration's notification proxy once for each detection"""

    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, notifier: Notifier, unique_id: str) -> None:
        super().__init__()
        self.hass = hass
        self.notifier = notifier
        self.source_entry_id: str = entry.data[CONF_SOURCE_ENTRY_ID]
        self._attr_unique_id = unique_id
        self._attr_translation_key = LAST_SNAPSHOT
        source = dr.async_get(hass).async_get(entry.data.get(CONF_DEVICE_ID, ""))
        if LINKED_DEVICES and isinstance(source, dr.DeviceEntry):
            # on the entry's own device, as `async_register_device` makes it
            self._attr_has_entity_name = True
            self._attr_device_info = DeviceInfo(identifiers=set(source.identifiers))
        else:
            self._attr_name = f"{entry.title} Last notification snapshot"
        self._fetched: tuple[str, bytes] | None = None

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        detection = self.notifier.last_snapshot
        if detection is None:
            return None
        if self._fetched is not None and self._fetched[0] == detection:
            return self._fetched[1]
        notifications = notifications_url(self.hass, self.source_entry_id, internal=True)
        if notifications is None:
            return None
        try:
            async with asyncio.timeout(ALPR_TIMEOUT):
                response = await async_get_clientsession(self.hass).get(snapshot_url(notifications, detection))
                response.raise_for_status()
                image = await response.read()
        except (TimeoutError, ClientError) as error:
            _LOGGER.warning("CAMERA_AUTONOTIFY No snapshot of %s for %s: %s", detection, self.entity_id, error)
            return None
        self._fetched = (detection, image)
        return image
