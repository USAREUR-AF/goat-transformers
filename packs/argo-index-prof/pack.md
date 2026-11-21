# Pack: argo-index-prof

One data line of the Argo Global Data Assembly Center profile directory file (`ar_index_global_prof.txt`, format
version 2.0), which lists every profile file of the GDAC. Written by hand from the file's
column header line. Wire `text`, delimiter `,`.

## The line

| Field | Key | Content |
|---|---|---|
| 0 | `file` | path of the profile file under the GDAC `dac/` directory |
| 1 | `date` | date and time of the profile, `YYYYMMDDHHMMSS` |
| 2, 3 | `latitude`, `longitude` | position of the profile, degrees north and east (`float`) |
| 4 | `ocean` | ocean code (A, I, P) |
| 5 | `profiler_type` | float type code (`int`) |
| 6 | `institution` | institution code |
| 7 | `date_update` | date and time of the last update of the file, `YYYYMMDDHHMMSS` |

## Not mapped, or not bound

- **Dates** are 14 digits with no separators; `iso8601_ms` reads ISO 8601 text, and no
  transform reads this form, so the dates are raw strings and `time_ms` is not bound.
- **Position.** The file and the profile files it lists give latitude and longitude in degrees
  north and east and name no datum, so they are raw floats, not `lat` and `lon`. A missing
  position is an empty field, which reads as absent.
- A float is written back as its shortest decimal (`0.5430` becomes `0.543`).
- **Comment and header lines.** The lines that begin with `#` and the column header line are
  not records; a reader drops them first.

## Vectors

Written by `tools/gen/ocean-text-vectors.py` (no engine), from lines of the file as served on
2026-11-21 and lines written for the vectors.
