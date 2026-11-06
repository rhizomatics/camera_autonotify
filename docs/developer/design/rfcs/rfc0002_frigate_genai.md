# RFC 0002 - Frigate GenAI Notifications

**Status**: built in 0.4.0, 2026-11-06

## Summary

Notify from what Frigate's generative AI says about what it saw, using Frigate's own structured output where there
is one, and free text only where there isn't.

Frigate has two GenAI features, and both are in use on the live install:

- **Review summaries** (`review.genai`), one per review, with a title, a short summary and a **structured threat
  level**. This is the main source.
- **Object descriptions** (`objects.genai`), free text for each tracked object, sent on
  `{prefix}/tracked_object_update`. These have no structure, so a priority can only come from the wording the prompt
  asks for. They're a second source, with rules.

## Review of the first draft (2026-11-06)

The first draft took object descriptions as the only source, and read the priority from a risk level that the
prompt asks the model to write first. Checking that draft against the live install found these problems.

- **The example automation's priority only matched what it then filtered out.** Its regex wants whitespace straight
  after `RISK`, but the model mostly writes `RISK.` (191 of 211) or `RISK:` (4). The 16 that matched were all
  `NO RISK` or `LOW RISK`, which the condition drops anyway. So every description that was sent went at `medium`,
  with the prefix left in. Sent messages from the last two weeks:
  - `critical risk. masked individual moving quickly through the courtyard at night...`, sent at `medium`
  - `high risk. a person is obscuring the driveway camera lens...`, sent at `medium`
  - `medium risk: unidentified car at the pend entrance at night...`, sent at `medium`
- **Lower-casing the whole message loses names**, such as `Ramzi` and number plates.
- **Not every prompt follows the risk scheme.** The live install's `object_prompts.bird` starts with
  `BIRD IDENTIFIED` or `UNKNOWN BIRD`. Two thirds of the descriptions sent were birds, all at `medium`. A risk
  regex can't cover these; rules for each prompt can.
- **Frigate already has a structured threat level.** Review summaries have `potential_threat_level` in the
  review's `data.metadata`, set by Frigate's own `activity_context_prompt`, which the live install has customised.
  It's a number, so there's nothing to parse and no prompt wording to depend on. The first draft didn't use it.
- **Faces, plates and classifications are already structured too.** `tracked_object_update` can also carry `face`,
  `lpr` and `classification` messages, though none were sent in 30 days on the live install. Faces and plates
  already reach the camera entries as review `sub_labels`, so they need nothing new.

## Evidence from 30 days of MQTT

From the MQTT messages archive, to 6 November 2026.

| Message | Count |
|---------|-------|
| `frigate/reviews` `new` | 397 |
| `frigate/reviews` `update` | 86 |
| `frigate/reviews` `end` | 410 |
| `frigate/reviews` `genai` | 131 |
| `frigate/tracked_object_update` `description` | 228 |

- **Review summaries rarely raise the level.** Of 131, 129 were level 0 and 2 were level 1, with none at level 2.
  One of the two level 1s was the resident walking to the barn.
- **Descriptions were mostly no risk.** By first words: 171 `NO RISK`, 32 `LOW RISK`, 5 `MEDIUM RISK`, 3
  `HIGH RISK`, 16 `BIRD IDENTIFIED` and 1 `UNKNOWN BIRD`. Each tracked object got one description, never two.
- **The two sources disagree.** A description is matched to its review summary through the summary's
  `data.detections`, and 158 of the 228 had one. Each `MEDIUM` or `HIGH` description that had one was level 0 in
  the summary, and the summary's title usually explains it:
  - `HIGH RISK. A person is obscuring the driveway camera lens...`, against *Cleaning a security camera in the
    driveway*
  - `HIGH RISK. Two unidentified men in hoodies...`, against *Daytime delivery and item exchange in the courtyard*
  - `MEDIUM RISK. Unmarked white van with a man in...`, against *Daytime Package Delivery*

  A summary sees the whole review, every object in it and Frigate's activity context, while a description sees one
  object's snapshot. Here the summaries were the better judge, but three night-time `MEDIUM` descriptions had no
  summary at all.
