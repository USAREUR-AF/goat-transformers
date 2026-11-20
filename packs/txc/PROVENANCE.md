# Provenance of the txc pack

SPDX licence: OGL-UK-3.0

`tools/gen/xsd2pack.py` (run script `tools/gen/txc-run.sh`) reads the TransXChange 2.4
schema files that `tools/gen/sources/txc-xsd.txt` lists with their SHA-256 (also listed in
`pack.md`), and nothing else. The files are not kept in this repository. Read on 2026-11-20.

## Source

| | |
|---|---|
| Document | TransXChange 2.4 XML schema, the UK standard for exchanging bus schedules (Department for Transport) |
| Address | http://www.transxchange.org.uk/schema/2.4/ (`TransXChange_general.xsd` and the files it includes: `txc/`, `napt/`, `nptg/`) |
| Publication | GOV.UK, "TransXChange: downloads and schema", https://www.gov.uk/government/publications/transxchange-downloads-and-schema; its document `Downloads_Schema-2015-01-05_-_Updated.pdf` (SHA-256 `cf5ce98adf50860d9311c8abbbd62b388f5c533e147bec9db20e56210b67ddf8`) gives the 2.4 schema address above and lists 2.4 as the official release |
| Not read | the govtalk.gov.uk address and personal-details files (`apd/`), of namespaces declined for this set; `apd/CommonSimpleTypes-v1-2.xsd`, which one of them includes, is not at the address (HTTP 404) |

## Licence

Each schema file's header metadata states, in its `Rights` element, the GovTalk security
classification `Unclassified` (a schema header field, not a handling marking that restricts
distribution) and `Crown Copyright` with its years (2000-2010, 2000-2013 in the 2.5 files).
GOV.UK, through which the Department for Transport publishes the schema, states:

> All content is available under the Open Government Licence v3.0, except where otherwise stated

and the schema files state nothing otherwise. The Open Government Licence v3.0
(`LICENSES/OGL-UK-3.0.txt`) allows copying, publishing, adapting and commercial use, with
an attribution statement. This pack restates element and attribute names, types and value
ranges of the schema and is labelled `OGL-UK-3.0` (REUSE.toml).

Attribution: Contains public sector information licensed under the Open Government Licence
v3.0. TransXChange schema, Crown copyright, Department for Transport.
