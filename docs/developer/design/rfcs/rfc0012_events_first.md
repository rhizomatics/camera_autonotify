# RFC 0012 - Notify From Events Before Reviews

**Status**: Implemented, but for RFC 0006's count
2026-11-24, in 1.1.0

## Summary

Start a notification from Frigate's `{prefix}/events` when a wanted object enters a wanted zone and no review has
it yet, and let the review carry on that same notification once it comes. Reviews stay the main source, as Frigate
[recommends](https://docs.frigate.video/guides/ha_notifications/). Events only make sure nothing is late or missed
while Frigate has no review. A camera's *Notify from* setting can switch this off, for reviews only.

The Frigate blueprint triggers only on `frigate/reviews`, so this is something it doesn't do, and a line for
[Migrating](../../../migrating.md#whats-new).

## Motivation

On 2026-11-24, a car arrived at 17:32:42 by the driveway probe. Frigate tracked it on three cameras, and on the
doorbell camera it was in `pend` at 17:33:24. But it stopped almost as soon as it was seen, so its
`position_changes` stayed 0. Frigate made no review of it until it moved off at 17:34:55. "Vehicle at Pend" was
notified at 17:34:56, 92s late. Meanwhile, person alerts for someone walking out to it were notified at once.

Frigate leaves out of reviews any object that hasn't moved at least once, as `position_changes`, or is stationary
([`review/severity.py`](https://github.com/blakeblackshear/frigate/blob/dev/frigate/review/severity.py)). Its box
must overlap its recent average by less than 0.9 to count as moving, so a car first seen as it stops, at the edge
of the frame, isn't. It becomes stationary after `detect.stationary.threshold` frames, 10s here, and stays out of
reviews until it moves again. The `events` topic has it from the start. In Frigate's `dev`, `max_severity` on an
event follows the same rules (#25041). On 0.18.3 it can say `alert` for an object no review will include. A
[Frigate discussion](https://github.com/blakeblackshear/frigate/discussions/21686) puts it as events for the
lowest latency, and reviews for one notification that keeps being updated.

### Findings, 2026-11-18 to 24

From the MQTT stream kept in OpenObserve: 3,783 `events` messages and 382 `reviews` messages, on courtyard,
driveway and doorbell. An object counts as wanted when its label is in the camera's `review.alerts.labels`, and it
is in one of the `required_zones`, or in any zone where there are none.

| Trigger on the event | Objects | Never reviewed | Reviewed >2s later |
|-----------------------|---------|----------------|--------------------|
| First message where wanted | 265 | 42 | 5 |
| First message in a wanted zone, not `stationary` | 213 | 14 | 5 |

- The 28 objects the second trigger leaves out are nearly all courtyard cars at dusk and dawn, re-detected while
  stationary, most likely a parked car as the light changes. Hence the guard.
- On 2026-11-19 a mobile tyre fitter's van parked in `pend` from 10:54 for about 45 minutes, and was reviewed only
  as it left, 2693s late. 7 of the 14 never reviewed are him and the cars moved while he worked, each of which
  would be notified apart from the cooldown. One visit, for [RFC 0008](rfc0008_visits.md) to group.
- The other late reviews: 362s for a doorbell car as the visit ended, 91s for today's, and 3s for two others.
- Of 199 objects reviewed, 190 were in a review by the second their event qualified, and 194 within 2s.

## Design

### When an event starts a notification

On an `events` message for an object no review has yet, of a label the camera's settings want, on its first
message where it is:

- **in a wanted zone**: `current_zones` meets the entry's *Zones* or, without them, the camera's `required_zones`
  for its severity, or any zone where there are none of either. *Every zone* and *Zones in order* use
  `entered_zones`
- **not `stationary`**, so a parked car re-detected is left alone

the tracker holds it for *Wait for a review*, 2s, the time nearly all reviews come by. If no review lists its id in `detections` by
then, it's notified as `NEW`. Its severity is Frigate's own, from the camera's `review` config: `alert` where the
label and zones meet `review.alerts`, otherwise `detection`. So *Severity* filters it as it does a review.

Each object is considered once. *Cooldown* covers both, so an event and a review starting together give one
notification.

### When the review comes

A review listing the event's id in `detections` takes over the notification. It uses the event's id as its tag,
as the tracker already does for a GenAI description notified before its review (`tag_id`). Its first message is an
update, silent under *Sound only the first*, with what the review adds. A review that never comes leaves the one
notification. *Notify when over* is sent on the event's `end`.

### Image

Frigate serves an event's `snapshot.jpg` from the tracked object while it's tracked, whatever `has_snapshot` says,
and once it's ended only with `has_snapshot` (`event_snapshot` in `frigate/api/media.py`). So the notification has
the event's snapshot, fetched as it's sent, but no clip, and *View snapshot* fails once an object that never moved
has gone. The review's update brings the review's snapshot and clip.

### Settings

In a new *Advanced* section of a camera's or zone's settings, collapsed:

| Setting | Options | Default |
|---------|---------|---------|
| *Notify from* | *Reviews, and objects not yet reviewed*; *Reviews only* | *Reviews, and objects not yet reviewed* |
| *Wait for a review* | Seconds, 0 to 10 | 2 |

*Reviews only* behaves as now, and as the blueprint does.

### Where it goes

- `hub.py`: the `events` subscription, already there for `FactStore`, is passed to each watcher as well.
- `tracker.py`: `on_event(payload, now)` returns a `Wait` for the hold, and `on_timer` decides. A `Review` stand-in
  for the event, as `Review.of_object` is for a description, carries its camera, label, zones and severity. Events
  still waiting, by id, are kept until `end`, or `STALE_AFTER`.
- `frigate.py`: severity from the camera's `review` config.
- Each event that would be notified before its review, and how late the review came or that it never did, is
  counted for [RFC 0006](rfc0006_config_health_report.md)'s check 10, with *Reviews only* too.
- Tests: from the 2026-11-24 messages, and one where the review comes first, within the hold, and never.

## Open questions

- Is 2s right on other installs? The findings come from one install, and the log timestamps only go to the second,
  hence the setting.
