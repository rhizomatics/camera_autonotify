# Development


## Running Locally

```shell
uv sync
uv run pytest
uv run ruff check --fix && uv run ruff format
uv run mypy custom_components/camera_autonotify
```

## Design

See the [implementation plan](https://github.com/rhizomatics/camera_autonotify/blob/main/docs/developer/design/rfcs/rfc0001_initiation.md). This component is an implementation of
[RFC 0006](https://supernotify.rhizomatics.org.uk/latest/developer/rfcs/0006-frigate_auto_notifier/) from
[Supernotify](https://supernotify.rhizomatics.org.uk).

## Development Docs

{{ pagetree(siblings) }}
