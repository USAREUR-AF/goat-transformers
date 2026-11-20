# Provenance of the ocsf-placed pack

`tools/gen/ocsf2pack.py` reads the files below, resolves the class `placed` into a JSON
Schema of structure only and passes it to `tools/gen/jsonschema2pack.py`. The files are
not kept in this repository. Read on 2026-11-20.

| | |
|---|---|
| Document | Open Cybersecurity Schema Framework (OCSF) 1.9.0, event class `placed` |
| Publisher | OCSF, a Series of LF Projects, LLC |
| Repository | https://github.com/ocsf/ocsf-schema at tag `1.9.0`, commit `856d462bd20dc46cc1ffed2dfffe3b91ef0fbeba` |

| File | SHA-256 |
|---|---|
| `LICENSE` | `c665f47ab8605c845a2e6036ccbb89bcfde4999a5caf791464323b931b6dc131` |
| `NOTICE` | `8d71b868af0a0e12b101b21979de9843019133bb366fc17ccecfb3ef6e1cae6f` |
| `categories.json` | `83cb9df1f389eb0759c7ac941b650ac93880f58df41c93bed8dc12124ef685b5` |
| `dictionary.json` | `eb41dddfdcb64b1b8923ba88af31fb4bfee94157cf46150d9d0c6950dfaefa4f` |
| `events/base_event.json` | `7df6c8f0606fa7a9937eff109fe687d700e8c141476616fef79fd604d110cb63` |
| `events/cat/cat.json` | `9e394e53afdefb4f310b1daf3b936adbd371da9c7bc754eb2af6f3ccd7e8e3bc` |
| `events/cat/placed.json` | `0bf2afab62c7722204d1a580657e93b00552191b7efae9890db68641ebbf5e63` |
| `objects/_entity.json` | `32585fb9477c205429bb82b2186e20fa74552ef0e759dbd93d15892913ac57f9` |
| `objects/device.json` | `417d2f65b1d474bb978ad4997b6071eb6ba3624426837d59e17543a34039264f` |
| `objects/location.json` | `83c94cc503a62e423edb51f82a0414a93fc10af1e97fe79bc0d8b5acc612d068` |
| `objects/metadata.json` | `e7ddb2daf20637f7f7d5f8ab5ec46c6d84d8ef23961cf9d137eab5fb6368a51b` |
| `profiles/host.json` | `2afbb24bf1811bb615c884efde6c31fb566fc1fb72d57b22c792de93690f1546` |
| `profiles/labels.json` | `206270eaf070a3e9c9cfe69f93568296f46e89a1d1dbde4fef98853501e977b0` |

## License

The repository's `LICENSE` (SHA-256 `c665f47ab8605c845a2e6036ccbb89bcfde4999a5caf791464323b931b6dc131`) is the Apache License, Version 2.0; it opens:

> Apache License
> Version 2.0, January 2004
> http://www.apache.org/licenses/

Its `NOTICE` (SHA-256 `8d71b868af0a0e12b101b21979de9843019133bb366fc17ccecfb3ef6e1cae6f`), which the license asks to be carried with derivative works, in full:

> Test notice written for the generator tests.

The pack restates the class's structure (attribute names, types, nesting) with keys of
this project's naming. It takes no description, caption or enum text of the schema. It
is not endorsed by the OCSF project.
