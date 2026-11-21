#!/usr/bin/env python3
"""Write the ais-binary-regional pack and its module: the St. Lawrence Seaway and USCG PAWSS AIS binary
messages (DAC 316 Canada and 366 United States, FI 1, 2 and 32), from the Seaway's AIS Data Messaging
Formats and Specifications, Revision 4.1, which gpsd's AIVDM document names as their description.

Each application is a message ID after the DAC and FI, and most repeat a report to the end of the
payload, so the pack is a sequential layout with `armor sixbit`, chosen by `switch` blocks on the
message type, DAC, FI and message ID. The header is on the `ais` and `aisbin` keys of `ais-binary`.
The vectors are not written here: tools/gen/ais-regional-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/ais-regional-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = ('source        "St. Lawrence Seaway AIS Data Messaging Formats and Specifications, Harmonized with U.S. Coast Guard '
       'PAWSS AIS Messages, Revision 4.1, April 9, 2010 (U.S. DOT Volpe Center for the SLSDC and SLSMC), '
       'https://greatlakes-seaway.com/wp-content/uploads/2020/05/Seaway-AIS-message-specifications-R41.pdf (sha256 '
       '79da3b8f29acf7543ff440903769a702c98bd7dc4dba438720c75150262b917d), no licence stated; layout restated"')
M = "aisregion"


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


def f(k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (M, k, b, tr)


def group(lst, body):
    return ["group  %s.%s  rest" % (M, lst)] + ind(1, body) + ["end"]


def timetag(p=""):
    return [f(p + "month", 4), f(p + "day", 5), f(p + "hour", 5), f(p + "minute", 6)]


def station():
    return timetag() + [f("station_id", 42, "sixbit"), f("lon", 25, "twos"), f("lat", 24, "twos")]


FI1 = [  # message ID, report body after the station block
    ("1", [f("wind_speed", 10), f("wind_gust", 10), f("wind_dir", 9), f("pressure", 14), f("air_temp", 10, "twos"),
           f("dew_point", 10, "twos"), f("visibility", 8), f("water_temp", 10, "twos")]),
    ("2", [f("wind_speed", 10), f("wind_gust", 10), f("wind_dir", 9), f("report_spare", 4)]),
    ("3", [f("level_type", 1), f("level", 16, "twos"), f("level_datum", 2), f("reading_type", 2), f("report_spare", 12)]),
    ("4", [f("current_speed", 8), f("current_dir", 9), f("report_spare", 16)]),
    ("5", [f("salinity", 10), f("water_temp", 10, "twos"), f("report_spare", 13)]),
    ("6", [f("water_flow", 14), f("report_spare", 19)]),
]


def seaway():
    fi1 = sw("aisregion.message_id", [(mid, group("reports", station() + body)) for mid, body in FI1])
    lockage = (timetag() + [f("lock_id", 42, "sixbit"), f("lon", 25, "twos"), f("lat", 24, "twos"), f("lock_spare", 9)] +
               group("schedule", [f("vessel_name", 90, "sixbit"), f("upbound", 1)] + timetag("eta_") + [f("schedule_spare", 9)]))
    locktimes = (timetag() + [f("vessel_name", 90, "sixbit"), f("last_location", 42, "sixbit")] + timetag("ata_") +
                 [f("first_lock", 42, "sixbit")] + timetag("first_eta_") + [f("second_lock", 42, "sixbit")] +
                 timetag("second_eta_") + [f("delay_lock", 42, "sixbit"), f("locktimes_spare", 4)])
    fi2 = sw("aisregion.message_id", [("1", lockage), ("2", locktimes)])
    fi32 = sw("aisregion.message_id", [("1", [f("major_version", 8), f("minor_version", 8), f("version_spare", 8)])])
    return sw("aisbin.fid", [("1", [f("reserved", 2), f("message_id", 6)] + fi1),
                             ("2", [f("reserved", 2), f("message_id", 6)] + fi2),
                             ("32", [f("reserved", 2), f("message_id", 6)] + fi32)])


def pack():
    L = ["# St. Lawrence Seaway and USCG PAWSS AIS binary messages (DAC 316 and 366): FI 1 meteorological and",
         "# hydrological reports (weather, wind, water level, current, salinity and temperature, water flow), FI 2 lock",
         "# scheduling (lockage order, estimated lock times), FI 32 version. The input is the armored payload of a type 6",
         "# or type 8 message. Written by tools/gen/ais-regional-pack.py; do not edit by hand.",
         "format        ais-binary-regional", "version       0.1.0", "distribution  public", SRC,
         "uses          ais", "uses          aisbin", "uses          %s" % M,
         "wire          bits", "layout        sequential", "bit_order     msb", "armor         sixbit", "",
         "field  ais.msg_type  6  uint", "field  ais.repeat  2  uint", "field  ais.mmsi  30  uint"]
    addressed = (["field  aisbin.seqno  2  uint", "field  ais.dest_mmsi  30  uint", "field  aisbin.retransmit  1  uint",
                  "field  ais.spare  1  uint", "field  aisbin.dac  10  uint", "field  aisbin.fid  6  uint"] +
                 sw("aisbin.dac", [("316,366", seaway())]))
    broadcast = (["field  ais.spare  2  uint", "field  aisbin.dac  10  uint", "field  aisbin.fid  6  uint"] +
                 sw("aisbin.dac", [("316,366", seaway())]))
    L += sw("ais.msg_type", [("6", addressed), ("8", broadcast)])
    return "\n".join(L) + "\n"


T = "UTC; month 1-12 (0 not available), day 1-31 (0), hour 0-23 (24), minute 0-59 (60)"
KEYS = [
    ("key", "reserved", "the 2 reserved bits after the FI"),
    ("key", "message_id", "the Seaway message ID within the FI (FI 1: 1 weather, 2 wind, 3 water level, 4 hydro current, 5 hydro salinity and temperature, 6 water flow; FI 2: 1 lockage order, 2 estimated lock times; FI 32: 1 version)"),
    ("key", "month", "time tag month, " + T), ("key", "day", "time tag day"), ("key", "hour", "time tag hour"),
    ("key", "minute", "time tag minute"),
    ("list", "reports", "FI 1: the station reports, 1 to 6 (1 to 4 for weather), to the end of the payload"),
    ("key", "station_id", "station ID, seven six-bit characters"),
    ("key", "lon", "longitude, thousandths of a minute, signed, east positive; 181 degrees not available"),
    ("key", "lat", "latitude, thousandths of a minute, signed, north positive; 91 degrees not available"),
    ("key", "wind_speed", "average wind speed, tenths of a knot; 1022 is 102.2 knots or more, 1023 not available"),
    ("key", "wind_gust", "wind gust, tenths of a knot; 1022 is 102.2 knots or more, 1023 not available"),
    ("key", "wind_dir", "wind direction, degrees (quantized to 16 points by the Seaway); 511 not available"),
    ("key", "pressure", "atmospheric pressure, tenths of a millibar; 16383 not available"),
    ("key", "air_temp", "air temperature, tenths of a degree Celsius, signed; -512 not available"),
    ("key", "dew_point", "dew point, tenths of a degree Celsius, signed; -512 not available"),
    ("key", "visibility", "visibility, tenths of a kilometre; 254 is 25.4 km or more, 255 not available"),
    ("key", "water_temp", "water temperature, tenths of a degree Celsius, signed; -512 not available"),
    ("key", "report_spare", "the reserved bits at the end of a report"),
    ("key", "level_type", "water level type: 0 relative to the datum, 1 water depth"),
    ("key", "level", "water level, centimetres, signed; -32768 not available"),
    ("key", "level_datum", "reference datum: 0 MLLW, 1 IGLD-85"),
    ("key", "reading_type", "reading type: 0 average of actual readings, 1 estimated from adjacent sensors"),
    ("key", "current_speed", "PAWSS current speed, tenths of a knot"),
    ("key", "current_dir", "PAWSS current direction (travelling toward), degrees"),
    ("key", "salinity", "PAWSS salinity, tenths of a practical salinity unit"),
    ("key", "water_flow", "water flow, cubic metres per second; 16383 not available"),
    ("key", "lock_id", "lockage order: the lock, seven six-bit characters"),
    ("key", "lock_spare", "lockage order: the 9 reserved bits before the schedule"),
    ("list", "schedule", "lockage order: the lock schedule reports, 1 to 6"),
    ("key", "vessel_name", "vessel name, fifteen six-bit characters"),
    ("key", "upbound", "lock schedule: 1 upbound, 0 downbound"),
    ("key", "eta_month", "lock schedule ETA month"), ("key", "eta_day", "lock schedule ETA day"),
    ("key", "eta_hour", "lock schedule ETA hour"), ("key", "eta_minute", "lock schedule ETA minute"),
    ("key", "schedule_spare", "lock schedule: the 9 reserved bits"),
    ("key", "last_location", "estimated lock times: the last location, seven six-bit characters"),
    ("key", "ata_month", "estimated lock times: last ATA month"), ("key", "ata_day", "last ATA day"),
    ("key", "ata_hour", "last ATA hour"), ("key", "ata_minute", "last ATA minute"),
    ("key", "first_lock", "estimated lock times: the first lock, seven six-bit characters"),
    ("key", "first_eta_month", "first lock ETA month"), ("key", "first_eta_day", "first lock ETA day"),
    ("key", "first_eta_hour", "first lock ETA hour"), ("key", "first_eta_minute", "first lock ETA minute"),
    ("key", "second_lock", "estimated lock times: the second lock, seven six-bit characters"),
    ("key", "second_eta_month", "second lock ETA month"), ("key", "second_eta_day", "second lock ETA day"),
    ("key", "second_eta_hour", "second lock ETA hour"), ("key", "second_eta_minute", "second lock ETA minute"),
    ("key", "delay_lock", "estimated lock times: the first lock where a vessel is delayed, seven six-bit characters"),
    ("key", "locktimes_spare", "estimated lock times: the 4 reserved bits"),
    ("key", "major_version", "version message: major revision of the specification in use"),
    ("key", "minor_version", "version message: minor revision"),
    ("key", "version_spare", "version message: the 8 reserved bits"),
]
STRINGS = ["station_id", "lock_id", "vessel_name", "last_location", "first_lock", "second_lock", "delay_lock"]


def module():
    w = max(len(k[1]) for k in KEYS)
    L = ["# The aisregion module: St. Lawrence Seaway and USCG PAWSS AIS binary messages. Written by tools/gen/ais-regional-pack.py.",
         "module        %s" % M, "version       0.1.0", "distribution  public", SRC]
    for k in KEYS:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], "string" if k[1] in STRINGS else "int", k[2]))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/ais-binary-regional/pack.def", pack())
    out.write("model/aisregion.def", module())
    return {"ais-regional": 2}


def main(argv=None):
    return genio.vector_main("ais-regional-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
