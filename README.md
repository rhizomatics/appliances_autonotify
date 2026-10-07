# Appliance Auto Notifier

Automatic notifications for household appliances in Home Assistant, with no automations or YAML.

When a dishwasher, washing machine, oven or other appliance starts a cycle, you're told it started, your phone
shows a [Live Activity](https://companion.home-assistant.io/docs/notifications/live-activities) with progress
and time remaining while it runs, and you're told when it finishes.

This is an early version to try with real appliances. It supports Bosch, Neff and Siemens appliances connected
with the Home Assistant [Home Connect](https://www.home-assistant.io/integrations/home_connect/) integration,
in English only. Any other appliance can be added by hand if it has a power monitor, such as a smart plug.

## What You Need

- Home Assistant 2026.7 or later
- An appliance set up with the Home Connect integration, or one with a power sensor
- [Supernotify](https://supernotify.rhizomatics.org.uk), installed from HACS, for Live Activities and for anything
  beyond a plain notification
- Home Assistant app installed on an Apple mobile device, minimum iOS/iPadOS 17.2

Without Supernotify, it only sends a start and an end notification, to notify entities you choose.

## Install

1. In HACS, add `https://github.com/rhizomatics/appliances_supernotifications` as a custom repository of type
   *Integration*, install *Appliance Auto Notifier* and restart Home Assistant

Home Connect appliances are offered automatically as *Discovered* on the *Devices & services* page, including
appliances you add later. Choose *Add* to set one up, or *Ignore* on any you don't want.

### Power Monitored Appliances

An appliance with no supported integration can be added if a sensor measures the power it draws.

1. In *Settings*, *Devices & services*, choose *Add integration* and pick *Appliance Auto Notifier*
2. Choose *Power Monitored Appliance*
3. Give the appliance a name, and choose its power sensor
4. Optionally change the notification settings

| Setting         | Default    | What it does                                                                              |
| --------------- | ---------- | ----------------------------------------------------------------------------------------- |
| Power threshold | 1 W        | The appliance is running while it draws more than this                                    |
| Grace period    | 60 seconds | How long power must stay at or below the threshold before the cycle is over, so short drop outs are ignored |

Raise the grace period for appliances that pause mid-cycle, such as a washing machine soaking.

When appliances have been found and not yet set up, *Appliances found* is also offered, to set them all up
at once with the same settings.

## Settings

Each appliance is listed on the integration's page, where it can be changed, disabled or deleted.

| Setting                    | What it does                                                                                 |
| -------------------------- | -------------------------------------------------------------------------------------------- |
| Start title and message    | Shown with the default, "Dishwasher started", to change. `{name}` becomes the name of the appliance |
| End title and message      | Shown with the default, "Dishwasher is finished", to change                                  |
| Targets                    | With Supernotify, the same choice of entities, devices, areas, floors and labels as any Supernotify notification, and optional. Without, notify entities only, and at least one is needed |
| Custom targets             | Only with Supernotify: targets outside Home Assistant, such as e-mail addresses or phone numbers |
| Deliveries                 | Only with Supernotify: limit notifications to these deliveries. Leave empty for Supernotify to choose |

## What Gets Sent

| When                                   | With Supernotify                                                    | Without             |
| -------------------------------------- | ------------------------------------------------------------------- | ------------------- |
| Cycle starts                           | Start notification everywhere, opening a Live Activity on phones     | Start notification  |
| Every 10% of progress                  | Silent update of the Live Activity, on phones only                  | Nothing             |
| Cycle finishes                         | Live Activity closed, then an end notification everywhere           | End notification    |
| Cycle is aborted, or fails             | Live Activity closed, with no end notification                      | Nothing             |

Pausing and resuming an appliance counts as the same cycle. An appliance that is switched off, like an oven,
counts as finished.

## Known Limits

- If the appliance never reports the end of its cycle, the Live Activity stays on the phone until dismissed
- If Home Assistant restarts mid-cycle, the end is still notified and the Live Activity closed
- Progress and time remaining are only shown where the appliance reports them, so never for a power monitored appliance

## Development

```shell
uv sync
uv run pytest
uv run ruff check --fix && uv run ruff format
uv run mypy custom_components/appliance_auto_notifier
```
