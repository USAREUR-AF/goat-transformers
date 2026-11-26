#!/usr/bin/env python3
"""drip-vectors: write the conversion vectors of the drip pack.

Python 3 standard library only; imports no engine and reads no pack.def. The
layouts below are this program's own restatement of IETF RFC 9575 sections 3.2
and 4 (the Authentication Payload, the DRIP Link, Wrapper and Manifest) and,
for a wrapped Location message, of the F3411 Location layout as pack remote-id
states it from opendroneid-core-c.

Inputs: messages built here field by field. No message is taken from a
document: a Link; Manifests with no and with three message hashes; Wrappers
around a Basic ID and a Location message at 47.5 N 122.25 W, 1524 m, around a
Location and a System message, of four messages without a Location message,
and over an extended transport. A built message is sent as pages here too,
with null padding after the data, as an Authentication Message would be.

Every `expect` is this program's packing of the Authentication Headers and the
authentication data (what follows them, ADL, FEC and padding, is not written by
the pack). Every `model` value is read from the octets by this program.

Usage: python3 -I tools/gen/drip-vectors.py [--out DIR] [--check]
Writes packs/drip/vectors/*.json. With --check nothing is written and the exit
status is 1 when a committed file differs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402



SAM_LINK, SAM_WRAPPER, SAM_MANIFEST = 1, 2, 3


def le(b):
    return int.from_bytes(b, "little")


def headers(payload):
    """The authentication data of a payload, and the octets the pack writes back."""
    length = payload[1]
    return payload[6:6 + length], payload[:6 + length]


def octets_model(model, lst, data):
    model["drip.%s.#" % lst] = str(len(data))
    for i, b in enumerate(data):
        model["drip.%s[%d].drip.octet" % (lst, i)] = str(b)


def plain(x):
    """Shortest decimal text that reads back to the double, no exponent (engine-spec ruling 3 of 0.1.1)."""
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return repr(x)


# The Location message after its type and version octet, as pack remote-id states it:
# (key, first bit counted from bit 0 of the message's octet 0 upward, bits, kind).
# kind: "u" unsigned, "s" two's complement, or ("scale", factor, offset, signed).
LOCATION = [
    ("rid.speed_mult", 8, 1, "u"), ("rid.ew_direction", 9, 1, "u"), ("rid.height_type", 10, 1, "u"),
    ("rid.status", 12, 4, "u"), ("rid.direction_raw", 16, 8, "u"), ("rid.speed_h_raw", 24, 8, "u"),
    ("rid.speed_v", 32, 8, ("scale", 0.5, 0, True)),
    ("lat", 40, 32, ("scale", 1e-7, 0, True)), ("lon", 72, 32, ("scale", 1e-7, 0, True)),
    ("rid.alt_baro", 104, 16, ("scale", 0.5, -1000, False)), ("hae", 120, 16, ("scale", 0.5, -1000, False)),
    ("rid.height", 136, 16, ("scale", 0.5, -1000, False)),
    ("rid.horiz_acc", 152, 4, "u"), ("rid.vert_acc", 156, 4, "u"), ("rid.speed_acc", 160, 4, "u"),
    ("rid.baro_acc", 164, 4, "u"), ("rid.timestamp_ds", 168, 16, "u"), ("rid.ts_acc", 184, 4, "u"),
    ("rid.reserved", 192, 8, "u"),
]


def location_model(msg, model):
    """Model values of a 25-octet Location message, bit 0 = least significant bit of octet 0."""
    v = le(msg)
    model["rid.proto_version"] = str(msg[0] & 15)
    for key, start, n, kind in LOCATION:
        raw = (v >> start) & ((1 << n) - 1)
        if kind == "u":
            model[key] = str(raw)
            continue
        _, factor, offset, signed = kind
        if signed and raw >> (n - 1):
            raw -= 1 << n
        # a fraction factor is applied as the pack's scale is: v * num / den, then + offset
        x = raw * 1.0 / 10000000 if factor == 1e-7 else raw * 1.0 / 2
        model[key] = plain(x + offset)


def wrapped_model(model, lst, msgs):
    model["drip.%s.#" % lst] = str(len(msgs))
    for i, m in enumerate(msgs):
        p = "drip.%s[%d]." % (lst, i)
        model[p + "rid.proto_version"] = str(m[0] & 15)
        model[p + "rid.msg_type"] = str(m[0] >> 4)
        model[p + "drip.message_data.#"] = "24"
        model[p + "drip.message_data[0].drip.octet"] = str(m[1])
        model[p + "drip.message_data[23].drip.octet"] = str(m[24])


def common_model(payload, data, kind):
    m = {"@kind": kind, "rid.auth_last_page_index": str(payload[0]), "rid.auth_timestamp": str(le(payload[2:6])),
         "drip.vnb": str(le(data[1:5])), "drip.vna": str(le(data[5:9]))}
    return m


def link_model(payload):
    data, _ = headers(payload)
    assert len(data) == 137 and data[0] == SAM_LINK
    m = common_model(payload, data, "link")
    octets_model(m, "child_det", data[9:25])
    octets_model(m, "child_hi", data[25:57])
    octets_model(m, "parent_det", data[57:73])
    octets_model(m, "parent_signature", data[73:137])
    return m


def wrapper_model(payload):
    data, _ = headers(payload)
    assert data[0] == SAM_WRAPPER and (len(data) - 89) % 25 == 0
    n = (len(data) - 89) // 25
    msgs = [data[9 + 25 * i: 34 + 25 * i] for i in range(n)]
    loc = [i for i, msg in enumerate(msgs) if msg[0] >> 4 == 1]
    kind = "wrapper-%d-location-%d" % (n, loc[0] + 1) if loc else "wrapper-%d" % n
    m = common_model(payload, data, kind)
    if loc:
        i = loc[0]
        if i:
            wrapped_model(m, "wrapped", msgs[:i])
        location_model(msgs[i], m)
        if n - i - 1:
            wrapped_model(m, "wrapped_after", msgs[i + 1:])
    elif n:
        wrapped_model(m, "wrapped", msgs)
    tail = 9 + 25 * n
    octets_model(m, "ua_det", data[tail:tail + 16])
    octets_model(m, "ua_signature", data[tail + 16:tail + 80])
    return m


def manifest_model(payload):
    data, _ = headers(payload)
    assert data[0] == SAM_MANIFEST and (len(data) - 113) % 8 == 0
    n = (len(data) - 113) // 8
    m = common_model(payload, data, "manifest-%d" % n)
    octets_model(m, "previous_manifest_hash", data[9:17])
    octets_model(m, "current_manifest_hash", data[17:25])
    octets_model(m, "link_hash", data[25:33])
    if n:
        m["drip.message_hashes.#"] = str(n)
        for i in range(n):
            h = data[33 + 8 * i: 41 + 8 * i]
            m["drip.message_hashes[%d].drip.hash.#" % i] = "8"
            m["drip.message_hashes[%d].drip.hash[0].drip.octet" % i] = str(h[0])
            m["drip.message_hashes[%d].drip.hash[7].drip.octet" % i] = str(h[7])
    tail = 33 + 8 * n
    octets_model(m, "ua_det", data[tail:tail + 16])
    octets_model(m, "ua_signature", data[tail + 16:tail + 80])
    return m


# ---------------------------------------------------------------- messages built here

def payload_of(data, timestamp, pages=None):
    """Authentication Headers then data: last page index (from the page count the data needs,
    17 octets on page 0 and 23 on each further page), Length, timestamp least significant first."""
    if pages is None:
        pages = 1 + max(0, -(-(len(data) - 17) // 23))
    return bytes([pages - 1, len(data)]) + timestamp.to_bytes(4, "little") + data


def location_message(lat, lon, hae):
    """A Location message, protocol version 2: airborne, lat/lon in 1e-7 degree, geodetic
    altitude in (m + 1000) * 2; the other fields fixed small values."""
    raw_lat, raw_lon, raw_hae = round(lat * 1e7), round(lon * 1e7), round((hae + 1000) * 2)
    v = 0x12                                    # type 1, version 2
    v |= 2 << 12                                # status airborne
    v |= 90 << 16 | 40 << 24                    # direction 90, speed raw 40 (10 m/s)
    v |= (raw_lat & 0xFFFFFFFF) << 40 | (raw_lon & 0xFFFFFFFF) << 72
    v |= 4000 << 104 | raw_hae << 120 | 2100 << 136
    v |= 10 << 152 | 4 << 156 | 3 << 160 | 3 << 164 | 12345 << 168 | 1 << 184
    return v.to_bytes(25, "little")


def basic_id_message():
    """A Basic ID message, protocol version 2: ID type 1 (serial number), UA type 2, an ASCII serial."""
    return bytes([0x02, 0x12]) + b"DRIP-EXAMPLE-0001".ljust(20, b"\0") + bytes(3)


def message(msg_type, fill):
    return bytes([msg_type << 4 | 2]) + bytes((fill + i) % 256 for i in range(24))


DET = bytes.fromhex("2001003ffe000105" "0123456789abcdef")


def signature(seed):
    return bytes((seed * 7 + i * 13) % 256 for i in range(64))


def wrapper_data(msgs):
    return bytes([SAM_WRAPPER]) + (1000).to_bytes(4, "little") + (1120).to_bytes(4, "little") + \
        b"".join(msgs) + DET + signature(len(msgs))


def link_data():
    """A Link: the parent (an HDA) endorses the child (the aircraft's DET and host identity)."""
    child_hi = bytes((31 * i + 5) % 256 for i in range(32))
    parent = bytes.fromhex("2001003ffe000105" "00000000000000aa")
    return bytes([SAM_LINK]) + (900).to_bytes(4, "little") + (31536900).to_bytes(4, "little") + \
        DET + child_hi + parent + signature(1)


def padded(payload):
    """The payload as it arrives: whole pages of 23 octets, null padded after the data."""
    return payload + bytes(-(len(payload) - 23) % 23 if len(payload) > 23 else 23 - len(payload))


def manifest_data(hashes):
    ledger = bytes(range(1, 9)) + bytes(range(11, 19)) + bytes(range(21, 29))
    return bytes([SAM_MANIFEST]) + (1000).to_bytes(4, "little") + (1120).to_bytes(4, "little") + \
        ledger + b"".join(hashes) + DET + signature(9)


# ---------------------------------------------------------------- vectors

def vec(name, inp, expect=None, error=None, model=None, to="drip", ref=""):
    v = {"name": name, "from": "drip", "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = ref
    return v


def build():
    out = []
    lk = payload_of(link_data(), 2999)
    _, expect = headers(padded(lk))
    out.append(vec("link-roundtrip", padded(lk).hex(), expect.hex(), model=link_model(lk),
                   ref="built by this program: a Link, the parent's endorsement of the aircraft's DET; "
                       "the null padding after the 137 octets of data is read over and not written"))
    out.append(vec("link-cut-short-is-malformed", lk[:100].hex(), error="malformed-wire",
                   ref="the same Link's first 100 octets: Length states 137 octets of data and the input "
                       "ends before them"))
    # built here
    loc = location_message(47.5, -122.25, 1524.0)
    w = payload_of(wrapper_data([basic_id_message(), loc]), 3000)
    out.append(vec("wrapper-basic-id-and-location-roundtrip", w.hex(), w.hex(), model=wrapper_model(w),
                   ref="built by this program: a Wrapper of a Basic ID message and a Location message "
                       "at 47.5 N 122.25 W, geodetic altitude 1524 m"))
    out.append(vec("wrapper-basic-id-and-location-to-geojson", w.hex(),
                   '{"type":"Feature","geometry":{"type":"Point","coordinates":[-122.25,47.5,1524]},"properties":{}}',
                   to="geojson", model={"@kind": "wrapper-2-location-2", "lat": "47.5", "lon": "-122.25", "hae": "1524"},
                   ref="the same Wrapper; lat = 475000000 / 10^7, lon = -1222500000 / 10^7, "
                       "hae = 5048 / 2 - 1000, written by hand as GeoJSON"))
    four = [basic_id_message(), message(3, 40), message(4, 80), message(5, 120)]
    w4 = payload_of(wrapper_data(four), 3001)
    out.append(vec("wrapper-four-messages-no-location-roundtrip", w4.hex(), w4.hex(), model=wrapper_model(w4),
                   ref="built by this program: a Wrapper of a Basic ID, Self ID, System and Operator ID message"))
    w0 = payload_of(wrapper_data([]), 3002)
    out.append(vec("wrapper-extended-transport-roundtrip", w0.hex(), w0.hex(), model=wrapper_model(w0),
                   ref="built by this program: a Wrapper with no message, the form for extended "
                       "transports (RFC 9575 section 4.3.2)"))
    m0 = payload_of(manifest_data([]), 3003)
    out.append(vec("manifest-no-message-hash-roundtrip", m0.hex(), m0.hex(), model=manifest_model(m0),
                   ref="built by this program: a Manifest of the three ledger hashes only"))
    hashes = [bytes((40 * j + i) % 256 for i in range(8)) for j in range(1, 4)]
    m3 = payload_of(manifest_data(hashes), 3005)
    out.append(vec("manifest-three-message-hashes-roundtrip", m3.hex(), m3.hex(), model=manifest_model(m3),
                   ref="built by this program: a Manifest of the three ledger hashes and three message hashes"))
    ls = payload_of(wrapper_data([location_message(-33.75, 151.25, 20.0), message(4, 7)]), 3006)
    _, expect = headers(padded(ls))
    out.append(vec("wrapper-location-and-system-roundtrip", padded(ls).hex(), expect.hex(), model=wrapper_model(ls),
                   ref="built by this program: a Wrapper of a Location message in place 1 and a System "
                       "message, null padded to whole pages; the padding is not written back"))
    odd = payload_of(bytes([SAM_WRAPPER]) + bytes(99), 3004)
    out.append(vec("wrapper-length-of-no-whole-message-count-is-no-kind", odd.hex(), error="no-kind",
                   ref="built by this program: SAM Type 0x02 and 100 octets of data, which is not "
                       "89 + 25 n (RFC 9575 section 4.3.1)"))
    wu = payload_of(wrapper_data([basic_id_message(), location_message(47.5, -122.25, -1000.0)]), 3000)
    out.append(vec("wrapper-location-unknown-altitude-to-geojson", wu.hex(),
                   '{"type":"Feature","geometry":{"type":"Point","coordinates":[-122.25,47.5]},"properties":{}}',
                   to="geojson",
                   ref="built by this program: vector 04's Wrapper with the geodetic altitude of the wrapped "
                       "Location at raw 0, which encodes -1000 m, the unknown value: the point has no altitude"))
    return out


def build_files(out):
    vecs = build()
    assert len({v["name"] for v in vecs}) == len(vecs)
    keep = set()
    for i, v in enumerate(vecs, 1):
        name = "%02d-%s.json" % (i, v["name"])
        out.write("packs/drip/vectors/" + name, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        keep.add(name)
    for old in out.listdir("packs/drip/vectors"):
        if old.endswith(".json") and old not in keep:
            out.remove("packs/drip/vectors/" + old)
    return {"drip": len(vecs)}


def main(argv=None):
    return genio.vector_main("drip-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
