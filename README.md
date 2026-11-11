# Camera AutoNotify

[![Rhizomatics Open Source](https://img.shields.io/badge/rhizomatics%20open%20source-lightseagreen)](https://github.com/rhizomatics) [![managed by hq](https://raw.githubusercontent.com/rhizomatics/hq/main/assets/badge-managed-by-hq.svg)](https://github.com/rhizomatics/hq) [![hacs][hacsbadge]][hacs]
[![CI](https://github.com/rhizomatics/camera_autonotify/actions/workflows/ci.yml/badge.svg)](https://github.com/rhizomatics/camera_autonotify/actions/workflows/ci.yml)
[![Github Deploy](https://github.com/rhizomatics/camera_autonotify/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/rhizomatics/camera_autonotify/actions/workflows/deploy.yml)

Notifications for what your security cameras see in Home Assistant, sent through
[Supernotify](https://supernotify.rhizomatics.org.uk), with no blueprint, automations or YAML.

It starts with [Frigate](https://frigate.video): every camera is found and set up by itself, and each Frigate review is sent as a notification with its snapshot, tapped to play the clip. Other camera integrations are to follow.

**Early Release** - this is an early release, with more planned in the future, and feedback welcome. Please say how it goes, or report anything wrong, in the [issues](https://github.com/rhizomatics/camera_autonotify/issues).

## What You Need

- Home Assistant 2026.5 or later
- The [Frigate integration](https://docs.frigate.video/integrations/home-assistant/), with MQTT set up in Home Assistant, using the same broker as Frigate
- Home Assistant's external URL, or its internal one, set in *Settings*, *System*, *Network*, for the snapshot and clip links
- [Supernotify](https://supernotify.rhizomatics.org.uk), installed from HACS, for anything beyond a plain notification
  - Optional, however without Supernotify there is only a plain text notification, with no snapshot or links, sent to every phone with the Home Assistant app unless you choose other notify entities
  - The latest version is recommended, and at least v2.17.1, since a notification can have a title and no message, which earlier versions don't announce properly on Alexa

## Install

[![Open in Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=rhizomatics&repository=camera_autonotify&category=integration)

1. Use the button above, or look for **Camera Autonotify** in the Home Assistant Marketplace (its one of the default repositories), install it and restart Home Assistant
2. In *Settings*, *Devices & services*, choose *Add integration* and pick *Camera AutoNotify*
3. Leave *Set up cameras automatically* on, and submit

That's all. Every Frigate camera is set up straight away, and so is any you add to Frigate later. Each is listed on the integration's page, alongside *Global Settings*, and notifies Frigate's alerts with no further settings.

To stop the notifications for a camera, disable it rather than delete it, since a deleted camera is found and set up again.

### Removing

1. In *Settings*, *Devices & services*, open *Camera AutoNotify* and delete *Global Settings* first, so the cameras aren't found and set up again, then delete each camera and zone
2. Remove *Camera AutoNotify* in Marketplace and restart Home Assistant

It adds no automations, scripts or YAML of its own, and changes nothing in Frigate, so there is nothing else to clear up. If you moved from the Frigate blueprint, re-enable its automations to go back to it.

### Choosing Cameras Yourself

Turn *Set up cameras automatically* off, on the first screen or later from *Global Settings*, and cameras are instead offered as *Discovered* on the *Devices & services* page, beside Frigate's own. Choose *Add* to set one up, or *Ignore* on any you don't want.

### Zones

Frigate gives each of its zones a device too. Turn on *Find zones too* in *Global Settings* and each zone is found like a camera, for notifications about that zone alone. A zone in the view of more than one camera, such as a drive seen from the gate and from the house, notifies for reviews from any of them. It's off by default, since a zone is mostly covered by its camera's own notifications, and a camera's settings can already limit it to some of its zones.

### The Camera's Device

From Home Assistant 2026.8, each camera or zone gets a device of its own, sharing the identifiers of the device Frigate gave it, so each shows the other under *Linked devices*, and Camera AutoNotify shows as one more integration on that device. Earlier releases go without it, and notifications are the same either way.

## Settings

Nothing needs changing for notifications to work. Each camera or zone on the integration's page has settings, all of them optional.

| Setting        | Default     | What it does                                                                         |
| -------------- | ----------- | ------------------------------------------------------------------------------------ |
| Severity       | Alerts      | Which of Frigate's reviews to notify. Alerts are what Frigate is set to treat as important, detections are everything else it tracks |
| Objects        | Any         | Only notify when one of these is seen or heard, chosen from the objects, audio and review labels in the camera's Frigate config, or typed in |
| Zones          | Anywhere    | Only notify when one of these zones is entered. Cameras only                         |
| Every zone     | Off         | Only notify once every zone chosen has been entered, rather than any of them         |
| Zones in order | Off         | Only notify when the zones chosen are entered in the order listed, such as from the gate to the door |
| Notify when offline | On     | Notify when Frigate has no video from the camera, and again when it's back. Cameras only. See [Health Check](https://camera-autonotify.rhizomatics.org.uk/health/) |
| Powered by     | None        | What powers the camera, such as its PoE port or smart plug, or a schedule of when it's meant to be on. It isn't notified as offline while that's off. Cameras only. See [Cameras Switched Off on Purpose](https://camera-autonotify.rhizomatics.org.uk/health/#cameras-switched-off-on-purpose) |
| Time to start up | 3 minutes | How long after *Powered by* comes on before the camera is checked, for it to start up |

| Section              | What it does                                                                           |
| -------------------- | -------------------------------------------------------------------------------------- |
| Timing               | *Cooldown*, 30 seconds, is the time after a notification before another is sent for something new, though updates of one already sent aren't held back. *Initial delay*, none, holds back the first notification for a better snapshot. *Notify when over*, off, sends one more once Frigate has finished, after *Delay when over*. *Stop updates after*, 10 minutes, ends the updates however long a review goes on. *Sound only the first*, on, has updates replace the first notification silently. *Notify recognised faces and plates*, on, sends an update when Frigate recognises a face or number plate |
| GenAI                | Shown once Frigate has review summaries or object descriptions on for the camera. *Review summaries*, on, *Object descriptions*, on, and *Descriptions without a review*, off, choose what's used. *Lowest threat level*, 0, leaves out summaries below it, and the priority of each threat level is `medium`, `high` and `critical` to begin with. *Wait for GenAI*, 2 minutes, is how long an ended review is kept for what GenAI adds. See [GenAI Notifications](https://camera-autonotify.rhizomatics.org.uk/genai/) |
| Notification targets | With Supernotify, *Targets* is the same choice of entities, devices, areas, floors and labels as any Supernotify notification, *Custom targets* is for those outside Home Assistant, such as e-mail addresses or phone numbers, and *Deliveries* limits notifications to those chosen. Leave them empty for Supernotify to choose. Without Supernotify, *Targets* is a choice of notify entities, and left empty means every phone with the Home Assistant app |

### Frigate Health Check

The integration also notifies when a Frigate server stops responding, and when a camera stops sending Frigate video, once a few retries have failed, and again when it's back. Both are on to begin with, set in the *Frigate health check* section of *Global Settings*, and each camera's *Notify when offline*. Cameras switched off on purpose, by their PoE port, a smart plug or a schedule, can be kept quiet with *Powered by*. See [Health Check](https://camera-autonotify.rhizomatics.org.uk/health/).

### GenAI Summaries

Where Frigate makes GenAI review summaries, a summary of the day before is also sent each day, written by Frigate's GenAI from that day's reviews. It can instead be sent every few hours, and only when GenAI saw something suspicious in those hours. It needs Supernotify, and goes by e-mail, or whichever Supernotify deliveries you choose instead, such as Telegram, being too long for a phone's notification or a voice assistant. It's set in the *GenAI summary* section of *Global Settings*. Each summary is written by Frigate's GenAI provider, so is subject to its charges and limits. See [Summaries](https://camera-autonotify.rhizomatics.org.uk/genai/#summaries).

## What Gets Sent

Nothing is polled. Frigate publishes each review over MQTT as it starts, changes and ends, and a notification goes out as soon as one matches the settings, held back only by the *Timing* settings.

The title says what was seen and where, such as "Person detected at Barn Door", by the zones the review entered for a camera, or the camera's name when none, and the zone's name for a zone. There's no more to the message until Frigate's GenAI describes or summarises the review.

| When                                     | With Supernotify                                                   | Without                |
| ---------------------------------------- | ------------------------------------------------------------------ | ---------------------- |
| A review starts that matches the settings | A notification with the snapshot, `high` priority for an alert and `medium` for a detection | A plain text notification |
| A review that didn't match, then does, such as a detection raised to an alert | The same, as a first notification | The same |
| Something new is seen in the review, or a new zone entered, or a face or plate recognised | An update, taking the place of the last notification for that review, silently unless *Sound only the first* is off | Nothing |
| The review ends, with *Notify when over* on | A last update, its title ending "now ended" | Nothing |
| Frigate describes an object in the review | An update with the description, after [rules](https://camera-autonotify.rhizomatics.org.uk/genai/#rules) | Nothing |
| Frigate summarises the review | An update with its title and summary, at its threat level's priority | Nothing |

With Supernotify, each notification:

- shows the snapshot of the review, and opens the clip when tapped, played from Frigate as HLS
- has a *View snapshot* button
- is grouped with the others of the same camera
- passes the camera entity, so Supernotify's camera snooze works

Rules, added under *Global Settings*, can change the priority of any notification by what it says, silence it, or apply Supernotify scenarios. See [GenAI Notifications](https://camera-autonotify.rhizomatics.org.uk/genai/#rules).

Priority, critical alerts, sounds, who is told, snoozing, the archive and scenarios are all Supernotify's, so set them up there once rather than per camera.

### Who's Home, and the Alarm

How much a camera notification matters depends on who's home and whether the alarm is set: a person at the door is
routine in the afternoon with everyone in, and urgent at night with the house armed. Camera AutoNotify sends every
notification through Supernotify, so this can be decided there, once, for every camera, with no automations.

- **Scenarios** in Supernotify apply when their conditions are met, checked as each notification is sent. A condition
  can be any Home Assistant condition, so an `alarm_control_panel` state, a `person` being home or away, or
  Supernotify's own `occupancy`, such as `ALL_AWAY` or `LONE_HOME`, and the time of day. A scenario can switch
  deliveries on or off, such as announcing on speakers or sounding a chime only while armed, and raise the priority,
  up to `critical` so it breaks through a phone's silent mode. See
  [Scenarios](https://supernotify.rhizomatics.org.uk/latest/configuration/scenarios/) and
  [Conditions](https://supernotify.rhizomatics.org.uk/latest/configuration/conditions/).
- **People**: Supernotify knows who's home from their `person` entities, and a delivery can go only to those who are
  home, or only to those who are away, so a speaker announcement is heard by whoever's in, and a phone notification
  reaches whoever's out. See [People](https://supernotify.rhizomatics.org.uk/latest/configuration/people/).

For example, the conditions of a scenario for when the alarm is set at night, from Supernotify's own docs, to which the deliveries and priority it changes are added:

```yaml
more_attention:
  conditions:
    condition: and
    conditions:
      - not:
          - condition: state
            entity_id: alarm_control_panel.home_alarm_control
            state: disarmed
      - condition: time
        after: "21:30:00"
        before: "06:30:00"
```

[Auto Arm](https://autoarm.rhizomatics.org.uk) keeps the alarm control panel's state right without anyone having to
remember. It arms and disarms it from who's home, sunrise and sunset, and calendar events, with buttons, mobile
actions and voice commands for changing it by hand, so the scenarios above follow along by themselves.

It can also switch Frigate's own profile as the alarm state changes, from Frigate 0.18, so Frigate itself watches
differently when the house is empty: more cameras or zones raising alerts, say, or indoor cameras recording only
while `armed_away`. A Frigate profile named after an alarm state is used for it, or one named `armed` for any of the
armed states, and Frigate goes back to its base config when disarmed. A profile chosen by hand in Frigate is left
alone. See [Frigate Profile Switching](https://autoarm.rhizomatics.org.uk/configuration/frigate/).

Together, with nothing per camera: everyone leaves, Auto Arm arms the house, Frigate switches to its `armed_away`
profile and alerts on more, and Supernotify sends those alerts as `critical` to everyone's phone, while the same
camera notifications stay quiet and routine when someone's home.

### Video on iPhones

The clip is never attached to the notification. Attached as `clip.mp4`, an iPhone shows the snapshot only some of the time, and a Frigate clip is often too large for it to play from the notification. Attached as the HLS playlist, it shows no image at all. So every notification has the snapshot as its image, and opening it plays the clip, on iPhones and Android phones alike. This replaces the
[Apple push fix](https://supernotify.rhizomatics.org.uk/latest/recipes/fix_frigate_apple_push/), which isn't needed here.

## Moving From the Frigate Blueprint

Camera AutoNotify replaces the
[Frigate Notifications blueprint](https://github.com/SgtBatten/HA_blueprints/tree/main/Frigate_Camera_Notifications) for review notifications. Every camera is set up for you, so there's nothing to copy across camera by camera, though any filters changed from the blueprint's defaults need setting again. Disable the blueprint's automations once the cameras are set up, or you'll be told twice.

| Blueprint input | Where it is now |
| --------------- | --------------- |
| `camera` | One entry per camera, found by itself |
| `base_url`, `client_id`, `mqtt_topic` | Read from the Frigate integration and Home Assistant's URL, nothing to set |
| `review_severity` | *Severity* |
| `labels` | *Objects* |
| `zones`, `zone_multi`, `zone_order_enforced` | *Zones*, *Every zone* and *Zones in order* |
| `cooldown`, `initial_delay`, `final_update`, `final_delay`, `timeout`, `alert_once` | The *Timing* section |
| `update_sub_label` | *Notify recognised faces and plates*, in *Timing* |
| `notify_device`, `notify_group` | *Targets*, or Supernotify's recipients and mobile push delivery |
| `critical`, `interruption_level`, `sound`, `volume` | Supernotify, from the priority of the notification |
| `group`, `tag` | Set by camera and by review, nothing to set |
| `attachment`, `video`, `ios_live_view` | The snapshot, always, see [Video on iPhones](#video-on-iphones) |
| `tap_action`, `button_1` to `button_3` | Tap for the clip, and a *View snapshot* button |
| `button_3` silence, `silence_timer` | Supernotify's camera snooze |
| `title`, `message`, `subtitle` | Fixed wording, not editable |
| `color`, `icon`, `sticky`, `channel`, `android_auto` | Supernotify's mobile push delivery, where it has them |
| `presence_filter`, `state_filter`, `disable_times`, `master_condition`, `custom_filter` | Not offered yet. Supernotify's scenarios and snoozing cover some of these |
| `tts` | A Supernotify TTS delivery |
| `custom_action_manual`, `custom_action_auto` | Not offered |
| `telegram_*`, `tv_*` | Not offered, though both can be Supernotify deliveries |
| `debug` | Supernotify's archive, and the integration's diagnostics |

## Known Limits

- Frigate only, so far, and English only
- GenAI review summaries, licence plate notifications of their own, Live Activities and editable message text aren't part of this release
- The snapshot and clip links need Frigate's notification proxy, which the Frigate integration has on unless switched off. With it off, notifications have no image and open nothing when tapped, and with an expiry set, older notifications lose them. The setup and settings screens warn of either
- With more than one Frigate server, links name the server by its MQTT `client_id`, as the Frigate integration expects, so each server needs its own
- Links use Home Assistant's external URL, or its internal one if there's none, so away from home a phone only shows the snapshot where the external URL is reachable, such as through Home Assistant Cloud
- Without Supernotify, only the first notification of each review is sent, with no image, since there's nothing an update could take the place of
- Reviews are followed in memory, so one under way when Home Assistant restarts is treated as new if Frigate updates it afterwards

## Development

```shell
uv sync
uv run pytest
uv run ruff check --fix && uv run ruff format
uv run mypy custom_components/camera_autonotify
```

See the [implementation plan](https://github.com/rhizomatics/camera_autonotify/blob/main/docs/developer/design/plan.md). This component is an implementation of
[RFC 0006](https://supernotify.rhizomatics.org.uk/latest/developer/rfcs/0006-frigate_auto_notifier/) from
[Supernotify](https://supernotify.rhizomatics.org.uk).

If you liked this try [Appliance AutoNotify](https://appliance-autonotify.rhizomatics.org.uk) - Live activities on your phone for dishwashers, robot vacuums, power monitors etc with no config, no YAML, no blueprints, no automations.

[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg
