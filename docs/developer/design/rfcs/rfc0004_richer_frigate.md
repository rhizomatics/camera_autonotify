# RFC 0004 - Richer Frigate Integration

**Status**: Built in 0.10.0, but for what's listed under [As built](#as-built)
Reviewed 2026-11-13 against the Frigate integration's source, spiked against live MQTT messages, not yet built.
Rescoped 2026-11-17: priority by what's recognised moved to [RFC 0005](rfc0005_rules.md), and one visit across
cameras to [RFC 0008](rfc0008_visits.md), which isn't Frigate specific

## Summary

Make more of what Frigate and its Home Assistant integration already offer beyond reviews: actions on a
notification, recognition that reviews don't carry, the tracked object's own facts in the message, and coping with
cameras that move.

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
| Bird recognition | Bird classification sets the bird's sub label, so "Bird (Robin)" already comes through reviews | Notified already, but not prioritised: a rare visitor matters more than the daily robin. See [RFC 0005](rfc0005_rules.md#matching-whats-recognised) |

### Enrichment

| Item | What Frigate gives | Verdict |
|------|--------------------|---------|
| Object classification, from 0.17 | `type: classification`, with `model`, and a `sub_label` or an `attribute` | A `sub_label` already reaches reviews. An `attribute`, such as a delivery company, doesn't, and could be added to the headline |
| State classification, from 0.17 | `{prefix}/{camera}/classification/{model}`, such as a gate open or closed, already a sensor of the Frigate integration | A different kind of trigger, a change of state rather than a review. Not covered by Supernotify's [RFC 0010](https://supernotify.rhizomatics.org.uk/latest/developer/rfcs/0010-sensor_autonotify/), sensor autonotify, which is only for motion sensors and traditional alarms, so it's Frigate enrichment, here: a fact added to a review on the same camera, such as the gate being open as a car arrives, and possibly a notification of its own for a chosen change |
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
| `sub_label`, with its score | Who or what was recognised, and how sure | Confidence, for rules matching what's recognised, in [RFC 0005](rfc0005_rules.md#matching-whats-recognised) |
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

Which actions a notification has is a setting, *Actions*, a choice of those Frigate's config says the server can
do, all of them to begin with, in *Global Settings* and overridable for each camera or zone, as *GenAI image* is.
So an action that doesn't work for someone, such as *Submit to Frigate+* for a camera whose snapshots Frigate+
won't take, or one they don't want taking a place among iOS's few buttons, can be switched off, without needing the
gating to be perfect.

Actions are mobile only to begin with. E-mail can have them later, either once Supernotify supports actions for its
e-mail delivery, or as links in the HTML e-mail of [RFC 0007](rfc0007_rich_email.md), each link being a Home
Assistant webhook or a page that runs the action. Whichever it is, the action itself is the same, so only how it's offered
changes.

| Action | How | Verdict |
|--------|-----|---------|
| Move a PTZ camera | The integration's `frigate.ptz` action: move, zoom, stop or a preset | Feasible but niche, moving a camera you can't see from the notification |
| Submit to Frigate+ | Frigate's `POST /api/events/{id}/plus`, which the integration's client has no method for, so through its general `api_wrapper` | Feasible, though it leans on more of the client than `frigate.py` does today. Needs Frigate+ set up and a snapshot saved, so offered only where Frigate's config says both are |
| Keep | The integration's `frigate.favorite_event` action | Cheap, and keeps a clip someone cares about from Frigate's retention |
| Seen | `async_set_reviews_viewed`, from a button, or on tapping the notification | Cheap, marking the review as viewed in Frigate's own UI too |
| Export | `frigate.export_recording`, for a longer recording around the review | Lower priority than the others, and a button fewer for them where iOS runs out |

### Priority by what's recognised

