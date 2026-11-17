# RFC 0007 - Rich Email

## Summary

Use the features, including newly developed ones, of Supernotify to create rich HTML email, that has links back to Frigate, structured information, a place for diagnostics, and the same actions as available on mobile client.

Make this also available to other transports that can handle rich HTML.

## Implementation

TBD whether this uses `message_html`, the existing Supernotify Jinja2 templates, some extension of the templating, or something else.

Some of this is generic, such as the mobile actions reuse and diagnostics, so better handled in Supernotify, where Appliance AutoNotify and other clients can take advantage.
