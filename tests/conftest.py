from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.appliances_supernotifications.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


@dataclass
class FakeAppliance:
    device_id: str
    cycle: str
    progress: str
    finish_time: str


def add_appliance(hass: HomeAssistant, name: str = "Dishwasher", ha_id: str = "BOSCH-1") -> FakeAppliance:
    """Register a Home Connect appliance as the core integration would"""
    source = MockConfigEntry(domain="home_connect", entry_id=f"hc_{ha_id}")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("home_connect", ha_id)}, name=name
    )
    entity_registry = er.async_get(hass)
    entity_ids: dict[str, str] = {}
    for key in ("operation_state", "program_progress", "program_finish_time"):
        entity_ids[key] = entity_registry.async_get_or_create(
            "sensor",
            "home_connect",
            f"{ha_id}-{key}",
            suggested_object_id=f"{name.lower()}_{key}",
            device_id=device.id,
            config_entry=source,
            translation_key=key,
        ).entity_id
    return FakeAppliance(
        device.id, entity_ids["operation_state"], entity_ids["program_progress"], entity_ids["program_finish_time"]
    )


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
        response={"delivery": {"chimes": {"transport": "chime"}, "phones": {"transport": "mobile_push"}}},
        supports_response=SupportsResponse.ONLY,
    )
    return async_mock_service(hass, "supernotify", "notify")


async def setup_watcher(
    hass: HomeAssistant, appliance: FakeAppliance, options: dict[str, Any] | None = None
) -> MockConfigEntry:
    assert await async_setup_component(hass, "notify", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Dishwasher",
        unique_id=appliance.device_id,
        data={CONF_DEVICE_ID: appliance.device_id},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
