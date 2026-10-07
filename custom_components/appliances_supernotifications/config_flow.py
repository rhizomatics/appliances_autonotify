"""Config flow for Appliances SuperNotifications, one config entry per appliance"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME, CONF_TYPE, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TargetSelector,
    TextSelector,
    TextSelectorConfig,
)

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
    DEFAULT_END_MESSAGE,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_START_MESSAGE,
    DEFAULT_THRESHOLD,
    DEFAULT_TITLE,
    DOMAIN,
    NAME_PLACEHOLDER,
    SUPERNOTIFY_MISSING,
    SUPERNOTIFY_PRESENT,
    TYPE_POWER,
)
from .discovery import Appliance, find_appliances
from .supernotify_api import deliveries_by_transport, supernotify_available

CONF_OPTIONS = "options"
STEP_POWER = "power"
STEP_FOUND = "found"

# shown in the form, so there's something to edit rather than an empty box
DEFAULT_TEXTS: dict[str, str] = {
    CONF_START_TITLE: DEFAULT_TITLE,
    CONF_START_MESSAGE: DEFAULT_START_MESSAGE,
    CONF_END_TITLE: DEFAULT_TITLE,
    CONF_END_MESSAGE: DEFAULT_END_MESSAGE,
}


def supernotify_status(hass: HomeAssistant) -> str:
    return SUPERNOTIFY_PRESENT if supernotify_available(hass) else SUPERNOTIFY_MISSING


async def settings_schema(hass: HomeAssistant) -> vol.Schema:
    fields: dict[vol.Marker, Any] = {
        vol.Optional(CONF_START_TITLE): TextSelector(),
        vol.Optional(CONF_START_MESSAGE): TextSelector(TextSelectorConfig(multiline=True)),
        vol.Optional(CONF_END_TITLE): TextSelector(),
        vol.Optional(CONF_END_MESSAGE): TextSelector(TextSelectorConfig(multiline=True)),
    }
    if supernotify_available(hass):
        # the same pair of target fields as supernotify.notify itself
        fields[vol.Optional(CONF_TARGET)] = TargetSelector()
        fields[vol.Optional(CONF_CUSTOM_TARGET)] = TextSelector(TextSelectorConfig(multiple=True))
        deliveries = sorted({name for names in (await deliveries_by_transport(hass)).values() for name in names})
        fields[vol.Optional(CONF_DELIVERIES)] = SelectSelector(SelectSelectorConfig(options=deliveries, multiple=True))
    else:
        fields[vol.Required(CONF_TARGETS)] = EntitySelector(EntitySelectorConfig(domain="notify", multiple=True))
    return vol.Schema(fields)


def power_schema(with_name: bool) -> vol.Schema:
    fields: dict[vol.Marker, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME)] = TextSelector()
    fields[vol.Required(CONF_POWER_ENTITY)] = EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power"))
    fields[vol.Required(CONF_THRESHOLD, default=DEFAULT_THRESHOLD)] = NumberSelector(
        NumberSelectorConfig(min=0, step="any", mode=NumberSelectorMode.BOX, unit_of_measurement=UnitOfPower.WATT)
    )
    fields[vol.Required(CONF_GRACE_PERIOD, default=DEFAULT_GRACE_PERIOD)] = NumberSelector(
        NumberSelectorConfig(min=0, max=3600, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement=UnitOfTime.SECONDS)
    )
    return vol.Schema(fields)


def settings_errors(hass: HomeAssistant, user_input: dict[str, Any]) -> dict[str, str]:
    if not supernotify_available(hass) and not user_input.get(CONF_TARGETS):
        return {CONF_TARGETS: "targets_required"}
    return {}


class AppliancesConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._device_id: str | None = None
        self._name: str = ""
        self._appliances: list[Appliance] = []
        # set only for a power monitored appliance
        self._power: dict[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AppliancesOptionsFlow:
        return AppliancesOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the type of entry to add"""
        types = [STEP_POWER]
        # appliances found are usually set up from their discovery, this does all those left in one go
        if self._unconfigured():
            types.append(STEP_FOUND)
        return self.async_show_menu(step_id="user", menu_options=types)

    def _unconfigured(self) -> list[Appliance]:
        configured = self._async_current_ids()
        return [a for a in find_appliances(self.hass) if a.device_id not in configured]

    async def async_step_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """An appliance not found by itself, with a power monitor to tell when it's running"""
        if user_input is not None:
            self._name = user_input[CONF_NAME]
            self._power = {k: v for k, v in user_input.items() if k != CONF_NAME}
            await self.async_set_unique_id(user_input[CONF_POWER_ENTITY])
            self._abort_if_unique_id_configured()
            return await self.async_step_settings()
        return self.async_show_form(step_id=STEP_POWER, data_schema=power_schema(with_name=True))

    async def async_step_found(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set up every appliance found with the same settings, each as its own entry to change or disable later"""
        self._appliances = self._unconfigured()
        if not self._appliances:
            return self.async_abort(reason="no_appliances")
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = settings_errors(self.hass, user_input)
            if not errors:
                first, *others = self._appliances
                for appliance in others:
                    self.hass.async_create_task(
                        self.hass.config_entries.flow.async_init(
                            DOMAIN,
                            context={"source": SOURCE_IMPORT},
                            data={CONF_DEVICE_ID: appliance.device_id, CONF_NAME: appliance.name, CONF_OPTIONS: user_input},
                        )
                    )
                # a discovery of the same appliance may be waiting, and goes once this entry exists
                await self.async_set_unique_id(first.device_id, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=first.name, data={CONF_DEVICE_ID: first.device_id}, options=user_input)
        return self.async_show_form(
            step_id=STEP_FOUND,
            data_schema=self.add_suggested_values_to_schema(
                await settings_schema(self.hass), DEFAULT_TEXTS | (user_input or {})
            ),
            errors=errors,
            description_placeholders={
                "name": ", ".join(a.name for a in self._appliances),
                "supernotify": supernotify_status(self.hass),
                "placeholder": NAME_PLACEHOLDER,
            },
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """One of the other appliances of a user flow, with the settings given there"""
        await self.async_set_unique_id(import_data[CONF_DEVICE_ID], raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=import_data[CONF_NAME],
            data={CONF_DEVICE_ID: import_data[CONF_DEVICE_ID]},
            options=import_data[CONF_OPTIONS],
        )

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        self._device_id = discovery_info[CONF_DEVICE_ID]
        self._name = discovery_info[CONF_NAME]
        await self.async_set_unique_id(self._device_id)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_settings()

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = settings_errors(self.hass, user_input)
            if not errors:
                if self._power is not None:
                    return self.async_create_entry(
                        title=self._name, data={CONF_TYPE: TYPE_POWER}, options=user_input | self._power
                    )
                return self.async_create_entry(title=self._name, data={CONF_DEVICE_ID: self._device_id}, options=user_input)
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                await settings_schema(self.hass), DEFAULT_TEXTS | (user_input or {})
            ),
            errors=errors,
            description_placeholders={
                "name": self._name,
                "supernotify": supernotify_status(self.hass),
                "placeholder": NAME_PLACEHOLDER,
            },
        )


class AppliancesOptionsFlow(OptionsFlowWithReload):
    def __init__(self) -> None:
        self._settings: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = settings_errors(self.hass, user_input)
            if not errors:
                if self.config_entry.data.get(CONF_TYPE) == TYPE_POWER:
                    self._settings = user_input
                    return await self.async_step_power()
                return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                await settings_schema(self.hass), DEFAULT_TEXTS | (user_input or self.config_entry.options)
            ),
            errors=errors,
            description_placeholders={
                "name": self.config_entry.title,
                "supernotify": supernotify_status(self.hass),
                "placeholder": NAME_PLACEHOLDER,
            },
        )

    async def async_step_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=self._settings | user_input)
        return self.async_show_form(
            step_id=STEP_POWER,
            data_schema=self.add_suggested_values_to_schema(power_schema(with_name=False), self.config_entry.options),
            description_placeholders={"name": self.config_entry.title},
        )