- **Summaries stop when the GenAI tokens run out.** Every review is meant to get one, so a review without a summary
  is the usual case once the quota is used up, not a setting. 70 of the 228 descriptions had none.
- **Descriptions and reviews come in either order.** On 5 November from 17:55 to 17:56, four descriptions came
  15 to 31 seconds after their reviews had started, with the reviews already ended and no summary to follow. At
  other times the description comes before the review's messages. So neither can wait for the other, and a
  description often has no summary to be judged against.
- **Descriptions link to reviews by object ID, but not one to one.** A description's `id` (the same as its
  `event_id`) is a tracked object's ID, and reviews list their objects' IDs in `data.detections`. Over 31 days:
  - 238 of 247 descriptions were in some review's `detections`, always one on the same camera.
  - A review has one description for each of its objects, so it can have several: 162 reviews had a described
    object, and 139 had every object described.
  - An object can be in more than one review. Three were in two or three, once 19 hours apart, as a parked car is.
  - 9 descriptions, all from the doorbell, were in no review at all. The doorbell's alerts need the `pend_entrance`,
    `driveway_top` or `pend` zones, and object descriptions have no such filter, so Frigate described objects it had
    decided weren't worth a review. All 9 were `NO RISK` or `LOW RISK`.
  - A review's `detections` grow as objects join it, so an early `new` message can lack an object that a later
    `update` or `end` lists.
- **`other_concerns` are not threats in themselves.** *Visitors entering barn* came with level 0 each time.

## Frigate features used

From Frigate 0.18.2 and the Frigate integration 5.15.6 on the live install, with the MQTT messages checked against archive.

### Review summaries

Config: `review.genai`, globally or for each camera, with `enabled`, `alerts`, `detections`, `additional_concerns`,
`activity_context_prompt` and `image_source`.

When Frigate finishes a review summary, it stores it in the review's `data.metadata`. A real one, abridged:

```json
{
  "title": "Bird foraging in the turning circle",
  "shortSummary": "A single bird is observed foraging on the gravel at the edge of the turning circle during the early morning hours.",
  "scene": "The sequence begins at 07:52 AM on a Friday...",
  "observations": ["At the start of the sequence, a bird is visible...", "..."],
  "confidence": 1.0,
  "potential_threat_level": 0,
  "other_concerns": null,
  "time": "Friday, 07:52 AM"
}
```

- **`potential_threat_level`**: 0 normal, 1 suspicious, 2 critical, as Frigate's default activity context prompt
  defines them. A customised prompt can redefine what each level means, but the numbers stay the same.
- **`other_concerns`**: those of the `additional_concerns` the model saw, such as *packages left at front door*.
- **Delivery**: a further `{prefix}/reviews` message with `type` `genai`, after the review's `end`, with the
  summary in `after.data.metadata`, and `before` the same review without one. Frigate generates summaries for
  alerts and, where `review.genai.detections` is on, detections, for as long as the GenAI provider's tokens last.

### Object descriptions

Config: `objects.genai`, with `enabled`, `prompt`, `object_prompts` for each label, `objects`, `required_zones` and
`send_triggers`.

Each one is sent on `{prefix}/tracked_object_update` as
`{"type": "description", "id": ..., "camera": ..., "description": ...}`, with no label. The `id` is the tracked
object's, so the notification proxy serves its `snapshot.jpg` and `{camera}/master.m3u8`, as it does for a review's
detections. It's also how a description is matched to the review it's part of, through the review's
`data.detections`.

## Design

Both sources go on the existing camera and zone entries. A summary is about a review those entries track, by its
review ID. A description is about a tracked object, which is usually, but not always, one of a tracked review's
detections, and may come before or after that review's messages. So there's no new entry, discovery or device, and
descriptions are handled whether or not their review is known.

