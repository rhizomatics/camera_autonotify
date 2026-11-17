# RFC 0005 Rules

**Status**: Ready for Review
2026-11-13, nothing yet to build. 2026-11-17, matching what's recognised moved here from
[RFC 0004](rfc0004_richer_frigate.md)

## Summary

Use text matching in camera events, and other info out of event details (including some normalized across event sources) to select notification priority, targets, drop notifications or select Supernotify scenarios.

## Motivation

Frigate alerts can be many, varied and noisy. One way of handling that is Supernotify scenarios using regular
expressions on `notification_message` in conditions to override priority, delivery method (e.g. mobile only, not
email) based on the text. This is especially useful for bird recognition or GenAI, so that these messages are low
priority, or switched off (e.g. for boring birds).

None of this is Frigate specific. Any source can send text worth matching: an appliance's message, a doorbell, an
LLM's summary, or a notification from an automation. So by the [design principles](../design_principles.md), text
matching isn't unique to any one domain, and this RFC decides where it lives and how it behaves.

Rules can also match what a source knows as a fact, such as the object, or who or what was recognised, and whether
something that could be recognised wasn't, as text can't say. Working out those facts is domain logic, done by the
source, such as Camera AutoNotify gathering them from Frigate in [RFC 0004](rfc0004_richer_frigate.md). Matching
them is the same as matching text, so it's here, in [Matching what's recognised](#matching-whats-recognised).

## Where it's done today

| Where | Matches | Can do | Applies to |
|-------|---------|--------|------------|
| Supernotify scenario conditions | Any Home Assistant condition, so a template with a regular expression on `notification_message` or `notification_title` | Priority, deliveries, and anything else a scenario changes | Every notification, from any source |
| Camera AutoNotify [rules](https://camera-autonotify.rhizomatics.org.uk/genai/#rules) | The message, or the headline when there's nothing more, by starts with, contains or regular expression, ignoring case | Priority, silence, remove the text matched, apply scenarios | Camera AutoNotify's own notifications only |

Rules were built for GenAI's risk levels ([RFC 0002](rfc0002_frigate_genai.md)), but `rules.py` has nothing camera
specific in it.

### What's awkward

- **Scope**: a scenario sees every notification, so a pattern meant for one source can match another that happens
  to use the same words
- **Effort**: a scenario condition is YAML and a template, where a rule is a form
- **Two places**: with both in use, it's not obvious which one decided a notification's priority
- **Wording**: text matching depends on how a headline is phrased, or what a model chose to write, so a change of
  wording, or of language with translations, quietly stops a pattern matching

## How text matching should behave

Wherever it's done, text matching behaves the same, so a rule can move between places without being rewritten, and
nobody has to learn two:

- **Match**: starts with, contains, or regular expression, always ignoring case
- **What's matched**: the message, or the title when there's no message
- **Combining**: every rule that matches applies, so order doesn't matter. Silence wins, then the most urgent
  priority, and the scenarios of all of them are combined
- **Floors**: a rule may raise a priority a source set from a fact, such as a threat level, but never lower it
  below that
- **Removing**: the text matched can be taken out of the message, such as a risk level at its start
- **Scope**: a rule matches only the notifications it was written for, those of the integration it's set up in,
  or of the sources it names
- **Explained**: which rules matched, and what they changed, shows in diagnostics, debug logs and Supernotify's
  archive
- **Same words**: the same names for each of these in every form

## Matching what's recognised

Recognition matters as much for **how urgent** a notification is as for what it says. Today the priority comes only
from the review's severity, a GenAI threat level, or a rule matching the message text.

- **Vehicles**: a known plate, the household's own car, can be quieter than usual, and an unknown one louder,
  especially at night or with the house empty
- **Birds**: a species seen every day can be `low` or silenced, and a rare or chosen one raised
- **Faces**: the same, a known face quieter, a person with no face recognised louder

On the live install this is done by Supernotify scenarios matching the message with a regular expression, for birds,
and for known people named in GenAI descriptions. That works only while the words do, and can't say that nothing was
recognised.

### Proposed

Rules match on what was recognised, as well as on the text:

- **What**: the object, such as `bird` or `car`
- **Recognised as**: one of a chosen list of names, such as faces, plates or bird species
- **Or**: recognised as anything else, or not recognised at all, for an object that can be recognised but wasn't
- **Confidence**: a score below which a name isn't taken as recognised, so a doubtful name isn't treated as certain
- **Then**: as rules already do, a priority, silence, or Supernotify scenarios

The facts come from the source, in a schema of the source's kind rather than of one product, so the same rule works
whoever recognised the car:

| Source | Gives |
|--------|-------|
| Frigate, through Camera AutoNotify ([RFC 0004](rfc0004_richer_frigate.md)) | The review's sub labels, the `face`, `lpr` and `classification` messages, including what wasn't recognised, with their scores, and the names Frigate knows, from `async_get_faces` and each classification model's classes, to choose from |
| anpr2mqtt ([RFC 0003](rfc0003_anpr2mqtt.md)) | A plate, and a name for a known target, which Frigate may know nothing of, as found on the live install |
| UniFi Protect, later | Its own face and plate recognition |

A GenAI description naming a known person follows from the sub label it was written with, where Frigate gave the
GenAI provider one, so it needn't be matched in the description's text, though matching the text stays possible.
Supernotify's scenarios then still decide, as now, how the priority is delivered by who's home or whether the alarm
is set, without needing to know about birds or faces.

Where these rules live follows the options below for text: in Camera AutoNotify's rules to begin with, and in
Supernotify's once it has rules, matching the facts passed in a notification's data, scoped by source.

## Options

### A. Each AutoNotifier keeps its own rules

`rules.py` is copied, as `compat.py` and `supernotify_api.py` already are.

- Scoped by where it's set up, and silencing works without Supernotify
- Configured in as many places as there are AutoNotifiers, still not available to other notifications, and against
  the design principles, since text matching isn't domain logic

### B. Rules move into Supernotify

Supernotify gains rules as a form, matching any notification's text, scoped by source, and the AutoNotifiers drop
theirs.

- One place for every notification, from any source, in place of regular expressions in scenario conditions, and in
  line with the design principles
- Needs each notification to say where it's from, and silencing no longer works without Supernotify

### C. Both, for a while

Supernotify gains rules, and each AutoNotifier keeps its own until they're there, with the same behaviour.

- Nothing is lost while Supernotify's rules are built
- Two places to look in the meantime

## Recommendation

**B**, reached by way of **C**:

1. Camera AutoNotify's rules stay as they are, already behaving as above
2. Supernotify gets rules of its own, as a form, scoped by source, as a Supernotify RFC
3. Camera AutoNotify says where each notification is from on its `supernotify.notify` call, so Supernotify's rules
   can be scoped to it
4. Once Supernotify's rules are released, Camera AutoNotify's rules are moved over, with a repair issue or a
   migration on upgrade, and dropped, keeping only what's domain logic, such as the floor set by a GenAI threat
   level
5. Other AutoNotifiers never get text rules of their own

Without Supernotify, a notification is plain text to every phone, so losing rules there costs little.

## Open questions

- **Source**: a field of its own on `supernotify.notify`, or a convention inside `data`, such as
  `data.source: camera_autonotify`
- **Moving rules over**: copied into Supernotify automatically on upgrade, or listed for the user to recreate
- **Removing text**: whether Supernotify's rules can change the message, as removing a risk level does, or whether
  that stays with the source, as part of how it words its own notifications
- **Order with scenarios**: whether a rule's priority is set before Supernotify evaluates scenario conditions, so a
  condition can see it. Confirm, and document it
- **Moving the live install over**: the scenario conditions for birds, and for known people in GenAI descriptions,
  as worked examples in the docs, moved to rules matching what's recognised once they're built
- **Facts schema**: the names of the facts passed on, shared by every camera source, decided with RFC 0004's
  enrichment, so a rule in Supernotify needn't know which source it came from
- **Names to choose from**: read from each source, as Frigate's faces and classes, or typed, as plates mostly are
