# Provenance: sflow5-datagram pack

Read on 2026-11-20. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| sFlow.org, sFlow Version 5, July 2004 (version 1.00, FINAL) | https://sflow.org/sflow_version_5.txt | `83d4daf46d395733a1daa4eceeb405a7c0adedc2882f5e233e1c22c2a12f4bf1` |
| InMon Corp., sFlow License Agreement | http://www.inmon.com/technology/sflowlicense.txt, linked from https://sflow.org/developers/licensing.php | `c94af9b2d31a08308d226f5dab945afbd71d5df096aeab39149c3f9154d7df8c` |

## Licence

The specification carries this copyright notice:

> Copyright (C) sFlow.org (2004). All Rights Reserved.

sflow.org states that sFlow® is licensed free of charge from InMon Corporation, under the sFlow
License Agreement. The agreement opens with this acceptance notice:

> YOUR REPRODUCTION OR USE OF THE SOFTWARE AND/OR THE DOCUMENTATION AND/OR THE SPECIFICATIONS CONSTITUTES YOUR ACCEPTANCE OF THE TERMS AND CONDITIONS OF THIS AGREEMENT.

Section 2.1 grants a perpetual, nonexclusive, royalty-free, worldwide, transferable and
sublicensable licence to use and reproduce the Specifications and to implement them in Products.
Section 2.3 sets the conditions for a licensee: full adherence to the Specifications, the sFlow®
mark to identify products that implement them and on their documentation, and no change to the
copyright and trademark notices. Section 7 lets InMon terminate the agreement when a licensee
does not correct a non-compliance within three months. `LICENSES/LicenseRef-sFlow-License.txt`
quotes sections 2.1, 2.2, 2.3 and 7 with the agreement's address and SHA-256.

This project restates the layout of the datagram (structure order, field sizes, data format
numbers) in its own words; no text, XDR listing or example of the specification is copied. The
pack and the module `sflow` are labelled `LicenseRef-sFlow-License` in REUSE.toml
(LICENSING.md). The vectors are datagrams built by `tools/gen/flows-vectors.py` from values
chosen there; their expected bytes are derived there, without an engine.
