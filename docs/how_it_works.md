---
description: Details of how notifications are sourced and sent on.
---
# How It Works

## What Gets Sent

Nothing is polled. Frigate publishes each review over MQTT as it starts, changes and ends, and a notification goes out as soon as one matches the settings, held back only by the *Timing* settings.

The title says what was seen and where, such as "Person detected at Barn Door", by the zones the review entered for a camera, or the camera's name when none, and the zone's name for a zone. Under it goes what Frigate knows of the review's objects beyond the review, as far as it knows yet, such as "48 km/h · AB12CDE · Royal Mail", until Frigate's GenAI describes or summarises the review, which then says more instead. See [What Frigate Knows](#what-frigate-knows).

| When                                     | With Supernotify                                                   | Without                |
| ---------------------------------------- | ------------------------------------------------------------------ | ---------------------- |
| A review starts that matches the settings | A notification with the snapshot, `high` priority for an alert and `medium` for a detection | A plain text notification |
| A review that didn't match, then does, such as a detection raised to an alert | The same, as a first notification | The same |
| Something new is seen in the review, or a new zone entered, or a face or plate recognised | An update, taking the place of the last notification for that review, silently unless *Sound only the first* is off | Nothing |
| The review ends, with *Notify when over* on | A last update, its title ending "now ended" | Nothing |
| Frigate describes an object in the review | An update with the description, after [rules](https://camera-autonotify.rhizomatics.org.uk/genai/#rules) | Nothing |
| Frigate summarises the review | An update with its title and summary, at its threat level's priority | Nothing |

With Supernotify, each notification:

- shows the snapshot of the review, or the *Image* chosen instead, and opens the clip when tapped, played from Frigate as HLS
- has a *View snapshot* button, and the buttons of the [*Actions*](index.md#actions) chosen, such as *Keep* and *Seen*
- is grouped with the others of the same camera
- passes the camera entity, so Supernotify's camera snooze works

Rules, added under *Global Settings*, can change the priority of any notification by what it says, silence it, or apply Supernotify scenarios. See [GenAI Notifications](https://camera-autonotify.rhizomatics.org.uk/genai/#rules).

Priority, critical alerts, sounds, who is told, snoozing, the archive and scenarios are all Supernotify's, so set them up there once rather than per camera.

### What Frigate Knows

A review only says what was seen, where, and who or what was recognised. Frigate knows more of each object in it,
and says so over MQTT as the object moves, which is kept and said under the headline:

| Fact | From | Said as |
|------|------|---------|
| Speed | A zone with `distances` set, in Frigate's own unit system | The highest speed seen, such as "48 km/h", since Frigate's own speeds at the end are of the object slowing to a stop |
| A plate read | Frigate's licence plate recognition | The plate, where Frigate doesn't know it. A known plate is the review's sub label already |
| Attributes | Such as a delivery company's logo, with a Frigate+ model whose attributes the camera tracks, or object classification | "Royal Mail", named by *Object names* where given |
| A face not recognised | Face recognition, a person whose face Frigate saw but didn't recognise, at its own `recognition_threshold` | "Face not recognised". A person whose face it never saw says nothing |
| Not moving | The tracked object having stopped | "Not moving" |
| States | The camera's state classification, from Frigate 0.17 | Such as "Gate: open" |

Each comes only where Frigate has it set up, so there's nothing to switch on here. They're said in each notification
as it goes, the first, its updates, and the last with *Notify when over*, which says most, by when the object has
passed. Rules still match the headline, not these.

### Who's Home, and the Alarm

How much a camera notification matters depends on who's home and whether the alarm is set: a person at the door is
routine in the afternoon with everyone in, and urgent at night with the house armed. Camera AutoNotify sends every
notification through Supernotify, so this can be decided there, once, for every camera, with no automations.

- **Scenarios** in Supernotify apply when their conditions are met, checked as each notification is sent. A condition
  can be any Home Assistant condition, so an `alarm_control_panel` state, a `person` being home or away, or
  Supernotify's own `occupancy`, such as `ALL_AWAY` or `LONE_HOME`, and the time of day. A scenario can switch
  deliveries on or off, such as announcing on speakers or sounding a chime only while armed, and raise the priority,
  up to `critical` so it breaks through a phone's silent mode. See
  [Scenarios](https://supernotify.rhizomatics.org.uk/latest/configuration/scenarios/) and
  [Conditions](https://supernotify.rhizomatics.org.uk/latest/configuration/conditions/).
- **People**: Supernotify knows who's home from their `person` entities, and a delivery can go only to those who are
  home, or only to those who are away, so a speaker announcement is heard by whoever's in, and a phone notification
  reaches whoever's out. See [People](https://supernotify.rhizomatics.org.uk/latest/configuration/people/).

For example, the conditions of a scenario for when the alarm is set at night, from Supernotify's own docs, to which the deliveries and priority it changes are added:

```yaml
more_attention:
  conditions:
    condition: and
    conditions:
      - not:
          - condition: state
            entity_id: alarm_control_panel.home_alarm_control
            state: disarmed
      - condition: time
        after: "21:30:00"
        before: "06:30:00"
```

[Auto Arm](https://autoarm.rhizomatics.org.uk) keeps the alarm control panel's state right without anyone having to
remember. It arms and disarms it from who's home, sunrise and sunset, and calendar events, with buttons, mobile
actions and voice commands for changing it by hand, so the scenarios above follow along by themselves.

It can also switch Frigate's own profile as the alarm state changes, from Frigate 0.18, so Frigate itself watches
differently when the house is empty: more cameras or zones raising alerts, say, or indoor cameras recording only
while `armed_away`. A Frigate profile named after an alarm state is used for it, or one named `armed` for any of the
armed states, and Frigate goes back to its base config when disarmed. A profile chosen by hand in Frigate is left
alone. See [Frigate Profile Switching](https://autoarm.rhizomatics.org.uk/configuration/frigate/).

Together, with nothing per camera: everyone leaves, Auto Arm arms the house, Frigate switches to its `armed_away`
profile and alerts on more, and Supernotify sends those alerts as `critical` to everyone's phone, while the same
camera notifications stay quiet and routine when someone's home.


### Video on iPhones

The clip is never attached to the notification. Attached as `clip.mp4`, an iPhone shows the snapshot only some of the time, and a Frigate clip is often too large for it to play from the notification. Attached as the HLS playlist, it shows no image at all. So every notification has the snapshot, or the *Image* chosen instead, as its image, and opening it plays the clip, on iPhones and Android phones alike. This replaces the
[Apple push fix](https://supernotify.rhizomatics.org.uk/latest/recipes/fix_frigate_apple_push/), which isn't needed here.
