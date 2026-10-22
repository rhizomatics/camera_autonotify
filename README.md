# AutoNotify for Frigate

Notifications for [Frigate](https://frigate.video) camera reviews in Home Assistant, sent through
[Supernotify](https://supernotify.rhizomatics.org.uk), with no blueprint, automations or YAML.

**Work in progress** - see the [implementation plan](docs/developer/design/plan.md) and
[Supernotify RFC 0006](https://supernotify.rhizomatics.org.uk/latest/developer/rfcs/0006-frigate_auto_notifier/).

## Requirements

- Home Assistant 2026.4 or later
- The [Frigate integration](https://docs.frigate.video/integrations/home-assistant/) and MQTT
- [Supernotify](https://supernotify.rhizomatics.org.uk), for anything more than a plain text notification
