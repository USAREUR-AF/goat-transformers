#!/usr/bin/env python3
"""Write the maritime packs and their modules: the RTZ route exchange file (CIRM RTZ schema 1.2), the
NMEA 4.x TAG block, the u-blox PUBX proprietary NMEA 0183 sentences, and the AIS IMO289 area notice
(DAC 1, FI 22 broadcast and FI 23 addressed).

The area notice is a header and 1 to 10 sub-areas of 87 bits each, so it is a sequential layout with
a list of sub-areas to the end of the payload, each laid out by a `switch` on its shape; the
application is chosen by `switch` blocks on the message type, DAC and FI.
The vectors are not written here: tools/gen/maritime-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/maritime-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

GPSD = "https://gitlab.com/gpsd/gpsd commit c59fc6de479d06620c8b2ba395b728e10a71527b, BSD-2-Clause (gpsd COPYING)"
SRC = {
    "rtz": 'source        "CIRM, Route Exchange Format (RTZ) XML schema, revision 1.2 (IEC PAS 61174-1:2021), https://cirm.org/storage/documents/October2022/bWjrTyyfNGseK9ch3TKf.xsd from https://cirm.org/rtz-xml-schemas (sha256 ba5695107e2b559ea0594eb80f7407b7e4f1c10da8cf09b447b4b920f681ceff), no licence stated; structure restated"',
    "tag": 'source        "gpsd, AIVDM/AIVDO protocol decoding, section NMEA Tag Blocks, www/AIVDM.adoc (sha256 a55511139751f5b9385166143443c0353f64fc77155b4ef4026f4ab03e3dffbd) at %s; restated"' % GPSD,
    "pubx": 'source        "gpsd, NMEA Revealed, sections PUBX 00, 01, 03 and 04, www/NMEA.adoc (sha256 83192561db3198d46ef249233c689de2c9735af162c840155d11e6157574d29e) at %s; field order restated"' % GPSD,
    "area": 'source        "gpsd, AIVDM/AIVDO protocol decoding, sections IMO289 Area Notice (addressed and broadcast), Area Notice Description, Subarea Types and Subarea Payloads, www/AIVDM.adoc (sha256 a55511139751f5b9385166143443c0353f64fc77155b4ef4026f4ab03e3dffbd) at %s; layout restated"' % GPSD,
}


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def text(L):
    return "\n".join(L) + "\n"


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


def module(name, header, src, keys, strings=(), floats=()):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", src]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            t = "string" if k[1] in strings else "float" if k[1] in floats else "int"
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], t, k[2]))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- RTZ

ROUTE_INFO = [  # attribute, key, type, description
    ("routeName", "route_name", "string", "the route's name (required)"),
    ("routeAuthor", "route_author", "string", "who made the route"),
    ("routeStatus", "route_status", "string", "the route's status, free text"),
    ("validityPeriodStart", "validity_start", "string", "start of the validity period, ISO 8601 date and time as written"),
    ("validityPeriodStop", "validity_stop", "string", "end of the validity period, ISO 8601 date and time as written"),
    ("vesselName", "vessel_name", "string", "the ship's name"),
    ("vesselMMSI", "vessel_mmsi", "int", "the ship's MMSI"),
    ("vesselIMO", "vessel_imo", "int", "the ship's IMO number"),
    ("vesselVoyage", "vessel_voyage", "string", "voyage number"),
    ("vesselDisplacement", "vessel_displacement", "int", "displacement, tons"),
    ("vesselCargo", "vessel_cargo", "int", "cargo, tons"),
    ("vesselGM", "vessel_gm", "float", "metacentric height, metres"),
    ("optimizationMethod", "optimization_method", "string", "the performance indicator the route is optimized for"),
    ("vesselMaxRoll", "vessel_max_roll", "int", "largest roll angle allowed, degrees"),
    ("vesselMaxWave", "vessel_max_wave", "float", "significant wave height limit, metres"),
    ("vesselMaxWind", "vessel_max_wind", "float", "wind speed limit, knots"),
    ("vesselSpeedMax", "vessel_speed_max", "float", "the ship's top speed, knots"),
    ("vesselServiceMin", "vessel_service_min", "float", "lower end of the preferred service speed window, knots"),
    ("vesselServiceMax", "vessel_service_max", "float", "upper end of the preferred service speed window, knots"),
    ("routeChangesHistory", "route_changes_history", "string", "history of changes to the route, free text"),
]
LEG = [
    ("starboardXTD", "starboard_xtd", "float", "cross-track limit to starboard, nautical miles"),
    ("portsideXTD", "portside_xtd", "float", "cross-track limit to port, nautical miles"),
    ("safetyContour", "safety_contour", "float", "safety contour, metres"),
    ("safetyDepth", "safety_depth", "float", "safety depth, metres"),
    ("geometryType", "geometry_type", "string", "the leg's geometry: Loxodrome (rhumb line) or Orthodrome (great circle)"),
    ("speedMin", "speed_min", "float", "lowest planned speed on the leg, knots"),
    ("speedMax", "speed_max", "float", "highest speed allowed on the leg, knots"),
    ("draughtForward", "draught_forward", "float", "static draught forward, metres"),
    ("draughtAft", "draught_aft", "float", "static draught aft, metres"),
    ("staticUKC", "static_ukc", "float", "least static under-keel clearance on the leg (no unit of its own in the schema; its header's default, nautical miles, does not fit it)"),
    ("dynamicUKC", "dynamic_ukc", "float", "least dynamic under-keel clearance on the leg (no unit of its own in the schema; its header's default, nautical miles, does not fit it)"),
    ("masthead", "masthead", "float", "masthead height (no unit of its own in the schema; its header's default, nautical miles, does not fit it)"),
    ("legReport", "leg_report", "string", "reporting information for the leg"),
    ("legInfo", "leg_info", "string", "general information for the leg"),
    ("legNote1", "leg_note1", "string", "notes about the ETD or ETA"),
    ("legNote2", "leg_note2", "string", "local remarks"),
]
SCHED = [
    ("waypointId", "waypoint_id", "int", "the waypoint the element refers to (required)"),
    ("etd", "etd", "string", "estimated time of departure, UTC, ISO 8601 as written"),
    ("etdWindowBefore", "etd_window_before", "string", "how much earlier than the ETD departure may be, an XML duration"),
    ("etdWindowAfter", "etd_window_after", "string", "how much later than the ETD departure may be, an XML duration"),
    ("eta", "eta", "string", "estimated time of arrival, UTC, ISO 8601 as written"),
    ("etaWindowBefore", "eta_window_before", "string", "how much earlier than the ETA arrival may be, an XML duration"),
    ("etaWindowAfter", "eta_window_after", "string", "how much later than the ETA arrival may be, an XML duration"),
    ("stay", "stay", "string", "time to stay at the waypoint, an XML duration"),
    ("speed", "speed", "float", "true speed, knots"),
    ("speedWindow", "speed_window", "float", "uncertainty of the predicted speed, knots"),
    ("windSpeed", "wind_speed", "float", "true wind speed, knots"),
    ("windDirection", "wind_direction", "float", "true wind direction, degrees"),
    ("currentSpeed", "current_speed", "float", "current speed, knots"),
    ("currentDirection", "current_direction", "float", "current direction, degrees"),
    ("windLoss", "wind_loss", "float", "speed loss from wind, knots"),
    ("waveLoss", "wave_loss", "float", "speed loss from waves (no unit of its own in the schema; its header's default, nautical miles, does not fit it)"),
    ("totalLoss", "total_loss", "float", "total speed loss (no unit of its own in the schema; its header's default, nautical miles, does not fit it)"),
    ("rpm", "rpm", "int", "advised engine revolutions per minute"),
    ("pitch", "pitch", "int", "advised engine pitch"),
    ("fuel", "fuel", "float", "predicted fuel consumption on the leg (no unit of its own in the schema; its header's default, nautical miles, does not fit it)"),
    ("relFuelSave", "rel_fuel_save", "float", "relative fuel saving from optimization, percent"),
    ("absFuelSave", "abs_fuel_save", "float", "absolute fuel saving from optimization (no unit of its own in the schema; its header's default, nautical miles, does not fit it)"),
    ("Note", "note", "string", "a note"),
]


def rtz_pack():
    L = ["# RTZ route exchange file, schema revision 1.2 (CIRM; IEC PAS 61174-1:2021): the route information, the",
         "# default waypoint, the waypoints with their legs, and the first schedule's manual and calculated elements.",
         "# Written by tools/gen/maritime-pack.py; do not edit by hand.",
         "format  rtz-route", "version 0.1.0", "distribution public", SRC["rtz"], "uses    rtz", "wire    xml", "root    route",
         "when    @xmlns    http://www.cirm.org/RTZ/1/2", "when    @version  1.2", "", "kind    route"]
    L += ["field   rtz.%s  routeInfo/@%s  %s" % (k, a, t) for a, k, t, _ in ROUTE_INFO]
    L += ["field   rtz.default_radius  waypoints/defaultWaypoint/@radius  float"]
    L += ["field   rtz.default_%s  waypoints/defaultWaypoint/leg/@%s  %s" % (k, a, t) for a, k, t, _ in LEG]
    L += ["group   rtz.waypoints  waypoints/waypoint", "  field  rtz.id  @id  int", "  field  rtz.revision  @revision  int",
          "  field  rtz.name  @name  string", "  field  rtz.radius  @radius  float", "  field  rtz.lat  position/@lat  float",
          "  field  rtz.lon  position/@lon  float"]
    L += ["  field  rtz.%s  leg/@%s  %s" % (k, a, t) for a, k, t, _ in LEG] + ["end"]
    L += ["field   rtz.schedule_id  schedules/schedule/@id  int", "field   rtz.schedule_name  schedules/schedule/@name  string"]
    for part in ("manual", "calculated"):
        L += ["group   rtz.%s_elements  schedules/schedule/%s/scheduleElement" % (part, part)]
        L += ["  field  rtz.%s  @%s  %s" % (k, a, t) for a, k, t, _ in SCHED] + ["end"]
    return text(L)


def rtz_keys():
    keys = [("key", k, d) for _, k, _, d in ROUTE_INFO]
    keys += [("key", "default_radius", "default waypoint: turn radius, nautical miles")]
    keys += [("key", "default_" + k, "default waypoint: " + d) for _, k, _, d in LEG]
    keys += [("list", "waypoints", "the waypoints, in order (at least two)"),
             ("key", "id", "waypoint: its identifier, unique in the route (required)"),
             ("key", "revision", "waypoint: its revision, raised on every change (required)"),
             ("key", "name", "waypoint: its name"),
             ("key", "radius", "waypoint: turn radius, nautical miles"),
             ("key", "lat", "waypoint: latitude, degrees, WGS 84"),
             ("key", "lon", "waypoint: longitude, degrees, WGS 84")]
    keys += [("key", k, "the leg from the previous waypoint: " + d) for _, k, _, d in LEG]
    keys += [("key", "schedule_id", "the first schedule's identifier"), ("key", "schedule_name", "the first schedule's name"),
             ("list", "manual_elements", "the first schedule's manual schedule elements, in order"),
             ("list", "calculated_elements", "the first schedule's calculated schedule elements, in order")]
    keys += [("key", k, "schedule element: " + d) for _, k, _, d in SCHED]
    strings = [k for _, k, t, _ in ROUTE_INFO + LEG + SCHED if t == "string"] + ["name", "schedule_name"] + \
              ["default_" + k for _, k, t, _ in LEG if t == "string"]
    floats = [k for _, k, t, _ in ROUTE_INFO + LEG + SCHED if t == "float"] + ["default_radius", "radius", "lat", "lon"] + \
             ["default_" + k for _, k, t, _ in LEG if t == "float"]
    return keys, strings, floats


# ---------------------------------------------------------------- TAG block

def tag_pack():
    L = ["# NMEA 4.x TAG block (as gpsd's AIVDM document describes it): the text between the two backslashes",
         "# that precede a sentence, its parameters and checksum. Written by tools/gen/maritime-pack.py.",
         "format        nmea-tag-block", "version       0.1.0", "distribution  public", SRC["tag"], "uses          nmeatag",
         "wire          text", "checksum      nmea", "",
         "group  nmeatag.parameters  0  item 1", "  field  nmeatag.parameter  0  string", "end"]
    return text(L)


TAG_KEYS = [
    ("list", "parameters", "the TAG block's parameters, in order"),
    ("key", "parameter", "one parameter as written: a type letter (c UNIX time, d destination, g sentence group, n line count, r relative time, s source, t text; IEC 62320-1 uses c, d, x, s, i and xGy), a colon and the value"),
]


# ---------------------------------------------------------------- PUBX

def pubx_pack():
    common = ["field     pubx.time_s        2      hms:2"]
    pos_tail = [("7", "alt"), ("8", "nav_status"), ("9", "hacc"), ("10", "vacc"), ("11", "sog"), ("12", "cog"),
                ("13", "vvel"), ("14", "age_c"), ("15", "hdop"), ("16", "vdop"), ("17", "tdop"), ("18", "gps_used"),
                ("19", "glonass_used"), ("20", "dr_used")]
    L = ["# u-blox PUBX proprietary NMEA 0183 sentences (00, 01, 03, 04) as gpsd's NMEA Revealed lists them.",
         "# Written by tools/gen/maritime-pack.py; do not edit by hand.",
         "format        nmea0183-pubx", "version       0.1.0", "distribution  public", SRC["pubx"], "uses          pubx",
         "wire          text", 'start         "$"', "checksum      nmea", ""]
    L += ["kind      pubx-00", "when      0       PUBX", "when      1       00", "requires  lat lon"] + common + \
         ["field     lat                3+4    dm:2:6:NS", "field     lon                5+6    dm:3:6:EW"] + \
         ["field     pubx.%-16s %-6s string" % (k, i) for i, k in pos_tail] + [""]
    L += ["kind      pubx-01", "when      0       PUBX", "when      1       01", "requires  pubx.easting"] + common + \
         ["field     pubx.easting       3      string", "field     pubx.easting_ew    4      string",
          "field     pubx.northing      5      string", "field     pubx.northing_ns   6      string"] + \
         ["field     pubx.%-16s %-6s string" % (k, i) for i, k in pos_tail] + [""]
    L += ["kind      pubx-03", "when      0       PUBX", "when      1       03", "requires  pubx.sat_count",
          "field     pubx.sat_count     2      int", "group     pubx.satellites    3      item 6",
          "  field   pubx.sv_id         0      int:2", "  field   pubx.sv_status     1      string",
          "  field   pubx.azimuth       2      int:3", "  field   pubx.elevation     3      int:2",
          "  field   pubx.cno           4      int", "  field   pubx.lock_time     5      int:3", "end", ""]
    L += ["kind      pubx-04", "when      0       PUBX", "when      1       04", "requires  pubx.date"] + common + \
         ["field     pubx.date          3      string", "field     pubx.utc_tow       4      string",
          "field     pubx.week          5      int", "field     pubx.reserved      6      string",
          "field     pubx.clock_bias    7      string", "field     pubx.clock_drift   8      string",
          "field     pubx.pulse_granularity 9  string"]
    return text(L)


PUBX_KEYS = [
    ("key", "time_s", "the hhmmss.ss time field, seconds since midnight"),
    ("key", "alt", "PUBX 00 AltRef, PUBX 01 AltMSL: altitude, as written (unit not stated by the source)"),
    ("key", "nav_status", "navigation status, as written (G3 ...)"),
    ("key", "hacc", "horizontal accuracy estimate, as written"),
    ("key", "vacc", "vertical accuracy estimate, as written"),
    ("key", "sog", "speed over ground, as written (unit not stated by the source)"),
    ("key", "cog", "course over ground, as written"),
    ("key", "vvel", "vertical velocity, as written"),
    ("key", "age_c", "the field ageC, as written"),
    ("key", "hdop", "horizontal dilution of precision, as written"),
    ("key", "vdop", "vertical dilution of precision, as written"),
    ("key", "tdop", "time dilution of precision, as written"),
    ("key", "gps_used", "the field GU, as written"),
    ("key", "glonass_used", "the field RU, as written"),
    ("key", "dr_used", "the field DR, as written"),
    ("key", "easting", "PUBX 01: UTM easting, as written"),
    ("key", "easting_ew", "PUBX 01: the letter after the easting"),
    ("key", "northing", "PUBX 01: UTM northing, as written"),
    ("key", "northing_ns", "PUBX 01: the letter after the northing"),
    ("key", "sat_count", "PUBX 03: the field GT, the number of satellites that follow in the example"),
    ("list", "satellites", "PUBX 03: the satellites, six fields each"),
    ("key", "sv_id", "PUBX 03: satellite ID"),
    ("key", "sv_status", "PUBX 03: the field s, as written (the source gives examples U and -)"),
    ("key", "azimuth", "PUBX 03: the field AZM"),
    ("key", "elevation", "PUBX 03: the field EL"),
    ("key", "cno", "PUBX 03: the field SN"),
    ("key", "lock_time", "PUBX 03: the field LK"),
    ("key", "date", "PUBX 04: the date, ddmmyy as written"),
    ("key", "utc_tow", "PUBX 04: UTC time of week, as written"),
    ("key", "week", "PUBX 04: week number"),
    ("key", "reserved", "PUBX 04: the reserved field, as written"),
    ("key", "clock_bias", "PUBX 04: the field Clk_B, as written"),
    ("key", "clock_drift", "PUBX 04: the field Clk_D, as written"),
    ("key", "pulse_granularity", "PUBX 04: the field PG, as written"),
]
PUBX_STRINGS = ["alt", "nav_status", "hacc", "vacc", "sog", "cog", "vvel", "age_c", "hdop", "vdop", "tdop", "gps_used",
                "glonass_used", "dr_used", "easting", "easting_ew", "northing", "northing_ns", "sv_status", "date", "utc_tow",
                "reserved", "clock_bias", "clock_drift", "pulse_granularity"]
PUBX_FLOATS = ["time_s"]


# ---------------------------------------------------------------- AIS area notice

def a(k, b, tr="uint"):
    return "field  aisarea.%s  %d  %s" % (k, b, tr)


def subarea():
    pos = [a("scale", 2), a("lon", 25, "twos"), a("lat", 24, "twos"), a("precision", 3)]
    poly = [a("scale", 2)] + sum(([a("bearing_%d" % i, 10), a("distance_%d" % i, 10)] for i in range(1, 5)), []) + [a("poly_spare", 2)]
    return [a("shape", 3)] + sw("aisarea.shape", [
        ("0", pos + [a("radius", 12), a("circle_spare", 18)]),
        ("1", pos + [a("east", 8), a("north", 8), a("orientation", 9), a("rect_spare", 5)]),
        ("2", pos + [a("radius", 12), a("left", 9), a("right", 9)]),
        ("3,4", poly),
        ("5", [a("text", 84, "sixbit")])],
        [a("reserved_payload", 84, "hex")])


def notice():
    return ([a("linkage", 10), a("notice", 7), a("month", 4), a("day", 5), a("hour", 5), a("minute", 6), a("duration", 18),
             "group  aisarea.subareas  rest"] + ind(1, subarea()) + ["end"])


def area_pack():
    L = ["# AIS IMO289 area notice (DAC 1: FI 22 broadcast in message type 8, FI 23 addressed in type 6) as gpsd's",
         "# AIVDM document describes it: the header, then 1 to 10 sub-areas of 87 bits, each by its shape. The input is",
         "# the armored payload of the AIVDM sentence(s). Written by tools/gen/maritime-pack.py; do not edit by hand.",
         "format        ais-area-notice", "version       0.1.0", "distribution  public", SRC["area"],
         "uses          ais", "uses          aisbin", "uses          aisarea",
         "wire          bits", "layout        sequential", "bit_order     msb", "armor         sixbit", "",
         "field  ais.msg_type  6  uint", "field  ais.repeat  2  uint", "field  ais.mmsi  30  uint"]
    addressed = (["field  aisbin.seqno  2  uint", "field  ais.dest_mmsi  30  uint", "field  aisbin.retransmit  1  uint",
                  "field  ais.spare  1  uint", "field  aisbin.dac  10  uint", "field  aisbin.fid  6  uint"] +
                 sw("aisbin.dac", [("1", sw("aisbin.fid", [("23", notice())]))]))
    broadcast = (["field  ais.spare  2  uint", "field  aisbin.dac  10  uint", "field  aisbin.fid  6  uint"] +
                 sw("aisbin.dac", [("1", sw("aisbin.fid", [("22", notice())]))]))
    L += sw("ais.msg_type", [("6", addressed), ("8", broadcast)])
    return text(L)


AREA_KEYS = [
    ("key", "linkage", "message linkage ID: names the area, and links to a text message with the same ID"),
    ("key", "notice", "notice description, 0-127 (0-21 caution, 23-30 environmental caution, 32-38 restricted, 40-45 anchorage, 56-58 security, 64-76 distress, 80-85 instruction, 88-95 information, 96-108 chart feature, 112-114 report from ship, 125 other, 126 cancellation, 127 undefined)"),
    ("key", "month", "start month, UTC, 1-12; 0 not available"),
    ("key", "day", "start day, UTC, 1-31; 0 not available"),
    ("key", "hour", "start hour, UTC, 0-23; 24 not available"),
    ("key", "minute", "start minute, UTC, 0-59; 60 not available"),
    ("key", "duration", "duration, minutes; 262143 not available, 0 cancels the notice"),
    ("list", "subareas", "the sub-areas, 1 to 10, in order (87 bits each)"),
    ("key", "shape", "sub-area shape: 0 circle or point, 1 rectangle, 2 sector, 3 polyline, 4 polygon, 5 associated text; 6-7 reserved"),
    ("key", "scale", "power of ten applied to the sub-area's dimensions (metres)"),
    ("key", "lon", "longitude of the centre or south-west corner, thousandths of a minute, signed; 181000 not available"),
    ("key", "lat", "latitude of the centre or south-west corner, thousandths of a minute, signed; 91000 not available"),
    ("key", "precision", "decimal places of precision of the position"),
    ("key", "radius", "circle or sector radius, times 10^scale metres; 0 a point"),
    ("key", "circle_spare", "circle: the 18 spare bits"),
    ("key", "east", "rectangle: east dimension, times 10^scale metres"),
    ("key", "north", "rectangle: north dimension, times 10^scale metres"),
    ("key", "orientation", "rectangle: rotation, degrees clockwise from true north"),
    ("key", "rect_spare", "rectangle: the 5 spare bits"),
    ("key", "left", "sector: left boundary, degrees clockwise from true north"),
    ("key", "right", "sector: right boundary, degrees clockwise from true north"),
    ("key", "bearing_1", "polyline or polygon point 1: bearing from the previous point, half-degrees; 720 not available"),
    ("key", "distance_1", "polyline or polygon point 1: distance from the previous point, times 10^scale metres; 0 no point"),
    ("key", "bearing_2", "point 2: bearing, half-degrees"),
    ("key", "distance_2", "point 2: distance, times 10^scale metres"),
    ("key", "bearing_3", "point 3: bearing, half-degrees"),
    ("key", "distance_3", "point 3: distance, times 10^scale metres"),
    ("key", "bearing_4", "point 4: bearing, half-degrees"),
    ("key", "distance_4", "point 4: distance, times 10^scale metres"),
    ("key", "poly_spare", "polyline or polygon: the 2 unused bits"),
    ("key", "text", "associated text: 14 six-bit characters"),
    ("key", "reserved_payload", "a reserved shape (6, 7): its 84 bits, as hexadecimal digits"),
]


def build(out):
    out.write("packs/rtz-route/pack.def", rtz_pack())
    out.write("packs/nmea-tag-block/pack.def", tag_pack())
    out.write("packs/nmea0183-pubx/pack.def", pubx_pack())
    out.write("packs/ais-area-notice/pack.def", area_pack())
    rk, rs, rf = rtz_keys()
    out.write("model/rtz.def", module("rtz", ["# The rtz module: the fields of an RTZ 1.2 route file. Written by tools/gen/maritime-pack.py."],
                                      SRC["rtz"], rk, rs, rf))
    out.write("model/nmeatag.def", module("nmeatag", ["# The nmeatag module: NMEA 4.x TAG block parameters. Written by tools/gen/maritime-pack.py."],
                                          SRC["tag"], TAG_KEYS, ["parameter"]))
    out.write("model/pubx.def", module("pubx", ["# The pubx module: the fields of u-blox PUBX sentences. Written by tools/gen/maritime-pack.py."],
                                       SRC["pubx"], PUBX_KEYS, PUBX_STRINGS, PUBX_FLOATS))
    out.write("model/aisarea.def", module("aisarea", ["# The aisarea module: the IMO289 area notice (AIS DAC 1 FI 22 and 23). Written by tools/gen/maritime-pack.py."],
                                          SRC["area"], AREA_KEYS, ["text", "reserved_payload"]))
    return {"maritime": 8}


def main(argv=None):
    return genio.vector_main("maritime-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
