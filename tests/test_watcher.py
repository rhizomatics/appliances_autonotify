from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service

from custom_components.appliances_supernotifications.const import DOMAIN

from .conftest import add_appliance, mock_supernotify, setup_watcher


async def set_state(hass: HomeAssistant, entity_id: str, state: str) -> None:
    hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()


async def test_cycle_with_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    entry = await setup_watcher(hass, appliance)
    tag = f"appliance_{entry.entry_id}"

    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1
    assert calls[0].data == {
        "message": "Dishwasher started",
        "title": "Dishwasher",
        "extra_data": {"mobile_push_notification_tag": tag, "live_update": True, "notification_icon": "mdi:dishwasher"},
    }

    # paused and resumed is the same cycle
    await set_state(hass, appliance.cycle, "pause")
    await set_state(hass, appliance.cycle, "unavailable")
    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1

    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 3
    assert calls[1].data == {
        "message": "Dishwasher is finished",
        "title": "Dishwasher",
        "delivery_selection": "fixed",
        "force_resend": True,
        "delivery": ["mobile_push", "phones"],
        "extra_data": {"mobile_push_notification_tag": tag, "mobile_push_clear_notification": True},
    }
    assert calls[2].data == {"message": "Dishwasher is finished", "title": "Dishwasher"}

    # finished only once
    await set_state(hass, appliance.cycle, "inactive")
    assert len(calls) == 3


async def test_progress_updates_mobile_only(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance)
    tag = f"appliance_{entry.entry_id}"

    # progress outside a cycle is ignored
    await set_state(hass, appliance.progress, "50")
    assert not calls

    await set_state(hass, appliance.progress, "unavailable")
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.finish_time, "2026-10-06T21:44:16+00:00")
    await set_state(hass, appliance.progress, "4")
    assert len(calls) == 1

    await set_state(hass, appliance.progress, "12")
    assert len(calls) == 2
    assert calls[1].data == {
        "message": "12% complete",
        "title": "Dishwasher",
        "delivery_selection": "fixed",
        "force_resend": True,
        "delivery": ["mobile_push", "phones"],
        "extra_data": {
            "mobile_push_notification_tag": tag,
            "live_update": True,
            "notification_icon": "mdi:dishwasher",
            "progress": 12,
            "progress_max": 100,
            "chronometer": True,
            "when": 1791323056,
            "silent": True,
            "alert_once": True,
        },
    }

    # throttled to steps of ten percent
    await set_state(hass, appliance.progress, "19")
    assert len(calls) == 2
    await set_state(hass, appliance.progress, "20")
    assert len(calls) == 3


async def test_cycle_ends_without_finished_state(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass, "Oven")
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance)

    # an oven switched off never reports `finished`
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "ready")
    assert len(calls) == 3
    assert calls[1].data["extra_data"]["mobile_push_clear_notification"] is True
    assert calls[2].data == {"message": "Oven is finished", "title": "Oven"}

    await set_state(hass, appliance.cycle, "inactive")
    assert len(calls) == 3


async def test_abandoned_cycle_clears_without_end_notification(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance)

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "aborting")
    assert len(calls) == 2
    assert calls[1].data["extra_data"]["mobile_push_clear_notification"] is True


async def test_cycle_running_at_startup_is_ended(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "run")
    await setup_watcher(hass, appliance)
    assert not calls

    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 2


async def test_overrides_targets_and_deliveries(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(
        hass,
        appliance,
        {
            "start_title": "Kitchen",
            "start_message": "{name} is go {odd}",
            "end_title": "Kitchen done",
            "end_message": "Empty the {name}",
            "target": {"entity_id": ["person.joe"], "area_id": ["kitchen"]},
            "custom_target": ["joe@example.com"],
            "deliveries": ["phones", "chimes"],
        },
    )

    await set_state(hass, appliance.cycle, "run")
    assert calls[0].data["title"] == "Kitchen"
    assert calls[0].data["message"] == "Dishwasher is go {odd}"
    assert calls[0].data["target"] == {"entity_id": ["person.joe"], "area_id": ["kitchen"]}
    assert calls[0].data["custom_target"] == ["joe@example.com"]
    assert calls[0].data["delivery"] == ["phones", "chimes"]
    assert calls[0].data["delivery_selection"] == "explicit"

    await set_state(hass, appliance.cycle, "finished")
    # only the chosen deliveries that are mobile push have a Live Activity to clear
    assert calls[1].data["delivery"] == ["phones"]
    assert calls[2].data["title"] == "Kitchen done"
    assert calls[2].data["message"] == "Empty the Dishwasher"


async def test_no_mobile_deliveries_chosen(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance, {"deliveries": ["chimes"]})

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "50")
    await set_state(hass, appliance.cycle, "finished")
    assert [c.data["message"] for c in calls] == ["Dishwasher started", "Dishwasher is finished"]


