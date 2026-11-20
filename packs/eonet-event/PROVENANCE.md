# Provenance of the eonet-event pack

The pack and the module `eonet` are written by hand from the EONET v3 documentation; the
vectors by `tools/gen/usgov2-vectors.py` from events written for them. No source file is
kept in this repository. Read on 2026-11-20.

## Sources

| Document | Address | SHA-256 of the page as served |
|---|---|---|
| EONET API v3 documentation (Events, Events GeoJSON) | https://eonet.gsfc.nasa.gov/docs/v3 | `b509a146bc9b10140a5258d2642f707b213e535c562e31a4076e8d0765a7fe5c` |
| NASA Images and Media Usage Guidelines | https://www.nasa.gov/nasa-brand-center/images-and-media/ | `7ee561716398de54d181445e43e360318846f6e21dd40f3a377303f6bcffd0d9` |

The member types (which members may be `null`) were checked against a live response of
`api/v3/events/geojson` read on 2026-11-20; only its shape was looked at, and no event of it
is in this repository.

## License

EONET is a service of NASA's Goddard Space Flight Center; its documentation is a work of
the United States Government (17 U.S.C. 105). The EONET pages state no licence. NASA's
usage guidelines state:

> NASA content – images, audio, video, and media files used in the rendition of
> 3-dimensional models, such as texture maps and polygon data in any format – generally are
> not subject to copyright in the United States.

and ask that NASA be acknowledged as the source and that the use not imply endorsement:

> NASA content used in a factual manner that does not imply endorsement may be used without
> needing explicit permission. NASA should be acknowledged as the source of the material.

The events EONET serves are curated from other sources (each event names them in
`sources`); this pack holds the format only, and its vectors hold events written for them.
This pack is not endorsed by NASA.
