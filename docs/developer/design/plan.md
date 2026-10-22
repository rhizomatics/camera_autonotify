# Implementation Plan

Plan for building [Supernotify RFC 0006 - Frigate Auto Notifier](https://supernotify.rhizomatics.org.uk/latest/developer/rfcs/0006-frigate_auto_notifier/)
as the `camera_autonotify` custom component, following the shape and tooling of
[appliance_autonotify](https://github.com/rhizomatics/appliance_autonotify).

## Approach

- **Camera AutoNotify, Frigate first** (renamed 2026-10-22 from Frigate AutoNotify). Later sources are anpr2mqtt,
  UniFi Protect, Viseron and doorbell cameras.
  - **Entry data**: each entry records `source` (now always `frigate`), `source_entry_id` for that integration's
    own entry, and `source_name` for the camera's or zone's name as that integration gives it.
  - **Dependencies**: Frigate and MQTT are `after_dependencies`, so it installs without them.
  - **Still Frigate-specific**: `frigate.py`, the discovery in `discovery.py`, and the review tracker. Split them into a source interface when the second source comes, shaped by what it needs, rather than guessing now.
- **Same model as Appliance AutoNotify**: a config entry per camera, discovered from the camera's existing Frigate
  device and linked to it, so Camera AutoNotify shows as one more integration on that device. A single
  `discovery` entry holds the auto-discover switch. A camera added in Frigate shows up as discovered, beside
  Frigate's own discovery of it
- **Zones, optionally**. Frigate gives each zone a device as well. A second switch on the `discovery` entry,
  off by default, discovers zones too. A zone entry notifies for reviews on any camera whose zones include it
- **One Frigate server is the target**. Each camera entry records the `frigate` config entry it came from, so a second
  server isn't ruled out, but it gets no special handling or UI
- **Needs Supernotify to be useful**. Without it, a plain `notify.send_message` goes to the chosen notify entities,
  or to every mobile app, as in appliances. That means no images, no actions and no fix, and the setup screens say
  so
- **No YAML and no templating for users**. The fields are the Frigate blueprint's filters, as plain selectors, plus
  the same notification tuning as appliances: targets and deliveries. Anything Supernotify already does, such as priority mapping, recipients, snoozing, the archive and
  scenarios, is left to Supernotify
- **RFC 0003a is set aside**. Only what the Frigate use cases need gets built, in this component, and each
  workaround is listed in the [table below](#supernotify-candidates), to judge later whether it's worth moving
  into Supernotify

## Phase 0 - Scaffold

Copy from `appliance_autonotify` and rename:

- `pyproject.toml`, `mise.toml`, `.pre-commit-config.yaml`, `.python-version`, `refresh-deps.sh`, `hacs.json`,
  `.github/` workflows, `properdocs.yml`, `docgen/`, `LICENSE`, `CHANGELOG.md`, `README.md` skeleton
- `custom_components/camera_autonotify/`:
  - `manifest.json` - `dependencies: ["mqtt", "frigate"]`, since only Frigate cameras are ever set up,
    and `after_dependencies: ["supernotify"]`,
    `integration_type: service`, `iot_class: local_push`, version `0.1.0`
  - `compat.py` (the voluptuous/probatio shim and `LINKED_DEVICES`), copied as is
  - `supernotify_api.py` (`supernotify_available`, `deliveries_by_transport`), copied as is
  - `const.py`, `translations/en.json`, `brand/`
- `tests/conftest.py` using `pytest-homeassistant-custom-component`, coverage set to fail under 90%

## Phase 1 - Spikes, run against a real HA with `ha-repl`

Use the test instance, which will have Frigate installed alongside Supernotify. The real instance can be used
through `ha-repl` too where needed, for example for real review payloads and real camera devices, but only to read
it. `ha-repl` stays available in later phases for checking behaviour.

1. **Camera devices and entities**: what a Frigate camera's device looks like, including its identifiers and which
   `frigate` entry it belongs to, and how to find its `camera.*` entity and the camera name Frigate uses, from the
   entity registry rather than by guessing entity IDs
2. **Frigate config**: where the integration keeps the Frigate config, to read each camera's zones and tracked
   labels, `mqtt.topic_prefix`, the client ID and whether the notification proxy is on. Fall back to the
   integration's API client if it isn't held anywhere usable
3. **Proxy URL paths**: the actual paths for snapshot, thumbnail, clip, HLS `master.m3u8` and the review page,
   with and without a client ID, for both standalone Frigate and the HA app
4. **Review payloads**: capture real `frigate/reviews` messages (`new`, `update`, `end`, alert and detection) as
   test fixtures
5. **Apple video**: which of `clip.mp4` and `master.m3u8` actually play from an iOS notification, through
   Supernotify's `clip_url` as it stands today. This decides how much of the fix is needed

### Findings (2026-10-22)

From Frigate integration 5.15.6 with Frigate 0.18.2, on the test server and the real one.

- **Devices**: each Frigate device has the identifier `("frigate", "{entry_id}:{slug}")`, with `via` set to the
  server device `("frigate", entry_id)`.
  - **Cameras** have exactly one `camera.*` entity, whose unique ID is `{entry_id}:camera:{name}`. Read the camera
    name from that unique ID.
  - **Zones** get devices of the same shape, but have no camera entity, only occupancy and count sensors. Tell
    them apart by whether a camera entity is present. A zone is matched back to its cameras through the Frigate
    config.
  - **Name case**: zone names keep their case in the config and in review payloads (`Barn_Door`), but are
    slugified in device identifiers (`barn_door`), so compare slugs.
  - **Name clash**: a zone named the same as a camera would get the same identifier, an edge case in the Frigate
    integration.
- **Frigate config**: `hass.data["frigate"][entry_id]` has `client`, `config`, `coordinator`, `model`, and the
  `ws_event_proxy` and `ws_review_proxy` (these only forward MQTT to frontend websockets). From `config["cameras"][name]`:
  - `zones`
  - `objects.track`
  - `review.alerts` and `review.detections`, each with `labels` and `required_zones`
  - `enabled`

  The topic prefix is `config["mqtt"]["topic_prefix"]`.
- **Proxy URLs**: `/api/frigate/notifications/{id}/{path}`, with an optional `{instance_id}/` after `frigate/`, which
  is left out for a single server.
  - **By detection ID**: `snapshot.jpg`, `thumbnail.jpg`, `{camera}/clip.mp4` and `{camera}/master.m3u8` (HLS
    through Frigate's VOD module).
  - **By review ID**: `review_preview.gif` and `{camera}/review_thumbnail.webp`.
  - **Access**: unauthenticated requests are allowed unless `notification_proxy_expire_after_seconds` is set on
    the Frigate entry, and `notification_proxy_enable` is on by default. Warn if a user has switched it off.
- **Review shape**: `id`, `camera`, `start_time`, `end_time`, `severity`, `thumb_path`, and `data` with
  `detections`, `objects`, `verified_objects`, `sub_labels`, `zones`, `audio`, `thumb_time` and `metadata`
  (`metadata` holds the GenAI output, out of scope).
- **Test server**: MQTT was added on 2026-10-22, after the first capture attempt.
- **Apple video (spike 5)**: tested on an iPhone through Supernotify `mobile_push`, using the Nabu Casa URL and a
  review that had already ended.
  - **A**: `clip_url` set to `clip.mp4` showed a thumbnail the first time, but **no image** when sent again, so
    it's unreliable even for the image.
  - **B**: `clip_url` set to `master.m3u8` shows **no image at all**. iOS can't attach the playlist, and the
    `video` attachment replaces the snapshot.
  - **C**: snapshot only, with a notification-level tap to `master.m3u8`, shows the snapshot and opens the video
    when tapped. It worked both times.

  So **never send the `m3u8` as `clip_url`**. The broken image in the recipe comes from that.
  - **Tap**: tapping C opens the video through `master.m3u8`. Tapping A or B only opens the Home Assistant app,
    since neither had a tap URI.
  - **Long-press**: long-pressing A shows the action buttons and a loading spinner that never finishes. The clip
    was 15 MB at 3040x1368, which iOS doesn't play inline.

  **Decision**: never send `clip_url`. Every notification gets the snapshot, plus a notification-level action to
  `master.m3u8`, so tapping opens the video. The *Apple fix* is then simply how this component works, with no
  setting to turn it off. Android gets the same links, since `clickAction` to the playlist works there too (to
  confirm on an Android device).
- **Fixtures**: `tests/fixtures/reviews.json` has 7 real reviews from the API, used as the `after` of an MQTT
  message (`{"type": "new"|"update"|"end", "before": ..., "after": ...}`).
  - **Not seen**: the sample has no `detection` severity, sub-labels or audio. Capture a live `new`, `update` and
    `end` sequence in the daytime, when Frigate is busier (7.5 minutes in the evening caught nothing).
  - **Zones cross cameras**: `Pend` shows up in reviews from both `courtyard` and `driveway`, so one zone can
    belong to more than one camera.

## Phase 2 - Discovery and devices (`discovery.py`, `device.py`, `frigate.py`)

- `find_cameras(hass)`: the Frigate camera devices, each with its device ID, name, camera name, camera entity and
  `frigate` entry ID
- `async_start_discovery`, as in appliances: look now, and again on entity registry `create` events for Frigate
  camera entities, then either import (auto-discover on) or offer through `integration_discovery`. The unique ID is
  the device ID
- `async_register_device`: link to the camera's device by its shared identifiers, as appliances does with
  `LINKED_DEVICES`, and do without a device on older Home Assistant versions
- `frigate.py`: reads one camera's server details (topic prefix, client ID, zones, labels) and builds the URLs for
  `snapshot_url`, `thumbnail_url`, `hls_url` and `review_url` (the base comes from
  `get_url(prefer_external=True)`)

## Phase 3 - Review tracker (`tracker.py`)

Pure logic with no Home Assistant I/O, so it's the most heavily tested part.

- `ReviewTracker` per camera entry, holding in-memory state per `review_id`: severity, objects, sub-labels, zones,
  last sent time, and count sent
- `on_message(payload) -> Decision | None` applies the blueprint's filters:
  - severity: alert or detection
  - labels, zones, `zone_multi`, `zone_order_enforced`
  - `cooldown` for new reviews
  - `alert_once`, `update_sub_label`
  - `initial_delay`, `final_delay`, `final_update`, `timeout`, as timers through `async_call_later`
- A `Decision` carries what the notifier needs: the camera, label text with sub-labels merged, objects, zones,
  severity, the review and detection IDs, whether this is a new review, an update or the final notification, and
  why it was sent
- Clean up state on `end` and on `timeout`
- Tests are table-driven from the Phase 1 fixtures, one case per blueprint behaviour being replaced

### Built (2026-10-22)

`tracker.py` is pure logic: the time is passed in, and anything held back comes back as a `Wait` for the caller to
time and then call `on_timer` for.

- **Messages**: `on_message` gives a `Decision` (`NEW`, `LABEL`, `ZONE`, `SUB_LABEL`, `SEVERITY` or `FINAL`), a
  `Wait`, or `None`.
- **Matching**: a zone tracker follows its zone on any camera, matched by slug.
- **Audio**: audio labels count as objects.
- **Sub-labels**: given as `[name, score]` by newer Frigate, and read as the name.
- **Late matches**: a review that starts out not matching the filters is notified as `NEW` as soon as an update
  makes it match, for example a detection raised to an alert, or a chosen label appearing.
- **Cooldown**: a review passed over for the cooldown gets none of its updates either.
- **Already over**: a review that has ended before its first notification is due gets that one notification and
  nothing more.
- **Defaults**:
  - alerts only
  - `cooldown` 30 s
  - `timeout` 600 s
  - `alert_once` on
  - `update_sub_label` on
  - `final_update` off
  - no delays

## Phase 4 - Notifier (`notifier.py`)

Builds the `supernotify.notify` call in code:

- `title` and `message` from fixed wording with the label, camera and zones filled in. Users can't edit them,
  which keeps this free of templates
- `media`: `snapshot_url` and `camera_entity_id`, and never `clip_url` (see the spike 5 findings)
- `actions`: a notification-level tap URI to `master.m3u8`, as appliances does with its dashboard, plus a *View
  Snapshot* button
- `priority`: `high` for alerts and `medium` for detections, with Supernotify handling the mapping to critical and
  interruption level per platform
- `extra_data`: `mobile_push_notification_tag` set to the review ID, so updates replace the earlier notification,
  and a group by camera
- `target`, `custom_target` and `delivery`, from the settings, sent the same way as appliances `_supernotify`
- Context: a fresh `Context` per review, with later notifications as children of it, as in appliances
- Without Supernotify: `notify.send_message` with the title and message only

### Built (2026-10-22)

`notifier.py` builds the `supernotify.notify` call for each `Decision`.

- **Title**: the entry's name.
- **Message**:
  - `Person detected in Barn Door` for a camera, or `Person detected on Courtyard` for a zone.
  - `, now ended` is added to the final notification.
- **Priority**:
  - `high` for an alert, `medium` for a detection.
  - `low` for an update with alert once, since `low` is iOS passive, so no sound on any delivery.
- **Grouping**: tag `frigate_{review_id}` and group `frigate_{camera}`.
- **Media**:
  - the camera entity, for Supernotify's camera snooze, with the snapshot still the image;
  - the snapshot URL;
  - a tap to the HLS link, and a *View snapshot* button.
- **Options**: deliveries and targets from the entry's options.
- **Without an external or internal URL**: no snapshot or links.
- **Without Supernotify**: `notify.send_message` for the first notification of a review only, since each update
  would be a new notification with nothing to replace.

## Phase 5 - Config flow (`config_flow.py`)

Same structure as appliances, reusing its `sectioned()` and `flattened()` helpers and its rule that a value left
at its default isn't stored.

- **User step**: creates the `discovery` entry (auto-discover on by default) and lists the cameras found, with the
  Supernotify status text
- **Import and integration_discovery steps**: a camera entry per discovered camera, titled with the camera name
- **Camera options**:
  - main fields: severity, then labels and zones as multi-selects filled from the Frigate config
  - collapsed *Timing* section: cooldown, initial and final delay, final update, timeout, `alert_once`,
    `update_sub_label`
  - collapsed *Notify* section: `target`, `custom_target` and `deliveries`. Without
    Supernotify, this section is only a notify entity select
- Conditions such as presence, state and time aren't offered for now. They may suit the proposed quick selectors
  ([Supernotify RFC 0007](https://supernotify.rhizomatics.org.uk/latest/developer/rfcs/0007-quick_selectors/));
  noted only, not planned here

### Built (2026-10-22)

Each camera or zone entry's settings form:

- **Main fields**:
  - **Severity**: alerts and detections, with alerts chosen by default.
  - **Objects**: tracked objects, audio labels and review labels from the camera's Frigate config. A zone offers
    those of every camera it's on.
  - **Zones**, **Every zone** and **Zones in order**: for cameras only.
  - **Typed values**: objects and zones accept values that aren't in the list, for a label Frigate's config doesn't
    list.
- **Collapsed *Timing* section**: the tracker's timing settings.
- **Collapsed *Notification targets* section**: as in appliances.

**Storage**: options are stored flat under the tracker's own setting names, so `Settings.from_options` reads them
directly. Values left at the default aren't stored.

## Phase 6 - Runtime wiring (`__init__.py`)

- One shared MQTT subscription for each topic prefix in use, made on the first camera entry's setup and dropped
  with the last one. It routes each review by camera name to that entry's tracker
- `async_setup_entry`: build the tracker and notifier, and register the device. If the camera's Frigate entry
  isn't loaded, for example after a reload, raise `ConfigEntryNotReady`
- Every timer and listener goes through `entry.async_on_unload`. Options changes reload the entry
  (`OptionsFlowWithReload`)
- Diagnostics: redacted server info and the tracker's current reviews

### Built (2026-10-22)

`hub.py` has one shared `{prefix}/reviews` subscription for each topic prefix, dropped with its last entry. Each
camera's or zone's entry has a `ReviewWatcher`:

- **Settings**: its tracker is built from the entry's options, and a reload on saving the settings applies them.
- **Timing**: it times each `Wait` with `async_call_later`, and cancels the timers on unload.
- **Sending**: it sends each `Decision` as a background task.
- **Context**: each review gets a `Context`, and each later notification for it is a child of that one.
- **Readiness**: setup raises `ConfigEntryNotReady` until the Frigate entry's config and the MQTT client are ready.
- **Diagnostics**: entry data, options with targets redacted, and the reviews being followed.

## Phase 7 - Docs and release

- README and docs site: install, what gets discovered, a table mapping each blueprint input to where it lives now
  (here, in Supernotify, or dropped) for people migrating
- HACS `0.1.0` pre-release, with a feedback thread linked from the Supernotify discussion

### Built (2026-10-22)

- **README**, which is also the docs site's home page:
  - what you need, installing, choosing cameras yourself, zones and the linked device;
  - the settings, with their defaults, and what gets sent, with and without Supernotify;
  - why the clip is never attached, in place of the Apple push fix;
  - a table of each blueprint input and where it is now, for moving from the blueprint;
  - known limits.
- **Release**: `0.3.0`, already tagged, rather than `0.1.0`. The changelog describes it as the first pre-release.
- **Feedback**: through the repository's issues, since it has no discussions. A thread in the Supernotify discussions
  is still to be made.
- **Not built**: the warning for a Frigate entry with its notification proxy off, listed as a known limit instead.

## Supernotify candidates

Each one is built here first and reviewed once the component is in use. If Camera AutoNotify turns out to be the
only user, it stays here.

| Need | Done here as | Could move into Supernotify as |
|------|--------------|--------------------------------|
| Replace an earlier notification for the same review | Review ID as `mobile_push_notification_tag` | A first-class tag or notification ID (RFC 0009) |
| Cooldown between reviews | In the tracker | Per-source rate limiting |
| Silent updates (`alert_once`) | `priority: low` | An explicit `silent` on the call, so it's not tied to priority |
| Video that works on iOS | Snapshot plus a tap to the HLS link, never `clip_url` | Supernotify warning, or dropping an `m3u8` `clip_url` |
| Tap to open the clip | Notification-level action URI | n/a, already supported |
| Scenarios that match Frigate notifications | Message text only | A source or context passed on the call |

## Out of scope (per RFC)

GenAI summaries and `tracked_object_update`, ANPR, Telegram inline keyboards, Android TV overlays, Live Activities,
TTS, custom actions, and user-editable message text.

## Rough sequencing

Phase 0 and Phase 1 first. Phases 2 and 3 can then run in parallel, since the tracker is pure logic over fixtures.
Phase 4 needs the tracker's `Decision`, and Phase 5 needs Phase 2's discovery. Phase 6 joins them up and is the
first end-to-end test on a real Frigate. Phase 7 comes last.
