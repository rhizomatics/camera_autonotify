---
title: What's New
---

## Early Access

> Camera Autonotify was first released in October 2026 with support only for Frigate notifications. Its intended to be a `1.0.0` release by the end of 2026, with [ANPR2MQTT](https://anpr2mqtt.rhizomatics.org.uk) as the second integration. Ideas, improvements and other feedback very welcome - use the [Github Issues](https://github.com/rhizomatics/camera_autonotify/issues) to add them.

# 0.11.1
## ✨ Enhancements
- Speeds are said in km/h or mph by *Speed unit* in *Global Settings*, automatically mph where roads are signed in it, by Home Assistant's country, such as the UK and US, or where its units aren't metric, rather than in whatever unit Frigate happens to use.
## 🐞 Fixes
- The linked camera choice for an anpr2mqtt config entry is now limited to the ones it could be, e.g. Frigate if that's the only other integration.
## 📚 Documentation
- How to switch off the Frigate camera's notification of a car that anpr2mqtt also notifies, to avoid duplicates
- [RFC0003 - ANPR2MQTT Integration](./developer/design/rfcs/rfc0003_anpr2mqtt.md) updated: Frigate's plates looked up with the DVLA directly, with other countries' registers to follow, and vehicles registered here, with categories, corrections, ignores, visit history and a *Known vehicle* button
- [RFC0005 - Rules](./developer/design/rfcs/rfc0005_rules.md) updated with rules for known, dangerous, unknown and ignored vehicles

# 0.11.0
## ✨ Enhancements
### Number Plates from anpr2mqtt, Early Access
[RFC0003 - ANPR2MQTT Integration](./developer/design/rfcs/rfc0003_anpr2mqtt.md) is built as far as notifying anpr2mqtt's plates by themselves, as **early access**: it works, but has had little use yet, so full documentation will follow, as may fixes and improvements.
- Each anpr2mqtt camera, from anpr2mqtt 1.3.0, found and set up like a Frigate camera, with or without Frigate
- A new plate notified as anpr2mqtt describes the vehicle, with the plate, the sightings before and the DVLA's details, not the same plate again in the same visit, nor a republished sighting
- Images that work away from home, by Frigate's notification proxy or anpr2mqtt's image entity
- A linked camera, found from anpr2mqtt's `linked_cameras`, its area or its name, or chosen
- A priority, or no notification, and Supernotify scenarios, for each kind of vehicle: dangerous, unknown, known and ignored
- anpr2mqtt going unavailable notified, and coming back
- Not yet: joining a plate to the Frigate review of the same car, nor anpr2mqtt's other kinds of detection, such as faces or lines crossed
### Supernotify Images
- With Supernotify v2.19.0 or later:
  - the animated preview goes with the camera's still image behind it, tried in turn, so in e-mail and the other deliveries Supernotify fetches the image for, a preview Frigate can't make is replaced by the still image of the event, rather than no picture
  - an image that can't be fetched at all raises a Home Assistant repair, saying which images failed and why, linking to the camera's or zone's settings to choose another *Image*
  - Supernotify also takes the camera's live view as a last resort, which isn't the event, as [When the Image Can't Be Fetched](./how_it_works.md#when-the-image-cant-be-fetched) explains
- Earlier versions of Supernotify are sent the image as before
## 📚 Documentation
- [Migrating from Frigate Blueprint](./migrating.md) lists what's been added since, among the things the blueprint doesn't do
- The languages supported, each in its own name, at the top of the README

# 0.10.0
## ✨ Enhancements
[RFC0004 - Richer Frigate Integration](./developer/design/rfcs/rfc0004_richer_frigate.md) has been implemented.
### Mobile Actions
- Buttons on each notification on a phone, with Supernotify:
  - *Keep* the clip from Frigate's retention
  - Mark the review *Seen* in Frigate
  - Submit the snapshot to *Frigate+*
  - *Export* the recording around it.
- Chosen by *Actions* in *Global Settings*, keep, seen and Frigate+ to begin with, or by each camera or zone, and offered only where Frigate can do them: Frigate+ where it's set up and the camera saves snapshots, and only for a detection Frigate has a snapshot of, exporting where the camera records
### Enriched Message
- What Frigate knows of the review's objects beyond the review is said under the headline: the highest speed through a speed zone, a plate read that Frigate doesn't know, attributes such as a delivery company's logo, a face seen but not recognised, an object that has stopped, and the camera's state classifications, such as a gate open
### Autotracking Warning
- A warning in the settings of a camera that autotracks, or a zone on one, since its zones move with it
## 📚 Documentation
New design docs:
- [RFC0007 - Rich Email](./developer/design/rfcs/rfc0007_rich_email.md)
- [RFC0008 - Visits](./developer/design/rfcs/rfc0008_visits.md)
Updated design docs:
- [RFC0005 - Rules](./developer/design/rfcs/rfc0005_rules.md)

# 0.9.1
## ✨ Enhancements
- Smarter handling of when GIF option is available, e.g. not if camera has recording switched off, and not on first snapshot when not enough frames for Frigate to construct an animation.
- *GenAI image*, in *Global Settings*, is the picture shown with what Frigate's GenAI adds, a review summary or an object description, the animated GIF preview to begin with, as Frigate's own review shows. Each camera or zone can choose its own in its *GenAI* settings. Where the camera doesn't record, its own *Image* is shown instead
- *Image* is now the snapshot with the object's bounding box to begin with, rather than the whole snapshot. A camera or zone with *Image* already chosen keeps it
- A periodic report Frigate fails to write is asked for again, 3 times to begin with, a quarter of an hour apart, set by *Retries*. If it still fails, a notification says so, why as far as can be told, such as Frigate taking longer than the 60 seconds the Frigate integration waits, with links to Home Assistant's logs, the Frigate integration's diagnostics, and Frigate's GenAI troubleshooting

# 0.9.0
## ✨ Enhancements
- *Image* can also be an animated GIF preview of the event's first 20 seconds, made by Frigate from the camera's recordings. It has no bounding box or crop. The first notification shows the snapshot, before Frigate may have the frames for the preview, and updates switch to the preview, while a camera Frigate doesn't record always shows the snapshot
## 🌐 Translations
- Spanish, Portuguese (European and Brazilian) and Hindi translations
## 🐞 Fixes
- *Only when there's a concern* for periodic reports counts a review that began before the hours reported and went on into them, as Frigate's own report does, and no longer one still going on, which Frigate leaves out
- A periodic report of hours with nothing of concern, or no GenAI summaries at all, says so in Home Assistant's language, rather than sending Frigate's fixed English sentence
## 📚 Documentation
New design docs
- [RFC0006 Config Health](./developer/design/rfcs/rfc0006_config_health_report.md)

# 0.8.0
## ✨ Enhancements
- *Object names* in *Global Settings* gives any of Frigate's objects a name of its own in every notification, such as `car` as "Vehicle", or a translation
- *Image*, in each camera's or zone's settings, chooses the picture of each notification: the snapshot, as before, the snapshot with the object's bounding box, the snapshot cropped to the object, or the thumbnail. All still come through the Frigate integration's notification proxy
## 🌐 Translations
- The wording of every notification, the notes on the setup screens, and the reasons a camera waits to be set up are translatable, notifications following the language set for Home Assistant
- French, German and Italian translations
## 📚 Documentation
- New [Migrating from Frigate Blueprint](https://camera-autonotify.rhizomatics.org.uk/migrating/) page, with the steps, where each input of the blueprint's latest release is now, the defaults that differ, what isn't offered yet, and what's new
- New RFCs for improved Frigate integration, and text matching for priority setting, and start on design principles

# 0.7.2
## 🐞 Fixes
- *Only when there's a concern* for periodic reports no longer stops Frigate being asked for the report, only whether it's sent as a notification after being generated.
- *Global Settings* warns when saved if periodic reports are on with no deliveries chosen and Supernotify has no e-mail delivery, so they'd never be delivered. Saving again keeps the settings as they are.

# 0.7.1
## 📚 Documentation
- Correct wording on Frigate use of GenAI and token limits
- Include links to the Frigate GenAI troubleshooting FAQ and language selection
## 🐞 Fixes
- Only select 1 `email` delivery by default in Supernotify if there are several


# 0.7.0
## ✨ Enhancements
### GenAI Hourly/Daily Reports
- New option in *Global Settings* to send a report written by Frigate's GenAI of the reviews of the hours before, once a day, or every few hours. Defaults automatically to on where Frigate makes review summaries, and can be restricted to only send when GenAI saw something of concern in those hours. Requires Supernotify, and by default only sends via e-mail, though other deliveries can be chosen, e.g. Telegram.
## 🐞 Fixes
- A camera part way through its retries when its Frigate server stops answering starts them over once the server is back, rather than being notified as offline after fewer retries, with its time offline counted from before the server went down
## 📚 Documentation
- The health check, and keeping cameras switched off on purpose quiet, moved to a [Health Check](https://camera-autonotify.rhizomatics.org.uk/health/) page of its own
- Added hints on using Supernotify's occupancy and alarm panel mode to control notification delivery, and using Auto Arm to manage alarm panels and Frigate profiles

# 0.6.0
## ✨ Enhancements
- *Powered by* for each camera, the PoE port, smart plug or schedule it's powered by, so it's only notified as offline while that's on, with *Time to start up*, 3 minutes, before it's checked once it comes on
## 📝 Other changes
- Integration categories in the manifest, *Security & safety: Cameras* and *Messaging & notifications*

# 0.5.0
## ✨ Enhancements
- Frigate health check, notifying when a Frigate server stops responding and again when it's back, checked once a period, with retries that back off exponentially before a failure is notified, set in *Global Settings*
- *Notify when offline* for each camera, notifying when Frigate has no video from it and again when it's back, timed as the health check, unless the camera is disabled in Frigate
- Both read from the stats the Frigate integration already polls, so they add nothing to Frigate's load
## 📝 Other changes
- *Automatic discovery* is now *Global Settings*, renamed as it's set up
## 📚 Documentation
- RFC0003 published for integrating [anpr2mqtt](https://anpr2mqtt.rhizomatics.org.uk)

# 0.4.0
## ✨ Enhancements
- Warning on the setup and settings screens when a Frigate server's notification proxy is off, or its links expire
- Snapshot and clip links name the Frigate server by its instance id when there's more than one server
- More real Frigate reviews as test fixtures
- Frigate's GenAI review summaries update the review's notification, with the priority of their threat level
- Frigate's GenAI object descriptions update the notification of the review they're part of, whichever comes first
- Rules, for any notification, to set its priority, silence it, apply Supernotify scenarios or remove text, by what its message says
# 📚 Documentation
- A docs page on GenAI notifications, with a suggested prompt and rules

# 0.3.1
## 📚 Documentation
- Web documentation site improvements
## 📝 Other changes
- Tests work now on older less compatible HA 2026.4 releases

# 0.3.0

First pre-release, for feedback.

## ✨ Enhancements
- Frigate cameras found and set up by themselves, or offered as discovered with automatic discovery off, each linked to its Frigate device
- Frigate zones as well, optionally
- The Frigate blueprint's filters and timing as settings: severity, objects, zones, every zone, zones in order, cooldown, initial delay, notify when over, delay when over, stop updates after, sound only the first, and recognised faces and plates
- Notifications through Supernotify with the snapshot, a tap to play the clip as HLS and a *View snapshot* button, each update of a review taking the place of the last, or a plain notification without Supernotify
- Supernotify targets, custom targets and deliveries per camera
- Diagnostics, with the reviews being followed
