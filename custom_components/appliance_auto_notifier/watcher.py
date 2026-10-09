"""Watch one appliance, and notify as its cycle starts, progresses and ends"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_ENTITY_ID, ATTR_UNIT_OF_MEASUREMENT, CONF_DEVICE_ID, UnitOfPower
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import PowerConverter

from .const import (
    CONF_CUSTOM_TARGET,
    CONF_DELIVERIES,
    CONF_END_MESSAGE,
    CONF_END_TITLE,
    CONF_GRACE_PERIOD,
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
    FINISH_TIME_KEY,
    ICONS,
    MOBILE_PUSH_TRANSPORT,
    NAME_PLACEHOLDER,
    PROGRESS_KEY,
    PROGRESS_MESSAGE,
    PROGRESS_STEP,
    STATE_RUN,
    STATES_ABANDONED,
    STATES_ACTIVE,
    STATES_FINISHED,
    SUPERNOTIFY_DOMAIN,
)
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
        self.icon: str = next((icon for word, icon in ICONS.items() if word in self.name.lower()), DEFAULT_ICON)
        self.cycle_entity_id: str | None = None
        self.progress_entity_id: str | None = None
        self.finish_time_entity_id: str | None = None
        self.running: bool = False
        self.last_progress_step: int = 0
        # one notification at a time, so a progress update can't overtake the end and reopen the Live Activity
        self._sending: asyncio.Lock = asyncio.Lock()

    @callback
    def async_start(self) -> None:
        raise NotImplementedError

    async def _progress_changed(self, event: Event[EventStateChangedData]) -> None:
        progress = self._progress()
        if not self.running or progress is None or not supernotify_available(self.hass):
            return
        step = progress // PROGRESS_STEP
        if step <= self.last_progress_step:
            return
        self.last_progress_step = step
        async with self._sending:
            if not self.running:
                # the cycle ended while this waited its turn
                return
            # a Live Activity keeps the title it started with
            await self._supernotify(
                PROGRESS_MESSAGE.format(progress=progress),
                self._text(CONF_START_TITLE, DEFAULT_TITLE),
                mobile_only=True,
                extra_data=self._live_data() | {"silent": True, "alert_once": True},
            )

    async def _started(self) -> None:
        title = self._text(CONF_START_TITLE, DEFAULT_TITLE)
        message = self._text(CONF_START_MESSAGE, DEFAULT_START_MESSAGE)
        async with self._sending:
            if supernotify_available(self.hass):
                await self._supernotify(message, title, extra_data=self._live_data())
            else:
                await self._send_message(message, title)

    async def _ended(self, finished: bool) -> None:
        title = self._text(CONF_END_TITLE, DEFAULT_TITLE)
        message = self._text(CONF_END_MESSAGE, DEFAULT_END_MESSAGE)
        async with self._sending:
            if not supernotify_available(self.hass):
                if finished:
                    await self._send_message(message, title)
                return
            # closing the Live Activity is not a notification in itself, so the end is told separately
            await self._supernotify(
                message,
                title,
                mobile_only=True,
                extra_data={"mobile_push_notification_tag": self.tag, "mobile_push_clear_notification": True},
            )
            if finished:
                await self._supernotify(message, title)

    def _text(self, key: str, default: str) -> str:
        return str(self.entry.options.get(key) or default).replace(NAME_PLACEHOLDER, self.name)

    def _progress(self) -> int | None:
        state = self.hass.states.get(self.progress_entity_id) if self.progress_entity_id else None
        try:
            return int(float(state.state)) if state is not None else None
        except ValueError:
            return None

    def _live_data(self) -> dict[str, Any]:
        """Live Activity fields for the mobile app, leaving out whatever the appliance isn't reporting"""
        data: dict[str, Any] = {
            "mobile_push_notification_tag": self.tag,
            "live_update": True,
            "notification_icon": self.icon,
        }
        progress = self._progress()
        if progress is not None:
            data["progress"] = progress
            data["progress_max"] = 100
        state = self.hass.states.get(self.finish_time_entity_id) if self.finish_time_entity_id else None
        finish_time = dt_util.parse_datetime(state.state) if state is not None else None
        if finish_time is not None:
            data["chronometer"] = True
            data["when"] = int(finish_time.timestamp())
        return data

    async def _supernotify(
        self, message: str, title: str, mobile_only: bool = False, extra_data: dict[str, Any] | None = None
    ) -> None:
        data: dict[str, Any] = {"message": message, "title": title}
        deliveries: list[str] = list(self.entry.options.get(CONF_DELIVERIES) or [])
        try:
            if mobile_only:
                mobile = (await deliveries_by_transport(self.hass)).get(MOBILE_PUSH_TRANSPORT, [])
                deliveries = [d for d in mobile if not deliveries or d in deliveries]
                if not deliveries:
                    _LOGGER.warning("APPLIANCES No mobile push delivery found for %s, Live Activity not updated", self.name)
                    return
                data["delivery_selection"] = "fixed"
                # Supernotify's duplicate check ignores digits, so would drop progress updates as repeats
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
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {ATTR_ENTITY_ID: self.entry.options.get(CONF_TARGETS), "message": message, "title": title},
                blocking=True,
            )
        except HomeAssistantError:
            _LOGGER.exception("APPLIANCES Notification failed for %s", self.name)


class HomeConnectWatcher(ApplianceWatcher):
    """An appliance whose integration reports the state of its cycle"""

    @callback
    def async_start(self) -> None:
        device_id: str = self.entry.data[CONF_DEVICE_ID]
        device = dr.async_get(self.hass).async_get(device_id)
        if device is not None:
            self.name = device.name_by_user or device.name or self.name
        for entity in er.async_entries_for_device(er.async_get(self.hass), device_id):
            if entity.platform not in CYCLE_KEYS:
                continue
            if entity.translation_key == CYCLE_KEYS[entity.platform]:
                self.cycle_entity_id = entity.entity_id
            elif entity.translation_key == PROGRESS_KEY:
                self.progress_entity_id = entity.entity_id
            elif entity.translation_key == FINISH_TIME_KEY:
                self.finish_time_entity_id = entity.entity_id
        if self.cycle_entity_id is None:
            raise ConfigEntryNotReady(f"No cycle state entity found for {self.name}")

        # a cycle under way at startup still has its Live Activity closed when it ends
        state = self.hass.states.get(self.cycle_entity_id)
        self.running = state is not None and state.state in STATES_ACTIVE

        self.entry.async_on_unload(async_track_state_change_event(self.hass, self.cycle_entity_id, self._cycle_changed))
        if self.progress_entity_id is not None:
            self.entry.async_on_unload(
                async_track_state_change_event(self.hass, self.progress_entity_id, self._progress_changed)
            )

    async def _cycle_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if new_state is None:
            return
        state: str = new_state.state
        _LOGGER.debug("APPLIANCES %s cycle state %s, running: %s", self.name, state, self.running)
        if state == STATE_RUN and not self.running:
            self.running = True
            # with no progress yet to open the Live Activity with, the first reading is sent whatever it is
            self.last_progress_step = -1 if self._progress() is None else 0
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
