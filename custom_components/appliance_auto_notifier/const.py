"""Constants for Appliance Auto Notifier"""

from typing import Final

DOMAIN: Final[str] = "appliance_auto_notifier"
SUPERNOTIFY_DOMAIN: Final[str] = "supernotify"

CONF_START_TITLE: Final[str] = "start_title"
CONF_START_MESSAGE: Final[str] = "start_message"
CONF_END_TITLE: Final[str] = "end_title"
CONF_END_MESSAGE: Final[str] = "end_message"
# notify entities, used only without Supernotify
CONF_TARGETS: Final[str] = "targets"
# as the `target` and `custom_target` of supernotify.notify
CONF_TARGET: Final[str] = "target"
CONF_CUSTOM_TARGET: Final[str] = "custom_target"
CONF_DELIVERIES: Final[str] = "deliveries"
# the one entry that isn't an appliance, holding whether appliances found are set up without asking
TYPE_DISCOVERY: Final[str] = "discovery"
CONF_AUTO_DISCOVER: Final[str] = "auto_discover"
# an appliance with no integration of its own, known only by the power it draws
TYPE_POWER: Final[str] = "power"
CONF_POWER_ENTITY: Final[str] = "power_entity"
CONF_THRESHOLD: Final[str] = "threshold"
CONF_GRACE_PERIOD: Final[str] = "grace_period"
# watts above which the appliance is running
DEFAULT_THRESHOLD: Final[float] = 1
# seconds at or below the threshold before the cycle is over, so short drop outs are ignored
DEFAULT_GRACE_PERIOD: Final[float] = 60

# English only for the MVP
DISCOVERY_TITLE: Final[str] = "Automatic discovery"
NAME_PLACEHOLDER: Final[str] = "{name}"
DEFAULT_TITLE: Final[str] = "{name}"
DEFAULT_START_MESSAGE: Final[str] = "{name} started"
DEFAULT_END_MESSAGE: Final[str] = "{name} is finished"
PROGRESS_MESSAGE: Final[str] = "{progress}% complete"
SUPERNOTIFY_PRESENT: Final[str] = "Supernotify is installed, so mobile apps will show a Live Activity for each cycle."
SUPERNOTIFY_MISSING: Final[str] = (
    "**Supernotify is not installed.** Only a plain start and end notification can be sent, to every phone with the "
    "Home Assistant app, with no Live Activity. Install Supernotify from HACS for the full experience."
)

# translation key, per vendor platform, of the entity whose state follows the appliance cycle
CYCLE_KEYS: Final[dict[str, str]] = {"home_connect": "operation_state"}
PROGRESS_KEY: Final[str] = "program_progress"
FINISH_TIME_KEY: Final[str] = "program_finish_time"

STATE_RUN: Final[str] = "run"
# a cycle already under way, so not a new start when `run` follows
STATES_ACTIVE: Final[tuple[str, ...]] = ("run", "pause", "actionrequired")
# the cycle is over, an oven switched off goes straight from `run` to `ready` or `inactive` without ever being `finished`
STATES_FINISHED: Final[tuple[str, ...]] = ("finished", "ready", "inactive")
# the cycle is over without finishing, so the Live Activity goes without an end notification
STATES_ABANDONED: Final[tuple[str, ...]] = ("error", "aborting")

# percentage points between Live Activity updates, since mobile platforms throttle frequent ones
PROGRESS_STEP: Final[int] = 10

MOBILE_PUSH_TRANSPORT: Final[str] = "mobile_push"
# platform of the notify entities used when there's no Supernotify and none have been chosen
MOBILE_APP_PLATFORM: Final[str] = "mobile_app"

DEFAULT_ICON: Final[str] = "mdi:progress-clock"
# matched against the device name, first hit wins
ICONS: Final[dict[str, str]] = {
    "dishwasher": "mdi:dishwasher",
    "dryer": "mdi:tumble-dryer",
    "wash": "mdi:washing-machine",
    "oven": "mdi:stove",
    "microwave": "mdi:microwave",
    "coffee": "mdi:coffee-maker",
    "hood": "mdi:fan",
}
