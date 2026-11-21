## The message

Each DONKI-API endpoint (`https://ccmc.gsfc.nasa.gov/DONKI-API/get/<type>`, also served
through `https://api.nasa.gov/DONKI/<type>`) answers with a JSON array of records; one
message of a `donki-*` pack is one element of that array. The member names and types are
those of the API's OpenAPI document (components.schemas), which gives no description for
them; the DONKI user guide and the web application show what each event type holds.

Lists inside a record (instruments, linked events, sent notifications, the Kp values of a
storm, the analyses of a CME, the ENLIL runs of an analysis and their impacts) are groups.

## Not bound

Nothing is bound to a shared key:

- The times (`startTime`, `beginTime`, `peakTime`, `eventTime`, `submissionTime` and the
  others) are written to the minute with a `Z` and no seconds (`2026-10-01T02:36Z`), which
  `iso8601_ms` refuses; they are raw strings. They are times of a solar or geomagnetic
  event, not the time a position report is valid, so `time_ms` would not hold them anyway.
- `latitude`, `longitude` and `sourceLocation` of a CME or flare are heliographic
  coordinates on the Sun, not WGS 84 positions: raw keys, never `lat` or `lon`.
- `speed` of a CME analysis is the speed of the ejection away from the Sun, not the speed
  of a tracked entity: raw key, not `speed_ms`.
- The identifiers (`activityID`, `flrID`, `gstID`, `messageID` and the others) name a
  space weather event or a message, not an entity that is tracked: raw keys, not `uid`.
