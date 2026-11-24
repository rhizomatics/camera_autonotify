# RFC 0013 - Late GenAI Notifications

**Status**: Draft
2026-11-24

## Summary

Frigate's GenAI summaries and descriptions come after what they describe, sometimes minutes after, but are notified
as though it's happening now. Measure how late each one is, say so in the notification past one threshold, and past
another give it a priority of its own, *No delivery* among them, and Supernotify scenarios the user chooses, so
whether a late one is heard can be decided there, by occupancy or the alarm.

## Motivation

A summary saying "A person walks to the door", minutes after the person has gone, reads as someone at the door now.
How much a late one matters depends on who's home: with the alarm disarmed, a late low-priority summary isn't worth
hearing, but `armed_away` or `armed_vacation`, everything is.

### Findings, 2026-11-18 to 24

From the MQTT stream and Home Assistant's `supernotify.notify` calls in OpenObserve. OpenObserve stamps a review
message with the review's `start_time`, so a summary's arrival is taken from its notification, joined by the
review id in its tag, and its title.

| Measured from | Summaries, 98 | Descriptions, 192 |
|---------------|---------------|-------------------|
| End of the review, or object | median 51s, p90 80s, max 157s | median 4s, p90 33s, max 186s |
| Start, when its first notification went | median 68s, p90 130s, max 336s | 175 under 1 minute, 3 over 5, max 55 minutes |

- A summary can't come sooner than the review's end, at least `cutoff_time` after the object was last seen, 40s
  for alerts here, then the time GenAI takes.
- The 55-minute description is the tyre fitter's van of 2026-11-19, described as it left. From its end, it was on
  time.
- On 2026-11-23 and 24, with 75 of Gemini's `503 UNAVAILABLE`, only 5 summaries came, against about 20 a day
  before. A busy provider loses summaries, rather than making them later. That's for
  [RFC 0006](rfc0006_config_health_report.md)'s check 11.

## Design

### Lateness

How long after what it describes ended, which is all it can say anything about:

- **Summary**: when it comes, less the review's `end_time` in its payload
- **Description**: when it comes, less the object's `end_time`, from its `end` message on `{prefix}/events`, which
  the `FactStore` keeps. An object not yet ended isn't late

From the start would make any long review, or a van parked for an hour, late however soon GenAI was.

### Settings

In a camera's or zone's *GenAI* section:

| Setting | Default | What it does |
|---------|---------|--------------|
| *Say how long ago after* | 2 minutes | Starts the message with how long ago it ended, "Ended 3 minutes ago: A van parks…", translated as the other texts are. 0 never says it |
| *Late after* | 5 minutes | When it counts as late, for the two below |
| *Late priority* | As it is | The priority of a late one, in place of normal threat level's, or *No delivery*, which isn't sent at all. Suspicious and critical keep their own, and a rule can still raise it |
| *Late scenarios* | None | Supernotify scenarios added to a late one, by `apply_scenarios`, as vehicle categories and rules add theirs. Shown only with Supernotify |

The defaults are past this install's p90 and maximum, so that it's said only where it's unusual, and nothing's done
unless a priority or scenarios are chosen. *Ended … ago* isn't spoken by a voice assistant. The priority is
Camera AutoNotify's to set, and Supernotify's to interpret, as for any notification.

### Deciding in Supernotify

A scenario named in `apply_scenarios` is applied whatever its conditions, so the one chosen here, say
`genai_late`, only marks the notification. The user's own scenarios decide what that means, by its name in
`applied_scenarios`, with any other condition, such as one silencing a late notification while disarmed:

```yaml
genai_late: {}
quiet_when_late:
  conditions:
    - condition: template
      value_template: "{{ 'genai_late' in applied_scenarios and notification_priority in ['low', 'medium'] }}"
    - condition: state
      entity_id: alarm_control_panel.home_alarm_control
      state: disarmed
  delivery:
    .*:
      enabled: false
```

Armed, `quiet_when_late` doesn't apply, and every late one is heard. The recipe goes in the docs.

### Where it goes

- `tracker.py`: `Decision.lateness`, from the summary's `end_time`, or a description's object end, given to the
  tracker by the watcher from the `FactStore`
- `facts.py`: each object's `end_time`
- `notifier.py`: the text before the message, the priority, and the scenarios added after the rules'
- `texts.py`: "Ended {ago} ago", by `said_duration`, as other notifications say how long

## Open questions

- Whether suspicious and critical should take *Late priority* too, as a choice, for anyone who'd rather not have a
  late `critical` break through.
