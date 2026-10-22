from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    async_mock_service,
    mock_integration,
)

FRIGATE_ENTRY_ID = "01FRIGATE"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


@pytest.fixture(autouse=True)
def dependencies(hass: HomeAssistant) -> None:
    """The Frigate integration, a custom one not installed here, and MQTT, with no broker"""
    mock_integration(hass, MockModule("frigate"))
    mock_integration(hass, MockModule("mqtt"))


def mock_supernotify(hass: HomeAssistant) -> list[ServiceCall]:
    """Register the Supernotify actions used, returning the calls made to supernotify.notify"""
    async_mock_service(
        hass,
        "supernotify",
        "enquire_implicit_deliveries",
        response={"mobile_push": ["mobile_push"], "email": ["email"]},
        supports_response=SupportsResponse.ONLY,
    )
    async_mock_service(
        hass,
        "supernotify",
        "enquire_configuration",
        response={"delivery": {"phones": {"transport": "mobile_push"}}},
        supports_response=SupportsResponse.ONLY,
    )
    return async_mock_service(hass, "supernotify", "notify")


@dataclass
class FakeFrigate:
    entry: MockConfigEntry
    server_device_id: str
    # by Frigate's name for each
    cameras: dict[str, str] = field(default_factory=dict)
    zones: dict[str, str] = field(default_factory=dict)


def add_frigate(
    hass: HomeAssistant,
    cameras: dict[str, list[str]] | None = None,
) -> FakeFrigate:
    """A Frigate server registered as the Frigate integration does it, a device for the server, one for each camera
    with its camera entity, and one for each zone with only its occupancy sensors"""
    cameras = {"driveway": ["Turning_Circle", "Pend"], "courtyard": ["Barn_Door", "Pend"]} if cameras is None else cameras
    entry = MockConfigEntry(domain="frigate", entry_id=FRIGATE_ENTRY_ID, data={"url": "http://frigate:5000"})
    entry.add_to_hass(hass)
    hass.data.setdefault("frigate", {})[entry.entry_id] = {
        "config": {
            "mqtt": {"topic_prefix": "frigate"},
            "cameras": {name: {"zones": {zone: {} for zone in zones}} for name, zones in cameras.items()},
        }
    }
    devices = dr.async_get(hass)
    server = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("frigate", entry.entry_id)}, name="Frigate", manufacturer="Frigate"
    )
    fake = FakeFrigate(entry, server.id)
    for name in cameras:
        add_camera(hass, fake, name)
    for zone in sorted({zone for zones in cameras.values() for zone in zones}):
        device = devices.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={("frigate", f"{entry.entry_id}:{slugify(zone)}")},
            name=zone.replace("_", " ").title(),
            manufacturer="Frigate",
            via_device_id=server.id,
        )
        er.async_get(hass).async_get_or_create(
            "binary_sensor",
            "frigate",
            f"{entry.entry_id}:occupancy_sensor:{slugify(zone)}_all",
            device_id=device.id,
            config_entry=entry,
        )
        fake.zones[zone] = device.id
    return fake


def add_camera(hass: HomeAssistant, frigate: FakeFrigate, name: str) -> str:
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=frigate.entry.entry_id,
        identifiers={("frigate", f"{frigate.entry.entry_id}:{slugify(name)}")},
        name=name.title(),
        manufacturer="Frigate",
        model="0.18.2",
        via_device_id=frigate.server_device_id,
    )
    er.async_get(hass).async_get_or_create(
        "camera", "frigate", f"{frigate.entry.entry_id}:camera:{name}", device_id=device.id, config_entry=frigate.entry
    )
    frigate.cameras[name] = device.id
    return device.id
