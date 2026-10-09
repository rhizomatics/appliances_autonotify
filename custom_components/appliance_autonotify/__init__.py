"""Appliance Auto Notify - automatic notifications for household appliance cycles"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_TYPE
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, TYPE_DISCOVERY, TYPE_POWER
from .discovery import async_discover, async_start_discovery
from .watcher import ApplianceWatcher, HomeConnectWatcher, PowerWatcher

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type AppliancesConfigEntry = ConfigEntry[ApplianceWatcher]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_start_discovery(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AppliancesConfigEntry) -> bool:
    if entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
        # nothing to watch, only to look again now that automatic discovery may have been switched
        async_discover(hass)
        return True
    watcher_class = PowerWatcher if entry.data.get(CONF_TYPE) == TYPE_POWER else HomeConnectWatcher
    watcher: ApplianceWatcher = watcher_class(hass, entry)
    watcher.async_start()
    entry.runtime_data = watcher
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AppliancesConfigEntry) -> bool:
    # the watcher's listeners are removed by the entry's own unload callbacks
    return True
