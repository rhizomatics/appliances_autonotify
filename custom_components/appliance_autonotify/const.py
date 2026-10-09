"""Constants for Appliance Auto Notify"""

from typing import Final

DOMAIN: Final[str] = "appliance_autonotify"
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
# whether progress is told with ordinary notifications, the Live Activity is kept up to date regardless
CONF_NOTIFY_PROGRESS: Final[str] = "notify_progress"
# whether the start and the end are told with ordinary notifications, the Live Activity is opened and closed regardless
CONF_NOTIFY_START: Final[str] = "notify_start"
CONF_NOTIFY_END: Final[str] = "notify_end"
# whether the end of a phase, such as an oven getting up to heat, is told with an ordinary notification
CONF_NOTIFY_PHASE: Final[str] = "notify_phase"
# path of the dashboard opened by a tap on a notification, the app is opened where it was last if there's none
CONF_DASHBOARD: Final[str] = "dashboard"
LOVELACE_DOMAIN: Final[str] = "lovelace"
# the dashboard Home Assistant starts with has no path of its own in the list of them
DEFAULT_DASHBOARD: Final[str] = "lovelace"
DEFAULT_DASHBOARD_TITLE: Final[str] = "Overview"
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
PREHEAT_PHASE: Final[str] = "Pre-heating"
FAST_PREHEAT_PHASE: Final[str] = "Fast pre-heat"
PREHEAT_MESSAGE: Final[str] = "{phase}, {current} of {target}{unit}"
PREHEATED_MESSAGE: Final[str] = "{name} is pre-heated"
# what an oven up to heat is doing, and how hot it is
OVEN_MESSAGE: Final[str] = "{program}, {current}{unit}"
SUPERNOTIFY_PRESENT: Final[str] = "Supernotify is installed, so mobile apps will show a Live Activity for each cycle."
SUPERNOTIFY_MISSING: Final[str] = (
    "**Supernotify is not installed.** Only a plain start and end notification can be sent, to every phone with the "
    "Home Assistant app, with no Live Activity. Install Supernotify from HACS for the full experience."
)

# translation key, per vendor platform, of the entity whose state follows the appliance cycle
CYCLE_KEYS: Final[dict[str, str]] = {"home_connect": "operation_state"}
PROGRESS_KEY: Final[str] = "program_progress"
FINISH_TIME_KEY: Final[str] = "program_finish_time"
# selects, unlike the others, of the program under way, and of the one chosen, which is all an oven reports
PROGRAM_KEYS: Final[tuple[str, ...]] = ("active_program", "selected_program")
# an oven warming up has no progress of its own, only how hot it is and how hot it's to be
TARGET_TEMPERATURE_KEY: Final[str] = "setpoint_temperature"
CAVITY_TEMPERATURE_KEY: Final[str] = "oven_current_cavity_temperature"
PREHEAT_FINISHED_KEYS: Final[tuple[str, ...]] = ("preheat_finished", "regular_preheat_finished")
FAST_PREHEAT_KEY: Final[str] = "fast_pre_heat"
# domain, by translation key, of each entity of an appliance that's made use of
ENTITY_DOMAINS: Final[dict[str, str]] = {
    PROGRESS_KEY: "sensor",
    FINISH_TIME_KEY: "sensor",
    **dict.fromkeys(PROGRAM_KEYS, "select"),
    TARGET_TEMPERATURE_KEY: "number",
    CAVITY_TEMPERATURE_KEY: "sensor",
    **dict.fromkeys(PREHEAT_FINISHED_KEYS, "sensor"),
    FAST_PREHEAT_KEY: "switch",
}
# degrees between Live Activity updates of an oven up to heat, whose temperature never stops wandering
TEMPERATURE_STEP: Final[float] = 5
# an event sensor is `off` until whatever it tells of has happened
STATES_EVENT_ON: Final[tuple[str, ...]] = ("present", "confirmed", "on")

STATE_RUN: Final[str] = "run"
# a cycle already under way, so not a new start when `run` follows
STATES_ACTIVE: Final[tuple[str, ...]] = ("run", "pause", "actionrequired")
# the cycle is over, an oven switched off goes straight from `run` to `ready` or `inactive` without ever being `finished`
STATES_FINISHED: Final[tuple[str, ...]] = ("finished", "ready", "inactive")
# the cycle is over without finishing, so the Live Activity goes without an end notification
STATES_ABANDONED: Final[tuple[str, ...]] = ("error", "aborting")

# percentage points between Live Activity updates, since mobile platforms throttle frequent ones
PROGRESS_STEP: Final[int] = 10
# from here on the end is in sight and the bar is being watched, so it's kept closer to the appliance
PROGRESS_FINAL: Final[int] = 90
PROGRESS_FINAL_STEP: Final[int] = 2

MOBILE_PUSH_TRANSPORT: Final[str] = "mobile_push"
# platform of the notify entities used when there's no Supernotify and none have been chosen
MOBILE_APP_PLATFORM: Final[str] = "mobile_app"

DEFAULT_ICON: Final[str] = "mdi:progress-clock"
TYPE_OVEN: Final[str] = "oven"
# the type of a Home Connect appliance, by how its programs are named
APPLIANCE_TYPES: Final[dict[str, str]] = {
    "dishcare_dishwasher_program_": "dishwasher",
    "laundry_care_washer_program_": "washer",
    "laundry_care_washer_dryer_program_": "washer_dryer",
    "laundry_care_dryer_program_": "dryer",
    "cooking_oven_program_": TYPE_OVEN,
    "cooking_hob_program_": "hob",
    "cooking_common_program_hood_": "hood",
    "consumer_products_coffee_maker_program_": "coffee_maker",
    "consumer_products_cleaning_robot_program_": "cleaning_robot",
    "heating_ventilation_air_conditioning_air_conditioner_program_": "air_conditioner",
}
TYPE_ICONS: Final[dict[str, str]] = {
    "dishwasher": "mdi:dishwasher",
    "washer": "mdi:washing-machine",
    "washer_dryer": "mdi:washing-machine",
    "dryer": "mdi:tumble-dryer",
    TYPE_OVEN: "mdi:stove",
    "hob": "mdi:pot-steam",
    "hood": "mdi:fan",
    "coffee_maker": "mdi:coffee-maker",
    "cleaning_robot": "mdi:robot-vacuum",
    "air_conditioner": "mdi:air-conditioner",
}
# the types whose phases are worth a notification unless it's turned off, an oven up to heat being waited
# for where a dishwasher starting to rinse isn't
PHASES_NOTIFIED: Final[tuple[str, ...]] = (TYPE_OVEN,)
# matched against the device name where the type isn't known, first hit wins
ICONS: Final[dict[str, str]] = {
    "dishwasher": "mdi:dishwasher",
    "dryer": "mdi:tumble-dryer",
    "wash": "mdi:washing-machine",
    "oven": "mdi:stove",
    "microwave": "mdi:microwave",
    "coffee": "mdi:coffee-maker",
    "hood": "mdi:fan",
    "hob": "mdi:pot-steam",
    "vacuum": "mdi:robot-vacuum",
    "kettle": "mdi:kettle",
}
