"""Config flow for Frigate Auto Notify, one config entry per camera"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import BooleanSelector

from .compat import vol
from .const import CONF_AUTO_DISCOVER, DISCOVERY_TITLE, DOMAIN, SUPERNOTIFY_MISSING, SUPERNOTIFY_PRESENT, TYPE_DISCOVERY
from .supernotify_api import supernotify_available


def supernotify_status(hass: HomeAssistant) -> str:
    return SUPERNOTIFY_PRESENT if supernotify_available(hass) else SUPERNOTIFY_MISSING


def discovery_schema(auto_discover: bool = True) -> vol.Schema:
    return vol.Schema({vol.Required(CONF_AUTO_DISCOVER, default=auto_discover): BooleanSelector()})


class FrigateAutoNotifyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Automatic discovery, the cameras themselves set up as they're found"""
        await self.async_set_unique_id(TYPE_DISCOVERY)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title=DISCOVERY_TITLE, data={CONF_TYPE: TYPE_DISCOVERY}, options=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=discovery_schema(),
            description_placeholders={"supernotify": supernotify_status(self.hass)},
        )
