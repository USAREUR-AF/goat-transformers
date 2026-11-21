# Pack: argo-index-meta

One data line of the Argo Global Data Assembly Center metadata directory file (`ar_index_global_meta.txt`, format
version 2.0), which lists every metadata file of the GDAC. Written by hand from the file's
column header line. Wire `text`, delimiter `,`.

## The line

| Field | Key | Content |
|---|---|---|
| 0 | `file` | path of the metadata file under the GDAC `dac/` directory |
| 1 | `profiler_type` | float type code (`int`) |
| 2 | `institution` | institution code |
| 3 | `date_update` | date and time of the last update of the file, `YYYYMMDDHHMMSS` |

## Not mapped, or not bound

- **Dates** are 14 digits with no separators; `iso8601_ms` reads ISO 8601 text, and no
  transform reads this form, so the dates are raw strings and `time_ms` is not bound.
- **Comment and header lines.** The lines that begin with `#` and the column header line are
  not records; a reader drops them first.

## Vectors

Written by `tools/gen/ocean-text-vectors.py` (no engine), from lines of the file as served on
2026-11-21 and lines written for the vectors.
