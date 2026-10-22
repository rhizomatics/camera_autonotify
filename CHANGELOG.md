# Changelog

## 0.3.1
- Documentation update
- Tests work now on older less compatible HA 2026.4 releases

## 0.3.0

First pre-release, for feedback.

- Frigate cameras found and set up by themselves, or offered as discovered with automatic discovery off, each
  linked to its Frigate device
- Frigate zones as well, optionally
- The Frigate blueprint's filters and timing as settings: severity, objects, zones, every zone, zones in order,
  cooldown, initial delay, notify when over, delay when over, stop updates after, sound only the first, and
  recognised faces and plates
- Notifications through Supernotify with the snapshot, a tap to play the clip as HLS and a *View snapshot* button,
  each update of a review taking the place of the last, or a plain notification without Supernotify
- Supernotify targets, custom targets and deliveries per camera
- Diagnostics, with the reviews being followed