### Threat level priorities

Each threat level maps to a Supernotify priority, set for each camera or zone:

| Threat level | Meaning | Default priority |
|--------------|---------|------------------|
| 0 | Normal | `medium` |
| 1 | Suspicious | `high` |
| 2 | Critical | `critical` |

### Review summaries

- **Tracker**: a `genai` message for a tracked review gives a `Decision` with a new `Reason.SUMMARY`. An ended
  review is kept for a while, *Wait for GenAI*, so its summary still finds it.
- **Notification**: an update of the review's notification, with the same tag, so it replaces the first one:
  - title: the summary's `title`
  - message: its `shortSummary`, followed by any `other_concerns`
  - priority: the threat level's, in place of the alert or detection priority
  - same snapshot and HLS tap as now
- **Lowest threat level**: summaries below it are not sent. At 0, the default, every summary is an update, so the
  notification ends up with Frigate's own title and summary. At 1, only suspicious or worse.
- **Without a summary**: when the tokens have run out, the review's own notification, or its description, stands.

### Object descriptions

- **Subscription**: `{prefix}/tracked_object_update`, through the shared MQTT hub, as for reviews. Only
  `description` messages are used.
- **Linking**: by the description's `id` being in a tracked review's latest `detections`, on the same camera. Where
  several reviews have it, the most recent one, since an object that stays put, such as a parked car, turns up in
  later reviews too. The review ID stays the notification's key, so a review's descriptions, however many, and its
  summary all update the same notification.
- **When the review is already known**: the description is an update of the review's notification, as a summary is,
  with its message after rules, and its priority from rules or else the review's own. This includes a review that
  has ended but is still kept for *Wait for GenAI*.
- **When it's not**: the description is dropped, unless *Descriptions without a review* is on. In the evidence,
  these were objects outside the zones the camera's alerts require, which Frigate chose not to review, and all were
  no or low risk, and they'd skip the camera's object, zone and severity filters. With it on, the description is
  notified by itself, for a camera entry whose camera it's from, tagged
  `frigate_object_{id}`, with the object's snapshot and HLS link. Zone entries can't tell which zone an object was
  in from a description, so they only take descriptions of reviews they already know. Descriptions are kept by
  object ID for *Wait for GenAI*.
- **When the review comes after**: a review with a detection already described takes over that notification. It's
  sent with the description's tag and the description as its message, so the phone shows one notification, and the
  richer text, rather than two.
- **When the summary comes after**: it replaces the description, with its threat level's priority. Frigate's
  whole-review judgement wins over a single object's, as the evidence above suggests it should.
- **When there's no summary**: the description stands, so a night-time `MEDIUM RISK` is still sent at the priority
  its rules give it.

### Settings

A new collapsed *GenAI* section, on each camera and zone entry, shown only when the Frigate server has review
summaries or object descriptions on:

- *Review summaries*: on by default, where Frigate has them on for the camera
- *Lowest threat level*: 0, 1 or 2, default 0
- *Normal*, *Suspicious* and *Critical*: the priority for each threat level, defaulting to `medium`, `high` and
  `critical`
- *Object descriptions*: on by default, where Frigate has them on for the camera
- *Wait for GenAI*: how long an ended review, or a description with no review yet, is kept, default 120 seconds
- *Descriptions without a review*: off by default, for cameras only

### Rules, for any source

Rules match a notification's message and change how it's sent. They apply to every notification, whatever its
source: a review's own message, a summary or a description.

- **Kept as subentries of the discovery entry**, so each is added, changed and removed in the UI, with no YAML.
- **Each rule has**:
  - a name
  - a match: *starts with*, *contains* or *regular expression*, always case-insensitive
  - what it does, any of:
    - set the priority, to one of Supernotify's `critical`, `high`, `medium`, `low` or `minimum`
    - silence the notification, so it's not sent
    - apply Supernotify scenarios (`apply_scenarios`), chosen from those Supernotify has
    - remove the matched text from the message
