"""Config flow for Appliance Auto Notifier, one config entry per appliance"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME, CONF_TYPE, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
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
    CONF_AUTO_DISCOVER,
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
    DISCOVERY_TITLE,
    DOMAIN,
    NAME_PLACEHOLDER,
    SUPERNOTIFY_MISSING,
    SUPERNOTIFY_PRESENT,
    TYPE_DISCOVERY,
    TYPE_POWER,
)
from .discovery import find_appliances
from .supernotify_api import deliveries_by_transport, supernotify_available

STEP_POWER = "power"
STEP_DISCOVERY = "discovery"
STEP_SETTINGS = "settings"
SECTION_START = "start"
SECTION_END = "end"
SECTION_NOTIFY = "notify"

DEFAULT_TEXTS: dict[str, str] = {
    CONF_START_TITLE: DEFAULT_TITLE,
    CONF_START_MESSAGE: DEFAULT_START_MESSAGE,
    CONF_END_TITLE: DEFAULT_TITLE,
    CONF_END_MESSAGE: DEFAULT_END_MESSAGE,
}


def supernotify_status(hass: HomeAssistant) -> str:
    return SUPERNOTIFY_PRESENT if supernotify_available(hass) else SUPERNOTIFY_MISSING


def discovery_schema(auto_discover: bool = True) -> vol.Schema:
    return vol.Schema({vol.Required(CONF_AUTO_DISCOVER, default=auto_discover): BooleanSelector()})


async def settings_schema(hass: HomeAssistant) -> vol.Schema:
    notify: dict[vol.Marker, Any] = {}
    if supernotify_available(hass):
        # the same pair of target fields as supernotify.notify itself
        notify[vol.Optional(CONF_TARGET)] = TargetSelector()
        notify[vol.Optional(CONF_CUSTOM_TARGET)] = TextSelector(TextSelectorConfig(multiple=True))
        deliveries = sorted({name for names in (await deliveries_by_transport(hass)).values() for name in names})
        notify[vol.Optional(CONF_DELIVERIES)] = SelectSelector(SelectSelectorConfig(options=deliveries, multiple=True))
    else:
        notify[vol.Optional(CONF_TARGETS)] = EntitySelector(EntitySelectorConfig(domain="notify", multiple=True))
    sections: dict[str, dict[vol.Marker, Any]] = {
        SECTION_START: {
            vol.Optional(CONF_START_TITLE): TextSelector(),
            vol.Optional(CONF_START_MESSAGE): TextSelector(TextSelectorConfig(multiline=True)),
        },
        SECTION_END: {
            vol.Optional(CONF_END_TITLE): TextSelector(),
            vol.Optional(CONF_END_MESSAGE): TextSelector(TextSelectorConfig(multiline=True)),
        },
        SECTION_NOTIFY: notify,
    }
    # all tuning, so out of the way until it's wanted
    return vol.Schema({
        vol.Required(name): section(vol.Schema(fields), {"collapsed": True}) for name, fields in sections.items()
    })


def sectioned(schema: vol.Schema, values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Settings are stored flat, the sections are only for display"""
    return {
        str(name): {str(key): values[key] for key in fields.schema.schema if key in values}
        for name, fields in schema.schema.items()
    }


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


class AppliancesConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._device_id: str | None = None
        self._name: str = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AppliancesOptionsFlow:
        return AppliancesOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Automatic discovery the first time, and from then on an appliance to describe by hand"""
        if any(entry.data.get(CONF_TYPE) == TYPE_DISCOVERY for entry in self._async_current_entries()):
            return await self.async_step_power()
        if user_input is not None:
            await self.async_set_unique_id(TYPE_DISCOVERY)
            self._abort_if_unique_id_configured()
            # the appliances themselves are set up as this entry is, each as its own entry to change or disable
            return self.async_create_entry(title=DISCOVERY_TITLE, data={CONF_TYPE: TYPE_DISCOVERY}, options=user_input)
        configured = self._async_current_ids()
        found = [a.name for a in find_appliances(self.hass) if a.device_id not in configured]
        return self.async_show_form(
            step_id="user",
            data_schema=discovery_schema(),
            description_placeholders={"found": ", ".join(found) or "none yet", "supernotify": supernotify_status(self.hass)},
        )

    async def async_step_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """An appliance not found by itself, with a power monitor to tell when it's running"""
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_POWER_ENTITY])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={CONF_TYPE: TYPE_POWER},
                options={k: v for k, v in user_input.items() if k != CONF_NAME},
            )
        return self.async_show_form(step_id=STEP_POWER, data_schema=power_schema(with_name=True))

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """An appliance found with automatic discovery on, so set up without asking"""
        # a discovery of the same appliance may be waiting, and goes once this entry exists
        await self.async_set_unique_id(import_data[CONF_DEVICE_ID], raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=import_data[CONF_NAME], data={CONF_DEVICE_ID: import_data[CONF_DEVICE_ID]})

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        """An appliance found with automatic discovery off, so offered to be added"""
        self._device_id = discovery_info[CONF_DEVICE_ID]
        self._name = discovery_info[CONF_NAME]
        await self.async_set_unique_id(self._device_id)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=self._name, data={CONF_DEVICE_ID: self._device_id})
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._name, "supernotify": supernotify_status(self.hass)},
        )


class AppliancesOptionsFlow(OptionsFlowWithReload):
    def __init__(self) -> None:
        self._settings: dict[str, Any] = {}

    def _name(self) -> str:
        # the name notifications are sent with, which follows the device rather than the entry's title
        watcher = getattr(self.config_entry, "runtime_data", None)
        return watcher.name if watcher is not None else self.config_entry.title

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            return await self.async_step_discovery()
        return await self.async_step_settings()

    async def async_step_discovery(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id=STEP_DISCOVERY,
            data_schema=discovery_schema(self.config_entry.options.get(CONF_AUTO_DISCOVER, True)),
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        name = self._name()
        # as they'll be sent, so there's the real text to edit rather than a template or an empty box
        defaults = {key: text.replace(NAME_PLACEHOLDER, name) for key, text in DEFAULT_TEXTS.items()}
        if user_input is not None:
            # text left as the default isn't a setting, so it goes on following the name of the appliance
            settings = {
                key: value
                for fields in user_input.values()
                for key, value in fields.items()
                if value and value != defaults.get(key)
            }
            if self.config_entry.data.get(CONF_TYPE) == TYPE_POWER:
                self._settings = settings
                return await self.async_step_power()
            return self.async_create_entry(data=settings)
        schema = await settings_schema(self.hass)
        shown = dict(self.config_entry.options)
        for key, text in defaults.items():
            shown[key] = str(shown.get(key) or text).replace(NAME_PLACEHOLDER, name)
        return self.async_show_form(
            step_id=STEP_SETTINGS,
            data_schema=self.add_suggested_values_to_schema(schema, sectioned(schema, shown)),
            description_placeholders={"name": name, "supernotify": supernotify_status(self.hass)},
        )

    async def async_step_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=self._settings | user_input)
        return self.async_show_form(
            step_id=STEP_POWER,
            data_schema=self.add_suggested_values_to_schema(power_schema(with_name=False), self.config_entry.options),
            description_placeholders={"name": self.config_entry.title},
        )
