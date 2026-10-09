"""Find appliances with an identifiable cycle, and set each up or offer it as a discovered config entry"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_INTEGRATION_DISCOVERY
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME, CONF_TYPE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import discovery_flow
from homeassistant.helpers import entity_registry as er

from .const import CONF_AUTO_DISCOVER, CYCLE_KEYS, DOMAIN, TYPE_DISCOVERY

if TYPE_CHECKING:
    from homeassistant.helpers.entity_registry import EventEntityRegistryUpdatedData


@dataclass(frozen=True)
class Appliance:
    device_id: str
    name: str


@callback
def find_appliances(hass: HomeAssistant) -> list[Appliance]:
    """Devices of the known platforms that have a cycle state entity"""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    found: dict[str, Appliance] = {}
    for entity in entity_registry.entities.values():
        if entity.device_id is None or entity.disabled or entity.translation_key is None:
            continue
        if CYCLE_KEYS.get(entity.platform) != entity.translation_key:
            continue
        device = device_registry.async_get(entity.device_id)
        if device is not None:
            found[device.id] = Appliance(device.id, device.name_by_user or device.name or entity.entity_id)
    return list(found.values())


@callback
def auto_discovery(hass: HomeAssistant) -> bool:
    """Whether appliances found are set up without asking, so not while the discovery entry is disabled or deleted"""
    return any(
        entry.data.get(CONF_TYPE) == TYPE_DISCOVERY and entry.options.get(CONF_AUTO_DISCOVER)
        for entry in hass.config_entries.async_entries(DOMAIN, include_disabled=False)
    )


@callback
def async_discover(hass: HomeAssistant) -> None:
    """Set up every appliance found, or with automatic discovery off, offer each to be added"""
    source = SOURCE_IMPORT if auto_discovery(hass) else SOURCE_INTEGRATION_DISCOVERY
    for appliance in find_appliances(hass):
        # appliances already configured, ignored or in progress are dropped by the flow's unique id
        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            context={"source": source},
            data={CONF_DEVICE_ID: appliance.device_id, CONF_NAME: appliance.name},
        )


@callback
def async_start_discovery(hass: HomeAssistant) -> None:
    """Look for appliances now, and again whenever a known platform adds an entity"""

    @callback
    def entity_registry_updated(event: Event[EventEntityRegistryUpdatedData]) -> None:
        if event.data["action"] != "create":
            return
        entity = er.async_get(hass).async_get(event.data["entity_id"])
        if entity is not None and entity.platform in CYCLE_KEYS:
            async_discover(hass)

    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, entity_registry_updated)
    async_discover(hass)
