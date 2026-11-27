# RFC 0015 - anpr2mqtt Events Without a Target

**Status**: Implemented, but for the second image
2026-11-27, for [#45](https://github.com/rhizomatics/camera_autonotify/issues/45)

## Summary

anpr2mqtt 1.4.0 publishes any event of a camera's whose `target_type` isn't `plate`, such as a face, a scene change
or a line crossed, as a Home Assistant `event` entity on the camera's anpr2mqtt device. Discover each as a source of
its own, and notify it as it fires, with its own priority, scenarios, deliveries and quiet period, by
[RFC 0003](rfc0003_anpr2mqtt.md)'s decision 11.

## What anpr2mqtt gives

| | Plate | Other event, such as a face |
|---|---|---|
| Entity | `sensor.anpr_front`, the plate its state | `event.face_front`, `event_type` the event's name |
| Details | the sensor's attributes | the event's own payload: `target_type`, `image_event`, `event_time`, `description`, `camera`, `linked_cameras` |
| Image | `image.anpr_front` | `image.face_front`, such as the face, and optionally `image.face_front_face_background`, the scene |

Each entity of a camera's event has the unique id `{event}_{camera}`, a second image's that and `_{image_event}`.

## Design

- **Discovery**: each MQTT `event` entity on an anpr2mqtt device, by manufacturer and model, as for its sensors,
  its own entry type, `anpr_event`. Offered, or set up, as Frigate's cameras are.
- **What's new**: a change of the event entity's state, its time. Not an update of its attributes alone, such as
  its image counts, not its state restored as Home Assistant starts, and not one more than 10 minutes old.
- **Nothing generic left out**: by `event_type` and `description` alone, nothing of faces or of a camera maker's
  image names, so any event anpr2mqtt is set up for works the same way.

| Said | As |
|------|----|
| Title | Its `description`, such as anpr2mqtt's `default_description`, at the linked camera, *Face at Front*, as a plate's |
| Image | The event's image entity, by the image proxy, as a plate's, and the linked camera for Supernotify's camera snooze |
| Tag | Each event its own, by its time |

| Setting | Default | |
|---------|---------|-|
| *Linked camera* | Found | As a plate source's |
| *Quiet period* | 30 seconds | Since one with no target can't be told from the next, for a camera without anpr2mqtt's `min_event_gap_seconds` |
| *Priority* | Medium | Or *Don't notify* |
| *Scenarios* | None | Supernotify's, with Supernotify |
| *Targets* | | As any source |

## Left out

- **The second image**, beside the first in e-mail, waits on Supernotify's `extra_images`,
  [supernotify#348](https://github.com/rhizomatics/supernotify/issues/348). Nothing waits for it meanwhile.
- **One visit** of a face here and a Frigate person review: [RFC 0008](rfc0008_visits.md)'s.
- **Health from image counts**, a camera that's stopped sending images: an issue of its own.
