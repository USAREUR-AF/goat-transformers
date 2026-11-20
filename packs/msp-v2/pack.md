# Pack: msp-v2

MSP version 2 (INAV): the same four replies as `msp`, carried in the v2 frame, and
MSP2_INAV_ANALOG. Written by hand from INAV's message definitions and its MSP serial code
(`src/main/msp/msp_serial.c`, `msp_serial.h`), which lays out the v2 frame. Wire `bits`, least-significant-bit first, one byte per word. Five kinds.

## The message

One v2 reply frame without its CRC byte: `$` `X` `>` (common `when` lines), a flag byte
(raw key `msp2.flag`), the command (u16), the payload size (u16), the payload. Command and
size are each kind's `when`. The CRC (CRC-8 DVB-S2 over flag, command, size and payload)
follows the payload and is not read or written.

| Kind | Command | Size | Payload |
|---|---|---|---|
| `raw_gps`, `attitude`, `altitude`, `analog` | 106, 108, 109, 110 | as in `msp` | as in `msp` |
| `inav_analog` | 0x2002 MSP2_INAV_ANALOG | 24 | battery flags (u8), voltage (u16, 0.01 V), current (i16, 0.01 A), power (u32, 0.01 W), consumed capacity (u32, mAh) and energy (u32, mWh), remaining capacity (u32), remaining percentage (u8), RSSI (u16) |

## Evidence for the shared keys

As in `msp`: `lat`, `lon`, `speed_ms` and `course` of `raw_gps`.

## Not mapped

As in `msp`, and every other v2 message. The battery flags byte is one raw key (its bit
fields are not split).

## Vectors

Written by `tools/gen/rc-telemetry-vectors.py` (no engine): a round trip per kind.
