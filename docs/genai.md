---
description: Notifications from what Frigate's generative AI says about a review, by its threat level, and rules to set the priority of any notification by what it says.
---
# GenAI Notifications

Frigate can have a generative AI model look at what its cameras saw. Camera AutoNotify uses what comes back to
update the review's notification, so the phone ends up with a short account of what happened rather than only
"Person detected".

Frigate has two GenAI features, and both are used if Frigate has them on:

| Feature | Frigate setting | What it gives |
|---------|-----------------|---------------|
| Review summaries | `review.genai` | A title, a short summary and a **threat level** for the whole review, once it's over |
| Object descriptions | `objects.genai` | A description of each object tracked, written as the prompt asks |

Nothing needs setting up in Home Assistant beyond Frigate itself. The *GenAI* section of a camera's or zone's
settings appears once Frigate has either feature on for it.

## Review Summaries

A review summary takes the place of the review's notification once the review is over. Its title becomes the
notification's title, and its short summary the message, followed by any of the camera's `additional_concerns`
that were seen.

The priority comes from the summary's threat level:

| Threat level | Meaning | Priority, by default |
|--------------|---------|----------------------|
| 0 | Normal | `medium` |
| 1 | Suspicious | `high` |
| 2 | Critical | `critical` |

What counts as suspicious or critical is Frigate's to decide, through its `activity_context_prompt`, which can be
written for your own property. The priority for each level can be changed in the *GenAI* settings, and *Lowest
threat level* leaves out summaries below the one chosen.

With *Sound only the first* on, a summary at level 0 replaces the notification silently, while a summary at level 1
or 2 sounds, since it says something more urgent than the review did.

Summaries stop when the model's tokens run out, so a review may not get one. Its notification then stays as it was,
or as its descriptions left it.

## Object Descriptions

A description is of one object, the person or car, so a review can have several. Each takes the place of the
review's notification as it comes, whether it comes before the review's own messages or after the review has
ended, for as long as *Wait for GenAI* allows. A summary that follows takes the place of the descriptions.

A description has no structure, so its priority can only come from what the prompt asks the model to write, and a
[rule](#rules) to read it. A description that starts with the risk level makes that easy.

Frigate also describes objects it didn't make a review of, such as a person outside the zones a camera's alerts
need. These are left out, since Frigate decided they weren't worth reviewing, unless *Descriptions without a review*
is switched on for the camera. Zones never have these, since a description doesn't say which zone the object was
in.

### A Prompt to Start From

Start the object prompt in Frigate's `objects.genai.prompt` with this, then describe the property, the cameras and
who is usually around:

```text
Analyze the {label} in these images from the {camera} security camera. Begin the summary with the risk level in
upper case, one of NO RISK, LOW RISK, MEDIUM RISK, HIGH RISK or CRITICAL RISK. Keep it short. Focus on the actions,
behavior, and potential intent of the {label}, rather than just describing its appearance.
```

## Rules

Rules change how any notification is sent, by what its message says, whether it's a summary or a description, or the
title, such as "Person detected at Barn Door", of a notification with nothing more to say. They're added under *Global Settings*, on the integration's page, with *Add rule*.

Each rule looks for some text in the message, ignoring case, by *Starts with*, *Contains* or a *Regular expression*,
and can then do any of these:

- send at a chosen priority
- silence the notification, so it's not sent at all
- apply Supernotify scenarios
- remove the text it matched from the message, such as a risk level at its start

Every rule that matches applies, so their order doesn't matter. Silence wins over everything else, the most urgent
priority of those that match is used, and their scenarios are combined. A rule can raise a summary's priority, but
never lower it below what its threat level gives.

### Rules for the Suggested Prompt

| Name | Match | Text | Does |
|------|-------|------|------|
| Critical risk | Regular expression | `^critical risk\W*` | Priority critical, remove the text matched |
| High risk | Regular expression | `^high risk\W*` | Priority high, remove the text matched |
| Medium risk | Regular expression | `^medium risk\W*` | Priority medium, remove the text matched |
| No or low risk | Regular expression | `^(no\|low) risk\b` | Silence |
| Unclear | Regular expression | `^(unclear\|unknown\|uncertain)\b` | Silence |

The `\W*` takes whatever the model puts after the risk level, a full stop, a colon or a space, so "MEDIUM RISK. A
person in green..." is sent at `medium` as "A person in green...".

A prompt for a particular object, in Frigate's `object_prompts`, can start its own way, and have its own rule. For
birds, say:

| Name | Match | Text | Does |
|------|-------|------|------|
| Birds | Starts with | `bird identified` | Priority minimum, remove the text matched |

## Moving From an Automation

An automation on `frigate/tracked_object_update` that reads the risk level with a template can be replaced by the
rules above. Switch it off once they're in place, or each description will be notified twice.

Check its regular expression if it has one: `(\w+)\s+RISK\s+` doesn't match "MEDIUM RISK." or "MEDIUM RISK:", since
it needs a space straight after `RISK`, so every description it sends goes at the same priority.
