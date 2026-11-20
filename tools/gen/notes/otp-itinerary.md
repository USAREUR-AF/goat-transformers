## The message

One `Itinerary` object of a plan (`planConnection { edges { node { ... } } }` or the older
`plan { itineraries { ... } }`), with the fields the restatement lists: start, end, duration,
costs, transfers, walking and waiting, and its legs, each with its mode, times (scheduled
and estimated), from and to places, intermediate places, route, agency, trip and the encoded
leg geometry. Only the selected fields are present.

## Not bound

An itinerary is a plan of travel, not a report of an entity: no shared key is bound. Places
carry latitude and longitude, but as points of the plan (stops, origin, destination), not
the position of a vehicle. Times are planned or estimated departure and arrival times.
