"""Config flow for Appliances SuperNotifications, one config entry per appliance"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
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
    CONF_START_MESSAGE,
    CONF_START_TITLE,
    CONF_TARGET,
    CONF_TARGETS,
    DOMAIN,
    NAME_PLACEHOLDER,
    SUPERNOTIFY_MISSING,
    SUPERNOTIFY_PRESENT,
)
from .discovery import find_appliances
from .supernotify_api import deliveries_by_transport, supernotify_available


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


def settings_errors(hass: HomeAssistant, user_input: dict[str, Any]) -> dict[str, str]:
    if not supernotify_available(hass) and not user_input.get(CONF_TARGETS):
        return {CONF_TARGETS: "targets_required"}
    return {}


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
        configured = self._async_current_ids()
        appliances = {a.device_id: a.name for a in find_appliances(self.hass) if a.device_id not in configured}
        if not appliances:
            return self.async_abort(reason="no_appliances")
        if user_input is not None:
            self._device_id = user_input[CONF_DEVICE_ID]
            self._name = appliances[user_input[CONF_DEVICE_ID]]
            await self.async_set_unique_id(self._device_id)
            self._abort_if_unique_id_configured()
            return await self.async_step_settings()
        options = [SelectOptionDict(value=device_id, label=name) for device_id, name in appliances.items()]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): SelectSelector(SelectSelectorConfig(options=options))}),
            description_placeholders={"supernotify": supernotify_status(self.hass)},
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
                return self.async_create_entry(title=self._name, data={CONF_DEVICE_ID: self._device_id}, options=user_input)
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(await settings_schema(self.hass), user_input),
            errors=errors,
            description_placeholders={
                "name": self._name,
                "supernotify": supernotify_status(self.hass),
                "placeholder": NAME_PLACEHOLDER,
            },
        )


class AppliancesOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = settings_errors(self.hass, user_input)
            if not errors:
                return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                await settings_schema(self.hass), user_input or self.config_entry.options
            ),
            errors=errors,
            description_placeholders={
                "name": self.config_entry.title,
                "supernotify": supernotify_status(self.hass),
                "placeholder": NAME_PLACEHOLDER,
            },
        )
