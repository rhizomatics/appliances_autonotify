from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service

from custom_components.appliance_auto_notifier.const import DOMAIN

from .conftest import DISHWASHER_PROGRAMS, add_appliance, mock_dashboards, mock_supernotify, setup_watcher


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
    assert calls[2].data == {
        "message": "Dishwasher is finished",
        "title": "Dishwasher",
        "extra_data": {"notification_icon": "mdi:dishwasher"},
    }

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
    # the first reading is sent whatever it is, since the start had no progress to show
    await set_state(hass, appliance.progress, "4")
    assert len(calls) == 2
    assert calls[1].data["extra_data"]["progress"] == 4
    await set_state(hass, appliance.progress, "6")
    assert len(calls) == 2

    await set_state(hass, appliance.progress, "12")
    assert len(calls) == 3
    assert calls[2].data == {
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
    assert len(calls) == 3
    await set_state(hass, appliance.progress, "20")
    assert len(calls) == 4


async def test_progress_notified_when_asked_for(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance, {"notify_progress": True, "deliveries": ["chimes", "phones"]})
    tag = f"appliance_{entry.entry_id}"

    await set_state(hass, appliance.cycle, "run")
    # the first reading comes straight after the start, so only fills in the Live Activity
    await set_state(hass, appliance.progress, "4")
    assert len(calls) == 2
    assert calls[1].data["delivery"] == ["phones"]
    assert calls[1].data["extra_data"]["silent"] is True

    # an ordinary notification, everywhere chosen, which keeps the Live Activity up to date too
    await set_state(hass, appliance.progress, "10")
    assert len(calls) == 3
    assert calls[2].data == {
        "message": "10% complete",
        "title": "Dishwasher",
        "force_resend": True,
        "delivery_selection": "explicit",
        "delivery": ["chimes", "phones"],
        "extra_data": {
            "mobile_push_notification_tag": tag,
            "live_update": True,
            "notification_icon": "mdi:dishwasher",
            "progress": 10,
            "progress_max": 100,
        },
    }


async def test_progress_notified_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"], "notify_progress": True})
    calls = async_mock_service(hass, "notify", "send_message")

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "4")
    assert len(calls) == 1
    await set_state(hass, appliance.progress, "30")
    assert [c.data["message"] for c in calls] == ["Dishwasher started", "30% complete"]


async def test_progress_bar_updated_more_often_towards_the_end(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.progress, "0")
    await setup_watcher(hass, appliance, {"notify_progress": True})
    await set_state(hass, appliance.cycle, "run")

    sent: list[tuple[int, bool]] = []
    for progress in (80, 89, 90, 91, 92, 93, 97, 99, 100):
        await set_state(hass, appliance.progress, str(progress))
        sent = [(c.data["extra_data"]["progress"], "silent" in c.data["extra_data"]) for c in calls[1:]]
    # every two percent from ninety, of which only the tens are also ordinary notifications
    assert sent == [(80, False), (90, False), (92, True), (97, True), (99, True), (100, False)]


async def test_live_activity_names_the_program(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.progress, "0")
    await setup_watcher(hass, appliance)
    await set_state(hass, appliance.cycle, "run")

    # not yet known, so nothing to say but the progress
    await set_state(hass, appliance.program, "unknown")
    await set_state(hass, appliance.progress, "10")
    assert calls[1].data["message"] == "10% complete"

    await set_state(hass, appliance.program, "dishcare_dishwasher_program_eco_50")
    key = "component.home_connect.entity.select.active_program.state.dishcare_dishwasher_program_eco_50"
    with patch("homeassistant.helpers.translation.async_get_cached_translations", return_value={key: "Eco 50ºC"}):
        await set_state(hass, appliance.progress, "20")
    assert calls[2].data["message"] == "Eco 50ºC"
    assert calls[2].data["extra_data"]["progress"] == 20


