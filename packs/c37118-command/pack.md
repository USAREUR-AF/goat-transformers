# c37118-command

IEEE C37.118.2 synchrophasor frame. A command frame without extended data: 18 bytes.

## Source and status

IEEE Std C37.118.2 is a paid IEEE standard and is not used. The layouts are those
that pypmu (BSD-3-Clause), an implementation of C37.118.2-2011, writes and reads;
they are restated here in this repository's own words. See PROVENANCE.md.

## Message convention

One message is one frame, as hex text, every number big-endian (`bit_order msb`).
Every frame starts with the common header and ends with CHK:

| Bytes | Content | Keys |
|---|---|---|
| 0 | 0xAA | common `when` |
| 1 | a reserved bit (0), the frame type (3 bits), the version (4 bits) | the kind's `when`; `c37118.version` |
| 2-3 | FRAMESIZE, the whole frame in bytes | the kind's `when` (each pack has fixed sizes) |
| 4-5 | IDCODE | `c37118.idcode` |
| 6-9 | SOC, seconds since 1970-01-01 UTC | `c37118.soc` |
| 10 | a reserved bit, the leap second direction, occurred and pending flags, the time quality code (4 bits) | `c37118.leap_*`, `c37118.time_quality`, `time_error_ms` |
| 11-13 | FRACSEC, the fraction of the second in counts of TIME_BASE | `c37118.fracsec` |
| last 2 | CHK, CRC-CCITT (0x1021, initial 0xFFFF) of the bytes before it | `c37118.chk` |

## Shared keys

| Key | Field | Evidence |
|---|---|---|
| `time_error_ms` | the message time quality code | pypmu's table of the code: 0 locked to UTC, n from 1 to 11 within 10^(n-10) s of UTC, 15 clock failure. Codes 1 to 11 map to their bound in milliseconds (`tq_bound`); 0 states no bound and 15 a failure, so the key is absent for them (`absent 0,12,13,14,15`) |

No other key binds. A synchrophasor frame carries no position.

## Not mapped, and why

| What | Why |
|---|---|
| `time_ms` | the frame time is SOC + FRACSEC / TIME_BASE. TIME_BASE is in the configuration frame (another message), and with the common base of 1,000,000 a fraction in microseconds is a whole number of milliseconds only when it is a multiple of 1000: the sum is not exact in general. SOC and FRACSEC are raw keys |
| `uid` | IDCODE is an integer and `uid` text; no `bits` transform writes an integer as text |
| CHK as a check | the `bits` wire computes no CRC: CHK is carried, so a frame written from another format, or with changed values, has a wrong CHK. Decode does not check it |
| other configurations | the data frame's layout is set by the configuration frame (the numbers of phasors, analogs and digital words and the FORMAT bits). Each pack is one configuration, selected by FRAMESIZE; another configuration needs its own pack. A layout chosen by the values of another message is not a construct of the pack language |
| more than one PMU in a frame | the per-PMU blocks repeat NUM_PMU times, and each block's size depends on its own counts and format bits |
| configuration frame 3 | its variable-length names and extra fields (PMU location, service class, window lengths) |
| header frame (type 1) | its ASCII text runs to two bytes before the end of the frame: a `rest` group must be the last line of its extent, and CHK follows the text |
| command frames with extended data | the data runs to CHK, as for the header frame |
| phasor and analog units applied to values | the 16-bit integer phasors are scaled by PHUNIT of the configuration frame: values of another message |

## Vectors

`tools/gen/c37118-vectors.py` builds every frame with `struct`, CHK included, from values
it chooses; no sample frame of the standard or of pypmu is used. No engine is run.
