# RFC 0004 - Richer Frigate Integration

**Status**: draft, reviewed 2026-11-13 against the Frigate integration's source, spiked against live MQTT messages, not yet built

## Summary

Make more of what Frigate and its Home Assistant integration already offer beyond reviews: actions on a
notification, recognition that reviews don't carry, and coping with cameras that move.

[RFC 0002](rfc0002_frigate_genai.md) left notifying on `face`, `lpr` or `classification` messages by themselves out of
scope, since reviews already carry what's recognised as sub labels, and an update is sent when one appears
(`update_sub_label`). So this RFC is about what reviews **don't** carry.

## First outline

- **Triggers**: face detection, licence plate recognition, bird recognition
- **Enrichment**: object and state classification, PTZ info, speed and other attributes of the tracked object
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

### Enriching the message

A review only says what was seen, where, and what was recognised. Each of its detections is a tracked object, and
Frigate publishes the full object on `{prefix}/events`, as `before` and `after` with `type` `new`, `update` or `end`,
by the same ids the review lists in `data.detections`. That object carries much more than the review, checked
against Frigate's `tracked_object.py`:

| Attribute | What it gives | Use in a notification |
|-----------|---------------|-----------------------|
| `current_estimated_speed`, `average_estimated_speed` | Speed, only through a zone with `distances` set, in km/h or mph by Frigate's `ui.unit_system` | "Car at 48 km/h on the lane", the highest seen over its updates, as the [findings](#findings-2026-11-13) show. Also a fact a rule could raise the priority on, such as a speeding car past the house |
| `velocity_angle` | Direction of travel in the frame | Only "towards" or "away" once mapped per camera, so later, if at all |
| `recognized_license_plate`, with its score | The plate read, recognised or not | The unknown plate itself, alongside the `lpr` messages, see [Triggers](#triggers) |
| `sub_label`, with its score | Who or what was recognised, and how sure | Confidence for [priority by what's recognised](#priority-by-whats-recognised) |
| `current_attributes`, `attributes` | Attributes found on the object, such as a face, a plate, or a delivery company's logo with a Frigate+ model | "Person (Amazon)" without classification |
| `stationary`, `motionless_count`, `position_changes` | Whether it has stopped, and for how long | "Car parked at the gate", or quieter updates for something that hasn't moved |
| `top_score` | Detection confidence | A floor below which a detection isn't notified, or is quieter |
| `pending_loitering` | Loitering in a zone with `loitering_time` set | Loitering is Frigate's own, through its zones, so nothing for the blueprint's `loiter_timer` to replace |

Feasible: one more subscription on the same hub, joined to reviews by detection id, as GenAI descriptions are
already. The cost is volume, since `update` comes often for a moving object, so only the latest of each detection
the entry follows should be kept, and nothing sent for it alone.

Where it shows:

- **Message**: a short line of the facts worth saying, such as speed, the plate read, or a logo, under the headline,
  where there's no GenAI description or summary to say more. With one, the facts could go after it, or be left out
- **Facts passed on**: every attribute kept is also passed to Supernotify as `data`, by the
  [design principles](../design_principles.md#pass-the-facts-on), in a schema of Camera AutoNotify's own rather than
  Frigate's raw payload, so the same facts can come from another source later, such as anpr2mqtt or UniFi Protect,
  and Supernotify's scenario conditions don't change when they do
- **Rules**: matching facts such as speed, or a score, as recognition does above

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

### One visit across cameras

Found in the spikes above, and not in the outline. A vehicle or person passing several cameras is one visit, but each
camera's review is notified by itself, with its own GenAI summary and descriptions. Two ideas decide which of those
are worth a notification of their own.

#### Activity type

What's happening, where it can be known:

| Activity | Where it can come from |
|----------|------------------------|
| Vehicle arriving | Zones entered in order, from the gate inwards, as *Zones in order* already checks. `velocity_angle`, once mapped per camera to inwards and outwards, above a speed. GenAI's observations, such as "enters the driveway" |
| Vehicle departing | The same, the other way |
| Person moving | A person review with no vehicle, or one leaving a vehicle, by GenAI's observations |
| Suspicious behaviour | GenAI's threat level above 0, or `other_concerns`, or a rule matching a description's risk |

Not every camera can give every activity, and GenAI may not have run, so an activity is known, or it isn't, and
nothing is guessed. A camera's settings could say which way is in, as a zone order or a direction, for the
cameras where that matters.

#### Semantic richness

The levels from RFC 0003, each saying more than the one before:

1. A camera event, the object and where
2. Recognition, a face or a plate, by Frigate or anpr2mqtt
3. Enrichment, such as speed, a logo, or a plate looked up with the DVLA
4. GenAI, a description or a summary

#### Deciding

Reviews on cameras next to each other, of the same label, starting within a short time, are taken as one visit.
Within a visit:

- **A new activity** is a new notification, such as the van departing after it arrived, or anything suspicious
- **The same activity, richer** updates the visit's notification, silently, as a review's updates do now, such as
  a plate read, or GenAI's summary
- **The same activity, no richer** is dropped, such as the second camera's "Car detected" while the first already
  said so, or a second GenAI summary of the same arrival

For the two vans that's two notifications each, arriving and departing, each updated as recognition and GenAI
catch up, rather than nine. Which cameras are next to each other, and the time between them, are settings of their
own, or learnt from the order cameras usually see things. Supernotify's own duplicate detection works on the
message, which GenAI words differently for each camera, so this belongs here, by the
[design principles](../design_principles.md), being camera domain logic.

## Proposed scope

1. **Actions first**: *Keep*, *Seen* and *Submit to Frigate+*. New, cheap, needing no new trigger, and they settle
   the action plumbing for whatever follows
2. **Priority by what's recognised**: rules matching known and unknown vehicles, birds and faces as facts, following
   the [design principles](../design_principles.md), since recognition is camera domain logic
3. **What reviews don't carry**: unknown faces, unknown plates with RFC 0003, classification attributes, and
   confidence thresholds, which priority by what's recognised needs for its "not recognised" case
4. **Enriching the message**: speed first, then the plate read, attributes, stationary and confidence, from
   `{prefix}/events`, in the message and as facts passed on in Camera AutoNotify's own schema
5. **One visit across cameras**: grouping by activity type and semantic richness, once enrichment and recognition
   give the richness levels something to compare
6. **Autotracking**: the settings warning only
7. **Left out**: state classification, to Supernotify RFC 0010; PTZ info and PTZ actions, until someone asks

## Spikes, against a real Frigate with `ha-repl`

1. What `face` and `lpr` messages look like for a face or plate not recognised, and how they tie to a review's
   detections
2. Whether Frigate's config says Frigate+ is set up, and which detections have a snapshot it would accept
3. How reviews and zones behave while a camera is autotracking
4. Which actions a phone shows, and in what order, alongside the existing *View snapshot* button
5. How often `{prefix}/events` updates arrive for a busy camera, and whether a speed zone gives a steady speed or
   one worth averaging, `average_estimated_speed` against `current_estimated_speed`. Done, see below

### Findings (2026-11-13)

From the MQTT messages of two delivery vans on the live install, read from the logs, over two hours: 159
`{prefix}/events` messages for 9 tracked objects, 22 on `{prefix}/reviews` with 11 GenAI summaries, and 9
descriptions. Plates and anything else identifying are left out here.

- **Volume**: about 16 `events` messages per object, several a second while a vehicle moves, then none once it
  stops. Easily kept as the latest per detection, as proposed
- **Speed**:
  - only on the one camera with a speed zone, as expected; the others give `0.0` throughout
  - the van peaked at about 40 km/h on its way in, but by its `end`, `current_estimated_speed` was `0.0` and
    `average_estimated_speed`, being of the last ten readings only, about 9 km/h as it slowed to stop
  - so neither field at the end says how fast it came: the notification needs the **highest** speed seen over the
    object's updates, kept by Camera AutoNotify, not either of Frigate's values at any one moment
- **Direction**: `velocity_angle` was steady while moving fast, and swung through 30° to 340° while slow or turning,
  so it's only worth reading above a speed
- **Plate read**: `recognized_license_plate` came as `[plate, score]`, first misread at 0.90, then corrected at
  0.97, rising to 0.98 by the `end`. It was never a sub label, the plate not being known to Frigate, so **the
  review never carried it**. Read the best scored, and only once the object has ended or the score settles.
  anpr2mqtt read the same plate worse, missing a character, which matters for [RFC 0003](rfc0003_anpr2mqtt.md)
- **Known elsewhere**: the second van was a target known to anpr2mqtt, by its own name, while Frigate knew nothing
  of it. Who knows a vehicle may not be Frigate, so priority by what's recognised should be able to take a name
  from anpr2mqtt too, when RFC 0003 is built
- **Attributes**: only `license_plate` and `face`, and over seven days only the labels `car`, `bird` and `person`,
  although there's a Frigate+ model. Its config, read afterwards, showed why:
  - a camera's own `objects.track` replaces the global one, and the cameras the vans passed had no logo labels in
    theirs, though the global list had them
  - the Frigate+ model's `attributes_map` puts the logos, `amazon`, `royal_mail`, `dhl` and the rest, under `car`,
    and `amazon` under `person` too, so once tracked they arrive as the vehicle's `current_attributes`, and a van
    becomes "Car (Royal Mail)" as a fact rather than by GenAI's text
  - an old `model.labelmap` override, from before the Frigate+ model, mapped a class that the Frigate+ model uses
    for `package` to `car`, so packages were being reported as cars

  So the delivery company was only in **GenAI's text** here, matched by [RFC 0005](rfc0005_text_matching.md), until
  the logos are tracked. Worth a settings warning, or a repair, where a camera's `objects.track` leaves out the
  attributes its model has, and where `model.labelmap` overrides a Frigate+ model's labels
- **Frigate+**: set up, with a fine-tuned model. Frigate's config has `plus.enabled`, and `model.plus` with the
  model's details and its `labelMap`, so the integration can tell, and offer *Submit to Frigate+* only then. Spike 2
  is left with which detections have a snapshot to submit
- **GenAI summaries**: carry `observations`, a list of short sentences, and a `confidence`, neither used today.
  `observations` could make a better message than `shortSummary` for a long review
- **One visit, many notifications**: each van passed three cameras, and each camera's review had its own
  notification, summary and description, so up to nine notifications for one delivery, all `LOW RISK` or
  `NO RISK`. See [One visit across cameras](#one-visit-across-cameras)
