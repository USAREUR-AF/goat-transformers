# Provenance of the usgs-earthquake-feed pack

The pack and the module `usgsquake` are written by hand from the USGS documentation of
the GeoJSON summary feed; the vectors by `tools/gen/usgs-earthquake-vectors.py` from
events written for them. No source file is kept in this repository. Read on 2026-11-20.

## Sources

| Document | Address | SHA-256 of the page as served |
|---|---|---|
| GeoJSON Summary Format (the member list) | https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php | `35ed455a1de0b9178ed59db2c73b59b98e59d03ff0c957e2de7894c9c26a2322` |
| ANSS ComCat event terms (units and meanings) | https://earthquake.usgs.gov/data/comcat/index.php as archived at https://web.archive.org/web/20260414120315/https://earthquake.usgs.gov/data/comcat/index.php | `e5d3a8d4f33cd343f6cd9725b96477ead521ab2d32110f096d854a790fd4ab01` |
| Feed Life Cycle Policy | https://earthquake.usgs.gov/earthquakes/feed/policy.php | `9476edbce614be0391422c3fa3934513954a94104c07ce5637a47464071b18e0` |
| USGS Copyrights and Credits | https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits | `6c3021eaa5a1e2e96a95cad200cc8cbef6984840bee243f684667de0bc88929e` |

The feed page's links to the event terms (`/data/comcat/data-eventterms.php#...`) now
redirect back to the feed page, and the current ComCat pages no longer list the terms; the
archived copy is the last one that gives them. The share of null members quoted in
`usgs-earthquake/pack.md` was counted, not copied, from the all-events past-week feed read
on 2026-11-20; no event of it is in this repository.

## License

The feed and its documentation are works of the U.S. Geological Survey, a United States
Government agency (17 U.S.C. 105). The USGS Copyrights and Credits page states:

> USGS-authored or produced data and information are considered to be in the U.S. Public
> Domain.

It adds that some non-USGS images and graphics on its sites are used with permission and
marked as copyrighted; the feed's member list and event terms are USGS-authored text and
carry no such mark. The feed pages state no other licence.
