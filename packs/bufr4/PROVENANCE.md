# Provenance of the bufr4 pack

Written by hand from the sources below; the vectors by `tools/gen/wmo-vectors.py` from messages
written for them. No source file is kept in this repository. Read on 2026-11-20.

| Source | Commit | What |
|---|---|---|
| https://github.com/wmo-im/GRIB2 | `83abc9f3858260734191f55ffb68f6ad37d2b722` | WMO's GRIB2 templates and code tables as CSV, with the template notes (the 1e-6 degree unit, the sign rule of regulation 92.1.5) |
| https://github.com/wmo-im/BUFR4 | `6a993796bf2661deb9cfe4da25435d5870566b20` | WMO's BUFR edition 4 tables A to D as CSV |
| https://github.com/ecmwf/eccodes | `f03b3c35e2914e607b226b8c167b78758c9e7385` | `definitions/grib2/section.0.def` to `section.8.def` and templates; `definitions/bufr/section.0.def` to `section.5.def`, `section.1.4.def` (the section layouts) |

## Licence: Apache-2.0

wmo-im/GRIB2 and wmo-im/BUFR4 carry the MIT licence:

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software
> and associated documentation files (the "Software"), to deal in the Software without
> restriction, including without limitation the rights to use, copy, modify, merge, publish,
> distribute, sublicense, and/or sell copies of the Software, [...] subject to the following
> conditions: The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.

ecCodes is under the Apache License, Version 2.0. The pack restates the layouts in this
repository's words and copies no code or table text, so it carries the repository's licence.

The Manual on Codes itself (WMO-No. 306, Volume I.2), whose Part B the two WMO repositories
state they publish, was not read: the WMO library does not serve the document to an automated
client, so its notice is not quoted here.
