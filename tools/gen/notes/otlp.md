## What the message is

The pack's message is one OpenTelemetry Protocol (OTLP) message of the type named above, in its
protobuf encoding: the `TracesData`, `MetricsData` or `LogsData` that a file or a queue holds, or
the request and response of the `Export` method of the trace, metrics or logs collector service
(OTLP/gRPC, or the body of an OTLP/HTTP POST with content type `application/x-protobuf`). The
gRPC framing and an HTTP body's compression are not part of the pack.

## Everything raw

OTLP carries telemetry of software: resources, scopes, spans, metric points and log records. No
field is a shared key, and the packs convert to no other format.

- Every time (`time_unix_nano`, `start_time_unix_nano`, ...) is `fixed64`, and the trace and span
  identifiers are `bytes`: the protobuf wire has no transform for either, so they are not carried.
  The sums and counts of histograms that are `fixed64`, and `sfixed64` values, are not carried
  either.
- `AnyValue` holds an `ArrayValue` and a `KeyValueList` that hold `AnyValue` again: the walk stops
  where a message type would stand inside itself.
- An export request holds the same tree as the matching `*Data` message (field 1 in both); the
  two are separate packs with separate modules so that each can be named by what carries it.
