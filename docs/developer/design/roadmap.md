# Roadmap

## Major Changes

See [RFCs](rfcs/index.md)

## Wish list

- Support anpr2mqtt, viseron, UniFi protect
- Distinguish live view from snapshot - one off vs ongoing
- Centralise the notification settings, with per camera override
- Use frigate event id as tag
- Plain email format for info
- \u00b7 to plain ascii -
- Richer periodic GenAI report, in steps:
    - *Plain or HTML* choice for e-mail. Frigate's report is Markdown, by its prompt's fixed layout (`# Security Summary`, `## Overview`, `## Timeline` of `**HH:MM** | Camera | ✓/⚠️/🔴` entries, `## Summary`), so HTML is that converted, sent as Supernotify's `message_html`, and plain is it with the Markdown stripped, rather than the raw `#` and `**` sent today. Don't parse the layout itself, since Frigate's prompt can change in any release
    - The reviews of concern beside the report, the same ones Frigate chose (overlapping the hours, ended, with GenAI metadata, threat level or other concerns, see `summary.found`), each with camera, time, threat level, and its `review_thumbnail.webp` and `review_preview.gif` through the notification proxy, which needs no login. Frigate returns no review ids with its report, so matching an entry of the timeline to its review would be by camera and time, Frigate title-casing camera names and using its container's time zone
    - A Supernotify template for the report, given the HTML and the reviews as data, rather than HTML built here
    - Supernotify changes: every transport that can show rich HTML, not just e-mail, honouring `message_html`, and its HTML templates extended beyond e-mail
    - Not Frigate's `preview.mp4` for the report's hours (Frigate integration v5.15.7 preview proxy): it needs a Home Assistant login, is per camera, and Frigate only uses the first hourly preview file of the range
- Say in the docs that Frigate behind an authenticating reverse proxy (Basic or Bearer, Frigate integration v5.15.7 on) works, once tested, since the health check uses the Frigate integration's own client
- Minor items left over from [RFC 0004](rfcs/rfc0004_richer_frigate.md) - smaller than its scope, and not moved to another RFC:
    - GenAI review summaries carry `observations`, a list of short sentences, and a `confidence`, neither used. `observations` could make a better message than `shortSummary` for a long review, and `confidence` could quieten a summary GenAI wasn't sure of
    - A floor on Frigate's detection confidence, the tracked object's `top_score`, below which a review isn't notified, or is quieter
    - Pass RFC 0004's facts on to Supernotify as data, in Camera AutoNotify's own schema, once Supernotify has a field that isn't passed on to transports (as `source`, Supernotify #293)
    - An update of its own when a plate is read, or a face isn't recognised, rather than only in the notifications sent anyway
    - PTZ: the integration's `frigate.ptz` as an action, moving a camera to a preset, and `async_get_ptz_info` for the preset names. Left out of RFC 0004 until someone asks
- Once Supernotify v2.19.0 ships (its #331, built but not yet released), and gated on the installed Supernotify version, with a plain string kept for older ones:
    - send the animated preview with the snapshot behind it, as `snapshot_url: [{url: ..._preview.gif, reprocess: never}, ...snapshot.jpg?bbox=1]`, so a GIF Frigate can't make falls back to the snapshot in e-mail and other deliveries Supernotify fetches for
    - send `help_url` as the camera's or zone's settings page, so an image that can't be fetched raises one Home Assistant repair linking there, rather than only a warning in the log
    - from that version Supernotify snaps `camera_entity_id`, which is always sent, when every URL fails, even a single one, where before the camera was ignored once `snapshot_url` was set. So a notification whose image can't be fetched shows the camera's live view instead of nothing, as How It Works now says, since the live view isn't the event
    - once Supernotify's "Image Notes" is scheduled (on its roadmap, not in v2.19.0, to be designed first, likely as template variables for the image's source and a note, so it works with templates, plain e-mail and every transport), pass what it then needs, possibly the event's time, and drop the caveat from How It Works. Don't send `event_time` before then
