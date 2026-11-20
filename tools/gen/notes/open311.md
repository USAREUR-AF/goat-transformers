## The form

One message is one object of Open311 GeoReport v2 in its JSON form, as the Swagger 2.0
document `data/georeport_v2-1.yaml` of `open311/open311.github.io` describes it under
`definitions`: a service request, the response to a new request, or a service type. The
API returns requests and services as JSON arrays; each element is one message. The XML
form of GeoReport v2 is not a pack.

## Evidence for the shared keys

- `open311-request`: `service_request_id` is the request's unique identifier (`uid`);
  `requested_datetime` is when the request was made, a `date-time` (`time_ms`; an offset is
  converted to UTC); `lat` and `long` are latitude and longitude in WGS 84 (`lat`, `lon`).
- `open311-request-response`: `service_request_id` of the request created (`uid`).

Not bound: `updated_datetime` (the last change) and `expected_datetime` (a forecast) are raw
keys; `service_code` identifies the type of service, not the request.
