#!/usr/bin/env python3
"""Hand-derived vectors of the agopengps-pgn pack.

Each frame is built as the AgOpenGPS PGN document lays it out: 0x80, 0x81, the source address, the
PGN, the number of data bytes, the data (little-endian, as C#'s BitConverter writes on the
platforms AgOpenGPS runs on), and the sum of the bytes from the source address to the last data
byte, modulo 256. The PGN 214 layout follows AgIO's encoder (NMEA.Designer.cs, 51 data bytes). The
GeoJSON text follows engine-spec 0.1.1 rulings 3 and 4. No engine is imported.

    python3 -I tools/gen/agopengps-vectors.py [--check] [<checkout>]
"""
import json
import os
import struct
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "AgOpenGPS 6.8.6 docs/pgn-protocol.md and AgIO's PGN 214 encoder; bytes by tools/gen/agopengps-vectors.py"
FMAX = struct.unpack("<f", struct.pack("<I", 0x7F7FFFFF))[0]
DMAX = struct.unpack("<d", struct.pack("<Q", 0x7FEFFFFFFFFFFFFF))[0]


def frame(src, pgn, data):
    body = bytes([src, pgn, len(data)]) + data
    return (bytes([0x80, 0x81]) + body + bytes([sum(body) % 256])).hex()


def vec(name, inp, expect, model=None, to="agopengps-pgn", note=""):
    v = {"name": name, "from": "agopengps-pgn", "to": to, "input": inp, "expect": expect}
    if model:
        v["model"] = {k: str(x) for k, x in model.items()}
    v["source"] = "constructed"
    v["reference"] = REF + ("; " + note if note else "")
    return v


def build(out):
    files = []
    lon, lat = 9.875, 52.5
    d214 = struct.pack("<dd", lon, lat) + struct.pack("<fffff", 181.5, 90.25, 7.5, -1.25, 54.5) + \
        struct.pack("<HBHHHhhh", 14, 4, 80, 120, 65535, 12, -30, 5)
    f214 = frame(0x7C, 214, d214)
    files.append(("01-gps-position.json", vec("agopengps-gps-position", f214, f214, {
        "@kind": "gps_position", "agopengps.source": 124, "lat": lat, "lon": lon, "agopengps.p214_heading_dual": 181.5,
        "agopengps.p214_heading_true": 90.25, "agopengps.p214_speed": 7.5, "agopengps.p214_roll": -1.25,
        "agopengps.p214_altitude_m": 54.5, "agopengps.p214_satellites": 14, "agopengps.p214_fix_quality": 4,
        "agopengps.p214_hdop_x100": 80, "agopengps.p214_imu_heading": 65535, "agopengps.p214_imu_pitch": -30,
        "agopengps.checksum": int(f214[-2:], 16)}, note="51 data bytes from AgIO, source 0x7C")))
    files.append(("02-gps-position-to-geojson.json", vec("agopengps-gps-position-to-geojson", f214,
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[9.875,52.5]},"properties":{}}', to="geojson",
        note="altitude is above mean sea level (from GGA), not hae")))
    d = struct.pack("<dd", DMAX, DMAX) + struct.pack("<fffff", FMAX, FMAX, FMAX, FMAX, FMAX) + struct.pack("<HBHHHhhh", 0, 0, 0, 0, 0, 0, 0, 0)
    fnone = frame(0x7C, 214, d)
    files.append(("03-gps-position-none-to-geojson.json", vec("agopengps-gps-position-none-to-geojson", fnone,
        '{"type":"Feature","geometry":null,"properties":{}}', to="geojson",
        note="double.MaxValue for latitude and longitude means no position: the keys are absent")))
    f208 = frame(0x7F, 208, struct.pack("<ii", 1193046470, 117891312))
    files.append(("04-lat-lon.json", vec("agopengps-lat-lon", f208, f208, {"@kind": "lat_lon"},
        note="latitude and longitude as int32 times 0x7FFFFFFF/90 and /180")))
    # The steer module sends eight data bytes; the pack reads the first seven, and encode writes only what
    # its lines hold (engine-spec 0.8, Lengths), so a round trip of that frame is not the identity. The
    # vector uses the seven bytes the document names.
    f253 = frame(0x7E, 253, struct.pack("<hhhBB", -1234, 9999, 8888, 0b00000011, 77))
    files.append(("05-steer-module-seven-bytes.json", vec("agopengps-steer-module-seven-bytes", f253, f253, {
        "@kind": "steer_module", "agopengps.p253_actual_steer_angle_deg": -12.34, "agopengps.p253_heading": 9999,
        "agopengps.p253_work_switch": 1, "agopengps.p253_steer_switch": 1, "agopengps.p253_pwm": 77},
        note="the seven data bytes the document names")))
    f242 = frame(0x7F, 242, struct.pack("<Hi", 397, -1500))
    files.append(("06-process-data.json", vec("agopengps-process-data", f242, f242, {
        "@kind": "process_data", "agopengps.p242_identifier": 397, "agopengps.p242_value": -1500})))
    msg = "Check hitch".encode()
    f221 = frame(0x7F, 221, bytes([5, 0]) + msg)
    files.append(("07-display-message.json", vec("agopengps-display-message", f221, f221, {
        "@kind": "display_message", "agopengps.p221_display_time_s": 5, "agopengps.p221_message.#": len(msg),
        "agopengps.p221_message[0].agopengps.p221_message_byte": msg[0]})))
    f240 = frame(0x80, 240, bytes([0b00000101, 12, 0b10101010, 0b00001111]))
    files.append(("08-isobus-heartbeat.json", vec("agopengps-isobus-heartbeat", f240, f240, {
        "@kind": "isobus_heartbeat", "agopengps.p240_section_control_enabled": 1, "agopengps.p240_clients": 2,
        "agopengps.p240_num_sections": 12, "agopengps.p240_section_states.#": 2})))
    f235 = frame(0x7F, 235, b"".join(struct.pack("<H", 300 + i) for i in range(16)) + bytes([6]))
    files.append(("09-section-dimensions.json", vec("agopengps-section-dimensions", f235, f235, {
        "@kind": "section_dimensions", "agopengps.p235_section_width_0": 300, "agopengps.p235_section_width_15": 315,
        "agopengps.p235_num_sections": 6})))
    files.append(("10-short-frame.json", {"name": "agopengps-short-frame", "from": "agopengps-pgn", "to": "agopengps-pgn",
                                          "input": f242[:-6], "expect_error": "malformed-wire", "source": "constructed",
                                          "reference": REF + "; the data length byte says six bytes; fewer follow"}))
    for n, v in files:
        out.write("packs/agopengps-pgn/vectors/" + n, json.dumps(v, indent=2) + "\n")
    return {"agopengps-pgn": len(files)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("agopengps-vectors", __doc__.split("\n")[0], build))
