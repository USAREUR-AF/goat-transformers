# Provenance: rinex-nav-line pack

SPDX licence: LicenseRef-unstated

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IGS/RTCM RINEX WG, RINEX The Receiver Independent Exchange Format, Version 4.01, 10 July 2023; Tables A7, A9 and A30-A34 | https://files.igs.org/pub/data/format/rinex_4.01.pdf | `5e917eb6d2224021c5f05adb333b5311b6cde0f58c3ca4e0ae5871ccd15ce0c8` |
| IGS/RTCM RINEX WG, RINEX Version 3.05, 1 December 2020 (the same observation columns; navigation records without the version 4 record line) | https://files.igs.org/pub/data/format/rinex305.pdf | `05de6c898e1cf4102d6d0ef8b2710a98a16a5105c49a6d972757d647c7593918` |
| IGS Data and Product Disclaimer and Terms of Use, 5 August 2020 | https://igs.org/wp-content/uploads/2020/09/IGS-Data-and-Product-Disclaimer-and-Terms-of-Use-200805.pdf | `7b4e253c24073af930c38ac65b30ae5208850c4a5681a0e2c6bbf388e72f8226` |

## Licence

The IGS publishes the format documents at https://igs.org/formats-and-standards/ with no registration.
Neither document carries a copyright notice or a licence (searched in the extracted text; the only
licence they mention is the LICENSE OF USE header line for data files). The IGS website's "Data and
Product Disclaimer and Terms of Use" (5 August 2020, sha256
`7b4e253c24073af930c38ac65b30ae5208850c4a5681a0e2c6bbf388e72f8226`) states that IGS data and products
are made openly available for use without restriction, and asks users to cite and attribute what they
take to the providers and to the IGS:

> By accessing data, products, and any other information from the IGS, users agree to appropriately
> cite and attribute these resources to providers and their sponsors, acknowledgment of IGS and its
> contributing organizations, and to adherence to professional and ethical standards.

This project's standing decision is that a document that states no licence, without limiting the
purpose of use, is restated from its text. The pack restates the column layouts (positions, widths,
labels) in this project's own words; no text, table or example line of the documents is copied, and
the attribution the IGS asks for is below. Because no licence is stated the pack is labelled
`LicenseRef-unstated` (REUSE.toml in this directory; model/rinexnav.def.license for the module), which keeps
it out of the `open` profile; the operator can overturn it.

The vectors are lines built by `tools/gen/rinex-vectors.py` from values chosen there; their expected
text is derived there, without an engine.

## Attribution

From RINEX, The Receiver Independent Exchange Format, Version 4.01 (10 July 2023) and Version 3.05,
IGS/RTCM RINEX Working Group (F. Gini, ed., 4.01; I. Romero, ed., 3.05), International GNSS Service and RTCM SC-104,
https://igs.org/formats-and-standards/. No copyright notice or licence stated; labelled
LicenseRef-unstated. Layouts restated, no text copied.