Moved to [RFC 0005](rfc0005_rules.md#matching-whats-recognised), since rules matching what's recognised, as facts, are
the same rules as those matching text, and the facts can come from sources other than Frigate, such as anpr2mqtt.
What stays here is gathering the facts: what reviews don't carry, the tracked object's attributes, and their
confidence, so a rule can say "not recognised", as text can't.

## Other possibilities

Found in the review, and more useful than some of the outline. Where each has gone:

| Item | Now |
|------|-----|
| Keep, Seen, Export | Actions, in the [proposed scope](#proposed-scope), mobile only to begin with |
| Unknown visitor, Unrecognised vehicle | Gathered here, as what reviews don't carry, and matched by rules in [RFC 0005](rfc0005_rules.md#matching-whats-recognised) |
| Confidence | Gathered here, the threshold being a rule in RFC 0005 |
| Version gating | In the [proposed scope](#proposed-scope) |

As first found:

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

Found in the spikes, and moved to [RFC 0008](rfc0008_visits.md), since a visit can be seen by more than Frigate, such
as anpr2mqtt reading the plate of the car a Frigate camera saw, or a doorbell pressed by the person it saw. The
enrichment here gives that RFC's semantic richness levels something to compare.

## Proposed scope

1. **Actions first**: *Keep*, *Seen* and *Submit to Frigate+*, then *Export*. New, cheap, needing no new trigger,
   and they settle the action plumbing for whatever follows. Each can be switched off, globally or per camera,
   in an *Actions* setting. Mobile only to begin with, and in e-mail once
   Supernotify supports it there, or as links in the HTML e-mail of [RFC 0007](rfc0007_rich_email.md)
2. **What reviews don't carry**: unknown faces, unknown plates with RFC 0003, classification attributes, and the
   confidence of each, which rules matching what's recognised in RFC 0005 need for their "not recognised" case
3. **Enriching the message**: speed first, then the plate read, attributes, stationary and confidence, from
   `{prefix}/events`, and state classification, such as a gate open, from the same camera, in the message and as
   facts passed on in Camera AutoNotify's own schema
4. **Autotracking**: the settings warning only
5. **Version gating**: faces and plates from Frigate 0.16, classification and state classification from 0.17, read
   from Frigate's config, as the GenAI settings already are, so nothing is offered that the server can't do, and
   *Submit to Frigate+* only where `plus.enabled` says Frigate+ is set up, with or without a Frigate+ model, and
   only for a detection with a snapshot
6. **Moved**: priority by what's recognised to [RFC 0005](rfc0005_rules.md); one visit across cameras to
   [RFC 0008](rfc0008_visits.md)
7. **Left out**: PTZ info and PTZ actions, until someone asks

## As built

Built 2026-11-17, with these decisions, and what's left:

- **Facts not passed on as data yet**: Supernotify merges a notification's extra `data` into what it sends each
  transport, so facts there could swell a phone's push payload. They go in the message only, until Supernotify has
  a field that isn't passed on, as asked for `source` in Supernotify #293
- **No new updates for facts**: a plate read or a face not recognised doesn't send an update of its own, the facts
  being said in each notification as it goes. *Notify when over* says most
- **Gating by config, not version**: each fact and action comes only where Frigate's config says it's set up, such as
  `face_recognition`, `lpr`, `plus.enabled` or a camera's `snapshots` and `record`, which older Frigate versions
  don't have, so no version numbers are read
- **Export off to begin with**: heavier than the others, and a button fewer where a phone has few
- **Spike 2**: settled by the tracked object's own `has_snapshot`, so *Submit to Frigate+* is offered only for a
  detection Frigate has a snapshot of, once that's known
- **Not yet**: the speed of an object passing several speed zones is the highest of any, and `velocity_angle` isn't
  read, being for [RFC 0008](rfc0008_visits.md)

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
  of it. Who knows a vehicle may not be Frigate, so rules matching what's recognised, in RFC 0005, should be able to
  take a name from anpr2mqtt too, when RFC 0003 is built
- **Attributes**: only `license_plate` and `face`, and over seven days only the labels `car`, `bird` and `person`,
  although there's a Frigate+ model. Its config, read afterwards, showed why:
  - a camera's own `objects.track` replaces the global one, and the cameras the vans passed had no logo labels in
    theirs, though the global list had them
  - the Frigate+ model's `attributes_map` puts the logos, `amazon`, `royal_mail`, `dhl` and the rest, under `car`,
    and `amazon` under `person` too, so once tracked they arrive as the vehicle's `current_attributes`, and a van
    becomes "Car (Royal Mail)" as a fact rather than by GenAI's text
  - an old `model.labelmap` override, from before the Frigate+ model, mapped a class that the Frigate+ model uses
    for `package` to `car`, so packages were being reported as cars

  So the delivery company was only in **GenAI's text** here, matched by [RFC 0005](rfc0005_rules.md), until
  the logos are tracked. A camera's `objects.track` leaving out the attributes its model has, and `model.labelmap`
  overriding a Frigate+ model's labels, are for the [config health report](rfc0006_config_health_report.md)
- **Frigate+**: set up, with a fine-tuned model. Frigate's config has `plus.enabled`, and `model.plus` with the
  model's details and its `labelMap`, so the integration can tell, and offer *Submit to Frigate+* only then.
  Submitting needs only `plus.enabled`, Frigate+ being set up, not a Frigate+ model, since images are submitted to
  train one in the first place. Spike 2 is left with which detections have a snapshot to submit
- **GenAI summaries**: carry `observations`, a list of short sentences, and a `confidence`, neither used today.
  `observations` could make a better message than `shortSummary` for a long review
- **One visit, many notifications**: each van passed three cameras, and each camera's review had its own
  notification, summary and description, so up to nine notifications for one delivery, all `LOW RISK` or
  `NO RISK`. See [RFC 0008](rfc0008_visits.md)
