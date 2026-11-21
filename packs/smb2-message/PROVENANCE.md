# Provenance: smb2-message pack

SPDX licence: LicenseRef-MS-OpenSpec

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| Microsoft, [MS-SMB2]: Server Message Block (SMB) Protocol Versions 2 and 3, protocol revision 88.0, 28 September 2026; sections 2.2.1-2.2.14, 2.2.41, 2.2.42 | https://winprotocoldocs-bhdugrdyduf5h2e4.b02.azurefd.net/MS-SMB2/%5bMS-SMB2%5d.pdf, from https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-smb2/ | `fef3a06507679130a8cfdcaeaed581482d7f235435dd904f6c794f113ff04bd1` |
| Microsoft, Open Specification Promise (revised 24 February 2023), its list of covered specifications | https://learn.microsoft.com/en-us/openspecs/dev_center/ms-devcentlp/1c24c7c8-28b0-4ce1-a47d-95fe1ff504bc | (web page, read for its list) |

## Licence

The document carries Microsoft's "Intellectual Property Rights Notice for Open Specifications
Documentation". Its copyright paragraph says:

> This documentation is covered by Microsoft copyrights. Regardless of any other terms that are contained
> in the terms of use for the Microsoft website that hosts this documentation, you can make copies of it in
> order to develop implementations of the technologies that are described in this documentation and can
> distribute portions of it in your implementations that use these technologies or in your documentation
> as necessary to properly document the implementation.

Its patent paragraph says that neither the notice nor the delivery of the documentation grants any licence
under Microsoft's patents, and that a given document might be covered by the Open Specifications Promise
or the Community Promise, with patent licences otherwise available from Microsoft. [MS-SMB2] is not on the
Open Specification Promise's list of covered specifications (read on the same day; the list names the old
CIFS draft, not SMB2). The notice ends: "All other rights are reserved".

This pack is an implementation artifact that restates the message layouts in this project's own words;
no text, table or figure of the document is copied. The copyright permission covers that use. Because the
notice grants no patent licence and SMB2 is not under the Promise, the pack carries its own label,
`LicenseRef-MS-OpenSpec` (added to licences.toml with commercial use "unknown", so it stays out of the
`open` profile; REUSE.toml in this directory and model/smb2.def.license). The operator can decide the
commercial flag.

The vectors are built by `tools/gen/remote-vectors.py` from values chosen there; their expected bytes are derived
there, without an engine.

## Attribution

From [MS-SMB2]: Server Message Block (SMB) Protocol Versions 2 and 3, Microsoft Open Specifications
documentation, revision 88.0 (2026). Copyright Microsoft Corporation; used under the Open Specifications
copyright permission for implementations; no patent licence granted. Layouts restated, no text copied.
