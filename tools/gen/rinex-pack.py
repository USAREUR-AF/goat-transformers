#!/usr/bin/env python3
"""Write the RINEX packs and their modules: one line of a RINEX 3.05 or 4.01 GNSS observation file
(rinex-obs-line) and one line of a RINEX navigation file (rinex-nav-line).

RINEX is fixed-column text. A header line is named by its label in columns 61-80, an observation
epoch line starts with `>`, an observation line with the satellite's system letter; in a navigation
file a record starts with `>` (version 4), its first line with the satellite or with four spaces and
the year, and the following lines hold four values each. The packs read one line per message on the
`text` wire with no delimiter, by column. Every value is kept as its column text: the wire's numeric
transforms pad with zeros (RINEX pads numbers with spaces) and do not read exponents.
The vectors are not written here: tools/gen/rinex-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/rinex-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = ('source        "IGS/RTCM RINEX WG, RINEX The Receiver Independent Exchange Format Version 4.01, 10 July 2023, '
       'https://files.igs.org/pub/data/format/rinex_4.01.pdf (sha256 5e917eb6d2224021c5f05adb333b5311b6cde0f58c3ca4e0ae5871ccd15ce0c8), '
       'Tables A2, A3, A7, A9 and A30-A34; and Version 3.05, https://files.igs.org/pub/data/format/rinex305.pdf (sha256 '
       '05de6c898e1cf4102d6d0ef8b2710a98a16a5105c49a6d972757d647c7593918); no licence stated (IGS terms of use: open use with '
       'attribution); layouts restated"')
SYSTEMS = [("G", "gps"), ("R", "glonass"), ("E", "galileo"), ("C", "beidou"), ("J", "qzss"), ("I", "navic"), ("S", "sbas")]
MAX_OBS = 40


def col(mod, key, start, length):
    return "field  %s.%s  0:%d:%d  string" % (mod, key, start, length)


def head(name, comment, mod):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC, "uses          %s" % mod,
             "wire          text", "delimiter     none", ""])


def label_kind(mod, slug, label, fields):
    return ["kind  %s" % slug, "when  0:60:20  \"%s\"" % label] + [col(mod, k, s, n) for k, s, n in fields] + [""]


O = "rinexobs"

OBS_HEADERS = [  # slug, label, fields (key, start, length)
    ("version-type", "RINEX VERSION / TYPE", [("format_version", 0, 9), ("file_type", 20, 1), ("file_type_text", 21, 19),
                                              ("satellite_system", 40, 1), ("satellite_system_text", 41, 19)]),
    ("program", "PGM / RUN BY / DATE", [("program", 0, 20), ("run_by", 20, 20), ("created", 40, 20)]),
    ("comment", "COMMENT", [("comment", 0, 60)]),
    ("marker-name", "MARKER NAME", [("marker_name", 0, 60)]),
    ("marker-number", "MARKER NUMBER", [("marker_number", 0, 20)]),
    ("marker-type", "MARKER TYPE", [("marker_type", 0, 20)]),
    ("observer-agency", "OBSERVER / AGENCY", [("observer", 0, 20), ("agency", 20, 40)]),
    ("receiver", "REC # / TYPE / VERS", [("receiver_number", 0, 20), ("receiver_type", 20, 20), ("receiver_version", 40, 20)]),
    ("antenna", "ANT # / TYPE", [("antenna_number", 0, 20), ("antenna_type", 20, 20)]),
    ("approx-position", "APPROX POSITION XYZ", [("approx_x", 0, 14), ("approx_y", 14, 14), ("approx_z", 28, 14)]),
    ("antenna-delta-hen", "ANTENNA: DELTA H/E/N", [("delta_h", 0, 14), ("delta_e", 14, 14), ("delta_n", 28, 14)]),
    ("antenna-delta-xyz", "ANTENNA: DELTA X/Y/Z", [("delta_x", 0, 14), ("delta_y", 14, 14), ("delta_z", 28, 14)]),
    ("antenna-phasecenter", "ANTENNA: PHASECENTER", [("pc_system", 0, 1), ("pc_code", 2, 3), ("pc_1", 5, 9), ("pc_2", 14, 14),
                                                     ("pc_3", 28, 14)]),
    ("antenna-bsight", "ANTENNA: B.SIGHT XYZ", [("bsight_x", 0, 14), ("bsight_y", 14, 14), ("bsight_z", 28, 14)]),
    ("antenna-zerodir-azi", "ANTENNA: ZERODIR AZI", [("zerodir_azi", 0, 14)]),
    ("antenna-zerodir-xyz", "ANTENNA: ZERODIR XYZ", [("zerodir_x", 0, 14), ("zerodir_y", 14, 14), ("zerodir_z", 28, 14)]),
    ("center-of-mass", "CENTER OF MASS: XYZ", [("com_x", 0, 14), ("com_y", 14, 14), ("com_z", 28, 14)]),
    ("doi", "DOI", [("doi", 0, 60)]),
    ("license", "LICENSE OF USE", [("license", 0, 60)]),
    ("station-information", "STATION INFORMATION", [("station_information", 0, 60)]),
    ("obs-types", "SYS / # / OBS TYPES", [("obs_system", 0, 1), ("obs_type_count", 3, 3)] +
     [("obs_type_%d" % k, 7 + 4 * (k - 1), 3) for k in range(1, 14)]),
    ("signal-strength-unit", "SIGNAL STRENGTH UNIT", [("signal_strength_unit", 0, 20)]),
    ("interval", "INTERVAL", [("interval", 0, 10)]),
    ("time-of-first-obs", "TIME OF FIRST OBS", [("first_year", 0, 6), ("first_month", 6, 6), ("first_day", 12, 6),
                                                ("first_hour", 18, 6), ("first_minute", 24, 6), ("first_second", 30, 13),
                                                ("first_time_system", 48, 3)]),
    ("time-of-last-obs", "TIME OF LAST OBS", [("last_year", 0, 6), ("last_month", 6, 6), ("last_day", 12, 6),
                                              ("last_hour", 18, 6), ("last_minute", 24, 6), ("last_second", 30, 13),
                                              ("last_time_system", 48, 3)]),
    ("rcv-clock-offs-appl", "RCV CLOCK OFFS APPL", [("clock_offset_applied", 0, 6)]),
    ("dcbs-applied", "SYS / DCBS APPLIED", [("corr_system", 0, 1), ("corr_program", 2, 17), ("corr_source", 20, 40)]),
    ("pcvs-applied", "SYS / PCVS APPLIED", [("corr_system", 0, 1), ("corr_program", 2, 17), ("corr_source", 20, 40)]),
    ("scale-factor", "SYS / SCALE FACTOR", [("content", 0, 60)]),
    ("phase-shift", "SYS / PHASE SHIFT", [("content", 0, 60)]),
    ("glonass-slot-frq", "GLONASS SLOT / FRQ #", [("content", 0, 60)]),
    ("glonass-cod-phs-bis", "GLONASS COD/PHS/BIS", [("content", 0, 60)]),
    ("leap-seconds", "LEAP SECONDS", [("leap_seconds", 0, 6), ("leap_seconds_future", 6, 6), ("leap_week", 12, 6),
                                      ("leap_day", 18, 6), ("leap_time_system", 24, 3)]),
    ("number-of-satellites", "# OF SATELLITES", [("satellite_count", 0, 6)]),
    ("prn-number-of-obs", "PRN / # OF OBS", [("content", 0, 60)]),
    ("end-of-header", "END OF HEADER", []),
]


def obs_pack():
    L = head("rinex-obs-line", ["One line of a RINEX 3.05 or 4.01 GNSS observation file: a header line by its label, an epoch line, or an",
                                "observation line. Every value is its column text. Written by tools/gen/rinex-pack.py; do not edit by hand."], O)
    for slug, label, fields in OBS_HEADERS:
        L += label_kind(O, slug, label, fields)
    L += ["kind  epoch", "when  0:0:1  >", col(O, "year", 2, 4), col(O, "month", 7, 2), col(O, "day", 10, 2),
          col(O, "hour", 13, 2), col(O, "minute", 16, 2), col(O, "second", 18, 11), col(O, "epoch_flag", 31, 1),
          col(O, "satellite_count_epoch", 32, 3), col(O, "clock_offset", 41, 15), ""]
    for letter, name in SYSTEMS:
        L += ["kind  observation-%s" % name, "when  0:0:1  %s" % letter, col(O, "satellite_system", 0, 1),
              col(O, "satellite_number", 1, 2)]
        for k in range(1, MAX_OBS + 1):
            s = 3 + 16 * (k - 1)
            L += [col(O, "obs_%d" % k, s, 14), col(O, "lli_%d" % k, s + 14, 1), col(O, "ssi_%d" % k, s + 15, 1)]
        L += [""]
    L += ["kind  header-other", "when  0:60:20  present", col(O, "content", 0, 60), col(O, "label", 60, 20)]
    return "\n".join(L) + "\n"


def obs_keys():
    desc = {
        "format_version": "format version, as written (F9.2: 3.05, 4.01 ...)", "file_type": "file type: O for observation data",
        "satellite_system": "satellite system letter (G GPS, R GLONASS, E Galileo, C BeiDou, J QZSS, I NavIC, S SBAS; M mixed in the version line)",
        "satellite_system_text": "the text after the system letter in the version line",
        "file_type_text": "the text after the file type letter in the version line (OBSERVATION DATA ...)",
        "program": "program that created the file", "run_by": "agency that created the file", "created": "creation date and time, as written",
        "comment": "a comment line's text", "marker_name": "antenna marker name", "marker_number": "antenna marker number",
        "marker_type": "marker type (GEODETIC, NON_GEODETIC, SPACEBORNE ...)", "observer": "observer", "agency": "agency",
        "receiver_number": "receiver serial number", "receiver_type": "receiver type", "receiver_version": "receiver version",
        "antenna_number": "antenna serial number", "antenna_type": "antenna type",
        "approx_x": "approximate marker position, geocentric (ECEF) X, metres, as written",
        "approx_y": "approximate marker position, ECEF Y, metres, as written",
        "approx_z": "approximate marker position, ECEF Z, metres, as written",
        "delta_h": "antenna height above the marker, metres, as written", "delta_e": "antenna eccentricity east, metres, as written",
        "delta_n": "antenna eccentricity north, metres, as written",
        "delta_x": "antenna reference point in the body frame, X, metres", "delta_y": "antenna reference point, Y, metres",
        "delta_z": "antenna reference point, Z, metres",
        "pc_system": "phase centre: satellite system", "pc_code": "phase centre: observation code",
        "pc_1": "phase centre: north or X, metres", "pc_2": "phase centre: east or Y, metres", "pc_3": "phase centre: up or Z, metres",
        "bsight_x": "antenna vertical axis direction, X", "bsight_y": "antenna vertical axis direction, Y", "bsight_z": "antenna vertical axis direction, Z",
        "zerodir_azi": "azimuth of the antenna zero direction, degrees", "zerodir_x": "antenna zero direction, X",
        "zerodir_y": "antenna zero direction, Y", "zerodir_z": "antenna zero direction, Z",
        "com_x": "centre of mass, X, metres", "com_y": "centre of mass, Y, metres", "com_z": "centre of mass, Z, metres",
        "doi": "digital object identifier for citing the data", "license": "data licence line", "station_information": "station metadata link",
        "obs_system": "SYS / # / OBS TYPES: satellite system (blank on a continuation line)",
        "obs_type_count": "SYS / # / OBS TYPES: number of observation types for the system (blank on a continuation line)",
        "signal_strength_unit": "unit of the carrier-to-noise observations (DBHZ ...)", "interval": "observation interval, seconds, as written",
        "clock_offset_applied": "1 if epochs and observations are corrected by the receiver clock offset",
        "corr_system": "DCB or PCV corrections: satellite system", "corr_program": "DCB or PCV corrections: program",
        "corr_source": "DCB or PCV corrections: source",
        "content": "the first 60 columns of a header line the pack does not divide", "label": "the header label (columns 61-80)",
        "leap_seconds": "current number of leap seconds since 6 January 1980", "leap_seconds_future": "future or past leap seconds (blank if unknown)",
        "leap_week": "week number of that leap second (blank if unknown)", "leap_day": "day number of that leap second (blank if unknown)",
        "leap_time_system": "time system of the leap second record (GPS, or blank)", "satellite_count": "number of satellites in the file",
        "year": "epoch year, in the file's time system", "month": "epoch month", "day": "epoch day", "hour": "epoch hour",
        "minute": "epoch minute", "second": "epoch second, as written (F11.7)",
        "epoch_flag": "epoch flag: 0 OK, 1 power failure since the previous epoch, 2-5 events (header lines follow), 6 cycle slips",
        "satellite_count_epoch": "number of satellites in the epoch (or of special records after an event)",
        "clock_offset": "receiver clock offset, seconds (optional), as written",
        "satellite_number": "satellite number (PRN or slot) within its system",
    }
    for p in ("first", "last"):
        for f in ("year", "month", "day", "hour", "minute", "second"):
            desc["%s_%s" % (p, f)] = "time of %s observation: %s, as written" % (p, f)
        desc["%s_time_system" % p] = "time of %s observation: time system (GPS, GLO, GAL, BDT, QZS, IRN)" % p
    for k in range(1, 14):
        desc["obs_type_%d" % k] = "observation descriptor %d of the line (type, band, attribute: C1C, L1C ...)" % k
    for k in range(1, MAX_OBS + 1):
        desc["obs_%d" % k] = "observation %d of the line, in the order of the system's SYS / # / OBS TYPES, as written (F14.3)" % k
        desc["lli_%d" % k] = "loss of lock indicator of observation %d" % k
        desc["ssi_%d" % k] = "signal strength indicator of observation %d (1-9)" % k
    order = []
    for _, _, fields in OBS_HEADERS:
        for k, _, _ in fields:
            if k not in order:
                order.append(k)
    for k in ["year", "month", "day", "hour", "minute", "second", "epoch_flag", "satellite_count_epoch", "clock_offset",
              "satellite_system", "satellite_number"] + sum((["obs_%d" % k, "lli_%d" % k, "ssi_%d" % k] for k in range(1, MAX_OBS + 1)), []) + ["content", "label"]:
        if k not in order:
            order.append(k)
    return [(k, desc[k]) for k in order]


N = "rinexnav"
NAV_HEADERS = [
    ("version-type", "RINEX VERSION / TYPE", [("format_version", 0, 9), ("file_type", 20, 1), ("file_type_text", 21, 19),
                                              ("satellite_system", 40, 1), ("satellite_system_text", 41, 19)]),
    ("program", "PGM / RUN BY / DATE", [("program", 0, 20), ("run_by", 20, 20), ("created", 40, 20)]),
    ("receiver", "REC # / TYPE / VERS", [("receiver_number", 0, 20), ("receiver_type", 20, 20), ("receiver_version", 40, 20)]),
    ("comment", "COMMENT", [("comment", 0, 60)]),
    ("merged-file", "MERGED FILE", [("merged_files", 0, 9)]),
    ("doi", "DOI", [("doi", 0, 60)]),
    ("license", "LICENSE OF USE", [("license", 0, 60)]),
    ("station-information", "STATION INFORMATION", [("station_information", 0, 60)]),
    ("leap-seconds", "LEAP SECONDS", [("leap_seconds", 0, 6), ("leap_seconds_future", 6, 6), ("leap_week", 12, 6),
                                      ("leap_day", 18, 6), ("leap_time_system", 24, 3)]),
    ("end-of-header", "END OF HEADER", []),
]
EPOCH = [("year", 4, 4), ("month", 9, 2), ("day", 12, 2), ("hour", 15, 2), ("minute", 18, 2), ("second", 21, 2),
         ("value_1", 23, 19), ("value_2", 42, 19), ("value_3", 61, 19)]


def nav_pack():
    L = head("rinex-nav-line", ["One line of a RINEX 3.05 or 4.01 navigation file: a header line by its label, a record line (version 4),",
                                "the first line of a record (satellite and epoch, or epoch alone), or a line of four values. Every value is",
                                "its column text. Written by tools/gen/rinex-pack.py; do not edit by hand."], N)
    for slug, label, fields in NAV_HEADERS:
        L += label_kind(N, slug, label, fields)
    L += ["kind  record", "when  0:0:1  >", col(N, "record_type", 2, 3), col(N, "satellite_system", 6, 1),
          col(N, "satellite_number", 7, 2), col(N, "message_type", 10, 4), ""]
    for letter, name in SYSTEMS:
        L += ["kind  satellite-epoch-%s" % name, "when  0:0:1  %s" % letter, col(N, "satellite_system", 0, 1),
              col(N, "satellite_number", 1, 2)] + [col(N, k, s, n) for k, s, n in EPOCH] + [""]
    for century in ("19", "20"):
        L += ["kind  epoch-%sxx" % century, "when  0:4:2  %s" % century] + [col(N, k, s, n) for k, s, n in EPOCH] + [""]
    L += ["kind  values", col(N, "value_0", 4, 19), col(N, "value_1", 23, 19), col(N, "value_2", 42, 19), col(N, "value_3", 61, 19)]
    return "\n".join(L) + "\n"


def nav_keys():
    desc = {
        "format_version": "format version, as written", "file_type": "file type: N for navigation data",
        "satellite_system": "satellite system letter (G GPS, R GLONASS, E Galileo, C BeiDou, J QZSS, I NavIC, S SBAS; M mixed)",
        "satellite_system_text": "the text after the system letter in the version line",
        "file_type_text": "the text after the file type letter in the version line (OBSERVATION DATA ...)",
        "program": "program that created the file", "run_by": "agency that created the file", "created": "creation date and time, as written",
        "receiver_number": "receiver serial number", "receiver_type": "receiver type", "receiver_version": "receiver version",
        "comment": "a comment line's text", "merged_files": "number of files merged", "doi": "digital object identifier for citing the data",
        "license": "data licence line", "station_information": "station metadata link",
        "leap_seconds": "current number of leap seconds since 6 January 1980", "leap_seconds_future": "future or past leap seconds (blank if unknown)",
        "leap_week": "week number of that leap second", "leap_day": "day number of that leap second",
        "leap_time_system": "time system of the leap second record (GPS, or blank)",
        "record_type": "version 4 record type: EPH ephemeris, STO system time offset, EOP earth orientation, ION ionosphere",
        "satellite_number": "satellite number (PRN or slot) within its system (blank for some STO, EOP, ION records)",
        "message_type": "navigation message type (LNAV, CNAV, CNV2, INAV, FNAV, FDMA, D1, D2, CNV1 ... IFNV, CNVX)",
        "year": "epoch year (Toc, or the record's reference epoch), in the satellite system's time", "month": "epoch month",
        "day": "epoch day", "hour": "epoch hour", "minute": "epoch minute", "second": "epoch second",
        "value_0": "a values line: the value in columns 5-23, as written (E19.12 or D19.12; blank if not known)",
        "value_1": "the value in columns 24-42, as written", "value_2": "the value in columns 43-61, as written",
        "value_3": "the value in columns 62-80, as written",
    }
    order = []
    for _, _, fields in NAV_HEADERS:
        for k, _, _ in fields:
            if k not in order:
                order.append(k)
    for k in ["record_type", "satellite_number", "message_type", "year", "month", "day", "hour", "minute", "second",
              "value_0", "value_1", "value_2", "value_3"]:
        if k not in order:
            order.append(k)
    return [(k, desc[k]) for k in order]


def module(name, header, keys):
    w = max(len(k) for k, _ in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", SRC]
    L += ['key   %-*s  string  -  "%s"' % (w, k, d) for k, d in keys]
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/rinex-obs-line/pack.def", obs_pack())
    out.write("packs/rinex-nav-line/pack.def", nav_pack())
    out.write("model/rinexobs.def", module("rinexobs", ["# The rinexobs module: the columns of RINEX observation file lines, as their text. Written by tools/gen/rinex-pack.py."], obs_keys()))
    out.write("model/rinexnav.def", module("rinexnav", ["# The rinexnav module: the columns of RINEX navigation file lines, as their text. Written by tools/gen/rinex-pack.py."], nav_keys()))
    return {"rinex": 4}


def main(argv=None):
    return genio.vector_main("rinex-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
