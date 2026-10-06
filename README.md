# Appliances SuperNotifications

Automatic notifications for household appliances in Home Assistant, with no automations or YAML.

When a dishwasher, washing machine, oven or other appliance starts a cycle, you're told it started, your phone
shows a [Live Activity](https://companion.home-assistant.io/docs/notifications/live-activities) with progress
and time remaining while it runs, and you're told when it finishes.

This is an early version to try with real appliances. It supports Bosch, Neff and Siemens appliances connected
with the Home Assistant [Home Connect](https://www.home-assistant.io/integrations/home_connect/) integration,
in English only.

## What You Need

- Home Assistant 2026.7 or later
- An appliance set up with the Home Connect integration
- [Supernotify](https://supernotify.rhizomatics.org.uk), installed from HACS, for Live Activities and for anything
  beyond a plain notification

Without Supernotify, it only sends a start and an end notification, to notify entities you choose.

## Install

1. In HACS, add `https://github.com/rhizomatics/appliances_supernotifications` as a custom repository of type
   *Integration*, install *Appliances SuperNotifications* and restart Home Assistant
2. In *Settings*, *Devices & services*, choose *Add integration* and pick *Appliances SuperNotifications*
3. Choose an appliance from the list of those found, and optionally change its settings

Once the first appliance is set up, any others are offered automatically as *Discovered* on the
*Devices & services* page, including appliances you add later. Choose *Ignore* on any you don't want.

## Settings

Each appliance is listed on the integration's page, where it can be changed, disabled or deleted.

| Setting                    | What it does                                                                                 |
| -------------------------- | -------------------------------------------------------------------------------------------- |
| Start title and message    | Replace the default "Dishwasher started". `{name}` becomes the name of the appliance         |
| End title and message      | Replace the default "Dishwasher is finished"                                                 |
| Targets                    | With Supernotify, the same choice of entities, devices, areas, floors and labels as any Supernotify notification, and optional. Without, notify entities only, and at least one is needed |
| Custom targets             | Only with Supernotify: targets outside Home Assistant, such as e-mail addresses or phone numbers |
| Deliveries                 | Only with Supernotify: limit notifications to these deliveries. Leave empty for Supernotify to choose |

## What Gets Sent

| When                                   | With Supernotify                                                    | Without             |
| -------------------------------------- | ------------------------------------------------------------------- | ------------------- |
| Cycle starts                           | Start notification everywhere, opening a Live Activity on phones     | Start notification  |
| Every 10% of progress                  | Silent update of the Live Activity, on phones only                  | Nothing             |
| Cycle finishes                         | Live Activity closed, then an end notification everywhere           | End notification    |
| Cycle stops early, or fails            | Live Activity closed, with no end notification                      | Nothing             |

Pausing and resuming an appliance counts as the same cycle.

## Known Limits

- If the appliance never reports the end of its cycle, the Live Activity stays on the phone until dismissed
- If Home Assistant restarts mid-cycle, the end is still notified and the Live Activity closed
- Progress and time remaining are only shown where the appliance reports them

## Development

```shell
uv sync
uv run pytest
uv run ruff check --fix && uv run ruff format
uv run mypy custom_components/appliances_supernotifications
```
