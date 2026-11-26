# RFC 0014 - Plate Image for Doubtful Reads

**Status**: Draft, needing Supernotify's `extra_images`
([supernotify#348](https://github.com/rhizomatics/supernotify/issues/348))
2026-11-26

## Summary

Where Frigate reads a plate it isn't sure of, and nothing else knows it, attach a close-up of the plate to the
e-mail, beside the snapshot, so whoever reads it can check the read. Cropped by Supernotify from the event's
snapshot, at the plate's box in that snapshot, and never shown on a phone, which has room for one image.

## Motivation

The plate read is said under the headline, and a misread one is looked up, classified and counted as a visit as
though right. A plate a vehicle category knows, or Frigate names, is already trusted, and a well read one needs
no picture. A doubtful read of an unknown plate is the one worth a second look, and in the snapshot it's a few
dozen pixels across.

### Where the plate is

Frigate's `lpr` message on `{prefix}/tracked_object_update` has `plate_box`, in pixels of the frame it read, and
`timestamp`, when it began reading it, not that frame's time. The snapshot is another frame. Two failed `lpr`
messages from Vector, 2026-11-25 and 26, against their events' snapshots:

| Object | `lpr` `plate_box` | Snapshot's `license_plate` attribute |
|--------|-------------------|--------------------------------------|
| `ctvnak`, LC710BJ, moving | `[1088,740,1244,831]`, then `[1118,676,1262,763]` 0.2s later | `[1044,891,1195,967]` |
| `036xtl`, SPI9TCY, nearly still | `[1071,605,1211,668]` | `[1083,611,1200,663]` |

So `plate_box` would miss the plate of a moving car in the snapshot. With a model that has `license_plate` as an
attribute, such as Frigate+'s, the event's `snapshot.attributes` has the plate's box in the snapshot itself, as
every plate event of the week did here. Without one, there's no box for the snapshot, and no plate image.

## Design

### When

On a notification whose review has a plate read, the best by score, as now, when all of:

- no vehicle category has it, and Frigate gives it no name, so it's unknown
- its score is below *Plate image below*
- its object's snapshot has a `license_plate` attribute, from `{prefix}/events`, kept by the `FactStore`

| Setting | Default | Where |
|---------|---------|-------|
| *Plate image below* | 0.95, the scores here being 0.93 to 0.99 | *Vehicles* in *Global Settings*, offered once Supernotify has `extra_images`. 0 never |

### What's sent

```yaml
media:
  snapshot_url: …/api/frigate/notifications/{id}/snapshot.jpg?bbox=1
  extra_images:
    - url: …/api/frigate/notifications/{id}/snapshot.jpg
      crop: [1044, 891, 1195, 967]
      desc: Plate read as {plate}, {score}%
```

The box is in the snapshot's own pixels, Frigate's detect resolution, the unscaled `snapshot.jpg` without `bbox`
or `crop`. Supernotify widens it a little, and enlarges a small one, which it can do with Pillow, as it already
reprocesses images.

### Needed from Supernotify

`media.extra_images`, a list of `url`, `crop` and `desc`, each fetched, checked and limited as `snapshot_url`
is, attached by the e-mail transports beside the snapshot, and left out by every transport with room for one
image, mobile push among them, and by its `TransportFeature` saying so. Not Frigate specific: a doorbell's face, or
a second camera of the same visit, for [RFC 0008](rfc0008_visits.md).

### Where it goes

- `facts.py`: each object's `license_plate` box, from `after.snapshot.attributes`
- `notifier.py`: `extra_images`, by the conditions above
- `supernotify_api.py`: whether Supernotify has `extra_images`, by its version, as `fallback_urls` is

## Out of scope

- Cropping here, or serving an image of its own, with a signed URL
- `lpr`'s `plate_box` and `timestamp`, until Frigate says which frame they're of
- Without a Frigate+ model, a plate image would need the frame Frigate read, which no API gives
