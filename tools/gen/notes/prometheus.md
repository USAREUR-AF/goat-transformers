## What the message is

The message is the body of one Prometheus remote-write HTTP request after its Snappy block
compression is undone: a protobuf `WriteRequest` (remote write 1.0, `prometheus-remote-write`) or
`io.prometheus.write.v2.Request` (remote write 2.0, `prometheus-remote-write-v2`). The HTTP
headers, which name the version and the compression, and the Snappy compression itself are not
part of the pack.

The schema files were read for names, field numbers and types only (`--no-comments`); these
notes are this repository's own words. The `gogoproto` options of the files change only the Go
code generated from them, not the bytes on the wire, and are not carried.

## Everything raw

A request holds many time series, each a set of labels and a list of samples, so no field is
one entity's position or time and no field binds a shared key: every field is a raw key of the
pack's own module.

- Sample, exemplar and histogram timestamps are int64 milliseconds since the Unix epoch (the
  schemas say so for every timestamp). They sit in lists of items, one per sample, so they are
  raw item keys and not the entity's `time_ms`.
- In 1.0 a series' labels are name/value pairs of strings. In 2.0 they are indexes into the
  request's `symbols` list of strings, and the pack keeps both lists as they are; resolving an
  index to its string is outside the pack language.
- The 2.0 schema file states its version as release candidate 5 of the 2.0 specification.
