# RFC 0006 - Frigate Config Health Report

**Status**: draft, 2026-11-13, not yet built

## Summary

A periodic check of Frigate's config and logs, and of how Camera AutoNotify is set up against them, written up by
an AI Task entity the user chooses, and sent by e-mail through Supernotify, like the
[periodic GenAI report](https://camera-autonotify.rhizomatics.org.uk/genai/#periodic-reports). Off to begin with.
The user can choose to hear nothing when there's nothing wrong.

## Motivation

Spiking [RFC 0004](rfc0004_richer_frigate.md) on the live install turned up config problems that had been there,
silently, for days or longer, none of which anything reported:

- an old `model.labelmap` override, from before a Frigate+ model, had turned the model's `package` class into
  `car`, so packages were reported as cars
- cameras' own `objects.track` replaced the global one, leaving out the logo attributes the model offers, and on
  one camera `person`
- a zone drawn in pixels for one camera's resolution made Frigate's profile manager fail to reset another camera's
  `detect` section on every profile change, logged as an error and nothing more
- the Frigate integration's copy of the config stayed stale until it was reloaded, so anything reading it, Camera
  AutoNotify's settings included, saw the old config

Each was found by reading the config and the logs together and asking whether they made sense, which is what a
model is good at, given the right material.

## Design

### Settings

A *Frigate Config Health Report* section in *Global Settings*, beside the periodic GenAI report, and on the same
pattern:

| Setting | Default | What it does |
|---------|---------|--------------|
| Send a report | Off | Whether the check runs at all |
| AI Task | None | The `ai_task` entity that writes the report, needed to switch it on |
| How often | Once a week | Daily or weekly, from a time of day |
| Starting at | | When it runs |
| Review config | On | Send Frigate's config and Camera AutoNotify's settings to the model |
| Review logs | 1 day | Send a digest of the logs to the model: *Off*, *1 day*, *1 week* or *All*, everything Frigate still holds since it last started |
| Only when there's an issue | On | Nothing is sent when the check finds nothing worth saying |
| Deliveries | Supernotify's e-mail | As the GenAI report, too long for a phone |

It needs Supernotify, as the GenAI report does, and says so where it's not installed.

*Review config* and *Review logs* are there to keep the tokens sent, and so the cost, down: config alone is the
cheaper review, and finds most of what [Motivation](#motivation) lists, while logs find what only shows when
Frigate runs, such as the profile reset error. With both off, only the checks in code run, and the AI Task isn't
called at all. The checks in code that read the logs, such as the same error logged again and again, look back as
far as *Review logs* says, or a day when it's off.

### What's checked

Two layers, so the model's work is the part only a model can do.

**Checks in code**, each a plain finding with a fix, given to the model as facts it needn't rediscover:

1. `model.labelmap` overriding the labels of a Frigate+ model, `model.plus.labelMap`
2. a camera's `objects.track` leaving out attributes the model offers for objects it does track, such as logos for
   `car`, or `face` for `person`
3. a label chosen in a camera's *Objects* setting here that the camera doesn't track, so it can never match
4. a zone chosen in a camera's *Zones* setting here that's no longer in Frigate's config
5. the Frigate integration's copy of the config differing from Frigate's own, so it needs a reload
6. the notification proxy switched off or expiring, as the settings screens already warn
7. a camera without video that has no *Powered by* to say it's off on purpose
8. GenAI on for a camera, but no review summaries seen from it since the last report
9. the same error logged again and again, such as a config validation error on each profile change

**The model's review**, given:

- with *Review config*, Frigate's config, from `/api/config`, which Frigate already redacts: MQTT, ONVIF and go2rtc passwords, GenAI keys,
  and the user and password in camera paths. `environment_vars`, which an admin is given, is dropped here too
- with *Review logs*, Frigate's warnings and errors from `/api/logs/frigate` and `/api/logs/go2rtc`, as a digest:
  each distinct message once, with how often and when first and last, over the period chosen
- Frigate's stats, from the integration's coordinator
- with *Review logs*, Home Assistant's own warnings and errors from the Frigate, MQTT and Camera AutoNotify
  integrations, from `system_log`
- with *Review config*, Camera AutoNotify's settings for each camera and zone, with targets left out
- the findings of the checks in code

It's asked for, by the `structure` of `ai_task.generate_data`:

- a short summary, and whether anything needs attention
- a list of issues, each with a severity (`critical`, `warning`, `info`), the camera or area, what's wrong, and the
  fix, as a few lines of config where that helps

Nothing is changed in Frigate or Home Assistant. The report only suggests.

### Sending

The issues are formatted as e-mail by Camera AutoNotify, not by the model, so its layout is stable: critical first,
each with its camera and fix. With *Only when there's an issue* on, a report with no issues, or only `info`, isn't
sent. Rules apply to it like any other notification.

### Without an AI Task entity

The checks in code need no model. They could run on their own, or raise repair issues as each is found, which
would also meet the `repair-issues` rule of the quality scale. See the open questions.

## Feasibility

- **AI Task**: `ai_task.generate_data` takes `task_name`, `instructions`, `entity_id`, `structure` and
  `attachments`, and returns the data in its response. It's in every Home Assistant release this supports
- **Frigate's config**: `async_get_config()` on the integration's client, already used here
- **Frigate's logs**: `/api/logs/{frigate,nginx,go2rtc}`, read through the client's general request method, as
  `async_get_path` does. The logs live in memory since Frigate last started, so *1 week* may see less than a week,
  and *All* is only as far back as that. Each line has its time, so a period is cut from it. They need the admin role, so with a login that isn't admin, the logs are left out and the report says so
- **Size**: the config of a few cameras is tens of kilobytes, the log digest smaller once each message is counted
  rather than repeated, and growing with the period chosen. Within the limits of cloud models, but maybe not of a
  small local one, which is what *Review config* and *Review logs* are for. The config may also need cutting to
  what's set rather than every default
- **Privacy**: the config names cameras, zones and the house's layout, and goes to whichever provider the AI Task
  entity uses, which may be in the cloud. Frigate's own redaction covers credentials. The settings should say what's
  sent, and the user chooses the provider
- **Cost**: one call per report, so small, but subject to the provider's charges, as the GenAI report is

## Open questions

- **Checks in code without AI**: run them anyway when the report is on with no AI Task entity, as with both reviews
  off, and as repair issues whether the report is on or not
- **How often**: weekly by default, since config changes rarely, with a report straight after Frigate's config
  changes as an option
- **Home Assistant's logs**: `system_log` only keeps the most recent entries, so whether that's enough, or the
  recorder is needed
- **Other servers**: one report per Frigate server, or one for all

## Spikes, against the live install

1. The size, in tokens, of the redacted config, and of the log digest for a day, a week and all, to set the
   defaults
2. `ai_task.generate_data` with the install's AI Task entity, on today's config and logs, to see whether it finds
   the problems above, and what it adds
3. Whether the Frigate integration's login has the admin role, so the logs can be read
