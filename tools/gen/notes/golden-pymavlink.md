# Golden vectors for packs/mavlink2 from pymavlink

`tools/gen/golden-pymavlink.py` writes `packs/mavlink2/vectors/golden-*.json`
from pymavlink 2.4.50, the reference MAVLink implementation, without an
engine (shared-model hardening, item 2). Each vector is a frame as pymavlink
packs it (the CRC left off, as the pack maps none), a round trip, and a
`model` of every key whose value follows from its field line.

On 21 Nov 2026: 197 vectors for the 235 kinds of the pack; the rest are below.

## Findings for the pack (not written as vectors)

1. **A same-format round trip loses microseconds** (`golden-pymavlink-skip.txt`):
   `system_time`, `camera_image_captured` and `utm_global_position` map a
   uint64 microsecond time to `time_ms`. Encoding writes the millisecond
   value back, so the frame that returns differs from the one that came in.
   A same-format round trip is lossless by the shared model's guarantee; the
   microseconds need a raw key (or `time_ns`, spec 0.45) beside `time_ms`.
2. **MAVLink 2 payload truncation**: every kind selects on the full payload
   length (`when 0:8:8 <length>`), extension fields included. A MAVLink 2
   sender drops the trailing zero bytes of the payload
   (https://mavlink.io/en/guide/serialization.html#payload_truncation), so a
   frame whose last fields are zero (or that leaves the extensions out) has
   a shorter LEN and selects no kind. pymavlink does this: GLOBAL_POSITION_INT
   with `hdg` 0 goes out with LEN 25, not 28, and decodes to `no-kind`. The
   golden vectors avoid it (every covered byte non-zero); real traffic does
   not.
3. **uint64 fields above 2^63**: the shared model's `int` is 64-bit signed, so
   a uint64 value of 2^63 or more cannot be a model value. The vectors keep
   the top byte below 0x80.

## Kinds without a vector for other reasons

- Messages that pymavlink 2.4.50's common dialect does not define, or defines
  shorter than the pack's message set (the pack follows a later common.xml):
  the generator writes no vector for them.
