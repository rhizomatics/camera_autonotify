from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_DEVICE_ID, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr

from custom_components.camera_autonotify.compat import LINKED_DEVICES
from custom_components.camera_autonotify.const import (
    CONF_AUTO_DISCOVER,
    CONF_DISCOVER_ZONES,
    CONF_FRIGATE_SILENT,
    CONF_IMAGE_PROCESSING_SILENT,
    CONF_SOURCE,
    CONF_SOURCE_ENTRY_ID,
    CONF_SOURCE_NAME,
    DOMAIN,
    SOURCE_FRIGATE,
    TYPE_CAMERA,
    TYPE_DISCOVERY,
    TYPE_ZONE,
)
from custom_components.camera_autonotify.discovery import (
    ANPR2MQTT,
    FRIGATE,
    IMAGE_PROCESSING,
    SourceDiscovery,
    async_discover,
    discovery_settings,
    find_cameras,
    find_zones,
)
from custom_components.camera_autonotify.entries import entry_name
from tests.ha_testing import MockConfigEntry

from .conftest import FRIGATE_ENTRY_ID, add_camera, add_frigate, global_form


async def set_up_discovery(
    hass: HomeAssistant, auto_discover: bool = True, discover_zones: bool = False, **options: bool
) -> None:
    """Global Settings made, then, as most tests want, Frigate's cameras and image processing entities set up without
    asking, unless `auto_discover` is off, and any other choices given"""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    chosen = {CONF_FRIGATE_SILENT: auto_discover, CONF_IMAGE_PROCESSING_SILENT: auto_discover} | options
    if discover_zones:
        chosen[CONF_DISCOVER_ZONES] = True
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_DISCOVERY)
    hass.config_entries.async_update_entry(entry, options=chosen)
    async_discover(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def watched(hass: HomeAssistant) -> dict[str, dict]:
    return {
        entry_name(entry): dict(entry.data)
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(CONF_TYPE) != TYPE_DISCOVERY
    }


async def test_cameras_found_by_their_camera_entity(hass: HomeAssistant):
    frigate = add_frigate(hass)
    cameras = {camera.source_name: camera for camera in find_cameras(hass)}
    assert set(cameras) == {"driveway", "courtyard"}
    assert cameras["driveway"].device_id == frigate.cameras["driveway"]
    assert cameras["driveway"].name == "Driveway"
    assert cameras["driveway"].source_entry_id == FRIGATE_ENTRY_ID


async def test_zones_are_the_other_frigate_devices(hass: HomeAssistant):
    frigate = add_frigate(hass)
    zones = {zone.source_name: zone for zone in find_zones(hass)}
    # slugified as for their device, neither the server nor a camera, and a zone of two cameras only once
    assert set(zones) == {"turning_circle", "pend", "barn_door"}
    assert zones["barn_door"].device_id == frigate.zones["Barn_Door"]
    assert zones["barn_door"].name == "Barn Door"


async def test_cameras_set_up_automatically(hass: HomeAssistant):
    frigate = add_frigate(hass)
    await set_up_discovery(hass)
    # the entries list says they're Frigate's, as an anpr2mqtt source's name says it's anpr2mqtt's
    assert {e.title for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) != TYPE_DISCOVERY} == {
        "Courtyard (Frigate)",
        "Driveway (Frigate)",
    }
    assert watched(hass) == {
        "Driveway": {
            CONF_DEVICE_ID: frigate.cameras["driveway"],
            CONF_TYPE: TYPE_CAMERA,
            CONF_SOURCE: SOURCE_FRIGATE,
            CONF_SOURCE_ENTRY_ID: FRIGATE_ENTRY_ID,
            CONF_SOURCE_NAME: "driveway",
        },
        "Courtyard": {
            CONF_DEVICE_ID: frigate.cameras["courtyard"],
            CONF_TYPE: TYPE_CAMERA,
            CONF_SOURCE: SOURCE_FRIGATE,
            CONF_SOURCE_ENTRY_ID: FRIGATE_ENTRY_ID,
            CONF_SOURCE_NAME: "courtyard",
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
    await hass.config_entries.options.async_configure(
        result["flow_id"], global_form(advanced_frigate={"frigate_silent": True, CONF_DISCOVER_ZONES: True})
    )
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
    shown = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert (shown.get("description_placeholders") or {}).get("proxy") == ""
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Driveway (Frigate)"
    assert result["data"][CONF_SOURCE_NAME] == "driveway"


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
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.title == "Driveway (Frigate)")
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    if not LINKED_DEVICES:
        # before devices were linked, the camera's own device is all there is
        assert devices == []
        return
    assert len(devices) == 1
    camera = dr.async_get(hass).async_get(frigate.cameras["driveway"])
    assert camera is not None
    assert devices[0].identifiers == camera.identifiers
    assert devices[0].manufacturer == "Frigate"


async def test_offered_with_proxy_warning(hass: HomeAssistant):
    add_frigate(hass, {"driveway": []}, title="House", options={"notification_proxy_enable": False})
    await set_up_discovery(hass, auto_discover=False)
    (flow,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    shown = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert "switched off for House" in (shown.get("description_placeholders") or {}).get("proxy", "")


async def test_entry_named_without_its_source(hass: HomeAssistant):
    """The entries list says where each is from, while notifications and entities say only the camera's name, even
    once renamed"""
    from custom_components.camera_autonotify.notifier import Notifier

    add_frigate(hass)
    await set_up_discovery(hass)
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.title == "Driveway (Frigate)")
    assert Notifier(hass, entry).name == "Driveway"
    hass.config_entries.async_update_entry(entry, title="Front Drive (Frigate)")
    assert Notifier(hass, entry).name == "Front Drive"
    hass.config_entries.async_update_entry(entry, title="Front Drive")
    assert entry_name(entry) == "Front Drive"


def test_discovery_settings():
    """Each source found and offered to begin with, and the one choice of earlier versions still followed until saved"""
    found = discovery_settings({})
    assert found == {
        FRIGATE: SourceDiscovery(find=True, silent=False),
        ANPR2MQTT: SourceDiscovery(find=True, silent=False),
        IMAGE_PROCESSING: SourceDiscovery(find=True, silent=False),
    }
    earlier = discovery_settings({CONF_AUTO_DISCOVER: True})
    assert earlier[FRIGATE].silent
    assert earlier[IMAGE_PROCESSING].silent
    assert not earlier[ANPR2MQTT].silent
    # once saved, the new choices instead
    assert not discovery_settings({CONF_AUTO_DISCOVER: True, CONF_FRIGATE_SILENT: False})[FRIGATE].silent


async def test_frigate_not_found_when_off(hass: HomeAssistant):
    add_frigate(hass)
    MockConfigEntry(
        domain=DOMAIN, data={CONF_TYPE: TYPE_DISCOVERY}, options={"frigate_discover": False}, unique_id=TYPE_DISCOVERY
    ).add_to_hass(hass)
    async_discover(hass)
    await hass.async_block_till_done()
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


async def test_global_settings_sections(hass: HomeAssistant):
    """Each source's choices in its own section, out of the way"""
    add_frigate(hass)
    await set_up_discovery(hass)
    discovery = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data[CONF_TYPE] == TYPE_DISCOVERY)
    result = await hass.config_entries.options.async_init(discovery.entry_id)
    schema = result["data_schema"]
    assert schema is not None
    sections = [str(key) for key in schema.schema]
    assert sections[-3:] == ["advanced_frigate", "advanced_anpr2mqtt", "advanced_image_processing"]
    assert "frigate_genai" in sections
    shown = {
        str(key): (key.description or {}).get("suggested_value") for key in schema.schema["advanced_frigate"].schema.schema
    }
    # set up without asking, as chosen for these tests
    assert shown["frigate_discover"] is True
    assert shown["frigate_silent"] is True
