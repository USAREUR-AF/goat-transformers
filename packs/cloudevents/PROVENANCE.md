# Provenance of the cloudevents pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/cloudevents-run.sh`) reads the files below and nothing
else. They are not kept in this repository. Read on 2026-11-19.

| | |
|---|---|
| Document | CloudEvents 1.0.2, JSON Schema of the JSON event format |
| Publisher | CloudEvents project (CNCF) |
| Repository | https://github.com/cloudevents/spec at commit `fc1f6f31f5f011a72183f1bcea20c987cb683ade` |
| Download | `https://raw.githubusercontent.com/cloudevents/spec/fc1f6f31f5f011a72183f1bcea20c987cb683ade/cloudevents/formats/cloudevents.json` |

| File | SHA-256 |
|---|---|
| `cloudevents/formats/cloudevents.json` | `e28a6d252d7b7238d176618f6bbf6cde570b26a867bc5241563aed34c9dd1d83` |

## License

The repository's `LICENSE` is the Apache License, Version 2.0; it opens: (SHA-256 of `LICENSE`: `c07c2bf22d1b6eadecdbc008b0693c9a876f85c1485c375ff57301085ffc8db9`)

> Apache License
> Version 2.0, January 2004
> http://www.apache.org/licenses/

The specification text (`cloudevents/spec.md`, `cloudevents/formats/json-format.md`) is in the same repository under the same license. The pack takes no text of it.

The pack restates the schema's structure (member names, types, nesting) with keys of this
project's naming. It is not endorsed by the publisher.
