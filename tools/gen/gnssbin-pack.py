#!/usr/bin/env python3
"""Write the GNSS receiver binary packs not yet in the catalogue, and their modules:

- novatel-oem-binary: a NovAtel OEM binary log: the 28-octet header (sync, header length, message
  ID, type, port, message length, sequence, idle time, time status, week, milliseconds, receiver
  status, reserved, software version) and, for BESTPOS (42), its 72 octets and the CRC; other logs'
  data and CRC as octets. Layout restated from swri-robotics/novatel_gps_driver (binary_header.h,
  parsers/bestpos.cpp, parsers/bestpos.h).
- sirf-binary: a SiRF binary frame (start A0 A2, payload length, payload, checksum, end B0 B3) and,
  for message ID 41 (Geodetic Navigation Data), the fields gpsd reads; other payloads as octets.
  Layout restated from gpsd drivers/driver_sirf.c.

u-blox UBX, Septentrio SBF and RTCM 3 are already in the catalogue (ubx-*, sbf-*, rtcm3).
The vectors are not written here: tools/gen/gnssbin-vectors.py derives them with an encoder of its
own.

Usage: python3 -I tools/gen/gnssbin-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

NV = "63e19e2e3088e80ecceaa18d86022afffb3ccaf3"
GP = "edd38e78a875062f53add5c1ade745761240fffb"
SRC = {
    "nv": ('source        "swri-robotics/novatel_gps_driver, https://github.com/swri-robotics/novatel_gps_driver at commit %s, '
           'novatel_gps_driver/include/novatel_gps_driver/binary_header.h, src/parsers/bestpos.cpp, include/.../parsers/bestpos.h '
           '(BSD-3-Clause, Copyright (c) 2017 Southwest Research Institute); layout restated, no code copied; NovAtel documentation '
           'not used"' % NV),
    "sirf": ('source        "gpsd, https://gitlab.com/gpsd/gpsd at commit %s, drivers/driver_sirf.c (BSD-2-Clause, compilation '
             'copyright the GPSD project); layout restated, no code copied; the SiRF protocol reference not used"' % GP),
}


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def sw(key, cases, other=None):
    L = ["switch  %s" % key]
    for vals, lines in cases:
        L.append("  case  %s" % vals)
        L += ind(2, lines)
    if other is not None:
        L.append("  else")
        L += ind(2, other)
    L.append("end")
    return L


def F(k, b, tr="uint"):
    return "field  %s  %d  %s" % (k, b, tr)


def octets(lst, octet):
    return ["group  %s  rest" % lst, "  " + F(octet, 8), "end"]


def head(name, comment, src, uses, order):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC[src]] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     %s" % order, ""])


def module(name, header, src, keys):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", SRC[src]]
    for k in keys:
        t, n, d = k[0], k[1], k[2]
        unit = k[3] if len(k) > 3 else "-"
        L.append('list  %-*s  "%s"' % (w, n, d) if t == "list" else 'key   %-*s  %-6s  %-4s  "%s"' % (w, n, t, unit, d))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- NovAtel

def novatel_pack():
    n = "novatel."
    bestpos = [F(n + "solution_status", 32), F(n + "position_type", 32), F(n + "latitude", 64, "f64"), F(n + "longitude", 64, "f64"),
               F(n + "height", 64, "f64"), F(n + "undulation", 32, "f32"), F(n + "datum_id", 32), F(n + "latitude_sigma", 32, "f32"),
               F(n + "longitude_sigma", 32, "f32"), F(n + "height_sigma", 32, "f32"), "field  novatel.base_station_id  32  chars:ascii8",
               F(n + "differential_age", 32, "f32"), F(n + "solution_age", 32, "f32"), F(n + "satellites_tracked", 8),
               F(n + "satellites_in_solution", 8), F(n + "satellites_l1", 8), F(n + "satellites_multi_frequency", 8),
               F(n + "reserved_68", 8), F(n + "extended_solution_status", 8), F(n + "signals_used", 8), F(n + "reserved_71", 8),
               F(n + "crc", 32)]
    L = head("novatel-oem-binary", ["NovAtel OEM binary log: the 28-octet header and, for BESTPOS, its fields and the CRC. Written by",
                                    "tools/gen/gnssbin-pack.py; do not edit by hand."], "nv", ["novatel"], "lsb")
    L += ["kind  oem-binary", "when  8  170", "const  8  68", "const  8  18",
          F(n + "header_length", 8), F(n + "message_id", 16), F(n + "message_type", 8), F(n + "port_address", 8),
          F(n + "message_length", 16), F(n + "sequence", 16), F(n + "idle_time", 8), F(n + "time_status", 8), F(n + "week", 16),
          F(n + "gps_milliseconds", 32), F(n + "receiver_status", 32), F(n + "reserved", 16), F(n + "software_version", 16)]
    L += sw("novatel.message_id", [("42", bestpos)], octets("novatel.data_and_crc", "novatel.octet"))
    return "\n".join(L) + "\n"


NOVATEL_KEYS = [
    ("int", "header_length", "header length in octets (28)"), ("int", "message_id", "message ID (42 BESTPOS ...)"),
    ("int", "message_type", "message type octet (format and response bits)"), ("int", "port_address", "port address"),
    ("int", "message_length", "length of the data after the header, octets, as sent"), ("int", "sequence", "sequence number"),
    ("int", "idle_time", "processor idle time, as sent"),
    ("int", "time_status", "Receiver time status (20 unknown, 60 approximate, 80 coarse adjusting, 100 coarse, 120 coarse steering, 130 freewheeling, 140 fine adjusting, 160 fine, 170 fine backup steering, 180 fine steering, 200 sattime)"),
    ("int", "week", "GPS week number"), ("int", "gps_milliseconds", "milliseconds into the GPS week", "ms"),
    ("int", "receiver_status", "receiver status word"), ("int", "reserved", "reserved"), ("int", "software_version", "receiver software build"),
    ("int", "solution_status", "BESTPOS: solution status"), ("int", "position_type", "BESTPOS: position type"),
    ("float", "latitude", "BESTPOS: latitude, in the datum of datum_id"), ("float", "longitude", "BESTPOS: longitude, in the datum of datum_id"),
    ("float", "height", "BESTPOS: height (the reference is not stated by the source; see pack.md)"),
    ("float", "undulation", "BESTPOS: undulation"), ("int", "datum_id", "BESTPOS: datum identifier"),
    ("float", "latitude_sigma", "BESTPOS: latitude standard deviation"), ("float", "longitude_sigma", "BESTPOS: longitude standard deviation"),
    ("float", "height_sigma", "BESTPOS: height standard deviation"), ("string", "base_station_id", "BESTPOS: base station ID, 4 characters"),
    ("float", "differential_age", "BESTPOS: differential age"), ("float", "solution_age", "BESTPOS: solution age"),
    ("int", "satellites_tracked", "BESTPOS: satellites tracked"), ("int", "satellites_in_solution", "BESTPOS: satellites used in the solution"),
    ("int", "satellites_l1", "BESTPOS: GPS and GLONASS L1 satellites used"),
    ("int", "satellites_multi_frequency", "BESTPOS: GPS and GLONASS L1 and L2 satellites used"),
    ("int", "reserved_68", "BESTPOS: octet 68 (not named by the source)"), ("int", "extended_solution_status", "BESTPOS: extended solution status"),
    ("int", "signals_used", "BESTPOS: signals-used mask"), ("int", "reserved_71", "BESTPOS: octet 71 (not named by the source)"),
    ("int", "crc", "the 32-bit CRC after the data, as sent (not computed)"),
    ("list", "data_and_crc", "another log's data and its 4-octet CRC, as octets"), ("int", "octet", "one octet"),
]


# ---------------------------------------------------------------- SiRF

def sirf_pack():
    s = "sirf."
    geodetic = [F(s + "unread_1", 16, "hex"), F(s + "nav_type", 16), F(s + "extended_week", 16), F(s + "time_of_week", 32),
                F(s + "utc_year", 16), F(s + "utc_month", 8), F(s + "utc_day", 8), F(s + "utc_hour", 8), F(s + "utc_minute", 8),
                F(s + "utc_second_ms", 16), F(s + "unread_19", 32, "hex"),
                F("lat", 32, "sscale:1/10000000"), F("lon", 32, "sscale:1/10000000"), F("hae", 32, "sscale:1/100"),
                F(s + "altitude_msl", 32, "sscale:1/100"), F(s + "map_datum", 8), F(s + "speed", 16, "uscale:1/100"),
                F(s + "track", 16, "uscale:1/100"), F(s + "unread_44", 16, "hex"), F(s + "climb", 16, "sscale:1/100"),
                F(s + "unread_48", 16, "hex"), F(s + "horizontal_error", 32, "uscale:1/100"), F(s + "vertical_error", 32, "uscale:1/100"),
                F(s + "unread_58", 32, "hex"), F(s + "speed_error", 16, "uscale:1/100"), F(s + "unread_64", 200, "hex"),
                F(s + "hdop", 8, "uscale:1/5"), F(s + "unread_90", 8, "hex")]
    L = head("sirf-binary", ["SiRF binary frame: start, length, payload, checksum, end; the Geodetic Navigation Data message (41)",
                             "laid out. Written by tools/gen/gnssbin-pack.py; do not edit by hand."], "sirf", ["sirf"], "msb")
    L += ["kind  sirf", "when  16  41122", "length  16  bytes", "  " + F(s + "message_id", 8)]
    L += ind(1, sw("sirf.message_id", [("41", geodetic)], octets("sirf.payload", "sirf.octet")))
    L += ["end", F(s + "checksum", 16), "const  16  45235"]
    return "\n".join(L) + "\n"


SIRF_KEYS = [
    ("int", "message_id", "message ID (41 Geodetic Navigation Data, 2 Measure Navigation Data, 4 tracker data ...)"),
    ("string", "unread_1", "MID 41 octets 1-2, which the source does not read, as hexadecimal digits"),
    ("int", "nav_type", "MID 41: navigation type (bits 2-0: 0 no fix, 4 and 6 a 3-D fix, 7 dead reckoning; bit 7 DGPS)"),
    ("int", "extended_week", "MID 41: extended GPS week"), ("int", "time_of_week", "MID 41: time of week in the GPS week", "ms"),
    ("int", "utc_year", "MID 41: UTC year"), ("int", "utc_month", "MID 41: UTC month"), ("int", "utc_day", "MID 41: UTC day"),
    ("int", "utc_hour", "MID 41: UTC hour"), ("int", "utc_minute", "MID 41: UTC minute"),
    ("int", "utc_second_ms", "MID 41: UTC seconds", "ms"),
    ("string", "unread_19", "MID 41 octets 19-22 (not read by the source)"),
    ("float", "altitude_msl", "MID 41: altitude above mean sea level", "m"), ("int", "map_datum", "MID 41: map datum code"),
    ("float", "speed", "MID 41: speed over ground", "m/s"), ("float", "track", "MID 41: course over ground (true)", "deg"),
    ("string", "unread_44", "MID 41 octets 44-45 (magnetic variation; not read by the source)"),
    ("float", "climb", "MID 41: climb rate", "m/s"), ("string", "unread_48", "MID 41 octets 48-49 (not read by the source)"),
    ("float", "horizontal_error", "MID 41: horizontal position error estimate (EHPE)", "m"),
    ("float", "vertical_error", "MID 41: vertical position error estimate (EVPE)", "m"),
    ("string", "unread_58", "MID 41 octets 58-61 (not read by the source)"),
    ("float", "speed_error", "MID 41: horizontal velocity error estimate (EHVE)", "m/s"),
    ("string", "unread_64", "MID 41 octets 64-88 (not read by the source)"),
    ("float", "hdop", "MID 41: HDOP"), ("string", "unread_90", "MID 41 octet 90 (not read by the source)"),
    ("list", "payload", "another message's payload after its ID, as octets"),
    ("int", "checksum", "the 15-bit checksum, as sent (not computed)"), ("int", "octet", "one octet"),
]


def build(out):
    out.write("packs/novatel-oem-binary/pack.def", novatel_pack())
    out.write("packs/sirf-binary/pack.def", sirf_pack())
    out.write("model/novatel.def", module("novatel", ["# The novatel module: NovAtel OEM binary header and BESTPOS fields. Written by tools/gen/gnssbin-pack.py."], "nv", NOVATEL_KEYS))
    out.write("model/sirf.def", module("sirf", ["# The sirf module: SiRF binary frame and Geodetic Navigation Data fields. Written by tools/gen/gnssbin-pack.py."], "sirf", SIRF_KEYS))
    return {"gnssbin": 4}


def main(argv=None):
    return genio.vector_main("gnssbin-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
