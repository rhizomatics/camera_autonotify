# Camera AutoNotify

[![Rhizomatics Open Source](https://img.shields.io/badge/rhizomatics%20open%20source-lightseagreen)](https://github.com/rhizomatics) [![managed by hq](https://raw.githubusercontent.com/rhizomatics/hq/main/assets/badge-managed-by-hq.svg)](https://hq.rhizomatics.org.uk/) [![Home Assistant Marketplace][marketplacebadge]][marketplace]
[![CI](https://github.com/rhizomatics/camera_autonotify/actions/workflows/ci.yml/badge.svg)](https://github.com/rhizomatics/camera_autonotify/actions/workflows/ci.yml)
[![Github Deploy](https://github.com/rhizomatics/camera_autonotify/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/rhizomatics/camera_autonotify/actions/workflows/deploy.yml)

Notifications for what your security cameras see in Home Assistant, sent through
[Supernotify](https://supernotify.rhizomatics.org.uk), with no blueprint, automations or YAML. Supports Frigate's GenAI features, and can notify when cameras are down.

It starts with [Frigate](https://frigate.video): every camera is found and set up by itself, and each Frigate review is sent as a notification with its snapshot, tapped to play the clip.

Number plates read by [anpr2mqtt](https://anpr2mqtt.rhizomatics.org.uk) are notified too, as an [early access](#number-plates-from-anpr2mqtt-early-access) feature. Other camera integrations may follow, possibly UniFi Protect or Viseron.

> 🌐 **Deutsch · English · Español · Français · हिन्दी · Italiano · Português · Português (Brasil)**

## What You Need

- Home Assistant 2026.5 or later
- The [Frigate integration](https://docs.frigate.video/integrations/home-assistant/), with MQTT set up in Home Assistant, using the same broker as Frigate
- Home Assistant's external URL, or its internal one, set in *Settings*, *System*, *Network*, for the snapshot and clip links
- [Supernotify](https://supernotify.rhizomatics.org.uk), installed from HACS, for anything beyond a plain notification
  - Optional, however without Supernotify there is only a plain text notification, with no snapshot or links, sent to every phone with the Home Assistant app unless you choose other notify entities
  - The latest version is recommended, and at least v2.17.1, since a notification can have a title and no message, which earlier versions don't announce properly on Alexa
  - v2.19.0 or later sends the still image when the animated preview can't be had, in e-mail and other deliveries Supernotify fetches the image for, and raises a repair, linking to the camera's settings, when no image can be had at all

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
| GenAI                | Shown once Frigate has review summaries or object descriptions on for the camera. *Review summaries*, on, *Object descriptions*, on, and *Descriptions without a review*, off, choose what's used. *Lowest threat level*, 0, leaves out summaries below it, and the priority of each threat level is `medium`, `high` and `critical` to begin with. *Wait for GenAI*, 2 minutes, is how long an ended review is kept for what GenAI adds. *GenAI image*, as in *Global Settings*, where it's the animated preview to begin with, is the picture shown with what GenAI adds. See [GenAI Notifications](https://camera-autonotify.rhizomatics.org.uk/genai/) |
| Image and targets    | *Image*, the snapshot with the object's bounding box drawn on, is the picture shown in each notification: the snapshot, the snapshot with the bounding box, the snapshot cropped to the object, Frigate's smaller thumbnail, or an animated GIF preview of the first 20 seconds. The preview has no bounding box or crop, and is made from the camera's recordings, so the first notification shows the snapshot with its box until Frigate has the frames for it, and a camera that doesn't record always shows it. The *View snapshot* button always shows the whole snapshot. With Supernotify, *Targets* is the same choice of entities, devices, areas, floors and labels as any Supernotify notification, *Custom targets* is for those outside Home Assistant, such as e-mail addresses or phone numbers, and *Deliveries* limits notifications to those chosen. Leave them empty for Supernotify to choose. Without Supernotify, *Targets* is a choice of notify entities, and left empty means every phone with the Home Assistant app. *Actions as Global Settings*, on, gives the camera the *Actions* of *Global Settings*. Switch it off to choose the camera's own *Actions* instead, or none |

### Frigate Health Checks

The integration also notifies when a Frigate server stops responding, and when a camera stops sending Frigate video, once a few retries have failed, and again when it's back. Both are on to begin with, set in the *Frigate health check* section of *Global Settings*, and each camera's *Notify when offline*. Cameras switched off on purpose, by their PoE port, a smart plug or a schedule, can be kept quiet with *Powered by*. See [Health Check](https://camera-autonotify.rhizomatics.org.uk/health/).

### Object Names

*Object names*, in *Global Settings*, gives any of Frigate's objects a name of its own in every notification, such as `car` as "Vehicle", or a translation into your own language. Objects given the same name are said once, and objects not named keep Frigate's name. See [Object Names](https://camera-autonotify.rhizomatics.org.uk/migrating/#object-names).

### Actions

With Supernotify, each notification on a phone has buttons for what Frigate can do with the review: *Keep* the clip from Frigate's retention, mark it *Seen* in Frigate's own UI, submit the snapshot to *Frigate+*, or *Export* the recording around it. Which are offered is set by *Actions* in *Global Settings*, keep, seen and Frigate+ to begin with, and each camera or zone can choose its own. Only those Frigate can do are offered: Frigate+ where it's set up and the camera saves snapshots, and exporting where the camera records. Switch off any that doesn't work for you, or that you'd rather not have taking a place among a phone's buttons. They're on phones only for now, not in e-mail.

### GenAI Periodic Reports

Where Frigate makes GenAI review summaries, a report of the day before is also sent each day, written by Frigate's GenAI from that day's reviews. It can instead be sent every few hours, and only when GenAI saw something suspicious in those hours. It needs Supernotify, and goes by e-mail, or whichever Supernotify deliveries you choose instead, such as Telegram, being too long for a phone's notification or a voice assistant. It's set in the *Frigate GenAI Periodic Report* section of *Global Settings*. Each report is written by Frigate's GenAI provider, so is subject to its charges and limits. See [Periodic Reports](https://camera-autonotify.rhizomatics.org.uk/genai/#periodic-reports).

### Number Plates from anpr2mqtt (Early Access)

> **Early access**: number plates from anpr2mqtt are new in 0.11.0. It works, but has had little use yet. Full documentation will follow, as may fixes and improvements, so expect it to change. Feedback is very welcome, in the [issues](https://github.com/rhizomatics/camera_autonotify/issues).

Each plate [anpr2mqtt](https://anpr2mqtt.rhizomatics.org.uk) reads is notified, with no automation, in place of the example automation in its docs:

- **What you need**: anpr2mqtt 1.3.0 or later, with its Home Assistant devices on (`device_creation`, as it comes). Each anpr2mqtt camera is then found and set up like a Frigate camera, by *Set up cameras automatically*. Frigate isn't needed
- **What's sent**: the vehicle as anpr2mqtt describes it, or its plate, at the camera, such as *Jey's Outlander at Driveway*, with the plate, the sightings before, and the DVLA's details where anpr2mqtt has them. Only a new plate is notified, not the same one again in the same visit, nor a sighting republished as Home Assistant starts
- **Images**: from Frigate's notification proxy for a plate Frigate read, and from anpr2mqtt's image entity otherwise, so they work away from home
- **Linked camera**: the same camera in Frigate or another camera integration, found by itself from anpr2mqtt's `linked_cameras`, its area or its name, or chosen in its settings, so the notification is named by it, and Supernotify's camera snooze covers both
- **Vehicles**: a priority for each kind, dangerous, unknown, known or ignored, as anpr2mqtt's targets and groups say, `critical`, `high`, anpr2mqtt's own and no notification to begin with, and Supernotify scenarios for each
- **Health**: anpr2mqtt going unavailable is notified, and again when it's back, with the timing of the Frigate health checks

Not yet: a plate isn't joined to the Frigate review of the same car, so the same arrival can be notified by both, though Supernotify's duplicate detection catches some. See [RFC 0003](https://camera-autonotify.rhizomatics.org.uk/developer/design/rfcs/rfc0003_anpr2mqtt/) for what's planned.


## Moving From the Frigate Blueprint

Camera AutoNotify can replace the
[Frigate Notifications blueprint](https://github.com/SgtBatten/HA_blueprints/tree/main/Frigate_Camera_Notifications) for review notifications. Every camera is set up for you, so there's nothing to copy across camera by camera, though any filters changed from the blueprint's defaults need setting again, and some of its defaults differ here. Disable the blueprint's automations once the cameras are set up, or you'll be told twice.

See [Migrating from Frigate Blueprint](https://camera-autonotify.rhizomatics.org.uk/migrating/) for the steps, where each blueprint input is now, the defaults that differ, what isn't offered yet, and what's new.

## Known Limits

- Frigate only, so far
- English, French, German, Italian, Spanish, Portuguese (European and Brazilian) and Hindi only so far. Notifications follow the language set for Home Assistant, and the setup screens the browser's. Frigate's object names stay in English unless given names in *Object names*
- Licence plate notifications of their own, Live Activities and editable message text aren't part of this release
- The snapshot and clip links need Frigate's notification proxy, which the Frigate integration has on unless switched off. With it off, notifications have no image and open nothing when tapped, and with an expiry set, older notifications lose them. The setup and settings screens warn of either
- With more than one Frigate server, links name the server by its MQTT `client_id`, as the Frigate integration expects, so each server needs its own
- Links use Home Assistant's external URL, or its internal one if there's none, so away from home a phone only shows the snapshot where the external URL is reachable, such as through Home Assistant Cloud
- Without Supernotify, only the first notification of each review is sent, with no image, since there's nothing an update could take the place of
- Reviews are followed in memory, so one under way when Home Assistant restarts is treated as new if Frigate updates it afterwards

If you liked this try [Appliance AutoNotify](https://appliance-autonotify.rhizomatics.org.uk) - Live activities on your phone for dishwashers, robot vacuums, power monitors etc with no config, no YAML, no blueprints, no automations.

[marketplace]: https://www.home-assistant.io/integrations/marketplace
[marketplacebadge]: https://img.shields.io/badge/Home%20Assistant-Marketplace-blue.svg
