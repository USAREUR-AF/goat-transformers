## The form

One message is one request or response body of TOMP-API 2.0.0 as `openapi.json` (the
merged OpenAPI document) describes it under `components/schemas`: a package, an offer
search request, an offer, asset or travel-document collection, a support ticket, or a
customer account.

## Evidence for the shared keys

- `uid`, `time_ms` in `tomp-support-ticket` only: `id` is the ticket's identifier (given
  when the ticket is created) and `timestamp` the time the support request was reported,
  a `date-time`.

Not bound:

- **Positions and times of trips.** Packages, offers, assets and travel documents are
  GeoJSON FeatureCollections: each leg, offer or asset is an item of `features`, and a
  list item's keys never become the entity's keys. Their geometries are any of Point,
  LineString or Polygon (and the schema gives a coordinate a minimum of 0, which no
  western or southern position meets), so no position is bound.
- `customerAccount.id` is described only as a string, so it is a raw key.
