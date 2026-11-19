# Provenance of the schema sources

`tools/gen/xsd2pack.py` (run script `tools/gen/xsd2pack-run.sh`, block "UCI 2.5")
reads the two files below and nothing else, and refuses a set when any file it is
given does not carry "Distribution Statement A" in its first 6000 bytes. Each file
is an unmodified copy of the publisher's file. The files are not kept in this
repository; `sources/uci-2.5/` is a directory under the path the run script is given.
Read on 2026-11-19.

## UCI 2.5 (`sources/uci-2.5/`)

| | |
|---|---|
| Document | Universal Command and Control Interface (UCI) Schema, OAC-STD-002 Rev E, UCI version 2.5, schema version `002.5.0`, released 2026-01-22 |
| Publisher | U.S. Air Force |
| Repository | https://github.com/open-arsenal/uci at tag `v2.5`, commit `093610b7753944059360d3236770ab446d039556` |
| Directory | `03_OAC-STD-002_RevE_UCI_Schema_v2_5/` |
| Download | `https://raw.githubusercontent.com/open-arsenal/uci/093610b7753944059360d3236770ab446d039556/03_OAC-STD-002_RevE_UCI_Schema_v2_5/<name>` |

| File | Bytes | SHA-256 | Read by the generator |
|---|---|---|---|
| `UCI_MessageDefinitions_v2_5_0.xsd` | 8287146 | `ac9430499e1107371345e04430895c8c9f18578c1a6b022958ca43ae8aa7bf27` | yes |
| `UCI_SecurityMarkings_v2_5_0.xsd` | 343221 | `4a8056f1503234d423a0c2495844ab65387febced62bea58b87d4f343e9e7a0b` | yes (`xs:include` of the first) |
| `UCI_Versioning_v2_5_0.xsd` | 2131 | `644f9c776c4e50c144b758e5daf83f069dc8ddc40a507e25cb033d5e65459b2e` | no: it declares the `version` annotation attribute the schema puts on its own declarations; no message contains it |
| `VDD.txt` | 735 | `6b308a17607c8ada0b28ff403434320a39185a07d615859351a67db13b6bc028` | no: the release note ("UCI Schema Official Release 002.5.0 - 2026-01-22") |

Statement, in the first `xs:documentation` of both files read (and in the header of
`VDD.txt`):

> Distribution Statement A. Approved for public release: distribution is unlimited.

The repository's `README.md` describes the standard as government-owned and
non-proprietary and carries the badge "License: Government Owned". The repository
has no `LICENSE` file.

## Why this pack exists: OMS 2.5

The Open Mission Systems (OMS) standard has no message schema of its own. Its
message set is the UCI schema:

| | |
|---|---|
| Document | OMS Standard, OMSC-STD-001 Rev M, OMS version 2.5 (released 2026-01-22) |
| Repository | https://github.com/open-arsenal/oms at commit `726272bd0390982a759c91a9cf4e13b81c2b510b`, `docs_official/02_OMSC-STD-001_RevM_OMS_Standard_DandD_v2_5.docx` (and its unofficial Markdown rendering under `docs_markdown_unofficial/`) |
| Statement | the documents carry Distribution Statement A |

The section "OMS Message Set and Schema" says that the compatible OMS Message
Schema for this version of the standard is the UCI Schema listed in its table of
reference standards, and that table lists OAC-STD-002, UCI Schema, revision E,
22 January 2026. The `uci` tag `v2.5` holds exactly that document
(`03_OAC-STD-002_RevE_UCI_Schema_v2_5`). So this pack is the OMS 2.5 message set;
`uci` (schema 002.6.0) is the next UCI release.

This pack has its own module, `uci25`, and its own names file
(`tools/gen/names/uci-2.5.json`), so its keys never change a `uci.*` key. Both
packs use the same XML namespace and root element names: a message does not say
which of the two schema versions it follows, and the caller chooses the pack.
