"""Config flow for AutoNotify for Frigate, one config entry per camera, or zone"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME, CONF_TYPE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import BooleanSelector

from .compat import vol
from .const import (
    CONF_AUTO_DISCOVER,
    CONF_DISCOVER_ZONES,
    CONF_FRIGATE_ENTRY_ID,
    CONF_FRIGATE_NAME,
    DISCOVERY_TITLE,
    DOMAIN,
    SUPERNOTIFY_MISSING,
    SUPERNOTIFY_PRESENT,
    TYPE_DISCOVERY,
)
from .discovery import find_cameras
from .supernotify_api import supernotify_available

STEP_DISCOVERY = "discovery"
# what a camera or zone's entry holds, as it's found
ENTRY_DATA = (CONF_DEVICE_ID, CONF_TYPE, CONF_FRIGATE_ENTRY_ID, CONF_FRIGATE_NAME)


def supernotify_status(hass: HomeAssistant) -> str:
    return SUPERNOTIFY_PRESENT if supernotify_available(hass) else SUPERNOTIFY_MISSING


def discovery_schema(auto_discover: bool = True, discover_zones: bool = False) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_AUTO_DISCOVER, default=auto_discover): BooleanSelector(),
        vol.Required(CONF_DISCOVER_ZONES, default=discover_zones): BooleanSelector(),
    })


class FrigateAutoNotifyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._found: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FrigateAutoNotifyOptionsFlow:
        return FrigateAutoNotifyOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Automatic discovery, the cameras themselves set up as they're found"""
        await self.async_set_unique_id(TYPE_DISCOVERY)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            # the cameras are set up as this entry is, each as its own entry to change or delete
            return self.async_create_entry(title=DISCOVERY_TITLE, data={CONF_TYPE: TYPE_DISCOVERY}, options=user_input)
        found = [camera.name for camera in find_cameras(self.hass)]
        if found:
            found_text = "Cameras found:\n\n" + "\n".join(f"- {name}" for name in found)
        else:
            found_text = "No Frigate cameras found yet."
        return self.async_show_form(
            step_id="user",
            data_schema=discovery_schema(),
            description_placeholders={"found": found_text, "supernotify": supernotify_status(self.hass)},
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """A camera found with automatic discovery on, so set up without asking"""
        # a discovery of the same camera may be waiting, and goes once this entry exists
        await self.async_set_unique_id(import_data[CONF_DEVICE_ID], raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=import_data[CONF_NAME], data={k: v for k, v in import_data.items() if k in ENTRY_DATA}
        )

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        """A camera found with automatic discovery off, or a zone, so offered to be added"""
        self._found = dict(discovery_info)
        await self.async_set_unique_id(discovery_info[CONF_DEVICE_ID])
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": discovery_info[CONF_NAME]}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._found[CONF_NAME], data={k: v for k, v in self._found.items() if k in ENTRY_DATA}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._found[CONF_NAME], "supernotify": supernotify_status(self.hass)},
        )


class FrigateAutoNotifyOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            return await self.async_step_discovery()
        # a camera's settings come with its notifications
        return self.async_abort(reason="no_settings")

    async def async_step_discovery(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id=STEP_DISCOVERY,
            data_schema=discovery_schema(options.get(CONF_AUTO_DISCOVER, True), options.get(CONF_DISCOVER_ZONES, False)),
        )
