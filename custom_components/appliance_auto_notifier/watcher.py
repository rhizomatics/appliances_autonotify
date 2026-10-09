"""Watch one appliance, and notify as its cycle starts, progresses and ends"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_DEVICE_ID,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfPower,
)
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.translation import async_translate_state
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import PowerConverter

from .const import (
    APPLIANCE_TYPES,
    CAVITY_TEMPERATURE_KEY,
    CONF_CUSTOM_TARGET,
    CONF_DASHBOARD,
    CONF_DELIVERIES,
    CONF_END_MESSAGE,
    CONF_END_TITLE,
    CONF_GRACE_PERIOD,
    CONF_NOTIFY_END,
    CONF_NOTIFY_PHASE,
    CONF_NOTIFY_PROGRESS,
    CONF_NOTIFY_START,
    CONF_POWER_ENTITY,
    CONF_START_MESSAGE,
    CONF_START_TITLE,
    CONF_TARGET,
    CONF_TARGETS,
    CONF_THRESHOLD,
    CYCLE_KEYS,
    DEFAULT_END_MESSAGE,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_ICON,
    DEFAULT_START_MESSAGE,
    DEFAULT_THRESHOLD,
    DEFAULT_TITLE,
    ENTITY_DOMAINS,
    FAST_PREHEAT_KEY,
    FAST_PREHEAT_PHASE,
    FINISH_TIME_KEY,
    ICONS,
    MOBILE_APP_PLATFORM,
    MOBILE_PUSH_TRANSPORT,
    NAME_PLACEHOLDER,
    OVEN_MESSAGE,
    PHASES_NOTIFIED,
    PREHEAT_FINISHED_KEYS,
    PREHEAT_MESSAGE,
    PREHEAT_PHASE,
    PREHEATED_MESSAGE,
    PROGRAM_KEYS,
    PROGRESS_FINAL,
    PROGRESS_FINAL_STEP,
    PROGRESS_KEY,
    PROGRESS_MESSAGE,
    PROGRESS_STEP,
    STATE_RUN,
    STATES_ABANDONED,
    STATES_ACTIVE,
    STATES_EVENT_ON,
    STATES_FINISHED,
    SUPERNOTIFY_DOMAIN,
    TARGET_TEMPERATURE_KEY,
    TEMPERATURE_STEP,
    TYPE_ICONS,
)
from .dashboards import dashboard_url
from .supernotify_api import deliveries_by_transport, supernotify_available

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class ApplianceWatcher:
    """The notifications of a cycle, for subclasses that know when one starts and ends"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.name: str = entry.title
        self.tag: str = f"appliance_{entry.entry_id}"
        self.icon: str = self._name_icon()
        self.cycle_entity_id: str | None = None
        # by translation key, whichever of those made use of the appliance has
        self.entity_ids: dict[str, str] = {}
        self.notify_start: bool = entry.options.get(CONF_NOTIFY_START, True)
        self.notify_end: bool = entry.options.get(CONF_NOTIFY_END, True)
        self.notify_progress: bool = entry.options.get(CONF_NOTIFY_PROGRESS, False)
        # whether phases are notified unless chosen otherwise, None for an appliance that reports none
        self.phase_default: bool | None = None
        self.notify_phase: bool = False
        self.running: bool = False
        # the progress last sent, rounded down to the step it was sent for
        self.last_progress_mark: int = 0
        # one notification at a time, so a progress update can't overtake the end and reopen the Live Activity
        self._sending: asyncio.Lock = asyncio.Lock()

    @callback
    def async_start(self) -> None:
        raise NotImplementedError

    def _name_icon(self) -> str:
        return next((icon for word, icon in ICONS.items() if word in self.name.lower()), DEFAULT_ICON)

    @staticmethod
    def _mark(progress: int) -> int:
        """The progress rounded down to the step it's sent for"""
        return progress - progress % (PROGRESS_FINAL_STEP if progress >= PROGRESS_FINAL else PROGRESS_STEP)

    async def _progress_changed(self, event: Event[EventStateChangedData]) -> None:
        progress = self._progress()
        if not self.running or progress is None:
            return
        mark = self._mark(progress)
        if mark <= self.last_progress_mark:
            return
        # the first reading only fills in the Live Activity, coming straight after the start notification, as do
        # the smaller steps towards the end
        ordinary = self.notify_progress and mark // PROGRESS_STEP > max(self.last_progress_mark, 0) // PROGRESS_STEP
        self.last_progress_mark = mark
        live = supernotify_available(self.hass)
        if not live and not ordinary:
            return
        async with self._sending:
            if not self.running:
                # the cycle ended while this waited its turn
                return
            message = self._progress_message(progress)
            if live and not ordinary:
                # the bar already shows how far along it is, so there's room to say what it's doing
                message = self._phase() or message
            await self._tell(message, ordinary, resend=True)

    async def _started(self) -> None:
        async with self._sending:
            await self._tell(self._text(CONF_START_MESSAGE, DEFAULT_START_MESSAGE), self.notify_start)

    async def _tell(self, message: str, ordinary: bool, resend: bool = False) -> None:
        """Notify of a cycle under way, either everywhere or with no more than its Live Activity brought up to date"""
        # a Live Activity keeps the title it started with
        title = self._text(CONF_START_TITLE, DEFAULT_TITLE)
        if not supernotify_available(self.hass):
            if ordinary:
                await self._send_message(message, title)
        elif ordinary:
            # everywhere, opening or updating the Live Activity on phones as it goes
            await self._supernotify(message, title, resend=resend, extra_data=self._live_data())
        else:
            # with nothing to hear, and nothing sent anywhere but to phones
            await self._supernotify(
                message,
                title,
                mobile_only=True,
                extra_data=self._live_data() | {"silent": True, "alert_once": True},
            )

    async def _ended(self, finished: bool) -> None:
        title = self._text(CONF_END_TITLE, DEFAULT_TITLE)
        message = self._text(CONF_END_MESSAGE, DEFAULT_END_MESSAGE)
        notify = finished and self.notify_end
        async with self._sending:
            if not supernotify_available(self.hass):
                if notify:
                    await self._send_message(message, title)
                return
            # closing the Live Activity is not a notification in itself, so the end is told separately
            await self._supernotify(
                message,
                title,
                mobile_only=True,
                extra_data={"mobile_push_notification_tag": self.tag, "mobile_push_clear_notification": True},
            )
            if notify:
                await self._supernotify(message, title, extra_data={"notification_icon": self.icon} | self._tap_data())

    def _text(self, key: str, default: str) -> str:
        return str(self.entry.options.get(key) or default).replace(NAME_PLACEHOLDER, self.name)

    def _state(self, key: str) -> State | None:
        """The state of one of the appliance's entities, where it has the entity and its state is known"""
        entity_id = self.entity_ids.get(key)
        state = self.hass.states.get(entity_id) if entity_id else None
        return None if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE) else state

    def _number(self, key: str) -> float | None:
        state = self._state(key)
        try:
            return float(state.state) if state is not None else None
        except ValueError:
            return None

    def _progress(self) -> int | None:
        progress = self._number(PROGRESS_KEY)
        return None if progress is None else int(progress)

    def _progress_message(self, progress: int) -> str:
        return PROGRESS_MESSAGE.format(progress=progress)

    def _phase(self) -> str | None:
        """What the appliance is doing, to say alongside a bar that already shows how far along it is"""
        return self._program()

    def _program_state(self) -> State | None:
        """The program under way, or failing that the one chosen, where the appliance reports either"""
        return next((state for key in PROGRAM_KEYS if (state := self._state(key)) is not None), None)

    def _program(self) -> str | None:
        """The program as Home Assistant shows it"""
        state = self._program_state()
        if state is None:
            return None
        entity = er.async_get(self.hass).async_get(state.entity_id)
        if entity is None:
            return state.state
        return async_translate_state(self.hass, state.state, state.domain, entity.platform, entity.translation_key, None)

    def _tap_data(self) -> dict[str, Any]:
        """Where a tap on the notification goes, for both mobile platforms, if a dashboard has been chosen"""
        url = dashboard_url(self.hass, self.entry.options.get(CONF_DASHBOARD))
        return {"url": url, "clickAction": url} if url else {}

    def _live_data(self) -> dict[str, Any]:
        """Live Activity fields for the mobile app, leaving out whatever the appliance isn't reporting"""
        data: dict[str, Any] = {
            "mobile_push_notification_tag": self.tag,
            "live_update": True,
            "notification_icon": self.icon,
        } | self._tap_data()
        progress = self._progress()
        if progress is not None:
            data["progress"] = progress
            data["progress_max"] = 100
        state = self._state(FINISH_TIME_KEY)
        finish_time = dt_util.parse_datetime(state.state) if state is not None else None
        if finish_time is not None:
            data["chronometer"] = True
            data["when"] = int(finish_time.timestamp())
        return data

    async def _supernotify(
        self,
        message: str,
        title: str,
        mobile_only: bool = False,
        resend: bool = False,
        extra_data: dict[str, Any] | None = None,
    ) -> None:
        data: dict[str, Any] = {"message": message, "title": title}
        if resend:
            # Supernotify's duplicate check ignores digits, so would drop progress updates as repeats
            data["force_resend"] = True
        deliveries: list[str] = list(self.entry.options.get(CONF_DELIVERIES) or [])
        try:
            if mobile_only:
                mobile = (await deliveries_by_transport(self.hass)).get(MOBILE_PUSH_TRANSPORT, [])
                deliveries = [d for d in mobile if not deliveries or d in deliveries]
                if not deliveries:
                    _LOGGER.warning("APPLIANCES No mobile push delivery found for %s, Live Activity not updated", self.name)
                    return
                data["delivery_selection"] = "fixed"
                data["force_resend"] = True
            elif deliveries:
                data["delivery_selection"] = "explicit"
            if deliveries:
                data["delivery"] = deliveries
            for key in (CONF_TARGET, CONF_CUSTOM_TARGET):
                if value := self.entry.options.get(key):
                    data[key] = value
            if extra_data:
                data["extra_data"] = extra_data
            await self.hass.services.async_call(SUPERNOTIFY_DOMAIN, "notify", data, blocking=True)
        except HomeAssistantError:
            _LOGGER.exception("APPLIANCES Supernotify notification failed for %s", self.name)

    async def _send_message(self, message: str, title: str) -> None:
        # with none chosen, every phone with the mobile app is told
        targets: list[str] = self.entry.options.get(CONF_TARGETS) or [
            entity.entity_id
            for entity in er.async_get(self.hass).entities.values()
            if entity.domain == "notify" and entity.platform == MOBILE_APP_PLATFORM and not entity.disabled
        ]
        if not targets:
            _LOGGER.warning("APPLIANCES Nothing to notify for %s, choose targets in its settings", self.name)
            return
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {ATTR_ENTITY_ID: targets, "message": message, "title": title},
                blocking=True,
            )
        except HomeAssistantError:
            _LOGGER.exception("APPLIANCES Notification failed for %s", self.name)


