"""The parts of Supernotify used, all through its actions and entities so there's no import dependency"""

from __future__ import annotations

from typing import Any

from homeassistant.core import Context, HomeAssistant, callback

from .const import SUPERNOTIFY_DOMAIN


@callback
def supernotify_available(hass: HomeAssistant) -> bool:
    return hass.services.has_service(SUPERNOTIFY_DOMAIN, "notify")


async def _enquire(hass: HomeAssistant, action: str, context: Context) -> dict[str, Any]:
    response = await hass.services.async_call(SUPERNOTIFY_DOMAIN, action, blocking=True, context=context, return_response=True)
    return dict(response) if response else {}


EMAIL_TRANSPORT = "email"


async def deliveries_by_transport(hass: HomeAssistant, context: Context | None = None) -> dict[str, list[str]]:
    """Delivery names for each transport, both those configured and those Supernotify set up itself"""
    # one context for both enquiries, where the caller has none of its own to pass on
    context = context or Context()
    by_transport: dict[str, list[str]] = {}
    # every delivery has a switch, the only place to find one Supernotify set up itself but that
    # Delivery Control has made explicit or scenario only, so is neither implicit nor configured
    for state in hass.states.async_all("switch"):
        if state.entity_id.startswith(f"switch.{SUPERNOTIFY_DOMAIN}_delivery_"):
            name, transport = state.attributes.get("name"), state.attributes.get("transport")
            if name and transport:
                by_transport.setdefault(transport, []).append(name)
    implicit = await _enquire(hass, "enquire_implicit_deliveries", context)
    for transport, names in implicit.items():
        known = by_transport.setdefault(transport, [])
        known.extend(name for name in names if name not in known)
    configured = (await _enquire(hass, "enquire_configuration", context)).get("delivery") or {}
    for name, delivery in configured.items():
        names = by_transport.setdefault(delivery.get("transport", name), [])
        if name not in names:
            names.append(name)
    return by_transport


async def email_deliveries(hass: HomeAssistant, context: Context | None = None) -> list[str]:
    """One delivery Supernotify sends e-mail by, for what's too long for a phone or a voice assistant, the one it
    calls `email` if it has it, since there may be others, such as for HTML, that would send it again, or nothing
    when there's none"""
    names = sorted((await deliveries_by_transport(hass, context)).get(EMAIL_TRANSPORT) or [])
    if not names:
        return []
    return [EMAIL_TRANSPORT if EMAIL_TRANSPORT in names else names[0]]


async def scenario_names(hass: HomeAssistant, context: Context | None = None) -> list[str]:
    """The scenarios Supernotify has, to apply by a rule"""
    scenarios = (await _enquire(hass, "enquire_configuration", context or Context())).get("scenarios") or []
    if isinstance(scenarios, dict):
        scenarios = list(scenarios)
    return sorted(str(name) for name in scenarios if name)
