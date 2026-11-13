from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from tests.ha_testing import (
    MockConfigEntry,
    MockModule,
    async_mock_service,
    mock_integration,
)

FRIGATE_ENTRY_ID = "01FRIGATE"


def _via(device_id: str, identifier: tuple[str, str]) -> dict[str, Any]:
    """The server a Frigate device is connected via: by `via_device_id` where Home Assistant has it, its older
    `via_device` by identifier being deprecated from then on, and the only one before"""
    if "via_device_id" in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters:
        return {"via_device_id": device_id}
    return {"via_device": identifier}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


@pytest.fixture(autouse=True)
def dependencies(hass: HomeAssistant) -> None:
    """The Frigate integration, a custom one not installed here, and MQTT, with no broker"""
    mock_integration(hass, MockModule("frigate"))
    mock_integration(hass, MockModule("mqtt"))


class FakeMQTT:
    """MQTT as far as it's used, a subscription to the reviews of a topic prefix, and messages sent to it"""

    def __init__(self) -> None:
        self.subscriptions: dict[str, list[Callable[[Any], None]]] = {}
        self.available = True

    async def subscribe(self, hass: HomeAssistant, topic: str, received: Callable[[Any], None]) -> Callable[[], None]:
        self.subscriptions.setdefault(topic, []).append(received)
        return lambda: self.subscriptions[topic].remove(received)

    def publish(self, topic: str, payload: dict[str, Any] | str) -> None:
        message = SimpleNamespace(topic=topic, payload=payload if isinstance(payload, str) else json.dumps(payload))
        for subscribed, receivers in list(self.subscriptions.items()):
            if _matches(subscribed, topic):
                for received in list(receivers):
                    received(message)


def _matches(subscribed: str, topic: str) -> bool:
    """As MQTT matches a topic to a subscription, `+` for any one level and `#` for the rest"""
    wanted, levels = subscribed.split("/"), topic.split("/")
    for index, part in enumerate(wanted):
        if part == "#":
            return True
        if index >= len(levels) or part not in ("+", levels[index]):
            return False
    return len(wanted) == len(levels)


@pytest.fixture(autouse=True)
def fake_mqtt() -> Iterator[FakeMQTT]:
    fake = FakeMQTT()
    with (
        patch("custom_components.camera_autonotify.hub.mqtt.async_subscribe", fake.subscribe),
        patch(
            "custom_components.camera_autonotify.mqtt.async_wait_for_mqtt_client",
            AsyncMock(side_effect=lambda hass: fake.available),
        ),
    ):
        yield fake


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
        response={"delivery": {"phones": {"transport": "mobile_push"}}, "scenarios": ["noisy", "high_alert"]},
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
    entry_id: str = FRIGATE_ENTRY_ID,
    options: dict[str, Any] | None = None,
    client_id: str = "frigate",
    title: str = "frigate:5000",
    genai: bool = False,
) -> FakeFrigate:
    """A Frigate server registered as the Frigate integration does it, a device for the server, one for each camera
    with its camera entity, and one for each zone with only its occupancy sensors"""
    cameras = {"driveway": ["Turning_Circle", "Pend"], "courtyard": ["Barn_Door", "Pend"]} if cameras is None else cameras
    entry = MockConfigEntry(
        domain="frigate", entry_id=entry_id, title=title, data={"url": "http://frigate:5000"}, options=options or {}
    )
    entry.add_to_hass(hass)
    hass.data.setdefault("frigate", {})[entry.entry_id] = {
        "config": {
            "mqtt": {"topic_prefix": "frigate", "client_id": client_id},
            "cameras": {
                name: {
                    "zones": {zone: {} for zone in zones},
                    "objects": {"track": ["person", "car"], "genai": {"enabled": genai}},
                    "audio": {"listen": ["bark"]},
                    "review": {
                        "genai": {"enabled": genai},
                        "alerts": {"labels": ["person", "car"]},
                        "detections": {"labels": [name == "driveway" and "fox" or "cat"]},
                    },
                }
                for name, zones in cameras.items()
            },
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
            **_via(server.id, ("frigate", entry.entry_id)),
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
        **_via(frigate.server_device_id, ("frigate", frigate.entry.entry_id)),
    )
    er.async_get(hass).async_get_or_create(
        "camera", "frigate", f"{frigate.entry.entry_id}:camera:{name}", device_id=device.id, config_entry=frigate.entry
    )
    frigate.cameras[name] = device.id
    return device.id


EN_JSON = Path(__file__).parent.parent / "custom_components" / "camera_autonotify" / "translations" / "en.json"


def english(key: str, **placeholders: object) -> str:
    """A text of the `common` translations in English, as a notification or a setup screen says it"""
    return json.loads(EN_JSON.read_text())["common"][key].format(**placeholders)
