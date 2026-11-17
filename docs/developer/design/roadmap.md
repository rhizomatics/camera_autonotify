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
    - Which detections have a snapshot Frigate+ would accept, so *Submit to Frigate+* is only offered for those (RFC 0004 spike 2)
    - PTZ: the integration's `frigate.ptz` as an action, moving a camera to a preset, and `async_get_ptz_info` for the preset names. Left out of RFC 0004 until someone asks
