# Provenance of the pegelonline-station pack

The pack and the module `pegelonline` (shared by `pegelonline-station`, `pegelonline-timeseries`
and `pegelonline-current`) are written by hand from the PEGELONLINE REST API documentation, with
the shape of the service's responses checked against it; the vectors by
`tools/gen/pegelonline-vectors.py` from responses written for them. No source file is kept in this
repository. Read on 2026-11-21.

| Document | Address | Version | SHA-256 |
|---|---|---|---|
| PEGELONLINE REST API documentation | https://www.pegelonline.wsv.de/webservice/dokuRestapi | API v2, as served 2026-11-21 | `812c97600632eed3dc4da55aec7d69d60aa459e8b09bed0dd72967cec58f65bb` |
| PEGELONLINE terms of use | https://www.pegelonline.wsv.de/gast/nutzungsbedingungen | as served 2026-11-21 | `d5e9194b6fb981df5eba1032c3d76d068a04123d05242a9549cb7b09e0013981` |

Holder: Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV), the German Federal Waterways
and Shipping Administration, which runs PEGELONLINE.

## Licence: DL-DE-ZERO-2.0

The terms of use state that information, products and services obtained from the site may be
taken over on the basis of the licence:

> DL-DE->Zero-2.0

and go on to permit commercial and non-commercial use, copying, change and combination with
other data without conditions. The licence (Datenlizenz Deutschland – Zero – Version 2.0)
requires no attribution; the source is named here and in the pack's notice entry all the same.
The pack restates the members in this repository's words.
