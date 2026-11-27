"""The Last notification snapshot camera of a camera's entry, Frigate's snapshot of the detection last notified, for a
dashboard. An option of any camera"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.camera import Camera
from homeassistant.const import CONF_DEVICE_ID, Platform
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .compat import LINKED_DEVICES
from .const import CONF_SOURCE_ENTRY_ID, DOMAIN
from .entries import entry_name, wants_last_snapshot
from .frigate import async_snapshot, frigate_coordinator
from .hub import ReviewWatcher

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .notifier import Notifier

_LOGGER = logging.getLogger(__name__)

LAST_SNAPSHOT = "last_snapshot"
# nothing polled, the image fetched only when asked for, once for each detection
PARALLEL_UPDATES = 0


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
            self._attr_name = f"{entry_name(entry)} Last notification snapshot"
        self._fetched: tuple[str, bytes] | None = None

    async def async_added_to_hass(self) -> None:
        """Available as the Frigate server is, as the Frigate integration finds it every few seconds"""
        await super().async_added_to_hass()
        if (coordinator := frigate_coordinator(self.hass, self.source_entry_id)) is not None:
            self.async_on_remove(coordinator.async_add_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        coordinator = frigate_coordinator(self.hass, self.source_entry_id)
        return coordinator is None or coordinator.last_update_success

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        detection = self.notifier.last_snapshot
        if detection is None:
            return None
        if self._fetched is not None and self._fetched[0] == detection:
            return self._fetched[1]
        image = await async_snapshot(self.hass, self.source_entry_id, detection)
        if image is None:
            return None
        self._fetched = (detection, image)
        return image
