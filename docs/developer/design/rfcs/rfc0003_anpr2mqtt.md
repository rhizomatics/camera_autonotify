# RFC 0003 - ANPR2MQTT Integration

**Status**: Phase 2 built in 0.11.0, as early access
Reviewed 2026-11-11, design agreed, upstream changes released in anpr2mqtt 1.3.0. Phase 2 built 2026-11-17, see
[As built](#as-built). 2026-11-17, the DVLA lookup moved here for Frigate's own plates, see
[DVLA enrichment of Frigate's plates](#dvla-enrichment-of-frigates-plates)

## Summary

Add [anpr2mqtt](https://anpr2mqtt.rhizomatics.org.uk) cameras, found automatically or added by hand, from the
entities anpr2mqtt creates by MQTT discovery, and notify with everything the example automation below does, without
the automation.

`anpr2mqtt` has two sources of images: a camera writing to a directory, by FTP or otherwise, or a Frigate licence
plate recognition. From either, it can do more OCR, and in the UK, look the plate up with the DVLA and correct it.

If the source is Frigate, it should be treated like other Frigate events, so that in future, here, in Supernotify or
elsewhere, events can be joined up, both to recognise what happened at a higher level and to detect duplicates.

### Semantic Levels and Dupe Detection

One idea some automations use for duplicate detection is semantic levels, such as a basic camera event, then an ANPR
detection, then ANPR with GenAI or with DVLA details. If a second notification is semantically richer than the
first, it still gets through, while one at the same or a lower level may be suppressed as a duplicate.

## Review of the first draft (2026-11-11)

The first draft was checked against the anpr2mqtt docs and source, and the live install, read-only with `ha-repl`:
its entities and devices, and the last populated states of `sensor.anpr_driveway` in the recorder.

### One car, up to four notifications

On 2026-11-09 at 14:25:03, `PX19TVD` arrived at the driveway, and was reported four times:

1. a Frigate review, notified by Camera AutoNotify as *Car detected at Driveway*
2. Frigate's own licence plate recognition, which knows the car as `jey_outlander`, updating the review with a sub
   label
3. anpr2mqtt, `source: filesystem`, from the Hikvision camera's FTP upload, at `14:25:03.000`
4. anpr2mqtt, `source: frigate`, from the same Frigate event, at `14:25:03.652`, 0.65 seconds later

The example automation fires on both anpr2mqtt sightings, so the duplicates in the summary are a real problem on the
live install, not a theoretical one.

### Findings

- **anpr2mqtt entities can't be told apart for sure.** They're plain MQTT entities. The device has
  `manufacturer: rhizomatics`, no model, the identifier `driveway.anpr2mqtt` and the name *anpr2mqtt on driveway*.
  The unique id, `anpr_driveway`, is `{event}_{camera}`, so `anpr_` is only the default event name, not a marker.
  The discovery payload's origin, `o.name: anpr2mqtt`, isn't kept anywhere an integration can read it. There's also
  an old disabled duplicate, `sensor.anpr_driveway_2`, from 0.7.0, with the camera named `Driveway`, and the target
  sensors, `plate_*`, which have no device and must not be taken for cameras.
- **`event_time` changing isn't enough to trigger on.** It also changes for retained state arriving when Home
  Assistant starts, the old state being `None`, and for a republish, which since anpr2mqtt 1.1.1 carries a `trigger`
  attribute. Autoclear sets the state back to `unknown` after 5 minutes, and since 1.2.0 the entities go
  `unavailable` while anpr2mqtt is down.
- **Camera names only match by luck.** anpr2mqtt's `driveway` and Frigate's `driveway` happen to be the same here.
- **Image links only work at home.** `event_image_url` is Frigate's own API for a Frigate sighting,
  `http://10.111.10.100:5000/api/events/…/snapshot.jpg`, and anpr2mqtt's local web server for a filesystem one.
  Neither reaches a phone away from home.
- **The example automation's visit history mixes clocks.** It adds am or pm to the 24 hour clock, giving `13pm`, and
  `'hourly_counts' in history` fails when `history` is `null`, as it is on a cleared state.
- **`history.is_new_visit` is there to use**, along with anpr2mqtt's own minimum gap between sightings.
- **The settings forms show raw names.** A camera's options form showed `zone_order`, `timing`, `genai`, `notify`,
  `custom_target` and `deliveries` rather than their labels. The live install's backend serves all 62 strings, for
  both `en` and its own `en-GB`, so this looks like a stale frontend translation cache, or a different instance. To
  be checked after a restart and a hard refresh, and fixed before any new form is added.

## Decisions

From the review of the findings above.

1. **Recognition is made certain upstream.** anpr2mqtt says that it's anpr2mqtt, and gives its camera's details,
   rather than Camera AutoNotify guessing. See [Upstream changes](#upstream-changes-to-anpr2mqtt).
2. **Only a new plate is notified**, whether or not the DVLA has added to it. A later sighting of the same plate in
   the same visit, or the same sighting with DVLA details added, isn't notified again.
3. **Cameras aren't assumed to be named the same in each product.** anpr2mqtt is *supplementary*: it adds plates to
   cameras that a *primary* integration already covers, such as Frigate, UniFi Protect, Blue Iris or Viseron, rather
   than Frigate being the anchor everything hangs from. There may be no primary at all, where anpr2mqtt is used by
   itself, or occasionally more than one, such as UniFi Protect and Frigate. Each anpr2mqtt entry picks the matching
   camera automatically where there's an obvious one, and it can be changed, or set where there isn't.
4. **The person notified isn't at home**, which is why they want to know who's there, so every image and link has to
   work away from home.
5. **The visit history uses one clock.** See [Content](#content).
6. **Known and dangerous vehicles have their own priority.**
7. **`constrain_scenarios` is Supernotify's.** It allows only the scenarios listed, beyond those applied, and doesn't
   select any itself. See
   [Scenario selection at notification](https://supernotify.rhizomatics.org.uk/latest/configuration/scenarios/#scenario-selection-at-notification).
8. **Each kind of vehicle has one choice of priority, or no delivery.** Ignored vehicles default to no delivery. The
   same choice for every kind means known vehicles can be set to no delivery as easily as ignored ones can be set to
   `low`.
9. **Scenario names belong to each install.** `known_vehicle` and `unknown_vehicle` are this install's, and go on a
   docs page of recommended Supernotify configuration. Scenarios are chosen in the same notification box as AutoArm
   has.
10. **The existing settings forms are tidied first**, so they show their labels rather than raw names.
11. **Event types other than plates go on the roadmap**, both anpr2mqtt's and Frigate's, to handle them the same way.
12. **"Stitching" means joining many events, from different sources, into the one thing that happened in the real
    world**, such as *the postman visited*. It's a hard feature for the future, not part of this one.
13. **Duplicates are a real concern.** Notifications follow Supernotify's
    [duplicate detection](https://supernotify.rhizomatics.org.uk/latest/configuration/dupe_detection/) rules, and
    use the same title and message for the same plate from either source, so it has a good chance of catching them.
    Duplicate detection at a higher level, which Supernotify is too low in the stack to do, goes on the roadmap.

14. **Frigate's plates don't go through anpr2mqtt.** Frigate to MQTT, to anpr2mqtt, back to MQTT and on to Home
    Assistant is a round trip for no gain, now that Camera AutoNotify reads Frigate's plates itself
    ([RFC 0004](rfc0004_richer_frigate.md)). The DVLA lookup anpr2mqtt does for them is done here instead, so a plate
    Frigate reads is enriched directly. anpr2mqtt stays for ANPR cameras sending images by FTP or to a NAS, and for
    its other kinds of detection
15. **anpr2mqtt keeps its Frigate listener and its vehicle classification**, for those not using Home Assistant, or
    not using Camera AutoNotify. Its docs recommend Camera AutoNotify's own instead with Home Assistant: the DVLA
    lookup below, and rules for known, dangerous and unknown vehicles in [RFC 0005](rfc0005_rules.md#vehicles)
16. **Vehicles are registered in Camera AutoNotify**, modelled on anpr2mqtt's targets and groups, with its
    corrections, ignores and visit history, since the much bigger opportunity is Frigate users wanting the
    enrichment, who have no anpr2mqtt. There are few anpr2mqtt installs, so its vehicle settings aren't migrated on
    upgrade: a *Known vehicle* button lets plates be registered as they arrive instead. It needn't be done exactly as
    anpr2mqtt does it, so long as it's at least a superset, and better or more Home Assistant like where it can be
17. **Lookups aren't only the DVLA's.** The DVLA is the first of any number of lookup providers, each for a country's
    or region's vehicle register, so plates elsewhere can be enriched the same way

## Upstream changes to anpr2mqtt

Made for anpr2mqtt 1.3.0, 2026-11-11, for the sensor, image and camera discovery of each event:

- **Device**: `manufacturer: Rhizomatics` and `model: anpr2mqtt`, so a device with both is anpr2mqtt's, and nothing
  else needs guessing, and `configuration_url` the camera's `live_url`, where it's `http` or `https`, since Home
  Assistant rejects the whole discovery message for one it can't use. The identifier, `{camera}.anpr2mqtt`, stays as
  it is, since changing it would make a new device for everyone. There's no `model_id`, since one device is shared by
  every event of a camera.
- **`linked_cameras`**: a new optional camera setting, naming the same camera in the primary integrations that see
  it, keyed by the Home Assistant domain of each, so `frigate`, `unifiprotect`, `viseron` or `blueiris`, and
  nothing in anpr2mqtt is particular to one of them. Every state has it as the `linked_cameras` attribute, `{}` when
  there are none, so an anpr2mqtt used by itself, or with a primary not yet supported, just has nothing to link.
  The `frigate` link has one more use, inside anpr2mqtt: its Frigate listener publishes a Frigate camera's plates as
  the camera linked to it, or as before, the camera of the same name. While the listener is on, that camera of the
  same name is added to the attribute when no other is set, though it's only a guess when the listener processes
  every Frigate camera, so it's checked against Frigate's own cameras.
- **Without devices** (`device_creation: false`), there's still no telling, so such cameras can only be added by hand,
  choosing the sensor.

## Design

### Entries

A new entry type, `anpr`, with source `anpr2mqtt`, one per anpr2mqtt camera and event, keyed by the sensor's unique
id. Found like Frigate cameras, set up automatically or offered as discovered as *Global Settings* says, and also
added by hand by choosing an MQTT sensor. Disabled entities and target sensors are left out. The entry's device is
linked to anpr2mqtt's, as a camera's is to Frigate's.

anpr2mqtt can be the only source, with no Frigate or other primary installed at all, and that's a case to support in
full, not a fallback. Frigate is already only an `after_dependency`, so nothing needs it to be there: *Global
Settings* is set up as usual, finds anpr2mqtt cameras with or without Frigate cameras beside them, and its health
checks have no Frigate servers to check, only anpr2mqtt itself. Its setup screen, which only talks about Frigate
today, says what was found of either.

### Linked camera

Each entry has a linked camera, per decision 3: a camera entity of any primary integration, kept as its entity id,
so nothing here is particular to Frigate either. It's chosen from, best first:

1. a camera named in the `linked_cameras` attribute, found as the entity of that camera by its integration's domain,
   such as Frigate's by its unique id, `{entry}:camera:{name}`, and UniFi Protect's by its device's name
2. the Frigate camera of a Frigate sighting's `frigate_event_id`, learned as sightings arrive
3. a camera entity in the same area as the anpr2mqtt device
4. a camera entity of the same name, slugified
5. a camera named in the `live_url`

It's chosen automatically only when one candidate comes out on top, and can always be changed in the entry's
settings, including to none. With more than one primary, a Frigate camera comes first, being the one that can also
be joined to, then the first of the others. What a linked camera gives depends on its integration:

| Linked camera      | Gives                                                                              |
| ------------------ | ---------------------------------------------------------------------------------- |
| Frigate            | its name, its entity for images and snoozes, and sightings joined to its reviews    |
| Any other          | its name, and its entity for images and snoozes                                     |
| None               | nothing, so sightings are notified by themselves, named by the anpr2mqtt camera     |

### When to notify

On a change of the sensor's state, only when:

- the state is a plate, not `unknown` or `unavailable`
- there was a state before, so not retained state arriving at start up
- there's no `trigger` attribute, so not a republish
- the plate differs from the last one notified for the entry, or `history.is_new_visit` is true, per decision 2

Where the linked camera is Frigate's, a Frigate sighting whose `frigate_event_id` is one of the detections of a
review that camera's entry is following updates that review's notification, as an object description does, matched
in either order. One from the filesystem is matched to that camera's open review the same way, by time. Either way,
without a match, or with another primary or none, it's notified by itself.

### Content

The same title and message for the same plate from either source, per decision 13, so built only from what both
sources have:

- **Title**: `{description} at {where}`, such as *Jey's Outlander at Driveway*, `where` being the linked camera's
  name, or the anpr2mqtt camera's without one
- **Message**: the plate, then the previous sightings and when last seen, then the DVLA details if there are any
- **Spoken message**: the title and the plate

Supernotify ignores digits and punctuation when comparing, so the count of sightings and the times don't stop a
duplicate being caught. The source's own details, such as `vehicle_direction`, which only the filesystem has, and the
visit history, go in the data for deliveries that show more, such as e-mail, not the title or message. The visit
history is given on the 12 hour clock, such as `9am: 2 times, 1pm: 15 times`, and left out when `history` is `null`.

### Images

Per decision 4, never a LAN address:

- **Frigate sighting**: the notification proxy's snapshot for the `frigate_event_id`, and its clip, as a review has
- **Filesystem sighting**: anpr2mqtt's image entity, `image.anpr_driveway`, served by Home Assistant
- **`camera_entity_id`**: the linked camera's entity for both, whatever its integration, so Supernotify sees the
  same camera, and its camera snooze covers both. Without one, anpr2mqtt's image entity

### Vehicles

Each kind of vehicle has a priority, or *no delivery*, per decisions 6 and 8, and its own Supernotify scenarios:

| Kind      | Default                                                   |
| --------- | --------------------------------------------------------- |
| Dangerous | `critical`                                                |
| Unknown   | `high`                                                    |
| Known     | the priority anpr2mqtt gives the target or group, or `medium` |
| Ignored   | no delivery                                               |

`constrain_scenarios` is the scenarios of every kind, so only the one applied is allowed, as the example automation
does.

### Notification box

A collapsed section, the same as AutoArm's: targets, custom targets and deliveries, a priority for each kind of
vehicle, and a choice of scenarios for each, from those Supernotify has. Shared with the camera settings once it's
built, so Camera AutoNotify and AutoArm look alike.

### Health

An anpr2mqtt entity being `unavailable` means anpr2mqtt is down, and is notified by the [health checks](https://camera-autonotify.rhizomatics.org.uk/health/) as a third kind beside servers and cameras, from the
entity's state, with nothing polled.

## DVLA enrichment of Frigate's plates

Per decision 14, the same lookup anpr2mqtt does, done by Camera AutoNotify for each plate Frigate reads. The DVLA, for
UK plates, is the first lookup provider, per decision 17, and the one described here. See
[Other countries](#other-countries) for the rest.

### What's looked up

- **When**: a plate read by Frigate, from the tracked object's `recognized_license_plate` or an `lpr` message,
  gathered with RFC 0004's facts, once its score is at least anpr2mqtt's default `min_score`, 0.7, and, as anpr2mqtt
  does, only once for each plate while it's cached
- **How**: the DVLA's Vehicle Enquiry Service, a `POST` to
  `https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles` with the `x-api-key` header and
  `{"registrationNumber": plate}`, by Home Assistant's own HTTP session, never blocking the notification
- **Cached**: a day to begin with, as anpr2mqtt's `cache_ttl`, kept in a Home Assistant `Store` so a restart doesn't
  ask again, a plate the DVLA doesn't know cached as such too
- **Failures**: an error, a refusal or a rate limit logged, and the plate notified without the DVLA's details. A key
  that's refused raises a repair, linking to the setting

### Correcting a misread

As anpr2mqtt's `correct_against_good_read`: where the DVLA doesn't know a plate, and it's within a character or two of
the last plate the DVLA confirmed on the same camera, within the cache's time, it's taken as that plate. Frigate's
own `lpr.known_plates` already matches a known plate with its `match_distance`, so this is only for plates Frigate
doesn't know.

### What it adds

The same as anpr2mqtt's `reg_info` gives today: the make, colour, year, fuel, tax and MOT, as a line of RFC 0004's
facts, *DVLA: MITSUBISHI, WHITE, 2019, Taxed*, said with the plate, and as variables for rules, such as
`event.vehicle.lookup.tax`, in the common schema of [Other countries](#other-countries), so a rule can raise an
untaxed vehicle. A review notified before the lookup returns has the
details in its next notification, as other facts do, or an update of its own, per the roadmap's update for a plate
read.

### Settings

The DVLA's part of the *Vehicle lookup* section of *Global Settings*: the API key, issued by the DVLA, off without
one, and how long to cache. A key is stored as a config entry's data, not its options, and left out of diagnostics.

### Other countries

Per decision 17, a lookup is a provider, with the DVLA only the first:

- **A provider** says which plates it's for, by country or region, and by the plate's format where that tells, what
  it needs, such as an API key, and turns a plate into the same details, the make, colour, year, and whatever its
  register has of tax, inspection or insurance, as a common schema, with anything more kept as it comes. Rules read
  the common schema, so a rule for an untaxed or uninspected vehicle works whichever country's register said so
- **Choosing**: one or more providers, each with its own settings, in the *Vehicle lookup* section of *Global
  Settings*, which replaces *DVLA*. A plate goes to the provider for its country, or to the one chosen where the
  plate's format can't tell
- **HA Image Processing** - compatibility with OpenALPR, and with others at https://www.home-assistant.io/integrations/image_processing/ where feasible
- **Others**: a provider for another country is added beside the DVLA's, without changing the rest. Some countries'
  registers are open data, needing no key, such as the Netherlands' RDW, which makes them a good second to prove the interface, though each is to be checked for its terms and limits first.
- **Caching, failures and correcting a misread** are the same for every provider, done once around them, not in each

### What it means for anpr2mqtt

- A Frigate-read plate is one notification, the Frigate review's, with the DVLA's details, rather than the review and
  an anpr2mqtt sighting
- anpr2mqtt's Frigate listener isn't needed with Home Assistant, and its docs say so, though it keeps working for
  those who use it, and its sightings are still notified, as phase 2 does
- [Joining to Frigate reviews](#phases), phase 3, is then only for an ANPR camera's own sightings, matched to a
  Frigate review by time, since Frigate's own plates no longer arrive by anpr2mqtt

## Vehicles in Camera AutoNotify

Per decision 16, what anpr2mqtt knows of vehicles, kept here, for every plate, from Frigate or anpr2mqtt. At least
what anpr2mqtt does, not a copy of it, so where Home Assistant has a way of its own, that's used:

- **Actions**: `camera_autonotify.add_plate` and `camera_autonotify.remove_plate`, with a category, a plate and a
  description, so plates can be added from automations, scripts and voice, not only the settings and the
  *Known vehicle* button
- **An event for each sighting**, `camera_autonotify_vehicle`, with the plate, its category, the DVLA's or another
  provider's details and its visit history, for automations, such as opening the gate for a family car, rather than
  each reading a sensor's attributes
- **Entities**: each category's sensor, of the last plate seen, with a device class, icon and translated name, and its
  visit history as attributes, so dashboards and the recorder have it as they do any other sensor
- **Better than plates alone**: a category can also match RFC 0004's facts, such as a delivery company's logo, so
  *Amazon Prime vans* can be every van with Amazon's logo, as well as a run of registrations

### Categories

A category of vehicles, a subentry of *Global Settings*, as rules are, modelled on an anpr2mqtt target group:

| Field | What it is |
|-------|------------|
| Name | Such as *Jey's Outlander*, *Family cars* or *Amazon Prime vans*, what rules match on |
| Icon | For its entity and where it's shown, as anpr2mqtt's `icon` |
| Description | What it's said as in a notification, where a plate of it has no description of its own |
| Entity id | Its sensor, the last plate seen of it and when, as anpr2mqtt's target sensors, to use in automations and dashboards |
| Look up | Whether the DVLA is asked about its plates, off for known vehicles to begin with, as anpr2mqtt's `lookup` |
| Plates | One or more, each a plate, or a regular expression for a run of plates, such as a fleet's, with an optional description of its own |

So a category can be a single vehicle, every family car, or a delivery company's vans. A plate is matched once
corrected, ignoring case and spaces, exactly, by expression, or within one character, as Frigate's own
`match_distance` does, so a misread of a known plate still finds it. Frigate's `lpr.known_plates` sub labels still
come through reviews as they do; categories are what rules and the *Known vehicle* button work with.

### Corrections and ignores

As anpr2mqtt's `correction` and `ignore`, in a *Plates* section of *Global Settings*, applied to every plate read,
before it's matched, looked up or counted:

- **Corrections**: a plate, and the reads that are really it, each a string or a regular expression, such as a camera
  that always reads an `O` as a `0` on one car
- **Ignores**: reads that aren't vehicles at all, such as a road sign or a van's livery, each a string or a regular
  expression, dropped without a notification or a sighting

### Visit history

For every plate, as anpr2mqtt's tracker keeps it, in a Home Assistant `Store`, counted from the sightings before this
one:

| Fact | What it is |
|------|------------|
| Previous sightings, last seen | How often, and when last |
| Count by hour | Sightings in each hour of the day, said on the 12 hour clock, such as `9am: 2 times, 1pm: 15 times` |
| New visit | Whether this sighting is a visit of its own, more than the minimum gap since the last, `min_visit_gap_seconds` in anpr2mqtt, a setting here, with a sighting within it not counted |
| Earliest and latest time of day | The earliest and latest times of day the plate has been seen |
| Within the usual times | Whether this sighting is between the two, or none without history, so a familiar car at 3am, earlier than ever before, can be raised |

The previous sightings and last seen are said in the message, as phase 2 does. A sighting outside the usual times
says so, such as *Earlier than ever seen before*. The rest are variables for rules, `event.vehicle.history`, and for
richer deliveries, such as the count by hour in the HTML e-mail of [RFC 0007](rfc0007_rich_email.md). History is kept
for a set time, a year to begin with, being personal data about who comes and goes, and never leaves Home Assistant.

### Registering as it happens

A *Known vehicle* button on a notification of a plate that's in no category, one more of
[RFC 0004](rfc0004_richer_frigate.md)'s actions, with a text box for its description, adds the plate to a category
chosen in *Global Settings*, *Known vehicles* to begin with, so a household fills its categories as cars arrive,
rather than typing plates in. A plate added this way is matched from its next sighting.

## Phases

1. **Tidy the settings forms** (decision 10), and release the **upstream changes**, made but not yet released, before anything here relies on them.
2. **anpr2mqtt cameras by themselves**: discovery, the entry with its linked camera, when to notify, content, images, vehicles, the notification box, health and documentation, with the recommended Supernotify scenarios. Done when the example automation can be deleted on the live install.
3. **DVLA enrichment of Frigate's plates**, per decision 14, so Frigate's plates need no anpr2mqtt, with anpr2mqtt's docs recommending it for Home Assistant. See [DVLA enrichment of Frigate's plates](#dvla-enrichment-of-frigates-plates).
4. **Vehicles in Camera AutoNotify**: categories, corrections and ignores, the visit history, and the *Known vehicle* button, per decision 16. See [Vehicles in Camera AutoNotify](#vehicles-in-camera-autonotify).
5. **Joined to Frigate reviews**: a filesystem sighting matched to a Frigate review by time, and a Frigate sighting from anpr2mqtt, for those still using its listener, updating its review's notification, and the semantic levels, so a sighting at a lower level than what's already been sent isn't sent. The level and the review's key go in `extra_data`, for Supernotify or anything else to use.
6. **Vehicle rules**: known, dangerous, unknown and ignored vehicles as [RFC 0005](rfc0005_rules.md#vehicles) rules over the categories, for Frigate's plates and anpr2mqtt's alike, with the vehicle settings of phase 2 kept, not migrated, for anpr2mqtt's own classification.

The recorder's three sightings above become test fixtures, as the real Frigate reviews already are, and the 14:25 visit, a review, a sub label and both sightings, is the test of phase 3: one notification, updated, not four.

## As built

Phase 2, released in 0.11.0 as early access, to get feedback from use before the rest:

- **Built**: discovery by anpr2mqtt's device manufacturer and model, one entry per camera and event keyed by the
  sensor's unique id, the linked camera by `linked_cameras`, area and name, when to notify, content, images, a
  priority and scenarios per kind of vehicle, the notification box, and health from the sensor going unavailable
- **Retained state**: taken as any change in the first few seconds of following the sensor, and any sighting more than
  ten minutes old, rather than the old state being `None`, since an MQTT sensor starts as `unknown`
- **Left for later**:
    - phases 3 to 6: the DVLA lookup here for Frigate's plates, vehicles registered here with their history, joining a
      sighting to its Frigate review, and vehicle rules
    - adding a sensor by hand, for anpr2mqtt without devices
    - the linked camera by `live_url`, and by `frigate_event_id` learned from sightings
    - the visit history and the source's own details, such as the OCR derived `vehicle_direction`, for richer deliveries, held back, as RFC 0004's facts are, until Supernotify has a data field it doesn't pass on to transports
    - phase 1's form tidy, the missing labels found in review looking like a stale translation cache, to be checked
      on the live install
    - the discovery confirm screen, which still asks about Frigate for an anpr2mqtt camera
- **Full user documentation**, once it's had some use

## Roadmap

- **Other primary integrations**, per decision 3: UniFi Protect, Blue Iris or Viseron as sources of reviews in their own right, as Frigate is, so sightings can be joined to their events too. A large feature, for its own RFC, but nothing here or in anpr2mqtt stands in its way.
- **Event types**, per decision 11: anpr2mqtt's line crossing, face and other targets, and Frigate's own, such as face recognition and audio, handled the same way.
- **Stitching**, per decision 12: joining many events from different sources into the one real world event.
- **Duplicate detection at a higher level**, per decision 13: by what happened, such as the same vehicle on two cameras, rather than by the text of the message, which is all Supernotify can compare.
- **Target sensors**: anpr2mqtt's sensors for a target or group, such as notifying when the postman has been.

## Example Automation

From a live Home Assistant installation, the one this replaces.

```yaml
alias: Driveway ANPR Alert
description: Notify via email, chime, Alexa and mobile push when a vehicle identified
triggers:
  - trigger: state
    entity_id:
      - sensor.anpr_driveway
    attribute: event_time
conditions:
  - condition: not
    conditions:
      - condition: state
        entity_id: sensor.anpr_driveway
        state:
          - unavailable
          - unknown
actions:
  - action: supernotify.notify
    metadata: {}
    data:
      message: >-
        {{ trigger.to_state.attributes.description }} with {{
        trigger.to_state.attributes.plate }} spotted at {{
        trigger.to_state.attributes.camera }} camera{% if
        trigger.to_state.attributes.vehicle_direction is defined %}, moving {{
        trigger.to_state.attributes.vehicle_direction }}{% endif %}

        {% if trigger.to_state.attributes.history.previous_sightings == 0 %} Not
        previously sighted  {% else %}  with {{
        trigger.to_state.attributes.history.previous_sightings }} previous
        sightings. {% endif %} {% if
        trigger.to_state.attributes.history.last_seen is defined and
        trigger.to_state.attributes.history.last_seen is not none %} last seen
        on {{ trigger.to_state.attributes.history.last_seen[:10] }} at {{
        trigger.to_state.attributes.history.last_seen[11:16] }}   {% endif %}

        {% if 'reg_info' in trigger.to_state.attributes and
        trigger.to_state.attributes.reg_info is not none %}  DVLA info: {{
        trigger.to_state.attributes.reg_info }}   {% endif %}

        {% if 'hourly_counts' in trigger.to_state.attributes.history and
        trigger.to_state.attributes.history.hourly_counts is not none %}  Visit
        History: {% for time,count in
        trigger.to_state.attributes.history.hourly_counts.items() %}
          {{ time }}{% if int(time) < 12 %}am{% else %}pm{% endif %} : {{ count }} times
        {% endfor %}{% endif %}
      title: >-
        {{ trigger.to_state.attributes.description }} spotted on {{
        trigger.to_state.attributes.camera }} camera
      priority: '{{ trigger.to_state.attributes.priority }}'
      spoken_message: >-
        {{ trigger.to_state.attributes.description }} with {{
        trigger.to_state.attributes.plate }} spotted at {{
        trigger.to_state.attributes.camera }} camera{% if
        trigger.to_state.attributes.vehicle_direction is defined %}, moving {{
        trigger.to_state.attributes.vehicle_direction }}{% endif %}
      apply_scenarios: >-
        {% if trigger.to_state.attributes.known %}known_vehicle{% else
        %}unknown_vehicle{% endif %}
      constrain_scenarios:
        - known_vehicle
        - unknown_vehicle
      media:
        camera_entity_id: image.anpr_{{trigger.to_state.attributes.camera}}
        snapshot_url: >-
          {% if 'event_image_url' in trigger.to_state.attributes %}{{
          trigger.to_state.attributes.event_image_url }}{% endif %}
mode: single

```

## Reference

- [anpr2mqtt](https://anpr2mqtt.rhizomatics.org.uk), and its
  [Home Assistant integration](https://anpr2mqtt.rhizomatics.org.uk/homeassistant/)
- Supernotify [scenarios](https://supernotify.rhizomatics.org.uk/latest/configuration/scenarios/) and
  [duplicate detection](https://supernotify.rhizomatics.org.uk/latest/configuration/dupe_detection/)
