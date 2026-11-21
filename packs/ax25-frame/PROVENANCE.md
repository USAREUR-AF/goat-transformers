# Provenance: ax25-frame pack

SPDX licence: LicenseRef-unstated

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| TAPR, AX.25 Link Access Protocol for Amateur Packet Radio, Version 2.2, Revision July 1998 | http://www.tapr.org/pdf/AX25.2.2.pdf, read from the Internet Archive capture of 2025-02-23 (https://web.archive.org/web/20250223023607/http://www.tapr.org/pdf/AX25.2.2.pdf); TAPR's current site no longer serves it | `af2070954468ef6498143ababf9beaf5d72b683ef82491dd7eb8e3670b29475c` |

## Licence

The document's title page says:

> Copyright (c) 1997 by Tucson Amateur Packet Radio Corporation
> Portions Copyright (c) 1984, 1993 by The American Radio Relay League, Inc.

No licence or terms of use are stated in the document. TAPR's publications page (Internet Archive
capture of 2019-11-03) listed it among its free electronic publications, with no terms. The file was
read from the Internet Archive's copy of TAPR's own address because that address now fails; a copy
on another host (ax25.net) was downloaded, found to differ in its bytes, and discarded.

This project's standing decision is that a document that reserves its rights, or states none, without
limiting the purpose of use, is restated from its text. Because no licence is stated the pack is labelled
`LicenseRef-unstated` (REUSE.toml in this directory; model/ax25.def.license for the module), which keeps it
out of the `open` profile; the choice is recorded for the operator, who can overturn it.

This pack restates the layouts (field order, sizes, codes) in its own words; no text, figure or table
of the source is copied. The vectors are frames built by `tools/gen/radio-vectors.py` from values
chosen there; their expected bytes are derived there, without an engine.
