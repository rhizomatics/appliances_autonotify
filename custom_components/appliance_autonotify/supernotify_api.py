"""The parts of Supernotify used, all through its actions and entities so there's no import dependency"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback

from .const import SUPERNOTIFY_DOMAIN


@callback
def supernotify_available(hass: HomeAssistant) -> bool:
    return hass.services.has_service(SUPERNOTIFY_DOMAIN, "notify")


async def _enquire(hass: HomeAssistant, action: str) -> dict[str, Any]:
    response = await hass.services.async_call(SUPERNOTIFY_DOMAIN, action, blocking=True, return_response=True)
    return dict(response) if response else {}


async def deliveries_by_transport(hass: HomeAssistant) -> dict[str, list[str]]:
    """Delivery names for each transport, both those configured and those Supernotify set up itself"""
    by_transport: dict[str, list[str]] = {}
    # every delivery has a switch, the only place to find one Supernotify set up itself but that
    # Delivery Control has made explicit or scenario only, so is neither implicit nor configured
    for state in hass.states.async_all("switch"):
        if state.entity_id.startswith(f"switch.{SUPERNOTIFY_DOMAIN}_delivery_"):
            name, transport = state.attributes.get("name"), state.attributes.get("transport")
            if name and transport:
                by_transport.setdefault(transport, []).append(name)
    implicit = await _enquire(hass, "enquire_implicit_deliveries")
    for transport, names in implicit.items():
        known = by_transport.setdefault(transport, [])
        known.extend(name for name in names if name not in known)
    configured = (await _enquire(hass, "enquire_configuration")).get("delivery") or {}
    for name, delivery in configured.items():
        names = by_transport.setdefault(delivery.get("transport", name), [])
        if name not in names:
            names.append(name)
    return by_transport
