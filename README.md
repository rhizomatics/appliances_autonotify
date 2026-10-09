# Appliance Auto Notifier

Automatic notifications for household appliances in Home Assistant, with no automations or YAML.

![Example Dishwasher Progress](docs/assets/images/dishwasher_progress.png)

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

Without Supernotify, it only sends a start and an end notification, to every phone with the Home Assistant app
unless you choose other notify entities.

## Install

1. In HACS, add `https://github.com/rhizomatics/appliances_supernotifications` as a custom repository of type
   *Integration*, install *Appliance Auto Notifier* and restart Home Assistant
2. In *Settings*, *Devices & services*, choose *Add integration* and pick *Appliance Auto Notifier*
3. Leave *Set up appliances automatically* on, and submit

That's all. Every Home Connect appliance is set up straight away, and so is any you add later. Each is listed on
the integration's page, alongside *Automatic discovery*, and notifies with no further settings.

To stop the notifications for an appliance, disable it rather than delete it, since a deleted appliance is found
and set up again.

### Choosing Appliances Yourself

Turn *Set up appliances automatically* off, on the first screen or later from the settings of *Automatic discovery*,
and appliances are instead offered as *Discovered* on the *Devices & services* page. Choose *Add* to set one up,
or *Ignore* on any you don't want.

### Power Monitored Appliances

An appliance with no supported integration can be added if a sensor measures the power it draws.

1. On the integration's page, choose *Add service*
2. Give the appliance a name, and choose its power sensor

| Setting         | Default    | What it does                                                                              |
| --------------- | ---------- | ----------------------------------------------------------------------------------------- |
| Power threshold | 1 W        | The appliance is running while it draws more than this                                    |
| Grace period    | 60 seconds | How long power must stay at or below the threshold before the cycle is over, so short drop outs are ignored |

Raise the grace period for appliances that pause mid-cycle, such as a washing machine soaking.

## Settings

Nothing needs changing for notifications to work. Each appliance on the integration's page has settings: a
*Notify progress* switch, off by default, and then three sections that start closed.

| Section              | What it does                                                                                 |
| -------------------- | -------------------------------------------------------------------------------------------- |
| Start message        | The title and message sent when the appliance starts, shown as they'll be sent, such as "Dishwasher started". Clear a box to go back to the usual wording |
| End message          | The same for when it finishes, such as "Dishwasher is finished"                              |
| Notification targets | With Supernotify, *Targets* is the same choice of entities, devices, areas, floors and labels as any Supernotify notification, *Custom targets* is for those outside Home Assistant, such as e-mail addresses or phone numbers, and *Deliveries* limits notifications to those chosen. Leave them empty for Supernotify to choose. Without Supernotify, *Targets* is a choice of notify entities, and left empty means every phone with the Home Assistant app |

## What Gets Sent

| When                                   | With Supernotify                                                    | Without             |
| -------------------------------------- | ------------------------------------------------------------------- | ------------------- |
| Cycle starts                           | Start notification everywhere, opening a Live Activity on phones     | Start notification  |
| Every 10% of progress                  | Silent update of the Live Activity, on phones only. With *Notify progress* on, a notification everywhere instead, which updates the Live Activity too | Nothing, or with *Notify progress* on, a notification |
| Cycle finishes                         | Live Activity closed, then an end notification everywhere           | End notification    |
| Cycle is aborted, or fails             | Live Activity closed, with no end notification                      | Nothing             |

Pausing and resuming an appliance counts as the same cycle. An appliance that is switched off, like an oven,
counts as finished.

## Known Limits

- If the appliance never reports the end of its cycle, the Live Activity stays on the phone until dismissed
- If Home Assistant restarts mid-cycle, the end is still notified and the Live Activity closed
- Progress and time remaining are only shown where the appliance reports them, so never for a power monitored appliance

## Known Issues

Both of these have been seen on an iPhone, and neither has a confirmed cause yet.

### Progress bar behind the appliance

The progress bar of the Live Activity can fall well behind, such as showing 40% while the appliance is at 74%.

The likely cause is iOS. Progress is sent with `silent: true`, so that the phone doesn't alert every 10%, and the
[Companion App](https://companion.home-assistant.io/docs/notifications/live-activities) sends silent updates at a
lower priority, which iOS may delay, batch or drop. This is a theory, since it hasn't been tested by sending the
updates without `silent`.

Turning on *Notify progress* sends each update as an ordinary notification, without `silent`, so is worth
trying if the bar matters more than the interruptions.

### Seconds shown as dashes

The time remaining sometimes has dashes in place of the seconds, such as `52:--` or `1:30:--`, on the Lock Screen
while the Dynamic Island shows a full countdown at the same moment.

The same finish time is sent however it ends up shown, and the Companion App has no setting for the format of the
timer, so this is down to the phone. The likely reason is that the Lock Screen is redrawn less often while it's
dimmed or always-on, so drops the seconds. This is also a theory, and nothing has been found that changes it.

## Development

```shell
uv sync
uv run pytest
uv run ruff check --fix && uv run ruff format
uv run mypy custom_components/appliance_auto_notifier
```