class HomeConnectWatcher(ApplianceWatcher):
    """An appliance whose integration reports the state of its cycle"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        # an oven on its way up to heat, and one that has been there since it was last switched on
        self.preheating: bool = False
        self.preheated: bool = False
        # the temperature the Live Activity last showed, of an oven up to heat
        self.shown_temperature: float | None = None

    @callback
    def async_start(self) -> None:
        device_id: str = self.entry.data[CONF_DEVICE_ID]
        device = dr.async_get(self.hass).async_get(device_id)
        if device is not None:
            self.name = device.name_by_user or device.name or self.name
        programs: list[str] = []
        for entity in er.async_entries_for_device(er.async_get(self.hass), device_id):
            if entity.platform not in CYCLE_KEYS or entity.translation_key is None:
                continue
            if entity.translation_key == CYCLE_KEYS[entity.platform]:
                self.cycle_entity_id = entity.entity_id
            elif ENTITY_DOMAINS.get(entity.translation_key) == entity.domain:
                self.entity_ids[entity.translation_key] = entity.entity_id
                if entity.translation_key in PROGRAM_KEYS:
                    programs.extend((entity.capabilities or {}).get("options") or [])
        if self.cycle_entity_id is None:
            raise ConfigEntryNotReady(f"No cycle state entity found for {self.name}")
        # the type of appliance isn't kept anywhere to be read, but its programs are named for it
        appliance_type = next(
            (kind for prefix, kind in APPLIANCE_TYPES.items() if any(p.startswith(prefix) for p in programs)), None
        )
        self.icon = TYPE_ICONS.get(appliance_type or "", self._name_icon())
        # the one phase there is to know of is an oven warming up, Home Connect reporting none for anything else
        if CAVITY_TEMPERATURE_KEY in self.entity_ids and TARGET_TEMPERATURE_KEY in self.entity_ids:
            self.phase_default = appliance_type in PHASES_NOTIFIED
            self.notify_phase = self.entry.options.get(CONF_NOTIFY_PHASE, self.phase_default)

        # a cycle under way at startup still has its Live Activity closed when it ends
        state = self.hass.states.get(self.cycle_entity_id)
        self.running = state is not None and state.state in STATES_ACTIVE
        # and with no knowing whether its oven has been up to heat, it isn't taken to be warming up
        self.preheated = self.running

        self.entry.async_on_unload(async_track_state_change_event(self.hass, self.cycle_entity_id, self._cycle_changed))
        for keys, listener in (
            ((PROGRESS_KEY,), self._progress_changed),
            ((CAVITY_TEMPERATURE_KEY, TARGET_TEMPERATURE_KEY), self._temperature_changed),
            (PREHEAT_FINISHED_KEYS, self._preheat_finished),
        ):
            if entity_ids := [self.entity_ids[key] for key in keys if key in self.entity_ids]:
                self.entry.async_on_unload(async_track_state_change_event(self.hass, entity_ids, listener))

    def _temperatures(self) -> tuple[float, float] | None:
        """How hot the oven is and how hot it's to be, where both are known"""
        current, target = self._number(CAVITY_TEMPERATURE_KEY), self._number(TARGET_TEMPERATURE_KEY)
        return None if current is None or target is None or target <= 0 else (current, target)

    def _preheating(self) -> tuple[float, float] | None:
        """The temperatures of an oven still on its way up to heat, whatever program it's on"""
        temperatures = None if self.preheated or not self.running else self._temperatures()
        return None if temperatures is None or temperatures[0] >= temperatures[1] else temperatures

    def _progress(self) -> int | None:
        temperatures = self._preheating()
        if temperatures is None:
            return super()._progress()
        # an oven without a timer set has no progress to speak of, so the bar is how near it is to its temperature
        return max(0, int(temperatures[0] * 100 / temperatures[1]))

    def _preheat_message(self) -> str | None:
        temperatures = self._preheating()
        if temperatures is None:
            return None
        # a button on the oven for more of its elements to be used, which goes off by itself
        fast = self._state(FAST_PREHEAT_KEY)
        phase = FAST_PREHEAT_PHASE if fast is not None and fast.state == STATE_ON else PREHEAT_PHASE
        return PREHEAT_MESSAGE.format(
            phase=phase, current=f"{temperatures[0]:g}", target=f"{temperatures[1]:g}", unit=self._temperature_unit()
        )

    def _temperature_unit(self) -> str:
        cavity = self._state(CAVITY_TEMPERATURE_KEY)
        return cavity.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "°") if cavity is not None else "°"

    def _progress_message(self, progress: int) -> str:
        return self._preheat_message() or super()._progress_message(progress)

    def _phase(self) -> str | None:
        if message := self._preheat_message():
            return message
        program, current = super()._phase(), self._number(CAVITY_TEMPERATURE_KEY)
        if program is None or current is None:
            return program
        return OVEN_MESSAGE.format(program=program, current=f"{current:g}", unit=self._temperature_unit())

    async def _temperature_changed(self, event: Event[EventStateChangedData]) -> None:
        if not self.running:
            return
        if self.preheated:
            await self._temperature_shown()
            return
        temperatures = self._temperatures()
        if temperatures is None:
            return
        if temperatures[0] < temperatures[1]:
            if not self.preheating:
                # whatever progress has been shown till now wasn't of this
                self.preheating = True
                self.last_progress_mark = -1
            await self._progress_changed(event)
        elif self.preheating:
            await self._preheated()
        else:
            # already hot when it was switched on
            self.preheated = True

    async def _preheat_finished(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        # only as it happens, since the sensor may still be telling of the last time the oven was heated
        if self.running and not self.preheated and new_state is not None and new_state.state in STATES_EVENT_ON:
            await self._preheated()

    async def _temperature_shown(self, always: bool = False) -> None:
        """Keep the Live Activity of an oven up to heat to its temperature, give or take a few degrees"""
        current = self._number(CAVITY_TEMPERATURE_KEY)
        shown = self.shown_temperature
        if not always and (current is None or (shown is not None and abs(current - shown) < TEMPERATURE_STEP)):
            return
        self.shown_temperature = current
        async with self._sending:
            if self.running and (message := self._phase()):
                await self._tell(message, ordinary=False)

    async def _preheated(self) -> None:
        """The oven is up to heat, and however its temperature then wanders isn't warming up again till it's been off"""
        self.preheated = True
        self.preheating = False
        # back to the progress of the program, for an oven with a timer set
        progress = self._progress()
        self.last_progress_mark = -1 if progress is None else self._mark(progress)
        message = PREHEATED_MESSAGE.replace(NAME_PLACEHOLDER, self.name)
        title = self._text(CONF_START_TITLE, DEFAULT_TITLE)
        async with self._sending:
            if not self.running or not self.notify_phase:
                pass
            elif supernotify_available(self.hass):
                # a notification of its own, so that it isn't lost as the Live Activity moves on
                await self._supernotify(
                    message, title, resend=True, extra_data={"notification_icon": self.icon} | self._tap_data()
                )
            else:
                await self._send_message(message, title)
        # which goes straight on to what the oven is now doing
        await self._temperature_shown(always=True)

    async def _cycle_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if new_state is None:
            return
        state: str = new_state.state
        _LOGGER.debug("APPLIANCES %s cycle state %s, running: %s", self.name, state, self.running)
        if state == STATE_RUN and not self.running:
            self.running = True
            # unless it's hot already, from not long having been off
            temperatures = self._temperatures()
            self.preheated = temperatures is not None and temperatures[0] >= temperatures[1]
            self.preheating = self._preheating() is not None
            self.shown_temperature = None
            # with no progress yet to open the Live Activity with, the first reading is sent whatever it is, and
            # an oven already warm starts part of the way along
            progress = self._progress()
            self.last_progress_mark = -1 if progress is None else self._mark(progress)
            await self._started()
        elif state in STATES_FINISHED and self.running:
            self.running = False
            await self._ended(finished=True)
        elif state in STATES_ABANDONED and self.running:
            self.running = False
            await self._ended(finished=False)
        # anything else, such as `unavailable` while the vendor cloud is away, leaves the cycle as it was


class PowerWatcher(ApplianceWatcher):
    """An appliance known only by the power it draws, running while that is above a threshold"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self.power_entity_id: str = entry.options[CONF_POWER_ENTITY]
        self.threshold: float = entry.options.get(CONF_THRESHOLD, DEFAULT_THRESHOLD)
        self.grace_period: float = entry.options.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD)
        self._cancel_end: CALLBACK_TYPE | None = None

    @callback
    def async_start(self) -> None:
        # a cycle under way at startup still has its Live Activity closed when it ends
        self.running = self._drawing(self.hass.states.get(self.power_entity_id)) is True
        self.entry.async_on_unload(async_track_state_change_event(self.hass, self.power_entity_id, self._power_changed))
        self.entry.async_on_unload(self._keep_running)

    def _drawing(self, state: State | None) -> bool | None:
        """Whether more power than the threshold is drawn, None if the power isn't known"""
        try:
            power = float(state.state) if state is not None else None
        except ValueError:
            power = None
        if state is None or power is None:
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit in PowerConverter.VALID_UNITS:
            power = PowerConverter.convert(power, unit, UnitOfPower.WATT)
        return power > self.threshold

    async def _power_changed(self, event: Event[EventStateChangedData]) -> None:
        drawing = self._drawing(event.data["new_state"])
        _LOGGER.debug("APPLIANCES %s drawing power %s, running: %s", self.name, drawing, self.running)
        if drawing is None:
            # `unavailable` while the power monitor is away leaves the cycle as it was
            return
        if drawing:
            self._keep_running()
            if not self.running:
                self.running = True
                await self._started()
        elif self.running and self._cancel_end is None:
            self._cancel_end = async_call_later(self.hass, self.grace_period, self._grace_over)

    @callback
    def _keep_running(self) -> None:
        if self._cancel_end is not None:
            self._cancel_end()
            self._cancel_end = None

    async def _grace_over(self, now: datetime) -> None:
        self._cancel_end = None
        self.running = False
        await self._ended(finished=True)