- **When several match**: silence wins, then the highest priority, and scenarios are combined. So order doesn't
  matter, and no ordering UI is needed.
- **Tidying**: after text is removed, leading punctuation and spaces go, and the first letter is capitalised. The
  message is never lower-cased.
- **Silent updates stay silent, unless raised**: with `alert_once`, an update is sent at `low`, unless it's a
  summary at threat level 1 or more, or a rule gives it a higher priority than the review's own.
- **A summary's threat level comes first**: a rule's priority applies to a summary only when it's higher than the
  threat level gives. Silence and scenarios apply as usual.

### Without Supernotify

Rules still silence notifications and remove text. Priority and scenarios have nothing to apply to.

## Documentation

Its own page, *GenAI notifications*, with:

- turning on review summaries in Frigate, and the threat level settings
- why summaries are preferred to descriptions, from the evidence above
- suggested `additional_concerns`
- a suggested object description prompt prefix, and the rules that go with it:

| Rule | Match | Does |
|------|-------|------|
| Critical risk | regular expression `^critical risk\W*` | priority `critical`, remove match |
| High risk | regular expression `^high risk\W*` | priority `high`, remove match |
| Medium risk | regular expression `^medium risk\W*` | priority `medium`, remove match |
| No or low risk | regular expression `^(no\|low) risk\b` | silence |
| Unclear | regular expression `^(unclear\|unknown\|uncertain)\b` | silence |
| Birds | starts with `bird identified` | priority `minimum`, remove match |

- moving from the example automation below

## Out of scope

- Frigate's GenAI chat, and `async_review_summarize` on demand
- Notifying on `face`, `lpr` or `classification` messages by themselves, which reviews already cover through
  sub-labels
- Rules that match anything but the message, such as camera, label or time; Supernotify's scenarios and conditions
  already cover those

## Example Prompt

This prefix comes from the live Frigate install, and is followed by a detailed description of the property, cameras
and occupants.

```jinja2
Analyze the {label} in these images from the {camera} security
camera. Begin the summary with the risk level in upper case, one of NO
RISK, LOW RISK, MEDIUM RISK, HIGH RISK or CRITICAL RISK. The summary will
be read out on an Alexa device so keep it short. Focus on the actions,
behavior, and potential intent of the {label}, rather than just describing
its appearance.
```

## Example Automation

As on the live install. Its priority never matches, as described in the review above.

```yaml
alias: Frigate GenAI Alerts
description: ''
triggers:
  - trigger: mqtt
    topic: frigate/tracked_object_update
    value_template: '{{ value_json.type }}'
    payload: description
conditions:
  - condition: template
    value_template: >-
      {{trigger.payload_json is defined and not
      trigger.payload_json.description.startswith('LOW') and not
      trigger.payload_json.description.startswith('NO RISK') and not
      trigger.payload_json.description.startswith('UNCLEAR') and not
      trigger.payload_json.description.startswith('UNKNOWN') and not
      trigger.payload_json.description.startswith('UNCERTAIN')}}
actions:
  - action: supernotify.notify
    metadata: {}
    data:
      message: >-
        {% set description = trigger.payload_json.description %} {{ description
        | regex_replace('^(\w+)\s+RISK\s+','',ignorecase=True) | lower}}
      title: Update on activity at {{trigger.payload_json.camera}}
      priority: >-
        {% set regex = "(\w+)\s+RISK\s+.*" %} {% set description =
        trigger.payload_json.description %} {% if description is
        match(regex,ignorecase=True) %} {{ description |
        regex_findall_index(regex,ignorecase=True) | lower}} {% else %} medium
        {% endif %}
      media:
        snapshot_url: http://192.168.1.100:8123/api/frigate/notifications/{{trigger.payload_json.id}}/thumbnail.jpg
        camera_entity_id: camera.{{trigger.payload_json.camera}}
mode: single
```
