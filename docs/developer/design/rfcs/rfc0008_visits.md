# RFC 0008 - One Visit Across Cameras

**Status**: Draft
2026-11-17, moved out of [RFC 0004](rfc0004_richer_frigate.md), nothing yet to build

## Summary

A vehicle or person passing several cameras is one visit, but each camera's event is notified by itself. Group the
events of one visit, so that a visit gets a notification for each new thing happening in it, updated as more is
known, rather than one for every camera, recognition and GenAI description.

Not Frigate specific: a visit can be seen by any camera source, such as a Frigate camera seeing a car, anpr2mqtt
reading its plate, and a doorbell pressed by the person who gets out of it.

## Motivation

Spiking RFC 0004 on the live install, each of two delivery vans passed three Frigate cameras, and each camera's
review had its own notification, GenAI summary and description: up to nine notifications for one delivery, all
`LOW RISK` or `NO RISK`. anpr2mqtt would have added its own for the plate, as [RFC 0003](rfc0003_anpr2mqtt.md)
describes for a single car reported four times.

Supernotify's duplicate detection works on the message, which GenAI words differently for each camera, so it doesn't
see these as the same. Knowing which events belong together is camera domain logic, so by the
[design principles](../design_principles.md) it's for Camera AutoNotify, across every camera source it supports.

## Design

Two ideas decide which events of a visit are worth a notification of their own.

### Activity type

What's happening, where it can be known:

| Activity | Where it can come from |
|----------|------------------------|
| Vehicle arriving | Zones entered in order, from the gate inwards, as *Zones in order* already checks. Direction of travel, such as Frigate's `velocity_angle`, once mapped per camera to inwards and outwards, and only above a speed, since it swings while slow or turning. GenAI's observations, such as "enters the driveway". A plate read at the gate before any other camera sees it |
| Vehicle departing | The same, the other way |
| Person moving | A person event with no vehicle, or one leaving a vehicle, by GenAI's observations, or a doorbell pressed |
| Suspicious behaviour | A GenAI threat level above 0, or `other_concerns`, or a rule matching a description's risk |

Not every camera can give every activity, and GenAI may not have run, so an activity is known, or it isn't, and
nothing is guessed. A camera's settings could say which way is in, as a zone order or a direction, for the cameras
where that matters.

### Semantic richness

The levels from RFC 0003, each saying more than the one before, from whichever source gives them:

1. A camera event, the object and where
2. Recognition, a face or a plate, by Frigate, anpr2mqtt or another source
3. Enrichment, such as speed, a logo, or a plate looked up with the DVLA, as [RFC 0004](rfc0004_richer_frigate.md)
   gathers from Frigate
4. GenAI, a description or a summary

### Deciding

Events on cameras next to each other, of the same kind of object, starting within a short time, are taken as one
visit, whichever source each came from. Within a visit:

- **A new activity** is a new notification, such as the van departing after it arrived, or anything suspicious
- **The same activity, richer** updates the visit's notification, silently, as a review's updates do now, such as
  a plate read, or GenAI's summary
- **The same activity, no richer** is dropped, such as the second camera's "Car detected" while the first already
  said so, or a second GenAI summary of the same arrival

For the two vans that's two notifications each, arriving and departing, each updated as recognition and GenAI catch
up, rather than nine.

## Depends on

- **Several sources**: Camera AutoNotify supporting a source other than Frigate, such as anpr2mqtt, see
  [RFC 0003](rfc0003_anpr2mqtt.md), for a visit to span them. Frigate alone is enough to begin with
- **Richness to compare**: RFC 0004's enrichment and recognition, and the facts schema shared by camera sources in
  [RFC 0005](rfc0005_rules.md), so an event from any source can be placed on the richness levels
- **Notification lifecycle**: one notification per visit, updated in place, by the tag Supernotify already supports

## Open questions

- **Neighbours**: which cameras are next to each other, and the time between them, as settings of their own, or
  learnt from the order cameras usually see things
- **Kind of object**: whether a person getting out of a car is the same visit, and how a plate read with no object
  joins the car a camera saw
- **Where it's set**: the visit's settings as global, in *Global Settings*, since a visit crosses cameras, with each
  camera only saying which way is in
- **Cooldown**: how a visit's notifications relate to each camera's *Cooldown*, which would otherwise hold back the
  second camera's notification that the visit has already decided to drop or update
- **Ending**: how long after the last event a visit is over, so a return later is a new visit

## Spikes

1. From the live install's logs, how far apart in time the same vehicle reaches neighbouring cameras, and how often
   two visits overlap, such as two vans arriving together
2. Whether GenAI's `observations` say arriving or departing reliably enough to be an activity type without
   direction of travel
