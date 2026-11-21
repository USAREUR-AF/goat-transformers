## The message

NeoWs (`https://api.nasa.gov/neo/rest/v1/`) answers each request with one JSON object:
`neo/{id}` gives one near-Earth object (`neows-neo`), `neo/browse` a page of them
(`neows-browse`), `feed` the objects with a close approach between two dates
(`neows-feed`) and `stats` two counts (`neows-stats`). The member names are those the
service maintainers' Ruby client models; several numbers are sent as strings (the miss
distances, the relative velocities and every member of `orbital_data`), and those members
are strings here. The unit of each distance, velocity and diameter is in its member name
(`kilometers_per_second`, `astronomical`, `lunar`, `meters` and so on).

The feed groups its objects by date under `near_earth_objects`, with each date as a member
name; member names that are data cannot be addressed, so that part of a feed is not mapped.
Each object of it reads with `neows-neo`.

Members the service sends that the client does not model (`id`, `is_sentry_object`, `links.previous` where the client has `prev`,
`close_approach_date_full`, `sentry_data`, and in `orbital_data` the observation dates and
counts and `orbit_class`) are not keys; on the `json` wire they travel as residue where
they are scalars outside a list.

## Not bound

Nothing is bound to a shared key. `epoch_date_close_approach` is the instant of a close
approach in milliseconds of the UNIX epoch, a predicted event and not the time of a report.
`neo_reference_id` identifies the asteroid in the JPL small-body database, and no position
or velocity of the object is given in a terrestrial frame.
