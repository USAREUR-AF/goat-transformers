# Golden vectors for packs/mavlink2 from pymavlink

`tools/gen/golden-pymavlink.py` writes `packs/mavlink2/vectors/golden-*.json`
from pymavlink 2.4.50, the reference MAVLink implementation, without an
engine (shared-model hardening, item 2). Each vector is a frame as pymavlink
packs it (the CRC left off, as the pack maps none), a round trip, and a
`model` of every key whose value follows from its field line.

On 24 Nov 2026: 200 vectors for the 235 kinds of the pack; the rest are below.

## Findings for the pack, and where they stand

1. **A same-format round trip lost microseconds** (fixed): `system_time`,
   `camera_image_captured` and `utm_global_position` mapped a uint64
   microsecond time to `time_ms`, so the frame that came back differed. After
   #335 and #338 their golden vectors pass, and the skip list is empty.
2. **MAVLink 2 payload truncation** (handled by the adapters, #338): every
   kind selects on the full payload length (`when 0:8:8 <length>`). A MAVLink
   2 sender drops the trailing zero bytes of the payload
   (https://mavlink.io/en/guide/serialization.html#payload_truncation).
   `goat-xf-pipe`'s framing `mavlink2` zero-fills each payload to its
   message's full length before the engine sees it, as the guide asks of a
   receiver. The library's `convert` still takes the full-length payload: a
   trimmed frame given to it directly (pymavlink's GLOBAL_POSITION_INT with
   `hdg` 0, LEN 25) is `no-kind`. The golden vectors are full length.
3. **uint64 fields above 2^63** (open): the shared model's `int` is 64-bit
   signed, so a uint64 value of 2^63 or more cannot be a model value. The
   vectors keep the top byte below 0x80.

## Kinds without a vector for other reasons

- Messages that pymavlink 2.4.50's common dialect does not define, or defines
  shorter than the pack's message set (the pack follows a later common.xml):
  the generator writes no vector for them.
