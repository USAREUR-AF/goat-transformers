# Provenance of the openc2-slpf pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/openc2-cacao-run.sh`) reads the files below and nothing
else. They are not kept in this repository. Read on 2026-11-20.

| | |
|---|---|
| Document | OpenC2 Stateless Packet Filtering profile 1.1, JSON Schema of the Command and the Response |
| Publisher | OASIS Open Command and Control (OpenC2) Technical Committee, TC Open Repository |
| Repository | https://github.com/oasis-open/openc2-custom-aps at commit `f6ef6b3747e6927e262a73f47edd6f8b72b71b83` |
| Download | `https://raw.githubusercontent.com/oasis-open/openc2-custom-aps/f6ef6b3747e6927e262a73f47edd6f8b72b71b83/Schema-Template/v1.1/JSON-Schema/oc2slpf-v1.1.json` |

| File | SHA-256 |
|---|---|
| `Schema-Template/v1.1/JSON-Schema/oc2slpf-v1.1.json` | `a3692f342005b8fa2a8526f9809ab222b21131200e2c5f8be04ea89c5bf1b36d` |

## License

The repository's `LICENSE.md` is the Apache License, Version 2.0. Its README states that the repository is an OASIS TC Open Repository whose contributions are under that license, and that its governance is separate from the OASIS TC Process. It opens: (SHA-256 of `LICENSE.md`: `69af5fed5a751a3d779a88403ac525c890d1999ec892b264704f0c3a3fa41535`)

> Apache License
> Version 2.0, January 2004
> http://www.apache.org/licenses/

The schemas restate the data types of the OpenC2 Language Specification 1.1 and the Stateless Packet Filtering actuator profile 1.1, OASIS Committee Specifications whose text is under the OASIS IPR policy. The pack takes no text of them.

The pack restates the schema's structure (member names, types, nesting) with keys of this
project's naming. It is not endorsed by the publisher.
