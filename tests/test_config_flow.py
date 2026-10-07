from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, SOURCE_USER, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.appliance_auto_notifier.const import DOMAIN, SUPERNOTIFY_MISSING, SUPERNOTIFY_PRESENT

from .conftest import add_appliance, mock_supernotify, setup_watcher


async def start_found(hass: HomeAssistant) -> ConfigFlowResult:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["power", "found"]
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "found"})


def suggested(result) -> dict[str, Any]:
    return {k: k.description["suggested_value"] for k in result["data_schema"].schema if k.description}


async def test_user_flow_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    result = await start_found(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "found"
    assert result["description_placeholders"] == {
        "name": "Dishwasher",
        "supernotify": SUPERNOTIFY_MISSING,
        "placeholder": "{name}",
    }
    assert "deliveries" not in result["data_schema"].schema
    # titles and messages start out as the default text
    assert suggested(result) == {
        "start_title": "{name}",
        "start_message": "{name} started",
        "end_title": "{name}",
        "end_message": "{name} is finished",
    }

    # a notify entity is mandatory without Supernotify
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"targets": [], "end_message": "Done"})
    assert result["errors"] == {"targets": "targets_required"}
    assert suggested(result)["end_message"] == "Done"
    assert suggested(result)["start_message"] == "{name} started"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"targets": ["notify.kitchen_display"], "end_message": "Done"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dishwasher"
    assert result["data"] == {"device_id": appliance.device_id}
    assert result["options"] == {"targets": ["notify.kitchen_display"], "end_message": "Done"}


async def test_user_flow_with_supernotify(hass: HomeAssistant) -> None:
    add_appliance(hass)
    mock_supernotify(hass)
    result = await start_found(hass)
    assert result["description_placeholders"]["supernotify"] == SUPERNOTIFY_PRESENT
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


async def test_user_flow_sets_up_every_appliance(hass: HomeAssistant) -> None:
    dishwasher = add_appliance(hass)
    oven = add_appliance(hass, "Oven", "NEFF-2")
    # as at startup, with each appliance already offered as a discovery
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert len(hass.config_entries.flow.async_progress_by_handler(DOMAIN)) == 2

    result = await start_found(hass)
    assert result["description_placeholders"]["name"] == "Dishwasher, Oven"

    options = {"targets": ["notify.kitchen_display"], "start_message": "{name} is go"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], options)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert {e.unique_id: e.title for e in entries} == {dishwasher.device_id: "Dishwasher", oven.device_id: "Oven"}
    assert all(e.options == options for e in entries)
    # the discoveries are no longer waiting
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_user_flow_no_appliances(hass: HomeAssistant) -> None:
    # only an appliance to describe by hand is on offer
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["power"]

    # and again once the only one found is set up
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"]})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["menu_options"] == ["power"]


async def test_power_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "power"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "power"
    defaults = {str(k): k.default() for k in result["data_schema"].schema if k.default is not vol.UNDEFINED}
    assert defaults == {"threshold": 1, "grace_period": 60}

    power = {"power_entity": "sensor.washer_power", "threshold": 5, "grace_period": 60}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Washer", **power})
    assert result["step_id"] == "settings"
    assert result["description_placeholders"]["name"] == "Washer"
    assert suggested(result)["start_message"] == "{name} started"

    settings = {"targets": ["notify.kitchen_display"], "end_message": "Hang out the washing"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], settings)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Washer"
    assert result["data"] == {"type": "power"}
    assert result["options"] == settings | power
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.runtime_data.power_entity_id == "sensor.washer_power"

    # one entry for each power sensor
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "power"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Again", **power})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"

    # the options have the same two pages
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"targets": ["notify.hall_display"]})
    assert result["step_id"] == "power"
    assert "name" not in result["data_schema"].schema
    assert suggested(result) == power
    result = await hass.config_entries.options.async_configure(result["flow_id"], power | {"threshold": 3})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {"targets": ["notify.hall_display"], **power, "threshold": 3}
    assert entry.runtime_data.threshold == 3


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
    assert suggested(result)["end_title"] == "{name}"
    assert suggested(result)["targets"] == ["notify.kitchen_display"]
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
