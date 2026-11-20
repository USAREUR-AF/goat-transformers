# Provenance of the nhc-current-storms pack

The pack and the module `nhc` are written by hand from the NHC file reference; the vectors
by `tools/gen/nhc-vectors.py` from storms written for them. No source file is kept in this
repository. Read on 2026-11-20.

## Sources

| Document | Address | SHA-256 |
|---|---|---|
| NHC Tropical Cyclone Status JSON File Reference (J. Greenlaw, last updated 2019-04-08) | https://www.nhc.noaa.gov/productexamples/NHC_Tropical_Cyclone_Status_JSON_File_Reference.pdf | `248df25b8e798765deb731d4c69c0609f787e227c699c2ce0d88a0126be7d316` |
| The product | https://www.nhc.noaa.gov/CurrentStorms.json (no active storm when read) | — |
| The site's example file (member types only, nothing copied) | https://www.nhc.noaa.gov/productexamples/NHC_JSON_Sample.json | — |

## License

The National Hurricane Center is part of the National Weather Service (NOAA); the file and
its reference are works of the United States Government (17 U.S.C. 105). The NHC site's
Disclaimer link is https://www.weather.gov/disclaimer, which states (read 2026-11-20, page
SHA-256 `c08c1597ebd52b31e3ba749f76d2217c290dcd16dc894cb4c109655566ecbbd1`):

> The information on National Weather Service (NWS) Web pages are in the public domain,
> unless specifically noted otherwise, and may be used without charge for any lawful
> purpose so long as you do not: 1) claim it is your own (e.g., by claiming copyright for
> NWS information -- see below), 2) use it in a manner that implies an endorsement or
> affiliation with NOAA/NWS, or 3) modify its content and then present it as official
> government material.

This pack is not official NWS material and implies no endorsement by NOAA or the NWS.
