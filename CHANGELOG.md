# Changelog

## 0.6.0
## ✨ Enhancements
- *Powered by* for each camera, the PoE port, smart plug or schedule it's powered by, so it's only notified as offline while that's on, with *Time to start up*, 3 minutes, before it's checked once it comes on

## 0.5.0
## ✨ Enhancements
- Frigate health check, notifying when a Frigate server stops responding and again when it's back, checked once a period, with retries that back off exponentially before a failure is notified, set in *Global Settings*
- *Notify when offline* for each camera, notifying when Frigate has no video from it and again when it's back, timed as the health check, unless the camera is disabled in Frigate
- Both read from the stats the Frigate integration already polls, so they add nothing to Frigate's load
## 📝 Other changes
- *Automatic discovery* is now *Global Settings*, renamed as it's set up
- Integration categories in the manifest, *Security & safety: Cameras* and *Messaging & notifications*
## 📚 Documentation
- RFC0003 published for integrating [anpr2mqtt](https://anpr2mqtt.rhizomatics.org.uk)

## 0.4.0
## ✨ Enhancements
- Warning on the setup and settings screens when a Frigate server's notification proxy is off, or its links expire
- Snapshot and clip links name the Frigate server by its instance id when there's more than one server
- More real Frigate reviews as test fixtures
- Frigate's GenAI review summaries update the review's notification, with the priority of their threat level
- Frigate's GenAI object descriptions update the notification of the review they're part of, whichever comes first
- Rules, for any notification, to set its priority, silence it, apply Supernotify scenarios or remove text, by what its message says
## 📚 Documentation
- A docs page on GenAI notifications, with a suggested prompt and rules

## 0.3.1
## 📚 Documentation
- Web documentation site improvements
## 📝 Other changes
- Tests work now on older less compatible HA 2026.4 releases

## 0.3.0

First pre-release, for feedback.

## ✨ Enhancements
- Frigate cameras found and set up by themselves, or offered as discovered with automatic discovery off, each linked to its Frigate device
- Frigate zones as well, optionally
- The Frigate blueprint's filters and timing as settings: severity, objects, zones, every zone, zones in order, cooldown, initial delay, notify when over, delay when over, stop updates after, sound only the first, and recognised faces and plates
- Notifications through Supernotify with the snapshot, a tap to play the clip as HLS and a *View snapshot* button, each update of a review taking the place of the last, or a plain notification without Supernotify
- Supernotify targets, custom targets and deliveries per camera
- Diagnostics, with the reviews being followed
