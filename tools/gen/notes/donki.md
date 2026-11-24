## The message

Each DONKI-API endpoint (`https://ccmc.gsfc.nasa.gov/DONKI-API/get/<type>`, also served
through `https://api.nasa.gov/DONKI/<type>`) answers with a JSON array of records; one
message of a `donki-*` pack is one element of that array. The member names and types are
those of the API's OpenAPI document (components.schemas), which gives no description for
them.

Lists inside a record (instruments, linked events, sent notifications, the Kp values of a
storm, the analyses of a CME, the ENLIL runs of an analysis and their impacts) are groups.

## Not bound

Nothing is bound to a shared key:

- The times (`startTime`, `beginTime`, `peakTime`, `eventTime`, `submissionTime` and the
  others) are plain strings in the document; the responses read write them to the minute with a
  `Z` and no seconds, which `iso8601_ms` refuses. They are raw strings.
- `latitude` and `longitude` have no stated reference frame, and `speed` no stated unit:
  raw keys, not `lat`, `lon` or `speed_ms`.
- The identifiers (`activityID`, `flrID`, `gstID`, `messageID` and the others) name a
  space weather event or a message, not an entity that is tracked: raw keys, not `uid`.
