---
description: Notifications from what Frigate's generative AI says about a review, by its threat level, reports of the day or of anything suspicious every few hours, and rules to set the priority of any notification by what it says.
---
# GenAI Notifications

Frigate can have a generative AI model look at what its cameras saw. Camera AutoNotify uses what comes back to update the review's notification, so the phone ends up with a short account of what happened rather than only
"Person detected".

Frigate has two GenAI features, and both are used if Frigate has them on:

| Feature | Frigate setting | What it gives |
|---------|-----------------|---------------|
| Review summaries | `review.genai` | A title, a short summary and a **threat level** for the whole review, once it's over |
| Object descriptions | `objects.genai` | A description of each object tracked, written as the prompt asks |

Nothing needs setting up in Home Assistant beyond Frigate itself. The *GenAI* section of a camera's or zone's
settings appears once Frigate has either feature on for it.

## Review Summaries

A review summary takes the place of the review's notification once the review is over. Its title becomes the notification's title, and its short summary the message, followed by any of the camera's `additional_concerns` that were seen.

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

A review may not get a summary, if Frigate's GenAI doesn't make one for it. Its notification then stays as it was,
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

## Periodic Reports

Frigate's GenAI can also write a report of everything its cameras saw over a period, from the reviews in it, as the
`frigate.review_summarize` action does. Camera AutoNotify sends one once a day to begin with, a little after
midnight, of the day before, titled such as "Frigate report for Tuesday 10 November". It can instead be sent every
few hours, and kept for when something in those hours was worth worrying about, as a regular check for suspicious
activity. The Frigate server's name is in the title too when there's more than one.

A report is too long for a phone's notification or a voice assistant, so it needs
[Supernotify](https://supernotify.rhizomatics.org.uk), and goes by e-mail unless you choose otherwise. Without
Supernotify it isn't sent, and its section of *Global Settings* only says Supernotify is needed to switch it on.

It's in the *Frigate GenAI Periodic Report* section of *Global Settings*:

| Setting | Default | What it does |
|---------|---------|--------------|
| Send a report | Automatic | *Automatic* sends it once Frigate makes review summaries, `review.genai`, for any camera, or a review summary came over MQTT in the hours summarised. *On* always tries, and *Off* never does |
| How often | Once a day | Every 1, 2, 3, 4, 6, 8 or 12 hours, or once a day. Each report covers the hours since the one before, up to the hour it's sent in |
| Starting at | 00:05 | When the first of the day is sent, and the others every so many hours from it |
| Only when there's a concern | Off | Only send it when GenAI gave one of the reviews in those hours a threat level of suspicious or critical, or noted other concerns |
| Deliveries | Supernotify's e-mail delivery | Choose others to send it by instead, such as Telegram. Left empty, it goes by Supernotify's e-mail delivery, the one called `email` if there's more than one, such as one for HTML too, so it's only sent once, and isn't sent at all if Supernotify has none, which Global Settings warns of when saved |

Frigate is asked for the report every time it's due, whatever reviews came over MQTT. Whether it's then sent, with
*Only when there's a concern* on, is read from the threat level and other concerns Frigate's GenAI already gave each
review in those hours. Each report goes at `medium` priority, and rules apply to it as to
any other notification. Frigate needs to be 0.17 or later.

### Two Ways to Use It

**A daily account, always sent.** Leave *How often* at once a day and *Only when there's a concern* off, and choose
an e-mail delivery. Every morning there's a report of the day before, worrying or not, to read when convenient.
Choose a later *Starting at* to have it arrive later in the morning, such as 08:30, and each report then covers
08:00 to 08:00.

| How often | Starting at | Only when there's a concern | Deliveries |
|-----------|-------------|-----------------------------|------------|
| Once a day | 00:05 | Off | `email` |

**A regular check that only speaks up when needed.** Set *How often* to every 4 hours, say, and switch on *Only when
there's a concern*, with a delivery that's seen sooner than e-mail, such as Telegram. Most of the time nothing is
sent, and when something suspicious was seen, the report puts it in the context of everything else in those hours,
such as a delivery van on another camera at the same time.

| How often | Starting at | Only when there's a concern | Deliveries |
|-----------|-------------|-----------------------------|------------|
| Every 4 hours | 00:05 | On | `telegram` |

Only one of these can be set at a time. The review's own notification already says when GenAI finds something
suspicious as it happens, so the regular check suits keeping a record that's easier to read, or being told by a
delivery the review notifications don't go to.

!!! tip "Keeping the reports in a file"
    To keep each report on Home Assistant's file system, as well as or instead of e-mailing it, set up the
    [File](https://www.home-assistant.io/integrations/file/#notifications) integration's notifications, which give a
    notify entity that adds each message to a file. Supernotify supports notify entities directly, so make a delivery
    for it, and choose that delivery in *Deliveries*, with the e-mail delivery too if both are wanted.

!!! note "Your GenAI provider"
    Every report is written by the GenAI provider Frigate is set up with, as each review's own summary is, so it's
    subject to whatever that provider charges or limits, and a report every hour or two asks for more of them than
    one a day. See Frigate's [GenAI configuration](https://docs.frigate.video/configuration/genai/genai_config) and [review summaries](https://docs.frigate.video/configuration/genai/genai_review). A report Frigate can't
    write is logged as a warning, and nothing is sent. If reports are missing, see Frigate's
    [How do I debug GenAI issues?](https://docs.frigate.video/configuration/genai/genai_config#how-do-i-debug-genai-issues).

!!! tip "Reports in your own language"
    Frigate writes its summaries in English unless its `review.genai.preferred_language` is set, such as to
    `Spanish`, which applies both to each review's summary and to these reports of the hours before. See Frigate's
    [Preferred Language](https://docs.frigate.video/configuration/genai/genai_review/#preferred-language).

### Moving From an Automation

An automation that calls `frigate.review_summarize` each night and sends what it answers can be switched off once
the report is set up, with its deliveries chosen, or the report will be sent twice.

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
