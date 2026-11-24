---
title: What's New
---

## New!

> Camera Autonotify was first released in October 2026 with support only for Frigate notifications. Its intended to be a `1.0.0` release by the end of 2026, with [ANPR2MQTT](https://anpr2mqtt.rhizomatics.org.uk) as the second integration. Ideas, improvements and other feedback very welcome - use the [Github Issues](https://github.com/rhizomatics/camera_autonotify/issues) to add them.

# 1.1.0
## ✨ Enhancements
- **Slow Frigate Reviews**
  - Occasionally Frigate may delay the `review` message for 10s of seconds after the initial `event` is posted. AutoNotify can now use both, and will use the event if there's more than a configurable delay for the review
  - An object Frigate hasn't reviewed yet is notified as soon as it's in a zone, such as a car that stops as it comes into view, which Frigate leaves out of reviews until it moves, and the review takes over the notification when it comes. - *Notify from*, in a camera's or zone's new *Advanced* settings, can be set to *Reviews only*, as the Frigate blueprint does, to switch off this behaviour.
  - See [Objects Not Yet Reviewed](how_it_works.md#objects-not-yet-reviewed)
- **Late GenAI**
  - Frigate's GenAI summaries and descriptions come a minute or two after what they describe has ended, and now and then more, which can read as though it's happening now. Once they're late enough, they start with how long ago, such as *Ended 3 minutes ago*
  - Late ones can be given a priority of their own, or not sent, and Supernotify scenarios, so whether a late one is heard can depend on who's home or the alarm. See [When GenAI Is Late](genai.md#when-genai-is-late)

# 1.0.1
## 🐞 Fixes
- With Supernotify v2.19.0 or later, each image is also tried at Home Assistant's own address, after the one a phone uses, so e-mail and the other deliveries Supernotify fetches the image for still get it, and no repair is raised, where Home Assistant can't reach itself at its external address, such as without hairpin NAT
- An anpr2mqtt sighting's headline names the vehicle by its category, where there's no description, or else as its vehicle register names it, by fields chosen for each register, colour and make for the DVLA, such as *Red Peugeot at Driveway*, or else as *Unknown vehicle JX123YYZ at Driveway*, rather than the bare plate
- Frigate's *on demand* recording, started by hand from its UI, is no longer notified as *On demand detected*, nor GenAI's summary of it ([#34](https://github.com/rhizomatics/camera_autonotify/issues/34))
- The fact for a tracked object that has stopped says *Stopped* rather than *Not moving*, which contradicted the highest speed said before it, as in *8 mph - Not moving*

# 1.0.0
## ✨ Enhancements
### Vehicle Classification and Enrichment

Features from `anpr2mqtt` are now brought directly into this plugin, so classifying, tracking and looking up plates happens here, for any source of plates, and `anpr2mqtt` is no longer need for Frigate LPR enrichment (e.g. DVLA):

- **Vehicle Categories**, known or dangerous, by plates or regular expressions, with each plate's corrections, and *Ignore*
- Pre-defined **vehicle rules**, once there's a category: a priority and scenarios for known (`medium`), unknown and unreadable (`high`) and dangerous (`critical`) vehicles. A misread plate matching a dangerous one can raise a false `critical`
- Each plate's visit history, with each sighting's camera and source
  - Stored with salted hash, never the plate itself. Tracker can be switched on or off in Settings
  - Pruned daily with configurable maximum days
  - Provides counts of previous sightings, count by hour, new visits, the times of day it's usually seen
    - Further classified into:
      - *Daily visitor* (5 days of 7, each of the last two weeks)
      - *Weekly visitor* (each of the last two weeks)
      - *Occasional visitor* (every month back to its first sighting), or otherwise previously seen.
- **DVLA lookup** for UK plates
  - Cached, correcting a misread by the last plate confirmed on the same camera
  - The DVLA's API key kept as a credential, in the entry's data, never shown again or in diagnostics
  - Each DVLA call logged at info, with the plate partly redacted, the status code and any error the DVLA gives
  - *Test the key*, looking up `A123TST`, which should be answered with JSON and 200 or 404
  - `classify_plate`'s lookup has the status, any error, and whether cached, with when it was retrieved, or `skipped`
- Frigate's plates classified, looked up and said under the headline, with their sightings
- anpr2mqtt's sightings classified here instead of by anpr2mqtt, with *Use anpr2mqtt's own classification* off, in each anpr2mqtt source's settings
- **New Actions**
  - `classify_plate` - Apply all the same lookups and enrichments as carried out for notifications, so can be used in other automations, e.g. to look up DVLA data, or get sightings
  - `add_plate` - Add a plate to vehicle categories, with optional corrections
  - `remove_plate` - Remove plate from vehicle categories
  - `list_vehicle_categories` - all of the vehicle categories in one call
  - `reset_sightings` - clear the sightings data for one, or all objects
- **New Mobile Notification Actions**
  - A *Known vehicle* button on a notification of an unknown plate, with a description typed on the phone
- **Image processing** integrations, such as *OpenALPR*, as a source of their own, each plate or face they find in their own camera's images notified, by Home Assistant's `found_plate` and `detect_face` events, found and set up by itself by its device class. See [Image Processing](./image_processing.md)
- A *Last notification snapshot* camera entity, an option of any camera, for a dashboard
- A `camera_autonotify_vehicle` event for each sighting, with OpenALPR's `plate`, `entity_id` and `confidence`, with *Fire vehicle events* on
- For `anpr2mqtt` users
  - Import anpr2mqtt dara by uploading an archive of its `config` and `data` folders, in *Global Settings* or as an anpr2mqtt source is set up, showing what was found before importing, and what was added after ([#27](https://github.com/rhizomatics/camera_autonotify/issues/27))
  - Switch on or off the server-side classifications and lookups, so this plugin can override
## 📝 Other changes
- Implemented next phase of [RFC0003](./developer/design/rfcs/rfc0003_anpr2mqtt.md)
- An anpr2mqtt source is always offered as discovered, and its setup asks about anpr2mqtt, not Frigate
- A Frigate camera or zone's entry titled with *(Frigate)* after its name, so the entries list shows where each is from, as an anpr2mqtt source's already does. Notifications and entities still say only the name
## 🐞 Fixes
- Spoken announcements, such as Alexa's, say only the headline, or with GenAI's summary or description after it, rather than reading out the facts under it, the speed and plate among them, like bullet points ([#26](https://github.com/rhizomatics/camera_autonotify/issues/26))
- A delivery company's logo from a Frigate+ model is said as its brand, such as *DPD* or *Royal Mail*, rather than *Dpd*, unless *Object names* names it otherwise, and isn't said again under the headline when it's already the object in it
- The facts under the headline are separated by a plain `-` rather than `·`
- anpr2mqtt's spoken message only adds the plate where the title is the vehicle's description, so an unknown vehicle's plate isn't said twice
- The buttons on a phone say what they do: *Keep clip*, *Mark reviewed*, *Submit to Frigate+* and *Export recording*, rather than *Keep*, *Seen*, *Frigate+* and *Export*
## 🌐 Translations
- All new functionality translated for Deutsch, English, Español, Français, हिन्दी, Italian, Português, Português (Brasil)
## 📚 Documentation
- Draft RFCs for [0010 - Unifi Protect](./developer/design/rfcs/rfc0010_unifi_protect.md), [0009 - Image Pipelines](./developer/design/rfcs/rfc0009_pipelines.md), [0008 - Visits](./developer/design/rfcs/rfc0008_visits.md), [0007 - Rich Emails](./developer/design/rfcs/rfc0007_rich_email.md) and [0006 - Frigate Config Health Report](./developer/design/rfcs/rfc0006_config_health_report.md)

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
