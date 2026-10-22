from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_DEVICE_ID, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr

from custom_components.frigate_autonotify.const import (
    CONF_AUTO_DISCOVER,
    CONF_DISCOVER_ZONES,
    CONF_FRIGATE_ENTRY_ID,
    CONF_FRIGATE_NAME,
    DOMAIN,
    TYPE_CAMERA,
    TYPE_DISCOVERY,
    TYPE_ZONE,
)
from custom_components.frigate_autonotify.discovery import find_cameras, find_zones

from .conftest import FRIGATE_ENTRY_ID, add_camera, add_frigate


async def set_up_discovery(hass: HomeAssistant, auto_discover: bool = True, discover_zones: bool = False) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AUTO_DISCOVER: auto_discover, CONF_DISCOVER_ZONES: discover_zones}
    )
    await hass.async_block_till_done()


def watched(hass: HomeAssistant) -> dict[str, dict]:
    return {
        entry.title: dict(entry.data)
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(CONF_TYPE) != TYPE_DISCOVERY
    }


async def test_cameras_found_by_their_camera_entity(hass: HomeAssistant):
    frigate = add_frigate(hass)
    cameras = {camera.frigate_name: camera for camera in find_cameras(hass)}
    assert set(cameras) == {"driveway", "courtyard"}
    assert cameras["driveway"].device_id == frigate.cameras["driveway"]
    assert cameras["driveway"].name == "Driveway"
    assert cameras["driveway"].frigate_entry_id == FRIGATE_ENTRY_ID


async def test_zones_are_the_other_frigate_devices(hass: HomeAssistant):
    frigate = add_frigate(hass)
    zones = {zone.frigate_name: zone for zone in find_zones(hass)}
    # slugified as for their device, neither the server nor a camera, and a zone of two cameras only once
    assert set(zones) == {"turning_circle", "pend", "barn_door"}
    assert zones["barn_door"].device_id == frigate.zones["Barn_Door"]
    assert zones["barn_door"].name == "Barn Door"


async def test_cameras_set_up_automatically(hass: HomeAssistant):
    frigate = add_frigate(hass)
    await set_up_discovery(hass)
    assert watched(hass) == {
        "Driveway": {
            CONF_DEVICE_ID: frigate.cameras["driveway"],
            CONF_TYPE: TYPE_CAMERA,
            CONF_FRIGATE_ENTRY_ID: FRIGATE_ENTRY_ID,
            CONF_FRIGATE_NAME: "driveway",
        },
        "Courtyard": {
            CONF_DEVICE_ID: frigate.cameras["courtyard"],
            CONF_TYPE: TYPE_CAMERA,
            CONF_FRIGATE_ENTRY_ID: FRIGATE_ENTRY_ID,
            CONF_FRIGATE_NAME: "courtyard",
        },
    }


async def test_zones_too_when_chosen(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass, discover_zones=True)
    assert {title: data[CONF_TYPE] for title, data in watched(hass).items()} == {
        "Driveway": TYPE_CAMERA,
        "Courtyard": TYPE_CAMERA,
        "Turning Circle": TYPE_ZONE,
        "Pend": TYPE_ZONE,
        "Barn Door": TYPE_ZONE,
    }


async def test_zones_found_once_switched_on(hass: HomeAssistant):
    add_frigate(hass)
    await set_up_discovery(hass)
    assert len(watched(hass)) == 2
    discovery = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data[CONF_TYPE] == TYPE_DISCOVERY)
    result = await hass.config_entries.options.async_init(discovery.entry_id)
    assert result["step_id"] == "discovery"
    await hass.config_entries.options.async_configure(result["flow_id"], {CONF_AUTO_DISCOVER: True, CONF_DISCOVER_ZONES: True})
    await hass.async_block_till_done()
    assert len(watched(hass)) == 5


async def test_offered_without_automatic_discovery(hass: HomeAssistant):
    frigate = add_frigate(hass)
    await set_up_discovery(hass, auto_discover=False)
    assert watched(hass) == {}
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert {flow["context"]["unique_id"] for flow in flows} == set(frigate.cameras.values())

    flow = next(f for f in flows if f["context"]["unique_id"] == frigate.cameras["driveway"])
    assert flow["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Driveway"
    assert result["data"][CONF_FRIGATE_NAME] == "driveway"


async def test_new_camera_found(hass: HomeAssistant):
    frigate = add_frigate(hass, {"driveway": []})
    await set_up_discovery(hass)
    assert set(watched(hass)) == {"Driveway"}
    add_camera(hass, frigate, "barn")
    await hass.async_block_till_done()
    assert set(watched(hass)) == {"Driveway", "Barn"}


async def test_nothing_found_without_discovery_entry(hass: HomeAssistant):
    add_frigate(hass)
    await hass.async_block_till_done()
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


async def test_device_linked_to_camera(hass: HomeAssistant):
    frigate = add_frigate(hass)
    await set_up_discovery(hass)
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.title == "Driveway")
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    camera = dr.async_get(hass).async_get(frigate.cameras["driveway"])
    assert camera is not None
    assert devices[0].identifiers == camera.identifiers
    assert devices[0].manufacturer == "Frigate"
