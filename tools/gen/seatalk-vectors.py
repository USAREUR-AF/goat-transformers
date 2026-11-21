#!/usr/bin/env python3
"""seatalk-vectors: write the vectors of seatalk1.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are this
program's own restatement of Signal K's SeaTalk hooks: a datagram is the command, the attribute
(low nibble: data octets after the first; high nibble: data in some datagrams), then the data;
16-bit values are sent low octet first except the apparent wind angle (high octet first); depth in
tenths of a foot; apparent wind angle in half degrees; speeds in tenths (0x20, 0x52) or hundredths
(0x26) of a knot; water temperature as (value - 100) / 10 degrees Celsius; latitude and longitude as
whole degrees and a 16-bit word whose top bit is the hemisphere and whose low 15 bits are the minutes
in hundredths; rudder and variation as signed octets.

Inputs: datagrams built here field by field from values chosen here; no datagram is taken from a
document or a capture. `expect` of a round trip is the input. `model` holds values that were packed.

Usage: python3 -I tools/gen/seatalk-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/seatalk-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R = "SignalK/signalk-parser-nmea0183 src/hooks/seatalk/"
P = "seatalk1"


def vec(name, inp, model=None, error=None, ref="", note=""):
    v = {"name": name, "from": P, "to": P, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


def dg(cmd, high, data):
    assert 1 <= len(data) <= 16
    return bytes([cmd, (high << 4) | (len(data) - 1)]) + data


def le16(v):
    return struct.pack("<H", v)


def vectors():
    out = []
    a = dg(0x00, 0, bytes([0x84]) + le16(325))
    out.append(("01-depth-roundtrip.json", vec("depth-roundtrip", a,
                {"@kind": "depth", "seatalk.attribute_length": "2", "seatalk.depth_anchor_alarm": "1", "seatalk.depth_transducer_defective": "1",
                 "seatalk.depth_raw": "325"}, ref=R + "0x00.ts", note="32.5 feet, anchor alarm on, transducer defective")))
    b = dg(0x10, 0, struct.pack(">H", 91))
    out.append(("02-apparent-wind-angle-roundtrip.json", vec("apparent-wind-angle-roundtrip", b,
                {"@kind": "apparent-wind-angle", "seatalk.apparent_wind_angle": "45.5"}, ref=R + "0x10.ts", note="45.5 degrees, high octet first")))
    c = dg(0x11, 0, bytes([0x0C, 0x05]))
    out.append(("03-apparent-wind-speed-roundtrip.json", vec("apparent-wind-speed-roundtrip", c,
                {"seatalk.apparent_wind_speed_units": "0", "seatalk.apparent_wind_speed_knots": "12", "seatalk.apparent_wind_speed_tenths": "5"},
                ref=R + "0x11.ts", note="12.5 knots")))
    d = dg(0x20, 0, le16(64))
    out.append(("04-speed-through-water-roundtrip.json", vec("speed-through-water-roundtrip", d, {"seatalk.speed_through_water": "6.4"},
                ref=R + "0x20.ts")))
    e = dg(0x25, 0x1, le16(0x2345) + le16(1234) + bytes([0x00]))
    out.append(("05-total-and-trip-log-roundtrip.json", vec("total-and-trip-log-roundtrip", e,
                {"@kind": "total-and-trip-log", "seatalk.attribute_high": "1", "seatalk.total_low": str(0x2345), "seatalk.trip_low": "1234",
                 "seatalk.trip_high": "0"}, ref=R + "0x25.ts", note="total (1 x 65536 + 0x2345) / 10 nm, trip 12.34 nm")))
    f = dg(0x26, 0, le16(650) + le16(612) + bytes([0x40]))
    out.append(("06-speed-through-water-2-roundtrip.json", vec("speed-through-water-2-roundtrip", f,
                {"seatalk.speed_sensor_1": "6.5", "seatalk.speed_sensor_2_or_average": "6.12", "seatalk.speed_flags_d": "4", "seatalk.speed_flags_e": "0"},
                ref=R + "0x26.ts")))
    g = dg(0x27, 0, le16(285))
    out.append(("07-water-temperature-roundtrip.json", vec("water-temperature-roundtrip", g, {"seatalk.water_temperature": "18.5"},
                ref=R + "0x27.ts", note="(285 - 100) / 10 = 18.5 degrees Celsius")))
    h = dg(0x50, 0, bytes([52]) + le16(0x8000 | 1234))
    out.append(("08-latitude-south-roundtrip.json", vec("latitude-south-roundtrip", h,
                {"@kind": "latitude", "seatalk.latitude_degrees": "52", "seatalk.latitude_minutes_raw": str(0x8000 | 1234)},
                ref=R + "0x50.ts", note="52 degrees 12.34 minutes south")))
    i = dg(0x51, 0, bytes([4]) + le16(0x8000 | 5321))
    out.append(("09-longitude-east-roundtrip.json", vec("longitude-east-roundtrip", i,
                {"seatalk.longitude_degrees": "4", "seatalk.longitude_minutes_raw": str(0x8000 | 5321)}, ref=R + "0x51.ts")))
    j = dg(0x54, 0x7, bytes([(30 << 2) | 2, 14]))
    out.append(("10-gmt-time-roundtrip.json", vec("gmt-time-roundtrip", j,
                {"@kind": "gmt-time", "seatalk.attribute_high": "7", "seatalk.time_rs": str((30 << 2) | 2), "seatalk.time_hours": "14"},
                ref=R + "0x54.ts", note="14:30:39 (seconds 2 x 16 + 7)")))
    k = dg(0x84, 0x2, bytes([0x2D, 0x5A, 0x02, 0x04, 0xFE, 0x00, 0x08]))
    out.append(("11-heading-course-rudder-roundtrip.json", vec("heading-course-rudder-roundtrip", k,
                {"@kind": "heading-course-rudder", "seatalk.heading_vw": str(0x2D), "seatalk.autopilot_mode": "2", "seatalk.alarms": "4",
                 "seatalk.rudder_position": "-2", "seatalk.autopilot_tt": "8"},
                ref=R + "0x84.ts", note="auto mode, off-course alarm, rudder 2 degrees to port")))
    m = dg(0x99, 0, bytes([0xFE]))
    out.append(("12-compass-variation-roundtrip.json", vec("compass-variation-roundtrip", m, {"seatalk.compass_variation": "-2"},
                ref=R + "0x99.ts", note="variation 2 degrees east")))
    n = dg(0x82, 0, bytes([0x15, 0xEA, 0x63, 0x9C, 0x2A, 0xD5]))
    out.append(("13-target-waypoint-name-roundtrip.json", vec("target-waypoint-name-roundtrip", n,
                {"seatalk.waypoint_xx": str(0x15), "seatalk.waypoint_xx_complement": str(0xEA)}, ref=R + "0x82.ts",
                note="each name octet followed by its complement")))
    o = dg(0x65, 0, bytes([0x02]))
    out.append(("14-other-datagram-roundtrip.json", vec("other-datagram-roundtrip", o,
                {"@kind": "other", "seatalk.command": str(0x65), "seatalk.data_first": "2", "seatalk.data_more.#": "0"},
                ref=R + "index.ts", note="a datagram the parser does not decode (0x65), kept as its octets")))
    out.append(("15-cut-depth-is-malformed.json", vec("cut-depth-is-malformed", a[:4], error="malformed-wire",
                ref=R + "0x00.ts", note="the depth word is cut")))
    return out


def build(out):
    vs = vectors()
    for fname, v in vs:
        out.write("packs/%s/vectors/%s" % (P, fname), json.dumps(v, indent=2) + "\n")
    return {P: len(vs)}


def main(argv=None):
    return genio.vector_main("seatalk-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
