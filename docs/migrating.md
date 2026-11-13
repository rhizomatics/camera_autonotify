---
description: How to move from the Frigate Notifications blueprint to Camera AutoNotify, where each blueprint input is now, the defaults that differ, what isn't offered yet, and what's new.
---
# Migrating from Frigate Blueprint

Camera AutoNotify can replace the [Frigate Notifications blueprint](https://github.com/SgtBatten/HA_blueprints/tree/main/Frigate_Camera_Notifications). There are no automations to keep up to date: every Frigate camera is found and set up by itself, with settings that work as they come, and the notifications go through [Supernotify](https://supernotify.rhizomatics.org.uk), which handles phones, sounds, emails with image attachments, spoken announcements, priority and who's told.

Most blueprint automations need nothing copied across at all. Only the filters and timing you changed from the blueprint's defaults need setting again, and a few of those defaults differ here, so check the [defaults that differ](#defaults-that-differ) before you start.

This page compares against the blueprint's Stable release of 13 November 2026, `0.14.0.2y`.

## Before You Start

You need the same things as the blueprint, apart from the automations:

- The [Frigate integration](https://docs.frigate.video/integrations/home-assistant/), with its notification proxy on, as the blueprint also needs
- MQTT in Home Assistant, on the same broker as Frigate
- Home Assistant's external URL, or its internal one, set in *Settings*, *System*, *Network*. The blueprint's `base_url` input isn't needed, since this is used instead
- [Supernotify](https://supernotify.rhizomatics.org.uk) from Marketplace (previously HACS), for the snapshot, the clip, sounds, critical alerts and updates. Without it, only the first notification of each review is sent, as plain text

## Moving Over

1. **Write down what you changed.** For each of the blueprint's automations, open it in *Settings*,
   *Automations & scenes*, choose *Edit in YAML* from its menu, and copy the `use_blueprint` `input` section somewhere. Only the inputs listed there differ from the blueprint's defaults. One automation may cover more than one camera, so note which.
2. **Install Camera AutoNotify** from the Home Assistant Marketplace, and restart.
3. **Add the integration** in *Settings*, *Devices & services*. To be told only by Camera AutoNotify from the start, turn *Set up cameras automatically* off on the first screen and add each camera when you're ready, from *Discovered*. Otherwise leave it on, and every camera is set up straight away.
4. **Disable the blueprint's automations** once the cameras are set up, or you'll be told twice. Disable rather than delete them until you're happy, so you can go back.
5. **Set each camera's settings** from what you wrote down, using the [table](#where-each-input-is-now) below. A camera's settings are under its entry on the integration's page. Watch the units, since the blueprint's *Timeout* is in minutes and *Stop updates after* is in seconds.
6. **Set who's told.** Leave the targets empty and Supernotify chooses, as it's set up to. To tell only some, choose them under *Image and targets* in a camera's settings, or set up recipients
and deliveries in Supernotify itself, once, for every camera.
7. **Name your objects**, if your blueprint had `label_names`, or you'd rather Frigate's `car` said "Vehicle", or have your own translations. See [Object Names](#object-names).
8. **Try it.** Walk in front of a camera, and check the notification, its image, and that tapping it plays the clip.

## Where Each Input Is Now

| Blueprint input | Where it is now |
| --------------- | --------------- |
| `camera` | One entry per camera, found by itself |
| `base_url`, `client_id`, `mqtt_topic` | Read from the Frigate integration and Home Assistant's URL, nothing to set |
| `review_severity` | *Severity* |
| `labels` | *Objects* |
| `zones`, `zone_multi`, `zone_order_enforced` | *Zones*, *Every zone* and *Zones in order* |
| `cooldown`, `initial_delay`, `final_update`, `final_delay`, `alert_once` | The *Timing* section, as *Cooldown*, *Initial delay*, *Notify when over*, *Delay when over* and *Sound only the first* |
| `timeout` | *Stop updates after*, in the *Timing* section, in seconds rather than minutes |
| `update_sub_label` | *Notify recognised faces and plates*, in *Timing* |
| `label_names` | *Object names* in *Global Settings*, for every camera at once. See [Object Names](#object-names) |
| `notify_device`, `notify_group` | *Targets*, or Supernotify's recipients and mobile push delivery |
| `critical`, `interruption_level`, `sound`, `volume` | Supernotify, from the priority of the notification |
| `tts`, `tts_helper` | A Supernotify TTS delivery |
| `group`, `tag` | Set by camera and by review, nothing to set |
| `attachment` | *Image*, under *Image and targets*: the snapshot, the snapshot with its bounding box, the snapshot cropped to the object, or the thumbnail |
| `attachment_2` | The same *Image* for the first notification and its updates |
| `video`, `ios_live_view` | Not attached, see [Video on iPhones](index.md#video-on-iphones). Tapping the notification plays the clip |
| `tap_action`, `button_1` to `button_3` | Tap for the clip, and a *View snapshot* button |
| `button_3` silence, `silence_timer` | Supernotify's camera snooze |
| `title`, `message`, `subtitle` | Fixed wording, not editable, translated into Home Assistant's language where there's a translation |
| `genai_notification_title` | Frigate's own title for a GenAI review summary, with no prefix, since the threat level sets the notification's priority instead. See [GenAI Notifications](genai.md) |
| `color`, `icon`, `sticky`, `channel`, `android_auto` | Supernotify's mobile push delivery, where it has them |
| `presence_filter`, `state_filter`, `disable_times`, `master_condition`, `custom_filter` | Not offered yet. Supernotify's scenarios and snoozing cover some of these |
| `loiter_timer` | Not needed, since the blueprint no longer uses it for reviews |
| `custom_action_manual`, `custom_action_auto`, `custom_action_auto_multi` | Not offered |
| `telegram_*`, `tv_*` | Not offered, though both can be Supernotify deliveries |
| `debug`, `redacted` | Supernotify's archive, and the integration's diagnostics, which leave out targets |

## Defaults That Differ

Where your blueprint automation left one of these inputs as it came, the camera's setting here may still need changing to keep what you had.

| Blueprint input | Blueprint default | Setting here | Default here |
| --------------- | ----------------- | ------------ | ------------ |
| `review_severity` | Alerts and detections | *Severity* | Alerts |
| `cooldown` | 0 seconds | *Cooldown* | 30 seconds |
| `alert_once` | Off | *Sound only the first* | On |
| `final_delay` | 5 seconds | *Delay when over* | 0 seconds |
| `timeout` | 2 minutes | *Stop updates after* | 600 seconds, 10 minutes |
| `attachment` | Thumbnail | *Image* | Snapshot |

## Object Names

The blueprint's `label_names` is now *Object names*, in *Global Settings*, and applies to every camera and zone. Each object Frigate tracks or hears can be given a name of its own, chosen from those in Frigate's config, or typed in. Use it to translate the objects into your own language, or just to say what they are in your home:

| Object | Name |
| ------ | ---- |
| `car` | Vehicle |
| `motorcycle` | Vehicle |
| `person` | Visitor |

Objects named the same are said once, so a review of a car and a motorcycle reads "Vehicle detected at Gate". Objects not named keep Frigate's name, with a capital letter, as the blueprint does. The faces and plates Frigate recognises are kept as they are, in brackets.

The rest of the wording, such as "detected at", is translated into the language set for Home Assistant, where the integration has a translation of it, and is English otherwise.

## What Isn't Offered Yet

- Filters on presence, the state of an entity, the time of day, or a template, the blueprint's `presence_filter`,
  `state_filter`, `disable_times`, `master_condition` and `custom_filter`. Supernotify's
  [scenarios](https://supernotify.rhizomatics.org.uk/latest/configuration/scenarios/) cover most of what these were
  used for, such as more urgent notifications when everyone's out or the alarm is set, and its snoozing covers
  quiet times
- Editable title and message. The wording is fixed, though [rules](genai.md#rules) can change a notification's priority, silence it, or apply scenarios by what it says
- Custom actions run with each notification
- Video attached to the notification, and iOS live view. The clip plays when the notification is tapped instead
- Telegram and TV notifications of the integration's own, though both are built into Supernotify, so can be easily switched on
- A different image for updates than for the first notification

## What's New

Things the blueprint doesn't do:

- **Cameras set up by themselves**, including any added to Frigate later, with no automation per camera
- **Zones of their own**, each notifying for reviews from any camera it's on. See [Zones](index.md#zones)
- **GenAI review summaries and object descriptions**, each updating the review's notification, with the priority set by the threat level Frigate's GenAI gives. See [GenAI Notifications](genai.md)
- **Rules** on what any notification says, to raise its priority, silence it, or apply Supernotify scenarios
- **Periodic GenAI reports**, of the day, or of anything suspicious every few hours, by e-mail or another delivery. See [Periodic Reports](genai.md#periodic-reports)
- **Health checks**, telling you when a Frigate server stops responding, or a camera stops sending video, and when it's back, with cameras switched off on purpose kept quiet. See [Health Check](health.md)
- **Supernotify** for every notification
  - priority, critical alerts and sounds set once for every camera
  - delivery by phone, e-mail, chime, speaker or anything else it has
    - Use a chime from a doorbell or Alexa device if you want for low priority Frigate events
    - Have notifications go out with push mobile alerts and an e-mail with attachments
    - Pick from any of he 22 different Supernotify transports and the [Frigate Recipes](https://supernotify.rhizomatics.org.uk/latest/recipes/)
  - snoozing, scenarios by who's home or whether the alarm is set
  - discovers and sends to all mobile devices automatically
  - archive of what was sent including all the rules on why delivery choices made
- **A device for each camera**, linked to Frigate's own, from Home Assistant 2026.8

## Going Back

Delete *Global Settings* first, so the cameras aren't found and set up again, then each camera and zone, and re-enable the blueprint's automations. Camera AutoNotify adds no automations, scripts or YAML of its own, and changes nothing in Frigate, so there's nothing else to undo.
