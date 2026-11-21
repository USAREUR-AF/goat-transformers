## The message

Bright Sky (`https://api.brightsky.dev`) serves the open data of Deutscher Wetterdienst
(DWD) as JSON. Each endpoint answers with one object: `/weather` hourly records and the
sources they come from (`brightsky-weather`), `/current_weather` one record compiled from
recent observations (`brightsky-current-weather`), `/synop` SYNOP records
(`brightsky-synop`), `/sources` the sources (`brightsky-sources`), `/alerts` DWD warnings
for a place (`brightsky-alerts`) and `/radar` radar records (`brightsky-radar`). Two packs
read single items: `brightsky-weather-record` and `brightsky-source`.

The units depend on the request's `units` parameter (`dwd`, the default, or `si`); the
document describes the values without units, and the API documentation lists both sets.
The packs keep the values as sent.

## Evidence for the shared keys

- `time_ms` (`timestamp` of a weather record, in `brightsky-weather-record` and as
  `weather.timestamp` in `brightsky-current-weather`): the document gives it as the
  ISO 8601 time of the record, with an offset; it is the time the values hold for.
  `iso8601_ms` reads it and converts to UTC. Records inside a list (`/weather`, `/synop`)
  are list items, where a shared key cannot be bound.

## Not bound

- A source's `lat` and `lon` are the station's latitude and longitude in decimal degrees;
  the document names no datum, so they are raw keys. `height` is the station height in
  metres with no stated reference: raw key, not `hae`.
- `id`, `dwd_station_id` and `wmo_station_id` identify a data source or a station, not a
  tracked entity: raw keys.
- `fallback_source_ids` maps parameter names to source ids (member names are data): not
  mapped. Radar `geometry` and `latlon_position` are free-form objects: not mapped.
