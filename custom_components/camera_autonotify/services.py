"""Home Assistant actions: classifying a plate, for any other source of plates or an automation, adding or removing
a plate, listing the vehicle categories, and forgetting plates' sightings"""

from __future__ import annotations

import logging
from typing import cast

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .compat import vol
from .const import (
    DOMAIN,
)
from .entries import global_settings
from .vehicles import vehicles

_LOGGER = logging.getLogger(__name__)

SERVICE_CLASSIFY = "classify_plate"
SERVICE_ADD = "add_plate"
SERVICE_REMOVE = "remove_plate"
SERVICE_CATEGORIES = "list_vehicle_categories"
SERVICE_RESET_SIGHTINGS = "reset_sightings"

CLASSIFY_SCHEMA = vol.Schema({
    vol.Required("plate"): cv.string,
    vol.Optional("camera"): cv.string,
    vol.Optional("record_sighting", default=False): cv.boolean,
})
ADD_SCHEMA = vol.Schema({
    vol.Required("category"): cv.string,
    vol.Required("plate"): cv.string,
    vol.Optional("description"): cv.string,
    vol.Optional("corrections"): vol.All(cv.ensure_list, [cv.string]),
})
REMOVE_SCHEMA = vol.Schema({vol.Required("plate"): cv.string, vol.Optional("category"): cv.string})
CATEGORIES_SCHEMA = vol.Schema({vol.Optional("category"): cv.string})
# a plate, or every plate only when asked for outright
RESET_SIGHTINGS_SCHEMA = vol.All(
    vol.Schema({vol.Optional("plate"): cv.string, vol.Optional("all", default=False): cv.boolean}),
    vol.Any(
        vol.Schema({vol.Required("plate"): cv.string, vol.Required("all"): False}),
        vol.Schema({vol.Required("all"): True}),
        msg="Give a plate, or all, not both",
    ),
)


@callback
def _needs_global_settings(hass: HomeAssistant) -> None:
    """Vehicle categories are kept in Global Settings, so a plate can't be added or removed without them"""
    if global_settings(hass) is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="global_settings_missing")


@callback
def async_register_services(hass: HomeAssistant) -> None:
    async def classify(call: ServiceCall) -> ServiceResponse:
        vehicle = await vehicles(hass).async_classify(
            call.data["plate"], call.data.get("camera"), record=call.data["record_sighting"]
        )
        return vehicle.as_dict()

    @callback
    def add_plate(call: ServiceCall) -> ServiceResponse:
        _needs_global_settings(hass)
        added = vehicles(hass).add_plate(
            call.data["category"], call.data["plate"], call.data.get("description"), call.data.get("corrections")
        )
        return {"added": added}

    @callback
    def remove_plate(call: ServiceCall) -> ServiceResponse:
        _needs_global_settings(hass)
        return {"categories": vehicles(hass).remove_plate(call.data["plate"], call.data.get("category"))}

    @callback
    def list_categories(call: ServiceCall) -> ServiceResponse:
        return cast("ServiceResponse", {"categories": vehicles(hass).categories(call.data.get("category"))})

    async def reset_sightings(call: ServiceCall) -> ServiceResponse:
        removed = await vehicles(hass).async_reset_sightings(None if call.data["all"] else call.data["plate"])
        return {"sightings": removed}

    hass.services.async_register(DOMAIN, SERVICE_CATEGORIES, list_categories, CATEGORIES_SCHEMA, SupportsResponse.ONLY)
    hass.services.async_register(
        DOMAIN, SERVICE_RESET_SIGHTINGS, reset_sightings, RESET_SIGHTINGS_SCHEMA, SupportsResponse.OPTIONAL
    )
    hass.services.async_register(DOMAIN, SERVICE_CLASSIFY, classify, CLASSIFY_SCHEMA, SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, SERVICE_ADD, add_plate, ADD_SCHEMA, SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE, remove_plate, REMOVE_SCHEMA, SupportsResponse.OPTIONAL)
