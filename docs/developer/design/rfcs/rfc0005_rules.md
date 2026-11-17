# RFC 0005 Rules

**Status**: Ready for Review
2026-11-13, nothing yet to build. 2026-11-17, matching what's recognised moved here from
[RFC 0004](rfc0004_richer_frigate.md), and rules rebuilt on Home Assistant's own conditions, staying in Camera
AutoNotify rather than moving to Supernotify

## Summary

Rules decide what a camera notification means before it's sent: its priority, whether it's sent at all, and which
Supernotify scenarios apply. They match the notification's text, and everything Camera AutoNotify knows of the
camera event behind it, such as the object, who or what was recognised, or the speed.

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
| Decide | What a camera notification means: how urgent, whether to send it, which scenarios apply | How a notification is delivered: which deliveries, to whom, by who's home or the alarm |
| Know | The notification, and the camera event behind it, as variables | The notification, and Supernotify's own state, such as occupancy |
| Apply to | Camera AutoNotify's own notifications | Every notification, from any source |
| Run | Before the notification is sent | As Supernotify delivers it |

A rule can apply scenarios, so the two work together: a rule says an unknown car at night is `high` and applies
`security`, and the `security` scenario decides who that reaches. The camera's domain data stays in Camera
AutoNotify, and only what's decided, the priority and scenarios, goes on to Supernotify.

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

Any Home Assistant condition, edited with Home Assistant's own condition editor, the `ConditionSelector`, as in an
automation: `and`, `or` and `not`, state, time, zone, sun, numeric state, and template conditions, which see the
notification and its event as variables. So "a person not recognised, after dark, with the alarm set" is three
conditions anyone who writes automations already knows, and a template covers the rest:

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
| `event.genai` | Whether the notification is what GenAI added, a summary or a description |

The names of `event`'s variables are kept stable once released, since rules are written against them, and named
for cameras rather than Frigate, so the same rule works whichever camera source the event came from.

### Then

As rules do today, for both types:

- **Priority**: raise or set it, never below a floor a source set from a fact, such as a threat level
- **Silence**: don't send it
- **Scenarios**: Supernotify scenarios to apply
- **Remove the text matched**: simple rules with *Text* only, such as a risk level at the start of a GenAI summary,
  since a condition has no text it matched

### Combining

Every rule that matches applies, so order doesn't matter. Silence wins, then the most urgent priority, and the
scenarios of all of them are combined. A rule whose condition can't be checked, such as a template that fails, is
taken as not matching, and logged.

### The form

Rules stay subentries of *Global Settings*, as now. *Add rule* first asks which type:

- **Simple**: one form, *Text*, *Object*, *Recognised as* and *Severity*, then *Priority*, *Silence*, *Remove the
  text matched* and *Scenarios*. The objects and names to choose from are read from Frigate, as *Object names*
  already reads its labels, with names typed for plates
- **Advanced**: Home Assistant's condition editor, then the same *Priority*, *Silence* and *Scenarios*. The
  conditions are checked when saved, with `async_validate_conditions_config`, so a mistake is shown in the form
  rather than found when a notification goes
- **Changing a rule**: its own type's form, with *Make advanced* on a simple rule, to carry on from the condition it
  was

Existing rules are simple rules, with *Text* as they have now, so nothing needs migrating.

## Matching what's recognised

Recognition matters as much for **how urgent** a notification is as for what it says. Today the priority comes only
from the review's severity, a GenAI threat level, or a rule matching the message text.

- **Vehicles**: a known plate, the household's own car, can be quieter than usual, and an unknown one louder,
  especially at night or with the house empty
- **Birds**: a species seen every day can be `low` or silenced, and a rare or chosen one raised
- **Faces**: the same, a known face quieter, a person with no face recognised louder

On the live install this is done by Supernotify scenarios matching the message with a regular expression, for birds,
and for known people named in GenAI descriptions. That works only while the words do, and can't say that nothing was
recognised. With the simple rule's *Object* and *Recognised as*, each is two fields, and night or the alarm an
advanced rule's extra condition.

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
Supernotify's scenarios then still decide, as now, how the priority is delivered by who's home or whether the alarm
is set, without needing to know about birds or faces.

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

1. Existing rules become simple rules, unchanged
2. Simple rules gain *Object*, *Recognised as* and *Severity*, over RFC 0004's facts
3. Advanced rules, with Home Assistant's condition editor and the variables above
4. Simple rules turned into conditions when loaded, so both types are checked the same way, with *Make advanced*
5. Worked examples in the docs: the live install's bird and known person scenario conditions as simple rules, and
   an unknown car at night as an advanced one
6. Other AutoNotifiers that need rules take the same approach, with variables of their own domain

## Open questions

- **Source**: still worth sending on `supernotify.notify`, so Supernotify's archive can say where a notification came
  from (Supernotify #293), though no longer needed to scope rules there
- **Order with scenarios**: rules run before Supernotify sees the notification, so a scenario condition sees the
  priority a rule set. Confirm, and document it
- **Advanced conditions and Supernotify**: whether an advanced rule's condition on `occupancy` should read
  Supernotify's, which only Supernotify knows, or be left to a scenario the rule applies
- **Removing text in advanced rules**: left out, since a condition has no text it matched. Whether that's missed, or
  better done as part of how the source words its own notifications
- **Names to choose from**: read from each source, as Frigate's faces and classes, or typed, as plates mostly are
- **Wording and translations**: *Text* matches what's sent, in Home Assistant's language, so a rule written for one
  language stops matching in another. *Object* and *Recognised as* don't depend on wording, which is one more reason
  to prefer them
- **Moving the live install over**: the scenario conditions for birds, and for known people in GenAI descriptions,
  as worked examples in the docs
