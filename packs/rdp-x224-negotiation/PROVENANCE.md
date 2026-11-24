# Provenance: rdp-x224-negotiation pack

SPDX licence: LicenseRef-MS-OpenSpec

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| Microsoft, [MS-RDPBCGR]: Remote Desktop Protocol: Basic Connectivity and Graphics Remoting, release of 9 March 2026 (v20260309); sections 2.2.1.1, 2.2.1.1.1, 2.2.1.1.2, 2.2.1.2, 2.2.1.2.1, 2.2.1.2.2 | https://winprotocoldocs-bhdugrdyduf5h2e4.b02.azurefd.net/MS-RDPBCGR/%5bMS-RDPBCGR%5d.pdf, from https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpbcgr/ | `77fae7d35a5cc4f3d0f4ab86ed752182ec675369655259cb999b7c41290d2d7d` |
| IETF RFC 1006 section 6 and IETF RFC 905 section 13, for TPKT and X.224 (see `packs/tpkt-x224/PROVENANCE.md`) | https://www.rfc-editor.org/rfc/rfc1006.txt, https://www.rfc-editor.org/rfc/rfc905.txt | `855adb9556880a3c71fb24c79f174026e763ff02b1ec19d7248a5a2005883f53`, `b15fd8a58189016a039c3409eb8f4cd1d9e02d10d9bc2a6fda6a5b5179e084bd` |
| Microsoft, Open Specification Promise (revised 24 February 2023), its list of covered specifications | https://learn.microsoft.com/en-us/openspecs/dev_center/ms-devcentlp/1c24c7c8-28b0-4ce1-a47d-95fe1ff504bc | (web page, read for its list) |

On 2026-11-24 the first address served release v20261123 (sha256
`4c9be5ad8ab3182c6d4550d6332059819bc3162a3f2909758a8d6207241a508d`). The following values of this pack were
compared with that release and match: the request flags 0x01, 0x02 and 0x08; the response flags 0x01, 0x02,
0x08 and 0x10; the protocols 0, 1, 2, 4, 8 and 0x10; the failure codes 1 to 7; the negotiation structure
length 8; the correlation info type 6, flags 0, length 36 and its 16-octet ID and reserved parts; the cookie
prefix. The pinned release could not be fetched again, so it was not re-checked.

## Licence

The document carries Microsoft's "Intellectual Property Rights Notice for Open Specifications
Documentation", the same notice as [MS-SMB2]. Its copyright paragraph permits copies made to develop
implementations of the described technologies, and distributing portions of the documentation in those
implementations or in their documentation as needed to document them. Its patent paragraph says that
Microsoft has patents that might cover implementations and that the notice grants no licence under them;
a document might be under the Open Specification Promise or the Community Promise. [MS-RDPBCGR] is not on
the Open Specification Promise's list of covered specifications (read on the same day). The notice
reserves all other rights.

This pack is an implementation artifact that restates the layouts in this project's own words; no text,
table or figure of the document is copied. The copyright permission covers that use. As for the SMB2 pack,
it carries `LicenseRef-MS-OpenSpec` (licences.toml, commercial use "unknown"; REUSE.toml in this directory
and model/rdpneg.def.license). The TPKT and X.224 lines restate the RFCs as `tpkt-x224` does and use its
`tpkt` module, which keeps Apache-2.0.

The vectors are built by `tools/gen/rdp-neg-vectors.py` from values chosen there; their expected bytes
are derived there, without an engine. The cookie identifier is invented.

## Attribution

From [MS-RDPBCGR]: Remote Desktop Protocol: Basic Connectivity and Graphics Remoting, Microsoft Open
Specifications documentation, release of 9 March 2026. Copyright Microsoft Corporation; used under the
Open Specifications copyright permission for implementations; no patent licence granted. Layouts
restated, no text copied. TPKT and X.224 from IETF RFC 1006 and RFC 905.
