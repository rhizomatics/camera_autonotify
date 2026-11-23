# RFC 0011 - Object Tracker

**Status**: Implemented, plates only
2026-11-22

## Summary

Replace the plate history inherited from anpr2mqtt's tracker with a tracker of any recognised object, a plate being
one kind, a face or a Frigate sub label others. Keep it in Home Assistant's `Store`, restructured, rather than
SQLite.

## Current structure

Three `Store` files, each loaded whole and rewritten whole on save:

| File | Shape |
|------|-------|
| `camera_autonotify.plate_history` | `{hmac(plate): ["2026-11-22T08:00:00+00:00", ...]}` |
| `camera_autonotify.plate_lookup` | `{"dvla:" + hmac(plate): {"at": ..., "found": {...}}}` |
| `camera_autonotify.plate_salt` | `{"salt": ...}` |

Its shortcomings:

- **Plates only**: a face, or anything else Frigate recognises, has no history
- **A sighting is only a time**: no camera, source or confidence, so no history per camera, and nothing for
  [RFC 0008](rfc0008_visits.md) to group a visit by
- **Pruned only when seen again**: a plate seen once is kept forever, as is an expired lookup
- **ISO strings**: parsed on every classification, and anpr2mqtt's may have no time zone

## Options

Measured with a year of sightings, the default *History days*, salted keys as now:

| Sightings a day | JSON size | JSON save | JSON load | SQLite size | SQLite insert | SQLite one object's history |
|-----------------|-----------|-----------|-----------|-------------|---------------|-----------------------------|
| 50 | 0.5 MB | 2 ms | 1 ms | 3.7 MB | 0.2 ms | 0.03 ms |
| 200 | 2.2 MB | 8 ms | 4 ms | 15.2 MB | 0.1 ms | 0.03 ms |

At a household's volume neither is slow enough to matter, so performance doesn't decide it.

| | `Store` (JSON) | SQLite |
|--|----------------|--------|
| Home Assistant style | What integrations use | Unusual outside the recorder |
| Backups | Included as is | Needs a `backup` platform to checkpoint WAL before a backup |
| Schema changes | `Store` versions with a migrate function | Hand-written migrations |
| Threading | Saves batched, off the event loop | Every query in the executor |
| Queries, such as a visit across cameras | Scans in memory, fast at this size | Indexed SQL |
| Diagnostics, inspecting | Readable JSON | Needs a SQLite client |

The recorder isn't an option: its purge, 10 days by default, would decide how long history is kept, and it is shared
with every other integration.

SQLite would only pay off if every tracked object, recognised or not, were kept. An unrecognised object has no
identity to have a history for, though. RFC 0008's visits need such objects only for minutes, which memory handles.

## Design

### Objects

An object has a kind and an identity: `plate` and the plate as normalised, `face` and the name, `sub_label` and
Frigate's sub label. A plate is keyed by `hmac(salt, plate)`, as the betas kept it, so their history moves across
as it is, and any other kind by `hmac(salt, "{kind}:{identity}")`, which a plate, having no `:`, can't collide with.

Plate-specific behaviour stays with plates: corrections, categories, the vehicle register lookup, and taking a misread
as the plate last confirmed on the camera. The visit analysis, with its hourly counts, visitor regularity and new
visit gap, applies to any kind.

### Storage

One `Store`, `camera_autonotify.tracker`, with the salt kept in its own file as now:

```json
{
  "objects": {
    "<hmac>": {"kind": "plate", "sightings": [[1795334400, "gate", "frigate"], ...]}
  },
  "lookups": {
    "dvla:<hmac>": {"at": 1795334400, "found": {...}}
  }
}
```

- A sighting is `[epoch seconds, camera, source]`, compact and quick to compare, with the local time worked out
  only when analysed
- Every object's sightings older than *History days*, and every expired lookup, are dropped on load and daily, and
  an object with no sightings left is removed
- Saves batched by `async_delay_save`, as now

### Interface

A pure `ObjectTracker` in `objects.py`, as `plates.py` is, with no Home Assistant in it: `record(kind, identity,
at, camera, source)`, `history(kind, identity, now)`, `prune(now)`. `Vehicles` keeps classifying and looking up, and
uses it for history.

## Open questions

- **Which kinds next**: Frigate faces, or every sub label
- **Per camera history**: whether a notification should say "seen 3 times at the gate", now that camera is kept
