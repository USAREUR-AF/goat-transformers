# Provenance of the ndbc-realtime2-stdmet pack

SPDX licence: Apache-2.0

Written by hand from the layout of NDBC realtime2 standard meteorological files; the vectors by
`tools/gen/ocean-text-vectors.py`. The files are not kept in this repository. Read on
2026-11-21.

## Source

| | |
|---|---|
| Document | NOAA National Data Buoy Center, realtime2 standard meteorological data files (`<station>.txt`), their two header lines (names and units) and the fixed column positions of their records |
| Publisher | National Data Buoy Center (NOAA, National Weather Service), United States |
| Address | https://www.ndbc.noaa.gov/data/realtime2/ (files of stations 46042 and 44013 read; every record of both has its columns at the same character positions) |
| Units | https://www.ndbc.noaa.gov/faq/measdes.shtml (NDBC measurement descriptions) |

## Licence

The document is a work of the United States Government, which has no copyright protection
in the United States (17 U.S.C. 105). The National Weather Service states, on
https://www.weather.gov/disclaimer (read 2026-11-19, SHA-256 of the page as served
`c08c1597ebd52b31e3ba749f76d2217c290dcd16dc894cb4c109655566ecbbd1`):

> The information on National Weather Service (NWS) Web pages are in the public domain,
> unless specifically noted otherwise, and may be used without charge for any lawful
> purpose so long as you do not: 1) claim it is your own (e.g., by claiming copyright for
> NWS information -- see below), 2) use it in a manner that implies an endorsement or
> affiliation with NOAA/NWS, or 3) modify its content and then present it as official
> government material.

and

> The information on National Weather Service Web servers and Web sites is in the public
> domain, unless specifically annotated otherwise, and may be used freely by the public.

The data files carry no other notice. This pack is not official NOAA material and implies no
endorsement by NOAA, the NWS or NDBC.
