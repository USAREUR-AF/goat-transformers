#!/usr/bin/env python3
"""gnssbin-vectors: write the vectors of novatel-oem-binary and sirf-binary.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of:
- novatel_gps_driver binary_header.h and parsers/bestpos.cpp: sync AA 44 12, header length (28),
  message ID (2), message type, port, message length (2), sequence (2), idle time, time status,
  week (2), milliseconds (4), receiver status (4), reserved (2), software version (2); BESTPOS
  (ID 42, 72 octets): solution status (4), position type (4), latitude, longitude, height (8-octet
  doubles), undulation (4-octet float), datum (4), three sigmas (floats), base station ID (4),
  differential age, solution age (floats), four satellite counts, an octet, the extended solution
  status, the signal mask, an octet; then a 4-octet CRC; all little-endian;
- gpsd driver_sirf.c: frame A0 A2, 2-octet payload length, payload, 2-octet checksum (the payload's
  sum, 15 bits), B0 B3, big-endian; MID 41 (91 octets) with the navigation type at payload offset 3,
  extended week 5, time of week 7 (ms), UTC year 11, month 13, day 14, hour 15, minute 16, seconds
  17 (ms), latitude 23 and longitude 27 (1e-7 degree), altitude above the WGS84 ellipsoid 31 and
  above mean sea level 35 (cm), map datum 39, speed 40 (cm/s), track 42 (0.01 degree), climb 46
  (cm/s), horizontal and vertical error 50 and 54 (cm), speed error 62 (cm/s), HDOP 89 (0.2).

Inputs: frames built here field by field from values chosen here; no frame is taken from a
document or a capture. The NovAtel CRC is an arbitrary 32-bit value (the pack does not compute it);
the SiRF checksum is computed here as the source states. `expect` of a round trip is the input.
`model` holds values that were packed.

Usage: python3 -I tools/gen/gnssbin-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/gnssbin-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_N = "novatel_gps_driver binary_header.h and parsers/bestpos.cpp"
R_S = "gpsd drivers/driver_sirf.c"


def vec(pack, name, inp, model=None, error=None, ref="", note="", to=None, expect=None):
    v = {"name": name, "from": pack, "to": to or pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect if isinstance(expect, str) else (expect if expect is not None else inp).hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


# ---------------------------------------------------------------- NovAtel

def nov_header(msg_id, msg_len, seq=0, week=2350, ms=345600000, time_status=180, mtype=0, port=0x20, idle=50, rx=0, sw=16809):
    return (bytes([0xAA, 0x44, 0x12, 28]) + struct.pack("<HBBHHBBHIIHH", msg_id, mtype, port, msg_len, seq, idle, time_status,
                                                           week, ms, rx, 0, sw))


def bestpos(lat, lon, hgt, und=-17.25, datum=61, sig=(0.5, 0.5, 1.0), stn=b"0\x00\x00\x00", diff=0.0, sol=0.0,
            svs=(14, 12, 12, 10), ext=0, sig_mask=0x33):
    return (struct.pack("<IIdddfIfff", 0, 16, lat, lon, hgt, und, datum, *sig) + stn + struct.pack("<ff", diff, sol) +
            bytes(svs) + bytes([0, ext, sig_mask, 0]))


def novatel_vectors():
    P = "novatel-oem-binary"
    out = []
    body = bestpos(51.0, -114.0, 1048.5)
    a = nov_header(42, len(body)) + body + struct.pack("<I", 0x89ABCDEF)
    out.append(("01-bestpos-roundtrip.json", vec(P, "bestpos-roundtrip", a,
                {"novatel.header_length": "28", "novatel.message_id": "42", "novatel.message_length": "72", "novatel.week": "2350",
                 "novatel.gps_milliseconds": "345600000", "novatel.time_status": "180", "novatel.position_type": "16",
                 "novatel.latitude": "51", "novatel.longitude": "-114", "novatel.height": "1048.5", "novatel.undulation": "-17.25",
                 "novatel.datum_id": "61", "novatel.base_station_id": "0", "novatel.satellites_tracked": "14",
                 "novatel.signals_used": str(0x33), "novatel.crc": str(0x89ABCDEF)},
                ref=R_N, note="BESTPOS, position type 16, datum 61, with an arbitrary CRC")))
    other = bytes(range(12)) + struct.pack("<I", 0x01020304)
    b = nov_header(43, 12, seq=1) + other
    out.append(("02-other-log-as-octets-roundtrip.json", vec(P, "other-log-as-octets-roundtrip", b,
                {"novatel.message_id": "43", "novatel.sequence": "1", "novatel.data_and_crc.#": "16"},
                ref=R_N, note="another log (ID 43): its data and CRC kept as octets")))
    out.append(("03-wrong-sync-is-no-kind.json", vec(P, "wrong-sync-is-no-kind", bytes([0xAB]) + a[1:], error="no-kind",
                ref=R_N, note="the first sync octet is not 0xAA")))
    out.append(("04-cut-bestpos-is-malformed.json", vec(P, "cut-bestpos-is-malformed", a[:60], error="malformed-wire",
                ref=R_N, note="the BESTPOS body is cut")))
    return P, out


# ---------------------------------------------------------------- SiRF

def sirf_frame(payload):
    return bytes([0xA0, 0xA2]) + struct.pack(">H", len(payload)) + payload + struct.pack(">H", sum(payload) & 0x7FFF) + bytes([0xB0, 0xB3])


def geodetic(lat_e7, lon_e7, hae_cm, msl_cm, navtype=0x0004, week=2350, tow=345600000, speed=123, track=9000, climb=-5,
             ehpe=250, evpe=400, ehve=10, hdop_x5=5, datum=21):
    p = bytes([41]) + bytes(2) + struct.pack(">HHI", navtype, week, tow)
    p += struct.pack(">HBBBBH", 2025, 1, 15, 12, 30, 45500) + bytes(4)
    p += struct.pack(">iiii", lat_e7, lon_e7, hae_cm, msl_cm) + bytes([datum])
    p += struct.pack(">HH", speed, track) + bytes(2) + struct.pack(">h", climb) + bytes(2)
    p += struct.pack(">II", ehpe, evpe) + bytes(4) + struct.pack(">H", ehve) + bytes(25) + bytes([hdop_x5, 0])
    assert len(p) == 91, len(p)
    return p


def sirf_vectors():
    P = "sirf-binary"
    out = []
    a = sirf_frame(geodetic(481234567, 115678901, 56789, 52000))
    out.append(("01-geodetic-navigation-roundtrip.json", vec(P, "geodetic-navigation-roundtrip", a,
                {"sirf.message_id": "41", "sirf.nav_type": "4", "sirf.extended_week": "2350", "sirf.time_of_week": "345600000",
                 "sirf.utc_year": "2025", "sirf.utc_second_ms": "45500", "lat": "48.1234567", "lon": "11.5678901", "hae": "567.89",
                 "sirf.altitude_msl": "520", "sirf.map_datum": "21", "sirf.speed": "1.23", "sirf.track": "90", "sirf.climb": "-0.05",
                 "sirf.horizontal_error": "2.5", "sirf.vertical_error": "4", "sirf.speed_error": "0.1", "sirf.hdop": "1"},
                ref=R_S, note="MID 41 with a 3-D fix: latitude, longitude and the height above the WGS84 ellipsoid")))
    b = sirf_frame(geodetic(-338765432, -705000000, -1250, 1500))
    out.append(("02-geodetic-southern-western-roundtrip.json", vec(P, "geodetic-southern-western-roundtrip", b,
                {"lat": "-33.8765432", "lon": "-70.5", "hae": "-12.5", "sirf.altitude_msl": "15"},
                ref=R_S, note="negative latitude, longitude and ellipsoidal height")))
    c = sirf_frame(bytes([0x0B, 0x84]))
    out.append(("03-other-message-as-octets-roundtrip.json", vec(P, "other-message-as-octets-roundtrip", c,
                {"sirf.message_id": "11", "sirf.payload.#": "1", "sirf.checksum": str(0x8F)},
                ref=R_S, note="MID 11 (command acknowledgement) with one octet")))
    out.append(("04-wrong-start-is-no-kind.json", vec(P, "wrong-start-is-no-kind", bytes([0xA0, 0xA3]) + c[2:], error="no-kind",
                ref=R_S, note="the start sequence is not A0 A2")))
    out.append(("05-cut-frame-is-malformed.json", vec(P, "cut-frame-is-malformed", a[:50], error="malformed-wire",
                ref=R_S, note="the payload is cut")))
    out.append(("06-to-geojson.json", vec(P, "to-geojson", a, to="geojson",
                expect='{"type":"Feature","geometry":{"type":"Point","coordinates":[11.5678901,48.1234567,567.89]},"properties":{}}',
                ref=R_S + " and RFC 7946 section 3.1.1 (position: longitude, latitude, altitude)",
                note="the shared lat, lon and hae become a GeoJSON point; the SiRF-only fields have no GeoJSON place")))
    return P, out


def build(out):
    counts = {}
    for pack, vs in (novatel_vectors(), sirf_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("gnssbin-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
