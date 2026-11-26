# dsmr-p1-line

One line of a P1 telegram of a Dutch smart meter (DSMR 5.0.2). Licence `LicenseRef-unstated`
(PROVENANCE.md).

## Message convention

A P1 telegram is a header line, data lines and an end line with a CRC16, separated by CR LF. The
`text` wire reads one record of one line (engine-spec 0.10: one line terminator, characters 0x20 to
0x7E), so the message of this pack is one line of the telegram, without its CR LF. The telegram as
a whole, and its CRC16 (computed over the whole telegram from '/' to '!'), are outside the pack.

## Kinds

`delimiter "("`: field 0 is the OBIS reduced code, field 1 the first value with its unit and ')'.
Each object of the standard's table is a kind selected by its OBIS code (`when 0 <code>`); the
header line by its first character '/' and the end line by '!'. A number in a fixed format is a
column of field 1 read through `dec:<f>:<w>` or `int:<w>`, and the text after it ('*kWh)', ')')
is a `const`, so a line round-trips. A value of variable length (the equipment identifier, the
text message, the M-Bus value whose width and unit depend on the medium, the entries of the power
failure log) is the field as sent, its ')' included. The M-Bus objects are one kind per channel 1
to 4, with the channel as a key.

On encode with no recorded kind (a library entity, or a conversion), each kind requires a key
of its own, so an entity is written as the line whose value it holds (before, every such entity
was written as the header line `/`). The four M-Bus channels' kinds have the same keys and differ
only in the channel digit inside their OBIS code, so `requires` reaches the channel 1 kind only:
an M-Bus entity of channel 2, 3 or 4 is written as channel 1. Choosing a kind by a key's value
is a language addition (`requires` on a value).

## Shared keys

None. The date-time line 0-0:1.0.0 (YYMMDDhhmmssX) is kept as text and not bound to `time_ms`:
it is local time, X saying whether daylight saving time applies (S) or not (W), and no transform
reads that form as UTC. Missing: a transform for YYMMDDhhmmss with a summer/winter letter and a
stated zone. Readings are energy, power, voltage and current, which have no shared key.

## Not mapped

- The telegram as one message, and its CRC16 (a CRC over several lines; the `text` wire reads one
  line and knows only the NMEA checksum).
- OBIS codes outside the standard's table are `no-kind`. A value written in another width than its
  format is `transform-decode`.
