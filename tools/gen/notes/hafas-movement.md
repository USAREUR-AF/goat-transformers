## The message

One movement of the result of hafas-client's `radar()`: a vehicle currently in the requested
area, with its location, line, direction, trip id, the next stopovers and the computed
frames.

## Evidence for the shared keys

- `lat`, `lon` (`location.latitude`, `location.longitude`): the vehicle's current position
  in decimal degrees. hafas-client's notes on the HAFAS mgate API say the endpoints use
  WGS 84 (with coordinates scaled by 10^6 on the HAFAS side, which hafas-client undoes).

## Not bound

- No time: a movement carries no time of its own; the result's `realtimeDataUpdatedAt` is
  the latest update of the realtime data as a whole (in `hafas-radar`).
- `tripId` identifies the trip, not the vehicle, so it is not `uid`.
- Stopover times and stops are the schedule of the trip, not the vehicle's report.
