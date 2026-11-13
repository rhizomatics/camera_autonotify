# RFC 0004 - Richer Frigate Integration

**Status**: draft, reviewed 2026-11-13 against the Frigate integration's source, not yet spiked or built

## Summary

Make more of what Frigate and its Home Assistant integration already offer beyond reviews: actions on a
notification, recognition that reviews don't carry, and coping with cameras that move.

[RFC 0002](rfc0002_frigate_genai.md) left notifying on `face`, `lpr` or `classification` messages by themselves out of
scope, since reviews already carry what's recognised as sub labels, and an update is sent when one appears
(`update_sub_label`). So this RFC is about what reviews **don't** carry.

## First outline

- **Triggers**: face detection, licence plate recognition, bird recognition
- **Enrichment**: object and state classification, PTZ info
- **Coping**: camera autotracking
- **Actions**: PTZ, submit to Frigate+

## Review (2026-11-13)

Checked against the Frigate integration's source (`api.py`, `services.yaml`, `sensor.py`, `switch.py`), and
Supernotify's handling of mobile actions.

### Triggers

| Item | What Frigate gives | Verdict |
|------|--------------------|---------|
| Face detection | `{prefix}/tracked_object_update` with `type: face`, `name` and `score`. Known faces are already review sub labels | Partly covered. What's new is a face **not** recognised, and the score |
| Licence plates | `type: lpr`, with `name` for a known plate, and the `plate` read otherwise. Only known plates become sub labels | A real gap for unknown plates, but it overlaps [RFC 0003](rfc0003_anpr2mqtt.md). Agree there which of them owns plates, or one car gets yet another notification |
| Bird recognition | Bird classification sets the bird's sub label, so "Bird (Robin)" already comes through reviews | Notified already, but not prioritised: a rare visitor matters more than the daily robin. See [Priority by what's recognised](#priority-by-whats-recognised) |

### Enrichment

| Item | What Frigate gives | Verdict |
|------|--------------------|---------|
| Object classification, from 0.17 | `type: classification`, with `model`, and a `sub_label` or an `attribute` | A `sub_label` already reaches reviews. An `attribute`, such as a delivery company, doesn't, and could be added to the headline |
| State classification, from 0.17 | `{prefix}/{camera}/classification/{model}`, such as a gate open or closed, already a sensor of the Frigate integration | A different kind of trigger, a change of state rather than a review. Better suited to Supernotify's [RFC 0010](https://supernotify.rhizomatics.org.uk/latest/developer/rfcs/0010-sensor_autonotify/), sensor autonotify |
| PTZ info | `async_get_ptz_info(camera)`, the presets and what the camera can do | Little use in a notification, only as the preset names for an action |

### Coping with autotracking

Frigate's zones are drawn on the frame, so once an autotracking camera moves, *Zones*, *Every zone* and *Zones in
order* stop meaning what they say. Autotracked reviews also run long, into *Stop updates after*. Whether a camera
autotracks is in its config, `onvif.autotracking.enabled_in_config`. The cheap answer is a warning in the settings
when zones are chosen for such a camera, and possibly not filtering by zone while it's tracking.

### Actions

The same plumbing serves every action. A button whose action is, say, `CAMERA_AUTONOTIFY_PLUS_{detection_id}` fires
`mobile_app_notification_action`, which the integration listens for. Supernotify only acts on actions starting
`SUPERNOTIFY_`, so the two don't clash. Buttons only reach mobile push, and iOS shows three or four at most, so each
must earn its place.

| Action | How | Verdict |
|--------|-----|---------|
| Move a PTZ camera | The integration's `frigate.ptz` action: move, zoom, stop or a preset | Feasible but niche, moving a camera you can't see from the notification |
| Submit to Frigate+ | Frigate's `POST /api/events/{id}/plus`, which the integration's client has no method for, so through its general `api_wrapper` | Feasible, though it leans on more of the client than `frigate.py` does today. Needs Frigate+ set up and a snapshot saved, so offered only where Frigate's config says both are |

### Priority by what's recognised

Recognition matters as much for **how urgent** a notification is as for what it says. Today the priority comes only
from the review's severity, a GenAI threat level, or a rule matching the message text.

- **Vehicles**: a known plate, the household's own car, can be quieter than usual, and an unknown one louder,
  especially at night or with the house empty
- **Birds**: a species seen every day can be `low` or silenced, and a rare or chosen one raised
- **Faces**: the same, a known face quieter, a person with no face recognised louder

#### Where it's done today

On the live install this is done by Supernotify scenarios matching the message with a regular expression, for birds,
and for known people named in GenAI descriptions. Text matching in general isn't Frigate specific, so where it lives
and how it behaves is left to [RFC 0005](rfc0005_text_matching.md). This RFC covers only matching what Frigate
recognised, as facts, which only Camera AutoNotify knows, and which can say "not recognised", as text can't.

#### Proposed

Extend rules to match on what was recognised, as well as on the message:

- **What**: the object, such as `bird` or `car`, from the review or the description
- **Recognised as**: one of a chosen list of names, such as faces, plates or bird species, from the review's sub
  labels, the `face`, `lpr` and `classification` messages, and the names Frigate knows (`async_get_faces`, and each
  classification model's classes)
- **Or**: recognised as anything else, or not recognised at all, for an object that can be recognised but wasn't
- **Then**: as rules already do, a priority, silence, or Supernotify scenarios

A GenAI description naming a known person follows from the sub label it was written with, where Frigate gave the
GenAI provider one, so it needn't be matched in the description's text, though matching the text stays possible.
Unknown plates and faces need the `lpr` and `face` messages, since reviews only carry what was recognised.
Supernotify's scenarios then still decide, as now, how the priority is delivered by who's home or whether the alarm
is set, without needing to know about birds or faces.

Moving the live install's scenario conditions over is covered by RFC 0005.

## Other possibilities

Found in the review, and more useful than some of the outline:

1. **Keep**: a button for the integration's `frigate.favorite_event` action, so a clip someone cares about isn't
   lost to Frigate's retention
2. **Seen**: `async_set_reviews_viewed`, from a button or on tapping the notification, so the review is marked as
   viewed in Frigate's own UI too
3. **Unknown visitor**: a person review in which no face was recognised, notified at a higher priority, or matched
   by a rule. Needs `face` messages tied to the review by detection, as GenAI descriptions already are
4. **Unrecognised vehicle**: the same for plates, once RFC 0003 has settled who owns them
5. **Confidence**: `face`, `lpr` and `classification` messages have a score, so a threshold could stop a doubtful
   name being notified as certain
6. **Export**: `frigate.export_recording` as a button, to keep a longer recording around the review. Lower
   priority
7. **Version gating**: faces and plates need Frigate 0.16, classification 0.17, read from Frigate's config as the
   GenAI settings already are, so nothing is offered that the server can't do

## Proposed scope

1. **Actions first**: *Keep*, *Seen* and *Submit to Frigate+*. New, cheap, needing no new trigger, and they settle
   the action plumbing for whatever follows
2. **Priority by what's recognised**: rules matching known and unknown vehicles, birds and faces as facts, following
   the [design principles](../design_principles.md), since recognition is camera domain logic
3. **What reviews don't carry**: unknown faces, unknown plates with RFC 0003, classification attributes, and
   confidence thresholds, which priority by what's recognised needs for its "not recognised" case
4. **Autotracking**: the settings warning only
5. **Left out**: state classification, to Supernotify RFC 0010; PTZ info and PTZ actions, until someone asks

## Spikes, against a real Frigate with `ha-repl`

1. What `face` and `lpr` messages look like for a face or plate not recognised, and how they tie to a review's
   detections
2. Whether Frigate's config says Frigate+ is set up, and which detections have a snapshot it would accept
3. How reviews and zones behave while a camera is autotracking
4. Which actions a phone shows, and in what order, alongside the existing *View snapshot* button