async def test_program_chosen_is_named_when_none_is_under_way(hass: HomeAssistant) -> None:
    # an oven reports the program it's set to, and never one under way
    oven = add_appliance(hass, "Oven", "NEFF-2", oven=True)
    calls = mock_supernotify(hass)
    hass.states.async_set(oven.progress, "0")
    hass.states.async_set(oven.program, "unknown")
    hass.states.async_set(oven.others["selected_program"], "cooking_oven_program_heating_mode_pizza_setting")
    await setup_watcher(hass, oven)
    await set_state(hass, oven.cycle, "run")

    key = "component.home_connect.entity.select.selected_program.state.cooking_oven_program_heating_mode_pizza_setting"
    with patch("homeassistant.helpers.translation.async_get_cached_translations", return_value={key: "Pizza setting"}):
        await set_state(hass, oven.progress, "10")
    assert calls[1].data["message"] == "Pizza setting"

    # the one under way is the one to go by, where there is one
    await set_state(hass, oven.program, "cooking_oven_program_heating_mode_hot_air")
    await set_state(hass, oven.progress, "20")
    assert calls[2].data["message"] == "cooking_oven_program_heating_mode_hot_air"


async def test_icon_follows_the_type_of_appliance(hass: HomeAssistant) -> None:
    # known by its programs, whatever it has been called
    appliance = add_appliance(hass, "Bertha", programs=DISHWASHER_PROGRAMS)
    oven = add_appliance(hass, "Downstairs", "NEFF-2", oven=True)
    unknown = add_appliance(hass, "Coffee machine", "BOSCH-3")
    calls = mock_supernotify(hass)
    for each in (appliance, oven, unknown):
        await setup_watcher(hass, each)
        await set_state(hass, each.cycle, "run")
        await set_state(hass, each.cycle, "finished")

    icons = [c.data["extra_data"].get("notification_icon") for c in calls]
    # on the start and the end, the clearing of the Live Activity between them having nothing to show
    assert icons == [
        "mdi:dishwasher",
        None,
        "mdi:dishwasher",
        "mdi:stove",
        None,
        "mdi:stove",
        "mdi:coffee-maker",
        None,
        "mdi:coffee-maker",
    ]


async def test_start_and_end_notifications_switched_off(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance, {"notify_start": False, "notify_end": False})
    tag = f"appliance_{entry.entry_id}"

    # the Live Activity is still opened, on phones alone and without a sound
    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1
    assert calls[0].data == {
        "message": "Dishwasher started",
        "title": "Dishwasher",
        "delivery_selection": "fixed",
        "force_resend": True,
        "delivery": ["mobile_push", "phones"],
        "extra_data": {
            "mobile_push_notification_tag": tag,
            "live_update": True,
            "notification_icon": "mdi:dishwasher",
            "silent": True,
            "alert_once": True,
        },
    }

    # and still closed
    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 2
    assert calls[1].data["extra_data"] == {"mobile_push_notification_tag": tag, "mobile_push_clear_notification": True}


async def test_start_and_end_switched_separately(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance, {"notify_end": False})

    await set_state(hass, appliance.cycle, "run")
    assert "delivery_selection" not in calls[0].data
    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 2


async def test_start_and_end_switched_off_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"], "notify_start": False})
    calls = async_mock_service(hass, "notify", "send_message")

    await set_state(hass, appliance.cycle, "run")
    assert not calls
    await set_state(hass, appliance.cycle, "finished")
    assert [c.data["message"] for c in calls] == ["Dishwasher is finished"]


PIZZA = "cooking_oven_program_heating_mode_pizza_setting"


async def start_oven(
    hass: HomeAssistant, target: str = "200", current: str = "20", options: dict[str, Any] | None = None, cycle: str = "ready"
):
    oven = add_appliance(hass, "Oven", "NEFF-2", oven=True)
    calls = mock_supernotify(hass)
    hass.states.async_set(oven.cycle, cycle)
    # any program will do, an oven warms up for all of them
    hass.states.async_set(oven.program, PIZZA)
    hass.states.async_set(oven.others["setpoint_temperature"], target, {"unit_of_measurement": "°C"})
    hass.states.async_set(oven.others["oven_current_cavity_temperature"], current, {"unit_of_measurement": "°C"})
    # as left by the last time the oven was heated
    hass.states.async_set(oven.others["preheat_finished"], "confirmed")
    hass.states.async_set(oven.others["regular_preheat_finished"], "off")
    hass.states.async_set(oven.others["fast_pre_heat"], "off")
    entry = await setup_watcher(hass, oven, options)
    await set_state(hass, oven.cycle, "run")
    return oven, calls, entry


