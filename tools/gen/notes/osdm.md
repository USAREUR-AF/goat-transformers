## The form

One message is one object of the OSDM online API as `specification/OSDM-online-api.yml`
and its schema files describe it. OSDM is large (about 500 schemas); the packs take the
objects that carry a place or a time: Place and StopPlace (a geographic place, with a WGS 84
position), Trip (start and end times), Booking and Offer (creation times).

## Evidence for the shared keys

- `uid`, `lat`, `lon` in `osdm-place` and `osdm-stop-place`: `id` is the place's identifier,
  a URN (UIC station codes and other reference systems); `geoPosition` is described as a
  WGS 84 position whose `latitude` and `longitude` are decimal degrees.

Not bound:

- **Times.** `Trip.startTime` and `endTime` are the scheduled departure and arrival of the
  trip, not the time of a report; `Booking.createdOn` and `Offer.createdOn` have no
  description. All are raw keys.
- `Trip.id` is unique only within one list of trips; `Booking.id` and `Offer.offerId` have
  no description. Raw keys.
