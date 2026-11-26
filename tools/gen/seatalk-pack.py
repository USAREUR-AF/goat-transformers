#!/usr/bin/env python3
"""Write the SeaTalk 1 datagram pack and its module.

A SeaTalk 1 (Raymarine) datagram is a command octet, an attribute octet whose low nibble is the
number of data octets after the first and whose high nibble often carries data, then the data.
This pack reads the 21 datagrams Signal K's NMEA 0183 parser decodes (from $STALK sentences) with
their fields, raw and scaled as the parser reads them, and any other datagram as its attribute and
data octets. Layouts restated from SignalK/signalk-parser-nmea0183 src/hooks/seatalk/*.ts.

The vectors are not written here: tools/gen/seatalk-vectors.py derives them with an encoder of its
own.

Usage: python3 -I tools/gen/seatalk-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SK = "5ab479bcfc1bec0d36f98616e5f9be96f52e3f23"
SRC = ('source        "SignalK/signalk-parser-nmea0183, https://github.com/SignalK/signalk-parser-nmea0183 at commit %s, '
       'src/hooks/seatalk/0x00.ts to 0x9C.ts (Apache License 2.0, Copyright 2016 Signal K and contributors); layouts restated, '
       'no code or comment copied"' % SK)


def F(k, b, tr="uint", swap=False):
    return "field  seatalk.%s  %d  %s%s" % (k, b, tr, "  swap" if swap else "")


ATTR = [F("attribute_high", 4), F("attribute_length", 4)]

# command: (kind name, data lines after the attribute octet)
DATAGRAMS = [
    (0x00, "depth", [F("depth_anchor_alarm", 1), F("depth_metric_units", 1), F("depth_flag_y1", 1), F("depth_flag_y0", 1),
                     F("depth_flag_z3", 1), F("depth_transducer_defective", 1), F("depth_deep_alarm", 1), F("depth_shallow_alarm", 1),
                     F("depth_raw", 16, swap=True)]),
    (0x10, "apparent-wind-angle", [F("apparent_wind_angle", 16, "uscale:1/2")]),
    (0x11, "apparent-wind-speed", [F("apparent_wind_speed_units", 1), F("apparent_wind_speed_knots", 7), F("apparent_wind_speed_pad", 4),
                                   F("apparent_wind_speed_tenths", 4)]),
    (0x20, "speed-through-water", [F("speed_through_water", 16, "uscale:1/10", swap=True)]),
    (0x21, "trip-mileage", [F("trip_low", 16, swap=True), F("trip_pad", 4), F("trip_high", 4)]),
    (0x22, "total-mileage", [F("total_mileage", 16, "uscale:1/10", swap=True), F("total_pad", 8)]),
    (0x25, "total-and-trip-log", [F("total_low", 16, swap=True), F("trip_low", 16, swap=True), F("trip_pad", 4), F("trip_high", 4)]),
    (0x26, "speed-through-water-2", [F("speed_sensor_1", 16, "uscale:1/100", swap=True), F("speed_sensor_2_or_average", 16, "uscale:1/100", swap=True),
                                     F("speed_flags_d", 4), F("speed_flags_e", 4)]),
    (0x27, "water-temperature", [F("water_temperature", 16, "uscale:1/10:-10", swap=True)]),
    (0x50, "latitude", [F("latitude_degrees", 8), F("latitude_minutes_raw", 16, swap=True)]),
    (0x51, "longitude", [F("longitude_degrees", 8), F("longitude_minutes_raw", 16, swap=True)]),
    (0x52, "speed-over-ground", [F("speed_over_ground", 16, "uscale:1/10", swap=True)]),
    (0x53, "magnetic-course", [F("course_vw", 8)]),
    (0x54, "gmt-time", [F("time_rs", 8), F("time_hours", 8)]),
    (0x56, "date", [F("date_day", 8), F("date_year", 8)]),
    (0x57, "satellite-info", [F("satellite_hdop", 8)]),
    (0x82, "target-waypoint-name", [F("waypoint_xx", 8), F("waypoint_xx_complement", 8), F("waypoint_yy", 8), F("waypoint_yy_complement", 8),
                                    F("waypoint_zz", 8), F("waypoint_zz_complement", 8)]),
    (0x84, "heading-course-rudder", [F("heading_vw", 8), F("autopilot_course_xy", 8), F("autopilot_pad", 4), F("autopilot_mode", 4),
                                     F("alarm_pad", 4), F("alarms", 4), F("rudder_position", 8, "twos"), F("autopilot_ss", 8), F("autopilot_tt", 8)]),
    (0x85, "navigation-to-waypoint", [F("xte_low", 8), F("nav_v", 4), F("nav_u", 4), F("nav_z", 4), F("nav_w", 4), F("nav_zz", 8),
                                      F("nav_y", 4), F("nav_f", 4), F("nav_zero", 8), F("nav_yf_complement", 8)]),
    (0x99, "compass-variation", [F("compass_variation", 8, "twos")]),
    (0x9C, "heading-rudder", [F("heading_vw", 8), F("rudder_position", 8, "twos")]),
]


def pack():
    L = ["# SeaTalk 1 datagram: command, attribute, data; 21 datagrams laid out, any other kept as octets. Written by",
         "# tools/gen/seatalk-pack.py; do not edit by hand.",
         "format        seatalk1", "version       0.1.0", "distribution  public", SRC, "uses          seatalk",
         "wire          bits", "layout        sequential", "bit_order     msb", ""]
    for cmd, name, lines in DATAGRAMS:
        L += ["kind  %s" % name, "when  8  %d" % cmd] + ATTR + lines + [""]
    L += ["kind  other", F("command", 8), F("attribute_high", 4), "count  extra_data  4", F("data_first", 8),
          "group  seatalk.data_more  count  @extra_data", "  " + F("octet", 8), "end"]
    return "\n".join(L) + "\n"


KEYS = [
    ("int", "attribute_high", "attribute octet, high nibble: data in several datagrams (0x25 total mileage bits 16-19, 0x50/0x51 a tag, 0x53/0x84/0x9C U, 0x54 T, 0x56 month, 0x57 satellite count, 0x85 X, the lowest hex digit of the cross-track error XXX = XX * 16 + X)"),
    ("int", "attribute_length", "attribute octet, low nibble: the number of data octets after the first, as sent"),
    ("int", "depth_anchor_alarm", "0x00: Y bit 3, anchor alarm active"), ("int", "depth_metric_units", "0x00: Y bit 2, metric (or fathom) display units"),
    ("int", "depth_flag_y1", "0x00: Y bit 1"), ("int", "depth_flag_y0", "0x00: Y bit 0"), ("int", "depth_flag_z3", "0x00: Z bit 3"),
    ("int", "depth_transducer_defective", "0x00: Z bit 2, transducer defective"), ("int", "depth_deep_alarm", "0x00: Z bit 1, deep alarm"),
    ("int", "depth_shallow_alarm", "0x00: Z bit 0, shallow alarm"),
    ("int", "depth_raw", "0x00: depth below transducer in tenths of a foot (the source masks bit 15 before scaling)"),
    ("float", "apparent_wind_angle", "0x10: apparent wind angle, degrees right of the bow"),
    ("int", "apparent_wind_speed_units", "0x11: display units, 1 m/s, 0 knots"), ("int", "apparent_wind_speed_knots", "0x11: whole knots"),
    ("int", "apparent_wind_speed_pad", "0x11: high nibble of the fourth octet"), ("int", "apparent_wind_speed_tenths", "0x11: tenths of a knot"),
    ("float", "speed_through_water", "0x20: speed through water, knots"),
    ("int", "trip_low", "0x21, 0x25: trip mileage, the low 16 bits (in hundredths of a nautical mile with trip_high)"),
    ("int", "trip_pad", "0x21, 0x25: high nibble of the last octet"), ("int", "trip_high", "0x21, 0x25: trip mileage bits 16-19"),
    ("float", "total_mileage", "0x22: total mileage, nautical miles"), ("int", "total_pad", "0x22: the last octet (0)"),
    ("int", "total_low", "0x25: total mileage, the low 16 bits (in tenths of a nautical mile, with attribute_high as bits 16-19)"),
    ("float", "speed_sensor_1", "0x26: speed through water from sensor 1, knots (valid if flag D bit 2)"),
    ("float", "speed_sensor_2_or_average", "0x26: average speed, or sensor 2 if flag D bit 3, knots"),
    ("int", "speed_flags_d", "0x26: flags D"), ("int", "speed_flags_e", "0x26: flags E (bit 0 average stopped, bit 1 display in mph)"),
    ("float", "water_temperature", "0x27: water temperature, degrees Celsius"),
    ("int", "latitude_degrees", "0x50: latitude, whole degrees"),
    ("int", "latitude_minutes_raw", "0x50: bit 15 set for south; bits 14-0 the minutes in hundredths"),
    ("int", "longitude_degrees", "0x51: longitude, whole degrees"),
    ("int", "longitude_minutes_raw", "0x51: bit 15 set for east; bits 14-0 the minutes in hundredths"),
    ("float", "speed_over_ground", "0x52: speed over ground, knots"),
    ("int", "course_vw", "0x53: VW octet (magnetic course = (U & 3) x 90 + (VW & 0x3F) x 2 + (U & 0xC) / 8, with U the attribute's high nibble)"),
    ("int", "time_rs", "0x54: RS octet (minutes = RS div 4; seconds = (RS & 3) x 16 + T, with T the attribute's high nibble)"),
    ("int", "time_hours", "0x54: hours"), ("int", "date_day", "0x56: day of the month"), ("int", "date_year", "0x56: year (two digits)"),
    ("int", "satellite_hdop", "0x57: horizontal dilution of position"),
    ("int", "waypoint_xx", "0x82: first name octet"), ("int", "waypoint_xx_complement", "0x82: its complement"),
    ("int", "waypoint_yy", "0x82: second name octet"), ("int", "waypoint_yy_complement", "0x82: its complement"),
    ("int", "waypoint_zz", "0x82: third name octet"), ("int", "waypoint_zz_complement", "0x82: its complement"),
    ("int", "heading_vw", "0x84, 0x9C: VW octet of the compass heading (with U, the attribute's high nibble)"),
    ("int", "autopilot_course_xy", "0x84: XY octet of the autopilot course (with the two high bits of V)"),
    ("int", "autopilot_pad", "0x84: high nibble of octet 4"), ("int", "autopilot_mode", "0x84: Z (bit 1 auto, bit 2 vane, bit 3 track)"),
    ("int", "alarm_pad", "0x84: high nibble of octet 5"), ("int", "alarms", "0x84: M (bit 2 off course, bit 3 wind shift)"),
    ("int", "rudder_position", "0x84, 0x9C: rudder position, degrees (positive steers right)"),
    ("int", "autopilot_ss", "0x84: SS display flags"), ("int", "autopilot_tt", "0x84: TT"),
    ("int", "xte_low", "0x85: XX, the two high hex digits of the cross-track error XXX = XX * 16 + X (X is attribute_high), in hundredths of a nautical mile"),
    ("int", "nav_v", "0x85: V"), ("int", "nav_u", "0x85: U (bits 1-0 bearing quadrant, bit 3 true)"), ("int", "nav_z", "0x85: Z"),
    ("int", "nav_w", "0x85: W"), ("int", "nav_zz", "0x85: ZZ (distance with Z)"), ("int", "nav_y", "0x85: Y (bit 0 distance in hundredths, bit 2 steer right)"),
    ("int", "nav_f", "0x85: F (bits 0-3: XTE, bearing, range present, XTE above 0.3 nm)"), ("int", "nav_zero", "0x85: the zero octet"),
    ("int", "nav_yf_complement", "0x85: the complement of YF"),
    ("int", "compass_variation", "0x99: compass variation, degrees (positive west, negative east)"),
    ("int", "command", "another datagram: the command octet"), ("int", "data_first", "another datagram: the first data octet"),
    ("list", "data_more", "another datagram: the data octets after the first (their count is the attribute's low nibble)"),
    ("int", "octet", "one octet"),
]


def module():
    w = max(len(k[1]) for k in KEYS)
    L = ["# The seatalk module: SeaTalk 1 datagram fields. Written by tools/gen/seatalk-pack.py.",
         "module        seatalk", "version       0.1.0", "distribution  public", SRC]
    for t, k, d in KEYS:
        L.append('list  %-*s  "%s"' % (w, k, d) if t == "list" else 'key   %-*s  %-6s  -  "%s"' % (w, k, t, d))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/seatalk1/pack.def", pack())
    out.write("model/seatalk.def", module())
    return {"seatalk1": 2}


def main(argv=None):
    return genio.vector_main("seatalk-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