async def set_temperature(hass: HomeAssistant, entity_id: str, temperature: str) -> None:
    hass.states.async_set(entity_id, temperature, {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()


async def test_oven_progress_is_its_temperature_until_up_to_heat(hass: HomeAssistant) -> None:
    oven, calls, entry = await start_oven(hass)
    cavity = oven.others["oven_current_cavity_temperature"]
    # the bar starts where the oven is, a tenth of the way to its temperature
    assert len(calls) == 1
    assert calls[0].data["message"] == "Oven started"
    assert calls[0].data["extra_data"]["progress"] == 10
    assert calls[0].data["extra_data"]["progress_max"] == 100

    # throttled as any other progress
    await set_temperature(hass, cavity, "38")
    assert len(calls) == 1
    await set_temperature(hass, cavity, "104")
    assert len(calls) == 2
    assert calls[1].data["message"] == "Pre-heating, 104 of 200°C"
    assert calls[1].data["extra_data"]["progress"] == 52
    assert calls[1].data["extra_data"]["silent"] is True

    await set_state(hass, oven.others["fast_pre_heat"], "on")
    await set_temperature(hass, cavity, "150")
    assert calls[2].data["message"] == "Fast pre-heat, 150 of 200°C"
    assert calls[2].data["extra_data"]["progress"] == 75

    # a lower temperature asked for moves the bar on too
    await set_temperature(hass, oven.others["setpoint_temperature"], "170")
    assert calls[3].data["message"] == "Fast pre-heat, 150 of 170°C"
    assert calls[3].data["extra_data"]["progress"] == 88

    # up to heat is told everywhere, in a notification of its own
    await set_temperature(hass, cavity, "171")
    assert len(calls) == 6
    assert calls[4].data == {
        "message": "Oven is pre-heated",
        "title": "Oven",
        "force_resend": True,
        "extra_data": {"notification_icon": "mdi:stove"},
    }
    # and the Live Activity, which stays for as long as the oven is on, goes straight on to what it's now doing
    assert calls[5].data["message"] == f"{PIZZA}, 171°C"
    assert calls[5].data["delivery"] == ["mobile_push", "phones"]
    assert calls[5].data["extra_data"] == {
        "mobile_push_notification_tag": f"appliance_{entry.entry_id}",
        "live_update": True,
        "notification_icon": "mdi:stove",
        "silent": True,
        "alert_once": True,
    }

    # however the temperature then wanders, it isn't warming up again, nor told of twice
    await set_temperature(hass, cavity, "168")
    await set_temperature(hass, cavity, "174")
    await set_state(hass, oven.others["regular_preheat_finished"], "present")
    assert len(calls) == 6
    # though the Live Activity is kept to within a few degrees of it
    await set_temperature(hass, cavity, "160")
    assert [c.data["message"] for c in calls[6:]] == [f"{PIZZA}, 160°C"]
    assert calls[6].data["extra_data"]["silent"] is True

    # with a timer set there's then the progress of the program to show, whatever the bar had got to
    await set_state(hass, oven.progress, "30")
    assert len(calls) == 8
    assert calls[7].data["message"] == f"{PIZZA}, 160°C"
    assert calls[7].data["extra_data"]["progress"] == 30

    await set_state(hass, oven.cycle, "ready")
    assert [c.data["message"] for c in calls[8:]] == ["Oven is finished", "Oven is finished"]
    calls.clear()

    # switched on again while warm, it has only the rest of the way to go
    await set_state(hass, oven.progress, "unavailable")
    await set_temperature(hass, cavity, "101")
    await set_state(hass, oven.cycle, "run")
    assert calls[0].data["extra_data"]["progress"] == 59
    await set_temperature(hass, cavity, "165")
    assert calls[1].data["message"] == "Fast pre-heat, 165 of 170°C"


async def test_oven_is_up_to_heat_when_it_says_so(hass: HomeAssistant) -> None:
    oven, calls, _entry = await start_oven(hass, options={"notify_phase": False})
    await set_temperature(hass, oven.others["oven_current_cavity_temperature"], "190")
    assert len(calls) == 2

    # only as it happens, and with phases not to be told of, on the Live Activity alone
    await set_state(hass, oven.others["preheat_finished"], "off")
    assert len(calls) == 2
    await set_state(hass, oven.others["preheat_finished"], "present")
    assert len(calls) == 3
    assert calls[2].data["message"] == f"{PIZZA}, 190°C"
    assert calls[2].data["delivery"] == ["mobile_push", "phones"]
    assert calls[2].data["extra_data"]["silent"] is True
    assert "progress" not in calls[2].data["extra_data"]

    await set_state(hass, oven.others["regular_preheat_finished"], "present")
    await set_temperature(hass, oven.others["oven_current_cavity_temperature"], "193")
    assert len(calls) == 3


async def test_oven_already_hot_is_not_warming_up(hass: HomeAssistant) -> None:
    oven, calls, _entry = await start_oven(hass, current="210")
    cavity = oven.others["oven_current_cavity_temperature"]
    assert "progress" not in calls[0].data["extra_data"]
    # nor told of as up to heat, only shown on the Live Activity as doing what it's doing
    await set_temperature(hass, cavity, "190")
    await set_temperature(hass, cavity, "192")
    await set_temperature(hass, cavity, "205")
    assert [c.data["message"] for c in calls[1:]] == [f"{PIZZA}, 190°C", f"{PIZZA}, 205°C"]
    assert all(c.data["extra_data"]["silent"] for c in calls[1:])


async def test_oven_on_at_startup_is_not_warming_up(hass: HomeAssistant) -> None:
    # there's no knowing whether it has been up to heat
    oven, calls, _entry = await start_oven(hass, cycle="run")
    cavity = oven.others["oven_current_cavity_temperature"]
    await set_temperature(hass, cavity, "120")
    await set_temperature(hass, cavity, "210")
    await set_state(hass, oven.others["regular_preheat_finished"], "present")
    assert [c.data["message"] for c in calls] == [f"{PIZZA}, 120°C", f"{PIZZA}, 210°C"]


async def test_oven_temperatures_known_only_once_started(hass: HomeAssistant) -> None:
    oven, calls, _entry = await start_oven(hass, target="unavailable")
    cavity = oven.others["oven_current_cavity_temperature"]
    assert "progress" not in calls[0].data["extra_data"]
    await set_state(hass, cavity, "garbled")
    assert len(calls) == 1

    # with no timer set, an oven's own progress is of nothing
    await set_state(hass, oven.progress, "100")
    assert calls[1].data["extra_data"]["progress"] == 100

    # the bar goes back to how far there is to go
    await set_temperature(hass, cavity, "50")
    await set_temperature(hass, oven.others["setpoint_temperature"], "200")
    assert len(calls) == 3
    assert calls[2].data["message"] == "Pre-heating, 50 of 200°C"
    assert calls[2].data["extra_data"]["progress"] == 25

    # hot enough without ever having been seen to warm up is still told of
    hass.states.async_set(oven.others["setpoint_temperature"], "unavailable")
    await set_temperature(hass, cavity, "220")
    await set_temperature(hass, oven.others["setpoint_temperature"], "200")
    assert [c.data["message"] for c in calls[3:]] == ["Oven is pre-heated", f"{PIZZA}, 220°C"]


async def test_tap_opens_chosen_dashboard(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    mock_dashboards(hass)
    hass.states.async_set(appliance.progress, "0")
    await setup_watcher(hass, appliance, {"dashboard": "dashboard-kitchen"})

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "10")
    await set_state(hass, appliance.cycle, "finished")
    tap = {"url": "/dashboard-kitchen", "clickAction": "/dashboard-kitchen"}
    # the start, each update of the Live Activity since iOS forgets otherwise, and the end, but not the clearing
    assert [{k: v for k, v in c.data.get("extra_data", {}).items() if k in tap} for c in calls] == [tap, tap, {}, tap]


async def test_tap_goes_nowhere_but_a_dashboard(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    mock_dashboards(hass)
    # not something the settings would save, nor a dashboard that's since been removed
    await setup_watcher(hass, appliance, {"dashboard": "/example.com/rickroll"})

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 3
    assert not any(key in call.data.get("extra_data", {}) for call in calls for key in ("url", "clickAction"))


async def test_progress_known_at_start_is_not_repeated(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.progress, "0")
    await setup_watcher(hass, appliance)

    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1
    assert calls[0].data["extra_data"]["progress"] == 0

    await set_state(hass, appliance.progress, "4")
    assert len(calls) == 1
    await set_state(hass, appliance.progress, "10")
    assert len(calls) == 2


async def test_progress_update_cannot_overtake_the_end(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance)
    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1

    # hold up the progress update while it's finding the mobile deliveries
    held = asyncio.Event()
    release = asyncio.Event()

    async def slow_enquiry(call: ServiceCall) -> dict[str, list[str]]:
        if not held.is_set():
            held.set()
            await release.wait()
        return {"mobile_push": ["mobile_push"]}

    hass.services.async_register(
        "supernotify", "enquire_implicit_deliveries", slow_enquiry, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set(appliance.progress, "100")
    await held.wait()
    hass.states.async_set(appliance.cycle, "finished")
    await asyncio.sleep(0.05)
    release.set()
    await hass.async_block_till_done()

    # were the update sent after the clear, the mobile app would open the Live Activity again
    assert [bool(call.data.get("extra_data", {}).get("live_update")) for call in calls[1:]] == [True, False, False]
    assert calls[2].data["extra_data"]["mobile_push_clear_notification"] is True


async def test_live_activity_cleared_on_delivery_known_only_by_its_switch(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    # Delivery Control can leave the standard mobile push delivery neither implicit nor configured
    async_mock_service(hass, "supernotify", "enquire_implicit_deliveries", response={}, supports_response=SupportsResponse.ONLY)
    async_mock_service(
        hass, "supernotify", "enquire_configuration", response={"delivery": {}}, supports_response=SupportsResponse.ONLY
    )
    calls = async_mock_service(hass, "supernotify", "notify")
    hass.states.async_set("switch.supernotify_delivery_mobile_push", "on", {"name": "mobile_push", "transport": "mobile_push"})
    hass.states.async_set("switch.supernotify_delivery_chimes", "on", {"name": "chimes", "transport": "chime"})
    await setup_watcher(hass, appliance)

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 3
    assert calls[1].data["delivery"] == ["mobile_push"]
    assert calls[1].data["extra_data"]["mobile_push_clear_notification"] is True


async def test_cycle_ends_without_finished_state(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass, "Oven")
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance)

    # an oven switched off never reports `finished`
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "ready")
    assert len(calls) == 3
    assert calls[1].data["extra_data"]["mobile_push_clear_notification"] is True
    assert calls[2].data == {"message": "Oven is finished", "title": "Oven", "extra_data": {"notification_icon": "mdi:stove"}}

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


async def test_phones_notified_when_nothing_chosen(hass: HomeAssistant, caplog) -> None:
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance)
    calls = async_mock_service(hass, "notify", "send_message")

    await set_state(hass, appliance.cycle, "run")
    assert not calls
    assert "Nothing to notify for Dishwasher" in caplog.text

    registry = er.async_get(hass)
    phone = registry.async_get_or_create("notify", "mobile_app", "phone", suggested_object_id="phone")
    registry.async_get_or_create("notify", "mobile_app", "old", disabled_by=er.RegistryEntryDisabler.USER)
    registry.async_get_or_create("notify", "demo", "display")
    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == [phone.entity_id]


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
    entry = await setup_power_watcher(hass, grace_period=10)
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
    assert calls[2].data == {
        "message": "Washer is finished",
        "title": "Washer",
        "extra_data": {"notification_icon": "mdi:washing-machine"},
    }

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
