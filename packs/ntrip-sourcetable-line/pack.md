# Pack: ntrip-sourcetable-line

One record of an NTRIP source-table (the list a caster sends a client that asks for no mountpoint), as
BKG's Ntrip 1.0 documentation describes it: one line per message. Wire `text`, delimiter `;`. Kinds by
field 0: `str` (a data stream), `cas` (a caster), `net` (a network of streams), `end` (the
`ENDSOURCETABLE` line). Written by `tools/gen/gnss-time-pack.py`. Labelled `LicenseRef-unstated`
(PROVENANCE.md).

## What is mapped

- **STR**: mountpoint, identifier, format, format details, carrier, navigation system, network,
  country, latitude, longitude, NMEA requirement, solution (single or network), generator,
  compression/encryption, authentication, fee, bit rate, miscellaneous.
- **CAS**: host, port, identifier, operator, NMEA capability, country, latitude, longitude, fallback
  host and port, miscellaneous.
- **NET**: identifier, operator, authentication, fee, network, stream and registration web addresses,
  miscellaneous.

Carrier, NMEA, solution, bit rate and the ports are integers; the rest are strings as written,
latitude and longitude included (the documentation states two decimals, and gives a longitude of
357.85).

## Shared keys

None. The latitude and longitude are a stream's or caster's approximate position, written in a form
(two decimals, longitude east 0-360) that core `lat` and `lon` would rewrite; they are kept as written.

## Not mapped

- **A quoted semicolon** inside a field (the documentation allows it) splits the field: the `text`
  wire has no quoting. Needed: a quoted-delimiter rule on the `text` wire.
- **Fields after the last named one**: the documentation lets tables add fields before the last
  (miscellaneous) one; such a record's later fields shift, and the pack reads them by position.
- **The HTTP response** around the table (status line, `Server:`, `Content-Type`, `Content-Length`) and
  NTRIP version 2 additions (the `NTRIP-...` headers; version 2 was not read).

## Vectors

`tools/gen/gnss-time-vectors.py`, without an engine: a stream; a network stream that needs NMEA; a
caster; a network; the end line; an unknown record type (`no-kind`).

## Kind on encode from another format

STR requires the mountpoint, CAS the host and port, NET the identifier, and the
closing record requires `ntrip.record_type`.
An entity that fits no kind is `no-kind`.
