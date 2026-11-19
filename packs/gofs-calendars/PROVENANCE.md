# Provenance of the gofs-calendars pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/gofs-run.sh`) reads the files below and nothing
else. They are not kept in this repository. Read on 2026-11-19.

| | |
|---|---|
| Document | General On-demand Feed Specification (GOFS), JSON Schema of `calendars.json` |
| Publisher | MobilityData |
| Repository | https://github.com/MobilityData/gofs at commit `ab9151ed0237de98e4f68f7c574da8b8dc34083d` |
| Download | `https://raw.githubusercontent.com/MobilityData/gofs/ab9151ed0237de98e4f68f7c574da8b8dc34083d/schema/calendars.json` |

| File | SHA-256 |
|---|---|
| `schema/calendars.json` | `10dfbad43affb0452b53ffd925ed62139d131128418bb14b63517e0aa631993b` |

## License

The repository's `LICENSE` is the Apache License, Version 2.0; it opens: (SHA-256 of `LICENSE`: `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`)

> Apache License
> Version 2.0, January 2004
> http://www.apache.org/licenses/

The specification (`reference.md`) is in the same repository under the same license. Its `schema/README.md` calls the schemas partial and a work in progress. The pack takes no text of the specification.

The pack restates the schema's structure (member names, types, nesting) with keys of this
project's naming. It is not endorsed by the publisher.
