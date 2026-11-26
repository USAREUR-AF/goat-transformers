# Pack: ndbc-realtime2-stdmet

One record of an NOAA National Data Buoy Center realtime2 standard meteorological file
(`https://www.ndbc.noaa.gov/data/realtime2/<station>.txt`): the observation time and the
measurements of one station at one time. Written by hand. Wire `text`, no delimiter: the
record is one field whose values are columns at fixed character positions (in every record
of the files read, each column ends at the same position, and values are right-aligned).

## The record

| Columns | Key | Content |
|---|---|---|
| 0-3, 5-6, 8-9, 11-12, 14-15 | `year`, `month`, `day`, `hour`, `minute` | the time of the observation, UTC (`int`) |
| 16-19 | `wdir` | direction the wind comes from, degrees from true north |
| 20-24, 25-29 | `wspd`, `gst` | wind speed and peak gust, m/s |
| 30-35, 36-41, 42-47 | `wvht`, `dpd`, `apd` | significant wave height (m), dominant and average wave period (s) |
| 48-51 | `mwd` | direction the dominant waves come from, degrees from true north |
| 52-58 | `pres` | sea level pressure, hPa |
| 59-64, 65-70, 71-76 | `atmp`, `wtmp`, `dewp` | air, sea surface and dewpoint temperature, degrees Celsius |
| 77-81 | `vis` | visibility, nautical miles |
| 82-86 | `ptdy` | pressure tendency, hPa |
| 87-92 | `tide` | water level relative to mean lower low water, ft |

The units are those of the file's second header line and NDBC's measurement descriptions.

## Not mapped, or not bound

- **Measurements are text.** A missing value is written `MM`. The text wire has no sentinel
  for a numeric column (`absent` is not allowed on `text`), and a numeric transform refuses
  `MM`, so every measurement column is a `string` raw key holding the value as written
  (leading spaces included). A transform option that reads a stated text as absent would let
  them be numbers.
- **Time.** The time is five separate numbers. No derive function builds epoch milliseconds
  from a year, month, day, hour and minute, so `time_ms` is not bound; the five parts are raw
  keys. Such a derive function would bind it.
- **Position.** The record holds no position; the station's position is in NDBC's station
  metadata, not in this file.
- **Header lines.** The two header lines (`#YY ...`, `#yr ...`) are not records: their year
  column is not a number, so decoding one is `transform-decode`. A reader drops them first.

## Vectors

Written by `tools/gen/ocean-text-vectors.py` (no engine): two records of the files as served
(station 46042, and station 44013 with missing values), a record cut short after the wind
speed, and a header line (`transform-decode`).
