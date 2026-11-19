"""Home Assistant actions: classifying a plate, for any other source of plates or an automation, adding or removing
a plate, and listing the vehicle categories and the plates' sightings"""

from __future__ import annotations

import logging
from typing import cast

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv

from .compat import vol
from .const import (
    DOMAIN,
)
from .vehicles import vehicles

_LOGGER = logging.getLogger(__name__)

SERVICE_CLASSIFY = "classify_plate"
SERVICE_ADD = "add_plate"
SERVICE_REMOVE = "remove_plate"
SERVICE_CATEGORIES = "list_vehicle_categories"
SERVICE_SIGHTINGS = "list_sightings"

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
SIGHTINGS_SCHEMA = vol.Schema({vol.Optional("plate"): cv.string})


@callback
def async_register_services(hass: HomeAssistant) -> None:
    async def classify(call: ServiceCall) -> ServiceResponse:
        vehicle = await vehicles(hass).async_classify(
            call.data["plate"], call.data.get("camera"), record=call.data["record_sighting"]
        )
        return vehicle.as_dict()

    @callback
    def add_plate(call: ServiceCall) -> ServiceResponse:
        added = vehicles(hass).add_plate(
            call.data["category"], call.data["plate"], call.data.get("description"), call.data.get("corrections")
        )
        return {"added": added}

    @callback
    def remove_plate(call: ServiceCall) -> ServiceResponse:
        return {"categories": vehicles(hass).remove_plate(call.data["plate"], call.data.get("category"))}

    @callback
    def list_categories(call: ServiceCall) -> ServiceResponse:
        return cast("ServiceResponse", {"categories": vehicles(hass).categories(call.data.get("category"))})

    async def list_sightings(call: ServiceCall) -> ServiceResponse:
        return cast("ServiceResponse", {"plates": await vehicles(hass).async_sightings(call.data.get("plate"))})

    hass.services.async_register(DOMAIN, SERVICE_CATEGORIES, list_categories, CATEGORIES_SCHEMA, SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, SERVICE_SIGHTINGS, list_sightings, SIGHTINGS_SCHEMA, SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, SERVICE_CLASSIFY, classify, CLASSIFY_SCHEMA, SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, SERVICE_ADD, add_plate, ADD_SCHEMA, SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE, remove_plate, REMOVE_SCHEMA, SupportsResponse.OPTIONAL)
