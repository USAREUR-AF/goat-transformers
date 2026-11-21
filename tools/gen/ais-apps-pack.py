#!/usr/bin/env python3
"""Write the ais-binary-apps pack and its module: the AIS binary application messages of variable length
that gpsd's AIVDM document describes and pack `ais-binary` does not build (type 6 DAC 1 FI 14, 25, 28,
32; type 8 DAC 1 FI 17, 26, 27). The text descriptions (FI 29 and 30) are not built: see pack.md.

Each repeats a record to the end of the payload, so the pack uses a sequential layout
with `armor sixbit`; `switch` blocks on the message type, DAC and FI choose the application, and a list
to the end of the payload (or counted, for routes) holds the records. The header is on the `ais` and
`aisbin` keys of `ais-binary`.
The vectors are not written here: tools/gen/ais-apps-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/ais-apps-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = ('source        "gpsd, AIVDM/AIVDO protocol decoding, sections IMO236 Tidal Window, IMO289 Dangerous Cargo Indication, '
       'IMO289 Route Information (addressed, broadcast), Tidal Window (IMO289), '
       'VTS-Generated/Synthetic targets and IMO289 Environmental, www/AIVDM.adoc (sha256 '
       'a55511139751f5b9385166143443c0353f64fc77155b4ef4026f4ab03e3dffbd) at https://gitlab.com/gpsd/gpsd commit '
       'c59fc6de479d06620c8b2ba395b728e10a71527b, BSD-2-Clause (gpsd COPYING); layout restated"')
M = "aisapp"


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


def tidal236():
    return [f("month", 4), f("day", 5)] + group("tidals", [
        f("tw_lat", 27, "twos"), f("tw_lon", 28, "twos"), f("from_hour", 5), f("from_min", 6), f("to_hour", 5),
        f("to_min", 6), f("cdir", 9), f("cspeed", 7)])


def tidal289():
    return [f("month", 4), f("day", 5)] + group("tidals", [
        f("tw_lon", 25, "twos"), f("tw_lat", 24, "twos"), f("from_hour", 5), f("from_min", 6), f("to_hour", 5),
        f("to_min", 6), f("cdir", 9), f("cspeed", 8)])


def cargo289():
    return [f("cargo_unit", 2), f("cargo_amount", 10)] + group("cargos", [f("cargo_code", 4), f("cargo_subtype", 13)])


def route():
    return ([f("linkage", 10), f("sender", 3), f("route_type", 5), f("month", 4), f("day", 5), f("hour", 5),
             f("minute", 6), f("duration", 18), "count  waycount  5", "group  aisapp.waypoints  count  @waycount",
             "  " + f("wp_lon", 28, "twos"), "  " + f("wp_lat", 27, "twos"), "end"])


def vts_targets():
    return group("targets", [f("idtype", 2)] + sw("aisapp.idtype", [("0,1", [f("target_id", 42)]),
                                                                    ("2,3", [f("target_name", 42, "sixbit")])]) +
                 [f("target_spare", 4), f("target_lat", 24, "twos"), f("target_lon", 25, "twos"), f("course", 9),
                  f("second", 6), f("speed", 10)])


ENV_TIME = [f("fc_day", 5), f("fc_hour", 5), f("fc_minute", 6)]
ENV_PAYLOADS = [
    ("0", [f("site_lon", 28, "twos"), f("site_lat", 27, "twos"), f("site_alt", 11), f("owner", 4), f("timeout", 3),
           f("payload_spare", 12)]),
    ("1", [f("station_name", 84, "sixbit"), f("payload_spare", 1)]),
    ("2", [f("wind_speed", 7), f("wind_gust", 7), f("wind_dir", 9), f("wind_gust_dir", 9), f("sensor_type", 3),
           f("fc_wind_speed", 7), f("fc_wind_gust", 7), f("fc_wind_dir", 9)] + ENV_TIME + [f("fc_duration", 8), f("payload_spare", 3)]),
    ("3", [f("level_absolute", 1), f("level", 16, "twos"), f("level_trend", 2), f("level_datum", 5), f("sensor_type", 3),
           f("fc_level_absolute", 1), f("fc_level", 16, "twos")] + ENV_TIME + [f("fc_duration", 8), f("payload_spare", 17)]),
    ("4", [f("cspeed1", 8), f("cdir1", 9), f("cdepth1", 9), f("cspeed2", 8), f("cdir2", 9), f("cdepth2", 9),
           f("cspeed3", 8), f("cdir3", 9), f("cdepth3", 9), f("sensor_type", 3), f("payload_spare", 4)]),
    ("5", [f("cnorth1", 8), f("ceast1", 8), f("cup1", 8), f("cdepth1", 9), f("cnorth2", 8), f("ceast2", 8), f("cup2", 8),
           f("cdepth2", 9), f("sensor_type", 3), f("payload_spare", 16)]),
    ("6", [f("hbearing1", 9), f("hdistance1", 7), f("cspeed1", 8), f("cdir1", 9), f("cdepth1", 9), f("hbearing2", 9),
           f("hdistance2", 7), f("cspeed2", 8), f("cdir2", 9), f("cdepth2", 9), f("payload_spare", 1)]),
    ("7", [f("swell_height", 8), f("swell_period", 6), f("swell_dir", 9), f("sea_state", 4), f("swell_type", 3),
           f("water_temp", 10), f("water_temp_depth", 7), f("depth_type", 3), f("wave_height", 8), f("wave_period", 6),
           f("wave_dir", 9), f("wave_type", 3), f("salinity", 9)]),
    ("8", [f("water_temp", 10), f("conductivity", 10), f("water_pressure", 16), f("salinity", 9), f("salinity_type", 2),
           f("sensor_type", 3), f("payload_spare", 35)]),
    ("9", [f("air_temp", 11, "twos"), f("sensor_type", 3), f("precip_type", 2), f("visibility", 8), f("dew_point", 10, "twos"),
           f("dew_type", 3), f("air_pressure", 9), f("pressure_tendency", 2), f("pressure_type", 3), f("salinity", 9),
           f("payload_spare", 25)]),
    ("10", [f("air_draught", 13), f("air_gap", 13), f("air_gap_trend", 2), f("fc_air_gap", 13)] + ENV_TIME +
           [f("payload_spare", 28)]),
]


def environmental():
    return group("reports", [f("sensor", 4), f("day", 5), f("hour", 5), f("minute", 6), f("site", 7)] +
                 sw("aisapp.sensor", ENV_PAYLOADS, [f("reserved_payload", 84, "hex"), f("payload_spare", 1)]))


def pack():
    L = ["# AIS binary application messages of variable length (gpsd AIVDM/AIVDO protocol decoding): type 6 DAC 1",
         "# FI 14 and 32 (tidal window), 25 (dangerous cargo), 28 (route); type 8 DAC 1 FI 17 (VTS targets),",
         "# 26 (environmental), 27 (route). The input is the armored payload. Written by",
         "# tools/gen/ais-apps-pack.py; do not edit by hand.",
         "format        ais-binary-apps", "version       0.1.0", "distribution  public", SRC,
         "uses          ais", "uses          aisbin", "uses          %s" % M,
         "wire          bits", "layout        sequential", "bit_order     msb", "armor         sixbit", "",
         "field  ais.msg_type  6  uint", "field  ais.repeat  2  uint", "field  ais.mmsi  30  uint"]
    addressed = (["field  aisbin.seqno  2  uint", "field  ais.dest_mmsi  30  uint", "field  aisbin.retransmit  1  uint",
                  "field  ais.spare  1  uint", "field  aisbin.dac  10  uint", "field  aisbin.fid  6  uint"] +
                 sw("aisbin.dac", [("1", sw("aisbin.fid", [("14", tidal236()), ("25", cargo289()), ("28", route()),
                                                           ("32", tidal289())]))]))
    broadcast = (["field  ais.spare  2  uint", "field  aisbin.dac  10  uint", "field  aisbin.fid  6  uint"] +
                 sw("aisbin.dac", [("1", sw("aisbin.fid", [("17", vts_targets()), ("26", environmental()), ("27", route())]))]))
    L += sw("ais.msg_type", [("6", addressed), ("8", broadcast)])
    return "\n".join(L) + "\n"


TQ = "thousandths of a minute, signed"
KEYS = [
    ("key", "month", "month, UTC, 1-12; 0 not available"),
    ("key", "day", "day, UTC, 1-31; 0 not available"),
    ("key", "hour", "hour, UTC, 0-23; 24 not available"),
    ("key", "minute", "minute, UTC, 0-59; 60 not available"),
    ("list", "tidals", "tidal window: the predictions, 1 to 3"),
    ("key", "tw_lat", "tidal window latitude, signed: ten-thousandths of a minute (FI 14, 27 bits) or thousandths (FI 32, 24 bits); 91000 not available as the source gives it"),
    ("key", "tw_lon", "tidal window longitude, signed: ten-thousandths of a minute (FI 14, 28 bits) or thousandths (FI 32, 25 bits); 181000 not available as the source gives it"),
    ("key", "from_hour", "tidal window from hour, UTC; 24 not available"),
    ("key", "from_min", "tidal window from minute, UTC; 60 not available"),
    ("key", "to_hour", "tidal window to hour, UTC; 24 not available"),
    ("key", "to_min", "tidal window to minute, UTC; 60 not available"),
    ("key", "cdir", "predicted current direction, degrees; 360 not available"),
    ("key", "cspeed", "predicted current speed, tenths of a knot (FI 14: 127 not available; FI 32: 251 is 25.1 knots or more, 255 not available)"),
    ("key", "cargo_unit", "dangerous cargo: unit of quantity code"),
    ("key", "cargo_amount", "dangerous cargo: amount; 0 not available"),
    ("list", "cargos", "dangerous cargo: the cargo types, 1 to 28"),
    ("key", "cargo_code", "cargo code: 0 not available, 1 IMDG, 2 IGC, 3 BC (IMSBC), 4 MARPOL Annex I, 5 MARPOL Annex II, 6 regional"),
    ("key", "cargo_subtype", "cargo subtype under its code (IMDG class, UN number, MARPOL category ...); 0 not available"),
    ("key", "linkage", "message linkage ID"),
    ("key", "sender", "route: sender class, 0 ship, 1 authority"),
    ("key", "route_type", "route type: 0 undefined, 1 mandatory, 2 recommended, 3 alternative, 4 through ice, 5 ship route plan, 31 cancel"),
    ("key", "duration", "route: duration from the start, minutes; 0 cancels, 262143 not available"),
    ("list", "waypoints", "route: the waypoints, 1 to 16; their number is written from the list"),
    ("key", "wp_lon", "waypoint longitude, ten-thousandths of a minute, signed; 181000 not available as the source gives it"),
    ("key", "wp_lat", "waypoint latitude, signed: ten-thousandths of a minute (the broadcast table says thousandths for the same 27 bits); 91000 not available as the source gives it"),
    ("list", "targets", "VTS targets: 1 to 4"),
    ("key", "idtype", "target identifier type: 0 MMSI, 1 IMO number, 2 call sign, 3 other"),
    ("key", "target_id", "target identifier, types 0 and 1: the number"),
    ("key", "target_name", "target identifier, types 2 and 3: seven six-bit characters"),
    ("key", "target_spare", "target: the 4 spare bits"),
    ("key", "target_lat", "target latitude, " + TQ + "; 91000 not available"),
    ("key", "target_lon", "target longitude, " + TQ + "; 181000 not available"),
    ("key", "course", "target course over ground, degrees; 360 not available"),
    ("key", "second", "target time stamp, second of the UTC minute"),
    ("key", "speed", "target speed over ground, knots; 255 not available"),
    ("list", "reports", "environmental: the sensor reports, 1 to 5, 112 bits each"),
    ("key", "sensor", "sensor report type: 0 site location, 1 station ID, 2 wind, 3 water level, 4 current 2D, 5 current 3D, 6 horizontal current, 7 sea state, 8 salinity, 9 weather, 10 air gap"),
    ("key", "site", "sensor site ID"),
    ("key", "site_lon", "site longitude, ten-thousandths of a minute, signed"),
    ("key", "site_lat", "site latitude, ten-thousandths of a minute, signed"),
    ("key", "site_alt", "sensor altitude above mean sea level, as the wire integer"),
    ("key", "owner", "sensor owner code"),
    ("key", "timeout", "data timeout code"),
    ("key", "station_name", "station ID: fourteen six-bit characters"),
    ("key", "wind_speed", "10-minute average wind speed, as the wire integer"),
    ("key", "wind_gust", "10-minute maximum wind speed, as the wire integer"),
    ("key", "wind_dir", "wind direction, degrees from true north"),
    ("key", "wind_gust_dir", "gust direction, degrees from true north"),
    ("key", "sensor_type", "sensor description: 0 no data, 1 raw real time, 2 real time with quality control, 3 predicted, 4 forecast, 5 nowcast, 7 not available"),
    ("key", "fc_wind_speed", "forecast wind speed, as the wire integer"),
    ("key", "fc_wind_gust", "forecast wind gust, as the wire integer"),
    ("key", "fc_wind_dir", "forecast wind direction, degrees"),
    ("key", "fc_day", "forecast valid time: day, UTC"),
    ("key", "fc_hour", "forecast valid time: hour, UTC"),
    ("key", "fc_minute", "forecast valid time: minute, UTC"),
    ("key", "fc_duration", "forecast duration, minutes"),
    ("key", "level_absolute", "water level type: 0 relative to the datum, 1 absolute"),
    ("key", "level", "water level, signed, as the wire integer (gpsd: hundredths of a metre)"),
    ("key", "level_trend", "water level trend: 0 increasing, 1 decreasing, 2 steady"),
    ("key", "level_datum", "vertical reference datum code (0 MLLW ... 10 WGS 84, 11 LAT, 14 not available)"),
    ("key", "fc_level_absolute", "forecast water level type"),
    ("key", "fc_level", "forecast water level, signed, as the wire integer"),
    ("key", "cspeed1", "current speed 1, tenths of a knot"), ("key", "cdir1", "current direction 1, degrees"),
    ("key", "cdepth1", "measurement depth 1, metres"), ("key", "cspeed2", "current speed 2, tenths of a knot"),
    ("key", "cdir2", "current direction 2, degrees"), ("key", "cdepth2", "measurement depth 2, metres"),
    ("key", "cspeed3", "current speed 3, tenths of a knot"), ("key", "cdir3", "current direction 3, degrees"),
    ("key", "cdepth3", "measurement depth 3, metres"),
    ("key", "cnorth1", "current north component 1, tenths of a knot"), ("key", "ceast1", "current east component 1, tenths of a knot"),
    ("key", "cup1", "current up component 1, tenths of a knot"), ("key", "cnorth2", "current north component 2, tenths of a knot"),
    ("key", "ceast2", "current east component 2, tenths of a knot"), ("key", "cup2", "current up component 2, tenths of a knot"),
    ("key", "hbearing1", "horizontal current 1: bearing, degrees"), ("key", "hdistance1", "horizontal current 1: distance, metres"),
    ("key", "hbearing2", "horizontal current 2: bearing, degrees"), ("key", "hdistance2", "horizontal current 2: distance, metres"),
    ("key", "swell_height", "swell height, tenths of a metre"), ("key", "swell_period", "swell period, seconds"),
    ("key", "swell_dir", "swell direction, degrees"), ("key", "sea_state", "sea state, Beaufort 0-12"),
    ("key", "swell_type", "swell sensor description"), ("key", "water_temp", "water temperature, as the wire integer (tenths of a degree with an offset the source gives)"),
    ("key", "water_temp_depth", "water temperature depth, tenths of a metre"), ("key", "depth_type", "depth sensor description"),
    ("key", "wave_height", "wave height, tenths of a metre"), ("key", "wave_period", "wave period, seconds"),
    ("key", "wave_dir", "wave direction, degrees"), ("key", "wave_type", "wave sensor description"),
    ("key", "salinity", "salinity, tenths of a percent"),
    ("key", "conductivity", "conductivity, as the wire integer (siemens per metre in tenths)"),
    ("key", "water_pressure", "water pressure, as the wire integer"), ("key", "salinity_type", "salinity type: 0 measured, 1 calculated, 2 simulated"),
    ("key", "air_temp", "air temperature, tenths of a degree Celsius, signed"), ("key", "precip_type", "precipitation type code"),
    ("key", "visibility", "horizontal visibility, tenths of a nautical mile"), ("key", "dew_point", "dew point, tenths of a degree Celsius, signed"),
    ("key", "dew_type", "dew point sensor description"), ("key", "air_pressure", "air pressure, as the wire integer (hectopascals with an offset)"),
    ("key", "pressure_tendency", "pressure tendency: 0 steady, 1 decreasing, 2 increasing"), ("key", "pressure_type", "pressure sensor description"),
    ("key", "air_draught", "air draught, hundredths of a metre"), ("key", "air_gap", "air gap, hundredths of a metre"),
    ("key", "air_gap_trend", "air gap trend: 0 steady, 1 decreasing, 2 increasing"), ("key", "fc_air_gap", "forecast air gap, hundredths of a metre"),
    ("key", "payload_spare", "the spare bits at the end of a sensor payload"),
    ("key", "reserved_payload", "a reserved sensor report type: its first 84 payload bits, as hexadecimal digits"),
]
STRINGS = ["target_name", "station_name", "reserved_payload"]


def module():
    w = max(len(k[1]) for k in KEYS)
    L = ["# The aisapp module: AIS binary application messages of variable length. Written by tools/gen/ais-apps-pack.py.",
         "module        %s" % M, "version       0.1.0", "distribution  public", SRC]
    for k in KEYS:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], "string" if k[1] in STRINGS else "int", k[2]))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/ais-binary-apps/pack.def", pack())
    out.write("model/aisapp.def", module())
    return {"ais-apps": 2}


def main(argv=None):
    return genio.vector_main("ais-apps-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
