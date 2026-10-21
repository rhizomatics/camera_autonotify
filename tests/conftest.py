from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from pytest_homeassistant_custom_component.common import MockModule, async_mock_service, mock_integration


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
