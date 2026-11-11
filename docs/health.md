---
description: Notifications when a Frigate server stops responding or a camera stops sending video, with retries before anything is said, and how to keep cameras switched off on purpose quiet.
---
# Health Check

Camera AutoNotify also notifies when a Frigate server stops responding, and when a camera stops sending Frigate video. Neither adds anything to Frigate's load: both are read from what the Frigate integration already asks Frigate for every few seconds, its stats, and only where those aren't there to read is Frigate asked for its version, as its own container health check does.

- **Frigate Server**: *Frigate is not responding* once the Frigate integration can't get its stats, or can't connect to it at all
- **Camera**: *Courtyard camera is offline* once Frigate has had no frames from the camera. A camera disabled in Frigate is taken as meant to be, and not notified. See [Cameras Switched Off on Purpose](#cameras-switched-off-on-purpose)

Once it's back, *Frigate is back* or *Courtyard camera is back* takes the place of that notification, saying how long it was gone.

## Retries

When a check fails it's tried again, after 10 seconds, then 20, then 40, each retry waiting twice as long as the one before, and only once every retry has failed is it notified, so a restart passes without a word.

## While Frigate Is Down

A server's cameras aren't checked while the server itself isn't answering, since there's nothing in its stats to tell from, so a Frigate outage is one notification, not one for every camera.

- A camera that was fine before the outage says nothing when Frigate comes back, unless it then has no video through every retry
- A camera already offline before the outage stays offline, and says it's back once Frigate has video from it again,
  the time it was gone including the outage
- A camera partway through its retries when Frigate stopped answering starts them over once Frigate is back

## Settings

Both checks are on to begin with. The server check and the timing of both are in the *Frigate health check* section
of *Global Settings*:

| Setting                | Default    | What it does                                                                  |
| ---------------------- | ---------- | ----------------------------------------------------------------------------- |
| Check Frigate's health | On         | Switch off for no notifications about the Frigate server                      |
| Check every            | 60 seconds | How often each Frigate server, and each camera, is checked                    |
| Retries                | 3          | How many more times a failed check is tried before it's notified. 0 notifies the first failure |
| First retry after      | 10 seconds | How long before the first retry, doubling for each after it                   |

Each camera has its own, in its settings:

| Setting             | Default   | What it does                                                                     |
| ------------------- | --------- | -------------------------------------------------------------------------------- |
| Notify when offline | On        | Notify when Frigate has no video from the camera, and again when it's back       |
| Powered by          | None      | What powers the camera, such as its PoE port or smart plug, or a schedule of when it's meant to be on. It isn't notified as offline while that's off |
| Time to start up    | 3 minutes | How long after *Powered by* comes on before the camera is checked, for it to start up |

Switching off *Check Frigate's health* leaves the cameras' own checks on, and they still keep quiet while their
server isn't answering.

## Who Is Told

These notifications go at `high` priority, and `low` for the recovery. A server's go to whoever Supernotify chooses, or without Supernotify, every phone with the Home Assistant app, and a camera's to the same targets and deliveries as
its other notifications. Rules apply to them as to any other, so they can change their priority or silence them, matching text such as *failed its health check*, *no video* or *again*. See [Rules](genai.md#rules).

## Cameras Switched Off on Purpose

A camera that's turned off on purpose, such as by an automation that switches off its PoE port during the day, or a smart plug on a timer, would otherwise be notified as offline every time. Either of these keeps it quiet, while still
telling you if it goes offline when it's meant to be on:

- **Powered by**: choose the entity that powers the camera in its settings. That can be the PoE port's switch, which UniFi, Omada and other network integrations provide, a smart plug, a `schedule` helper of when it should be on, or an
  `input_boolean`. While it's off the camera isn't checked, and once it's on again the camera isn't checked until *Time to start up* has passed. If the entity is unavailable or missing, the camera is checked as usual, so a problem
  with the switch can't hide a camera that's offline
- **Disable the camera in Frigate** from the same automation, before cutting its power, and enable it again once it's back. A camera disabled in Frigate is never notified as offline, and Frigate stops trying to reach it too. Frigate may enable the camera again if it restarts while the camera is off

To quieten them for a while rather than switching them off, such as while Frigate is being worked on, use Supernotify's snoozing, from a mobile action, a dashboard button or an automation. A snooze lasts a set time, or a silence until it's lifted, and either can cover everything, only what isn't critical, a delivery or a priority, for everyone or one person. See [Snoozing](https://supernotify.rhizomatics.org.uk/latest/usage/snoozing/) in the Supernotify docs.
