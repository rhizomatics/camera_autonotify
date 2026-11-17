# RFC 0005 Rules

**Status**: Ready for Review
2026-11-13, nothing yet to build. 2026-11-17, matching what's recognised moved here from
[RFC 0004](rfc0004_richer_frigate.md), and rules rebuilt on Home Assistant's own conditions, staying in Camera
AutoNotify rather than moving to Supernotify, and limited to classifying the event, with routing left to Supernotify

## Summary

Rules classify a camera event before it's notified: how important it is, whether it's worth notifying at all, and
what kind of event it is, as tags such as `unknown_vehicle` or `delivery`, which for now are Supernotify scenario
names. They match the notification's text, and
everything Camera AutoNotify knows of the event behind it, such as the object, who or what was recognised, or the
speed.

Rules never route. Who's told, by which deliveries, and how that changes with who's home or the alarm, is
Supernotify's, by its scenarios, which a rule's tags select.

Rules are built on Home Assistant's own conditions and templates, so there's nothing new to learn, and set up in a
form. A **simple** rule is a few fields for the common case, such as one word to look for. An **advanced** rule is
any Home Assistant condition, for anything else.

## Motivation

Frigate alerts can be many, varied and noisy. One way of handling that is Supernotify scenarios using regular
expressions on `notification_message` in conditions to override priority, delivery method (e.g. mobile only, not
email) based on the text. This is especially useful for bird recognition or GenAI, so that these messages are low
priority, or switched off (e.g. for boring birds).

Text is only part of it. Camera AutoNotify knows much more of each event than ends up in the message: the object,
the zones, who or what Frigate recognised and how sure it was, what it didn't recognise, the speed, the state of a
gate ([RFC 0004](rfc0004_richer_frigate.md)). That's camera domain data, richer than Supernotify should be given to
hold for every source, so rules that use it belong where it is, by the [design principles](../design_principles.md).

## Design goals

- **Nothing new to learn**: Home Assistant's own conditions, its condition editor, and Jinja templates, as in
  automations, with the same names for the notification's own variables as Supernotify's scenarios use
- **Simple needs stay simple**: silencing on one word, or raising the priority of a person at night, takes a few
  fields in a form, with no template or YAML
- **Full flexibility when it's needed**: anything a Home Assistant condition can say, over everything Camera
  AutoNotify knows of the event, and anything else in Home Assistant
- **The form is the way**: every rule is made, changed and understood in the integration's own config flow, not in
  YAML
- **One way to behave**: simple and advanced rules combine, and act, the same, so moving from one to the other
  changes nothing else
- **Explained**: which rules matched, and what they changed, shows in diagnostics and debug logs
- **Classify, don't route**: rules say what the event is, and scenarios where it goes, so each has one job
- **Help people keep the two apart**: in practice the line gets blurred, so the form, the checks and the docs steer
  towards the split, and show where it's crossed, rather than leaving a tangle to be found later

## Where it's done today