async def test_cycle_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    entry = await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"]})
    calls = async_mock_service(hass, "notify", "send_message")

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "50")
    assert len(calls) == 1
    assert calls[0].data == {"entity_id": ["notify.kitchen_display"], "message": "Dishwasher started", "title": "Dishwasher"}

    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 2
    assert calls[1].data["message"] == "Dishwasher is finished"

    # nothing to say when a cycle is abandoned and there's no Live Activity to clear
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "error")
    assert len(calls) == 3

    assert await hass.config_entries.async_unload(entry.entry_id)
    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 3


async def test_notification_failure_is_logged(hass: HomeAssistant, caplog) -> None:
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"]})

    def fail(call) -> None:
        raise HomeAssistantError("offline")

    hass.services.async_register("notify", "send_message", fail)
    await set_state(hass, appliance.cycle, "run")
    assert "Notification failed for Dishwasher" in caplog.text

    hass.services.async_register("supernotify", "notify", fail)
    await set_state(hass, appliance.cycle, "finished")
    assert "Supernotify notification failed for Dishwasher" in caplog.text


async def test_setup_retried_when_appliance_missing(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Gone", data={CONF_DEVICE_ID: "nosuchdevice"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def setup_power_watcher(hass: HomeAssistant, **options: float) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Washer",
        unique_id="sensor.washer_power",
        data={"type": "power"},
        options={"power_entity": "sensor.washer_power", **options},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def pass_time(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_power_monitored_cycle(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0.4", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass)
    tag = f"appliance_{entry.entry_id}"

    # at the threshold isn't running
    await set_state(hass, "sensor.washer_power", "1")
    assert not calls

    await set_state(hass, "sensor.washer_power", "1800")
    assert len(calls) == 1
    assert calls[0].data == {
        "message": "Washer started",
        "title": "Washer",
        "extra_data": {"mobile_push_notification_tag": tag, "live_update": True, "notification_icon": "mdi:washing-machine"},
    }

    # a drop out shorter than the grace period is the same cycle
    await set_state(hass, "sensor.washer_power", "0")
    freezer.tick(6)
    await pass_time(hass, 0)
    await set_state(hass, "sensor.washer_power", "unavailable")
    await set_state(hass, "sensor.washer_power", "300")
    freezer.tick(6)
    await pass_time(hass, 0)
    assert len(calls) == 1

    # the grace period is from when the power first dropped
    await set_state(hass, "sensor.washer_power", "0.8")
    freezer.tick(6)
    await pass_time(hass, 0)
    await set_state(hass, "sensor.washer_power", "0.2")
    assert len(calls) == 1
    freezer.tick(5)
    await pass_time(hass, 0)
    assert len(calls) == 3
    assert calls[1].data["extra_data"] == {"mobile_push_notification_tag": tag, "mobile_push_clear_notification": True}
    assert calls[2].data == {"message": "Washer is finished", "title": "Washer"}

    # ended only once
    await set_state(hass, "sensor.washer_power", "0")
    freezer.tick(60)
    await pass_time(hass, 0)
    assert len(calls) == 3


async def test_power_threshold_grace_and_units(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    # running at startup, so no start is notified
    hass.states.async_set("sensor.washer_power", "1.2", {"unit_of_measurement": "kW"})
    entry = await setup_power_watcher(hass, threshold=50, grace_period=120)
    assert entry.runtime_data.running
    assert not calls

    await set_state(hass, "sensor.washer_power", "0.04")
    freezer.tick(119)
    await pass_time(hass, 0)
    assert not calls
    freezer.tick(2)
    await pass_time(hass, 0)
    assert [c.data["message"] for c in calls] == ["Washer is finished", "Washer is finished"]

    hass.states.async_set("sensor.washer_power", "0.06", {"unit_of_measurement": "kW"})
    await hass.async_block_till_done()
    assert len(calls) == 3

    # nothing left waiting once unloaded
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "kW"})
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(300)
    await pass_time(hass, 0)
    assert len(calls) == 3
