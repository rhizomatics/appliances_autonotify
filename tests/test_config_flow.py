from __future__ import annotations

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.appliances_supernotifications.const import DOMAIN, SUPERNOTIFY_MISSING, SUPERNOTIFY_PRESENT

from .conftest import add_appliance, mock_supernotify, setup_watcher


async def test_user_flow_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["description_placeholders"] == {"supernotify": SUPERNOTIFY_MISSING}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device_id": appliance.device_id})
    assert result["step_id"] == "settings"
    assert "deliveries" not in result["data_schema"].schema

    # a notify entity is mandatory without Supernotify
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"targets": []})
    assert result["errors"] == {"targets": "targets_required"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"targets": ["notify.kitchen_display"], "end_message": "Done"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dishwasher"
    assert result["data"] == {"device_id": appliance.device_id}
    assert result["options"] == {"targets": ["notify.kitchen_display"], "end_message": "Done"}


async def test_user_flow_with_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_supernotify(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["description_placeholders"] == {"supernotify": SUPERNOTIFY_PRESENT}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device_id": appliance.device_id})
    deliveries = next(v for k, v in result["data_schema"].schema.items() if k == "deliveries")
    assert deliveries.config["options"] == ["chimes", "email", "mobile_push", "phones"]

    # the notify entity list is only for use without Supernotify
    assert "targets" not in result["data_schema"].schema

    # nothing is mandatory, Supernotify chooses
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"target": {"entity_id": ["person.joe"]}, "custom_target": ["joe@example.com"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {"target": {"entity_id": ["person.joe"]}, "custom_target": ["joe@example.com"]}


async def test_user_flow_no_appliances(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_appliances"

    # and none left once the only one is set up
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"]})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["reason"] == "no_appliances"


async def test_other_appliances_discovered_once_set_up(hass: HomeAssistant) -> None:
    dishwasher = add_appliance(hass)
    oven = add_appliance(hass, "Oven", "NEFF-2")
    await setup_watcher(hass, dishwasher, {"targets": ["notify.kitchen_display"]})

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY
    assert flows[0]["context"]["unique_id"] == oven.device_id
    assert flows[0]["context"]["title_placeholders"] == {"name": "Oven"}
    assert flows[0]["step_id"] == "settings"

    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"targets": ["notify.kitchen_display"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Oven"


async def test_new_appliance_discovered_when_added(hass: HomeAssistant) -> None:
    dishwasher = add_appliance(hass)
    await setup_watcher(hass, dishwasher, {"targets": ["notify.kitchen_display"]})
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)

    # entities of other platforms don't cause a search
    er.async_get(hass).async_get_or_create("sensor", "demo", "other", translation_key="operation_state")
    await hass.async_block_till_done()
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)

    washer = add_appliance(hass, "Washer", "BOSCH-3")
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["unique_id"] for f in flows] == [washer.device_id]


async def test_options_flow(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    entry = await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"]})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"targets": []})
    assert result["errors"] == {"targets": "targets_required"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"targets": ["notify.hall_display"], "start_title": "Kitchen"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {"targets": ["notify.hall_display"], "start_title": "Kitchen"}
    assert entry.runtime_data.entry.options["start_title"] == "Kitchen"


async def test_setup_without_entries(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