| Where | Matches | Can do | Applies to |
|-------|---------|--------|------------|
| Supernotify scenario conditions | Any Home Assistant condition, so a template with a regular expression on `notification_message` or `notification_title` | Priority, deliveries, and anything else a scenario changes | Every notification, from any source |
| Camera AutoNotify [rules](https://camera-autonotify.rhizomatics.org.uk/genai/#rules) | The message, or the headline when there's nothing more, by starts with, contains or regular expression, ignoring case | Priority, silence, remove the text matched, apply scenarios | Camera AutoNotify's own notifications only |

### What's awkward

- **Scope**: a scenario sees every notification, so a pattern meant for one source can match another that happens
  to use the same words
- **Effort**: a scenario condition is YAML and a template, where a rule is a form
- **Two places**: with both in use, it's not obvious which one decided a notification's priority
- **Wording**: text matching depends on how a headline is phrased, or what a model chose to write, so a change of
  wording, or of language with translations, quietly stops a pattern matching
- **Text only**: a rule today can't say "a car", "not recognised" or "after dark", only what the words say

## Rules and scenarios

Both use Home Assistant's conditions, but they're not the same thing, and neither replaces the other:

| | Camera AutoNotify rules | Supernotify scenarios |
|---|---|---|
| Decide | What the event is: how important, whether worth notifying, what kind, as tags | Where it goes: which deliveries, to whom, how loudly, by who's home or the alarm |
| Know | The notification, and the camera event behind it, as variables | The notification, its tags, and the house: occupancy, people, the alarm |
| Apply to | Camera AutoNotify's own notifications | Every notification, from any source |
| Run | Before the notification is sent | As Supernotify delivers it |

So for an unknown car at night: a rule matches a car, not recognised, after dark, and gives it `high` priority and
the tag `unknown_vehicle`. That tag selects the `security` scenario, which with the alarm set makes it `critical`,
to everyone's phone and the speakers, and with someone home, only their phone. The camera's domain data stays in
Camera AutoNotify, and only what's decided, the priority and tags, goes on to Supernotify.

Rules have no *Targets* or *Deliveries*, and no condition on who's home or the alarm. A camera or zone's own
*Targets* and *Deliveries* in its settings are where its notifications go to begin with, before scenarios, and stay
as they are.

## Design

### Rule types

| Type | For | Made of |
|------|-----|---------|
| Simple | The common cases: a word in the message, or what was seen and recognised | A few fields, each optional, all of those filled in needing to match |
| Advanced | Anything else | Home Assistant conditions, in its condition editor |

#### Simple rules

Today's rules, with the recognition fields of [Matching what's recognised](#matching-whats-recognised) beside the
text:

- **Text**: starts with, contains, or regular expression, always ignoring case, on the message, or the title when
  there's no message
- **Object**: one or more of the objects Frigate tracks, such as `car` or `bird`
- **Recognised as**: one of a chosen list of names, anything else, or nothing recognised
- **Severity**: alerts, detections, or either

A rule of only a word, `boring`, or only an object and *nothing recognised*, takes a single field or two. A simple
rule is turned into a condition when it's loaded, the same as an advanced rule is made of, so it behaves exactly the
same, and can be turned into an advanced rule in its form, showing the condition it was, as a start for more.

#### Advanced rules

Home Assistant conditions, edited with Home Assistant's own condition editor, the `ConditionSelector`, as in an
automation: `and`, `or` and `not`, time, sun, and template conditions, which see the notification and its event as
variables. So "a person not recognised, after dark" is two conditions anyone who writes automations already knows,
and a template covers the rest:

```yaml
condition: template
value_template: >
  {{ event.object == 'car' and not event.recognised and event.speed > 40 }}
```

### Variables

Given to every condition, simple or advanced, as `variables` when it's checked:

| Variable | What it is |
|----------|------------|
| `notification_title`, `notification_message`, `notification_priority` | As Supernotify's scenarios call them, the priority as set before rules |
| `event.camera`, `event.zones`, `event.severity` | The review's camera, zones entered in order, and `alert` or `detection` |
| `event.objects`, `event.object` | What was seen, and the first of it |
| `event.recognised`, `event.names` | Whether anything was recognised, and the names, from sub labels, faces and plates, or from anpr2mqtt once [RFC 0003](rfc0003_anpr2mqtt.md) is built |
| `event.face_unknown`, `event.plates`, `event.speed`, `event.attributes`, `event.states` | The facts of [RFC 0004](rfc0004_richer_frigate.md), such as a plate read that's not known, or a gate open |
| `event.threat_level` | GenAI's threat level, where it summarised the review |
| `event.profile` | Frigate's active profile, from `{prefix}/profile/state`, or `none` for its base config, where Frigate has profiles |
| `event.genai` | Whether the notification is what GenAI added, a summary or a description |

Time of day is part of what an event is, a car at 3am meaning something different from one at 3pm, so time and sun
conditions belong in rules. So, in the same way, does the house's state where it changes what the event means, and
the camera domain's own view of that is **Frigate's profile**: Frigate watches differently when the house is empty,
and [Auto Arm](https://autoarm.rhizomatics.org.uk/configuration/frigate/) switches the profile from the alarm's
state, so `event.profile == 'armed_away'` says the house is empty in Frigate's own terms, without a rule reading the
alarm or who's home itself.

The names of `event`'s variables are kept stable once released, since rules are written against them, and named
for cameras rather than Frigate, so the same rule works whichever camera source the event came from.

### Then

What a rule gives, for both types, all about the event, none about where it goes:

- **Priority**: how important the event is, raised or set, never below a floor a source set from a fact, such as a
  threat level. Scenarios can still raise it further, such as to `critical` with the alarm set
- **Silence**: not worth notifying at all, such as a bird seen every day
- **Tags**: what kind of event it is, such as `unknown_vehicle`, `delivery` or `wildlife`, as Supernotify scenario
  names, chosen from Supernotify's scenarios or typed
- **Remove the text matched**: simple rules with *Text* only, such as a risk level at the start of a GenAI summary,
  since a condition has no text it matched

### Tags are scenarios, for now

Rather than get ahead of Supernotify with a tag of its own, a tag is a Supernotify scenario name, sent by
`apply_scenarios`, as rules apply scenarios today. A scenario may in the end turn out to be a tag and a rule
together, but that's for Supernotify to settle, and until then nothing new is needed on either side:

- **A tag with a scenario**: the scenario applies, and says where the notification goes, as now
- **A tag without one**: Supernotify ignores an unknown name in `apply_scenarios`, logging it at debug only, rather
  than rejecting the notification. So a rule can give `unknown_vehicle` before anyone has made a scenario of that
  name, though there's little point until someone does
- **Seen by other scenarios**: Supernotify's `applied_scenarios` condition variable holds every name asked for, those
  it doesn't have included, so another scenario's condition can test `'unknown_vehicle' in applied_scenarios`, with
  no change to Supernotify

So there's no *Tags* section to set up, and no separate mapping: the rule's *Tags* are the scenario names. Today's
rules already apply scenarios, so they carry on unchanged, with nothing to migrate. If Supernotify later gives tags a
field of their own, *Tags* moves to it, and the names stay the same.

### Combining

Every rule that matches applies, so order doesn't matter. Silence wins, then the most urgent priority, and the
scenarios of all of them are combined. A rule whose condition can't be checked, such as a template that fails, is
taken as not matching, and logged.

### The form

Rules stay subentries of *Global Settings*, as now. *Add rule* first asks which type:

- **Simple**: one form, *Text*, *Object*, *Recognised as* and *Severity*, then *Priority*, *Silence*, *Tags* and
  *Remove the text matched*. The objects and names to choose from are read from Frigate, as *Object names* already
  reads its labels, with names typed for plates
- **Advanced**: Home Assistant's condition editor, then the same *Priority*, *Silence* and *Tags*. The conditions are
  checked when saved, with `async_validate_conditions_config`, so a mistake is shown in the form rather than found
  when a notification goes
- **Changing a rule**: its own type's form, with *Make advanced* on a simple rule, to carry on from the condition it
  was

Existing rules are simple rules, with *Text* as they have now, so nothing needs migrating.

## Keeping rules and scenarios apart

The split is clean on paper, and blurred in practice: a scenario that matches the message with a regular expression
is classifying, and a rule's condition on the alarm is routing. Neither is wrong in itself, but both together, for
the same thing, make a tangle that's hard to see into. So the integration helps people keep to the split, and see
where it's crossed:

- **The forms say which is which**: the rule form's description says it's for what the event is, not who's told, with
  a link to Supernotify's scenarios for that. *Tags* marks which names Supernotify has a scenario for, and which not
  yet
- **Warned, not blocked**: an advanced rule whose conditions test who's home, the alarm, people, device trackers or
  Supernotify's occupancy is saved, with a warning in the form that this is routing, better done in a scenario the
  rule's tag selects, or by Frigate's profile where it's what the event means. Blocking would only push it into a
  template
- **Shown together**: each notification's diagnostics and debug log say which rules matched, the priority and tags
  they gave, and which scenarios each tag selected, and Supernotify's archive then shows which scenarios applied and
  where it went. One notification can be followed from event to delivery
- **Tidiness checks**: in the [config health report](rfc0006_config_health_report.md), a tag Supernotify has no
  scenario for, which does nothing yet, and a Supernotify scenario whose condition matches `notification_message`
  with a pattern a rule already matches
- **Docs by example**: worked examples that show both halves, the rule and the scenario, for an unknown car at night,
  a boring bird, and a delivery, so the pattern is copied rather than reinvented

## Matching what's recognised

Recognition matters as much for **how urgent** a notification is as for what it says. Today the priority comes only
from the review's severity, a GenAI threat level, or a rule matching the message text.

- **Vehicles**: a known plate, the household's own car, can be quieter than usual, and an unknown one louder,
  especially at night or with the house empty
- **Birds**: a species seen every day can be `low` or silenced, and a rare or chosen one raised
- **Faces**: the same, a known face quieter, a person with no face recognised louder

On the live install this is done by Supernotify scenarios matching the message with a regular expression, for birds,
and for known people named in GenAI descriptions. That works only while the words do, and can't say that nothing was
recognised. With the simple rule's *Object* and *Recognised as*, each is two fields, night an advanced rule's
extra condition, or Frigate's profile, and who's told with the alarm set a scenario's, selected by the rule's
tag.

The facts come from the camera source, in a schema of the source's kind rather than of one product, so the same rule
works whoever recognised the car:

| Source | Gives |
|--------|-------|
| Frigate, through Camera AutoNotify ([RFC 0004](rfc0004_richer_frigate.md)) | The review's sub labels, the `face`, `lpr` and `classification` messages, including what wasn't recognised, with their scores, and the names Frigate knows, from `async_get_faces` and each classification model's classes, to choose from |
| anpr2mqtt ([RFC 0003](rfc0003_anpr2mqtt.md)) | A plate, and a name for a known target, which Frigate may know nothing of, as found on the live install |
| UniFi Protect, later | Its own face and plate recognition |

Confidence is Frigate's own: a face counts as recognised only at Frigate's `recognition_threshold`, as RFC 0004
already does, so a doubtful name isn't treated as certain, and needs no setting here. An advanced rule can still read
a score where it wants another threshold.

A GenAI description naming a known person follows from the sub label it was written with, where Frigate gave the
GenAI provider one, so it needn't be matched in the description's text, though matching the text stays possible.
Supernotify's scenarios then decide, as now, how it's delivered by who's home or whether the alarm is set, by the
rule's tags, without needing to know about birds or faces.

## Feasibility

- **The editor**: `ConditionSelector` is in Home Assistant's selectors, and works in a config flow, giving the same
  condition editor as automations
- **Checking**: `condition.async_validate_conditions_config` when saved, and `condition.async_conditions_from_config`
  when loaded, called with the variables above as each notification is sent, as Supernotify's scenarios already are
- **Cost**: a few conditions per notification, each cheap, the templates compiled once when the rule is loaded
- **Simple rules as conditions**: *Text* becomes a template using Home Assistant's own `search` or `match` tests,
  ignoring case, and *Object*, *Recognised as* and *Severity* plain comparisons, so there's one way of checking
  rules, not two

## Options

### A. Rules stay in Camera AutoNotify, on Home Assistant's conditions

As above. Each AutoNotifier that needs rules has its own, over its own domain data, all built on the same Home
Assistant conditions and variable names, so they're learnt once.

- Rules can use everything the source knows, and silencing works without Supernotify
- Configured per AutoNotifier, though each only for its own notifications, where the domain data is

### B. Rules move into Supernotify

Supernotify gains rules as a form, matching any notification's text, scoped by source, and the AutoNotifiers drop
theirs.

- One place for every notification's text
- Supernotify would need every source's domain data to match on it, which isn't Supernotify's to hold, or rules lose
  it and go back to text only. Silencing no longer works without Supernotify

## Recommendation

**A**:

1. Existing rules become simple rules, their *Scenarios* becoming *Tags*, unchanged
2. *Tags* taking names Supernotify has no scenario for yet, typed, as well as chosen
3. Simple rules gain *Object*, *Recognised as* and *Severity*, over RFC 0004's facts
4. Advanced rules, with Home Assistant's condition editor and the variables above, `event.profile` among them,
   warning of routing conditions
5. Simple rules turned into conditions when loaded, so both types are checked the same way, with *Make advanced*
6. Diagnostics following a notification from rules to tags to scenarios, and the tidiness checks in RFC 0006
7. Worked examples in the docs, each with both the rule and the scenario
8. Other AutoNotifiers that need rules take the same approach, with variables of their own domain

## Open questions

- **Source**: still worth sending on `supernotify.notify`, so Supernotify's archive can say where a notification came
  from (Supernotify #293), though no longer needed to scope rules there
- **Order with scenarios**: rules run before Supernotify sees the notification, so a scenario condition sees the
  priority a rule set. Confirm, and document it
- **What to call tags**: each of the obvious words is taken. Frigate's `label` is the object, Home Assistant's
  labels are what Supernotify targets by, and Supernotify's `tag` is the mobile push tag, which its snoozing also
  uses. While tags are scenario names, the form can call them *Scenarios*, as now, said to be what kind of event it
  is, which avoids the question until Supernotify settles what a tag is
- **The house's state**: time of day is settled as classification, and Frigate's profile brings the house's state
  in where it changes what the event means. Whether rules should also read Supernotify's occupancy directly, or
  the profile is enough, so the warning on routing conditions stays as it is
- **Priority**: treated as how important the event is, so a rule's, with scenarios free to raise it by the house's
  state. Whether that's clear enough in practice, or whether rules should give only tags, and leave priority to
  scenarios too
- **Removing text in advanced rules**: left out, since a condition has no text it matched. Whether that's missed, or
  better done as part of how the source words its own notifications
- **Names to choose from**: read from each source, as Frigate's faces and classes, or typed, as plates mostly are
- **Wording and translations**: *Text* matches what's sent, in Home Assistant's language, so a rule written for one
  language stops matching in another. *Object* and *Recognised as* don't depend on wording, which is one more reason
  to prefer them
- **Moving the live install over**: the scenario conditions for birds, and for known people in GenAI descriptions,
  as worked examples in the docs
