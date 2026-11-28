#!/usr/bin/env python3
"""golden-gdl90: golden vectors for packs/gdl90 from gdl90 (github.com/etdey/gdl90),
a reference GDL 90 encoder and decoder (shared-model hardening, item 2: meaning is
tested against an implementation outside this project, not only engine agreement).

The reference is not published as a package. Its files are fetched at commit
COMMIT and refused unless their SHA-256 is the one in FILES; they are imported
from the cache, run, not copied: none of its code is in this repository. It is
MIT-licensed.

Inputs, in this order:
  - two framed messages of its decoder tests (gdl90/tests/test_decoder.py:
    heartbeat and ownship geometric altitude; its ownship and traffic test
    messages have space-padded call signs, which the pack does not write);
  - messages its Encoder builds from the arguments in BUILD below: heartbeats,
    ownship and traffic reports in every quadrant, geometric altitudes, and the
    ForeFlight ID message.
Each frame is taken apart here as GDL 90 frames it (packs/gdl90/pack.md): the
0x7E flags removed, the 0x7D escapes undone, the CRC checked with the
reference's own crcCheck and dropped. The payload is what the pack reads.

Each vector, packs/gdl90/vectors/golden-<kind>-<n>.json:
  input, expect  the payload, lowercase hex: a round trip
  model          "@kind" and, under the pack's keys, what the reference's
                 messageToObject decodes. The ForeFlight ID message, which it
                 does not decode, takes the arguments its Encoder was given.
  source         the reference, its commit and the input's origin; no engine is run

Not compared, each for a reason in the reference:
  - the alert status of a traffic or ownship report: its decoder masks the
    nibble with 0x0b11110000, a hex literal whose low byte is 0, so it reports 0
    for every status (inputs carry other statuses; the round trip covers them)
  - a horizontal velocity of 0xFFF and a vertical velocity of 0x800 (no data):
    it reports both as 0, so the inputs carry known velocities
  - a call sign that is not 8 upper-case letters and digits: the reference
    drops other characters, and pads a short one with spaces (as the GDL 90 ICD,
    3.5.1.11, requires), where the pack pads with NUL bytes; so every call sign
    and ForeFlight name here fills its field
  - the message counts of a heartbeat: it reports the uplink count and the
    basic and long count and not the reserved bit between them; the inputs
    leave that bit 0, and the raw field is put back from the two counts
  - the uplink message (ID 7, 436 bytes) and the ForeFlight AHRS message: it
    has no encoder for either, and the pack maps only the uplink's header
  - the ForeFlight serial number, which its encoder writes as text and the
    pack reads as a number: only the "no serial" form is used, an absent key

Usage:
  python3 -I tools/gen/golden-gdl90.py [--cache DIR]           write
  python3 -I tools/gen/golden-gdl90.py --check [--cache DIR]   exit 1 when a
                                                               vector differs
"""
import argparse
import ast
import hashlib
import importlib
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "packs", "gdl90", "vectors")
REPO, COMMIT = "etdey/gdl90", "a026ec784acecb82741e729b658fc532f396a597"
FILES = {
    "LICENSE": "27130c67ffdc08f55a8a8fedc6e9652e2b632c9882ff970faab2e42d17bf4bc1",
    "gdl90/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "gdl90/encoder.py": "54de53c68a160f1991d2ceb9515dea5a41f591f3038f0766b3a571584954c0ca",
    "gdl90/fcs.py": "6e02b98d86b0cb050294928e44c1f98464eca7e8f511ccb696b417c081ccfe02",
    "gdl90/messages.py": "8d185810d738e694fafcd40d5f5ea1204dd560ec976b45bcf1f20142abf17de8",
    "gdl90/tests/test_decoder.py": "26573b7d68e3e35c23402980eaa8f6cab90b164833bb2f1e8b4495fcc6db1842",
}
TESTS = ["test_heartbeat", "test_ownship_geo_alt"]
# test_ownship and test_traffic are not used: their call signs are padded with spaces, as the GDL 90
# ICD (3.5.1.11) requires, and the pack writes NUL padding (packs/gdl90/pack.md), so their round
# trip is not byte for byte. Their fields are those of the encoder-built reports below.

# Encoder method and its keyword arguments. Positions are whole counts of the 24-bit
# field (k * 180 / 2**23 degrees), so the encoder's truncation keeps them exact;
# altitudes are whole 25 ft or 5 ft steps, vertical rates whole 64 fpm steps and tracks
# whole 360/256 degree steps.
P = 180.0 / 2 ** 23
BUILD = [
    ("msgHeartbeat", dict(st1=0x81, st2=0x01, ts=0, mc=0)),
    ("msgHeartbeat", dict(st1=0xED, st2=0x7F, ts=86399, mc=(31 << 11) | 1023)),
    ("msgHeartbeat", dict(st1=0x01, st2=0x00, ts=43210, mc=(5 << 11) | 300)),
    ("msgTrafficReport", dict(status=1, addrType=0, address=0xA1B2C3, latitude=4194304 * P, longitude=-6291456 * P,
                              altitude=35000, misc=9, navIntegrityCat=8, navAccuracyCat=9, hVelocity=450,
                              vVelocity=-1984, trackHeading=128 * 360 / 256, emitterCat=3, callSign="UAL123AB", code=0)),
    ("msgTrafficReport", dict(status=0, addrType=2, address=0x000001, latitude=-3355443 * P, longitude=7340032 * P,
                              altitude=-1000, misc=8, navIntegrityCat=11, navAccuracyCat=11, hVelocity=0,
                              vVelocity=0, trackHeading=0, emitterCat=1, callSign="N12345XY", code=2)),
    ("msgTrafficReport", dict(status=0, addrType=1, address=0xFFFFFE, latitude=8388607 * P, longitude=8388607 * P,
                              altitude=101350, misc=11, navIntegrityCat=6, navAccuracyCat=7, hVelocity=4094,
                              vVelocity=32512, trackHeading=255 * 360 / 256, emitterCat=14, callSign="ZZ9PLURA", code=6)),
    ("msgTrafficReport", dict(status=0, addrType=0, address=0x3C6586, latitude=-8388608 * P, longitude=-8388608 * P,
                              altitude=2500, misc=1, navIntegrityCat=0, navAccuracyCat=0, hVelocity=12,
                              vVelocity=-32512, trackHeading=64 * 360 / 256, emitterCat=7, callSign="DLH4AB01", code=1)),
    ("msgOwnshipReport", dict(status=0, addrType=0, address=0xBEEF01, latitude=2490368 * P, longitude=-1048576 * P,
                              altitude=4500, misc=9, navIntegrityCat=9, navAccuracyCat=10, hVelocity=120,
                              vVelocity=640, trackHeading=200 * 360 / 256, emitterCat=1, callSign="N123MEGA", code=0)),
    ("msgOwnshipReport", dict(status=1, addrType=1, address=0x00ABCD, latitude=-262144 * P, longitude=131072 * P,
                              altitude=0, misc=0, navIntegrityCat=5, navAccuracyCat=4, hVelocity=1,
                              vVelocity=-64, trackHeading=1 * 360 / 256, emitterCat=0, callSign="GABCD123", code=5)),
    ("msgOwnshipGeometricAltitude", dict(altitude=4155, merit=50, warning=False)),
    ("msgOwnshipGeometricAltitude", dict(altitude=-1250, merit=10, warning=True)),
    ("msgOwnshipGeometricAltitude", dict(altitude=163835, merit=32766, warning=False)),
    ("msgForeFlightMessage101", dict(sn=None, nameShort="Stratux1", nameLong="gdl90-encoder-16", capmask=1)),
    ("msgForeFlightMessage101", dict(sn=None, nameShort="GOATBOX2", nameLong="Golden vector 02", capmask=0)),
]
KIND = {"Heartbeat": "heartbeat", "OwnshipReport": "ownship", "TrafficReport": "traffic",
        "OwnshipGeometricAltitude": "ownship-geometric-altitude"}


def fetch(cache):
    """Fetch and check the reference's files; return the directory that holds package gdl90."""
    base = os.path.join(cache, COMMIT)
    for path, sha in FILES.items():
        local = os.path.join(base, *path.split("/"))
        if not os.path.exists(local):
            os.makedirs(os.path.dirname(local), exist_ok=True)
            url = "https://raw.githubusercontent.com/%s/%s/%s" % (REPO, COMMIT, path)
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
            with open(local, "wb") as fh:
                fh.write(data)
        if hashlib.sha256(open(local, "rb").read()).hexdigest() != sha:
            raise SystemExit("golden-gdl90: %s at %s is not SHA-256 %s" % (path, COMMIT[:7], sha))
    return base


def test_frames(base):
    """{test name: frame body (between the flags)} from the decoder tests."""
    src = open(os.path.join(base, "gdl90", "tests", "test_decoder.py"), encoding="utf-8").read()
    out = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name in TESTS:
            for st in ast.walk(node):
                if isinstance(st, ast.Assign) and getattr(st.targets[0], "id", "") == "rawdata":
                    out[node.name] = bytes(ast.literal_eval(st.value.args[0]))
    missing = [t for t in TESTS if t not in out]
    if missing:
        raise SystemExit("golden-gdl90: no rawdata in %s" % ", ".join(missing))
    return out


def unframe(body, fcs):
    """The payload of a frame body: escapes undone, CRC checked by the reference, dropped."""
    out, esc = bytearray(), False
    for c in body:
        if esc:
            out.append(c ^ 0x20)
            esc = False
        elif c == 0x7D:
            esc = True
        else:
            out.append(c)
    payload, crc = out[:-2], out[-2:]
    if not fcs.crcCheck(payload, crc):
        raise SystemExit("golden-gdl90: a frame's CRC does not check: %s" % bytes(body).hex())
    return bytes(payload)


def report_model(m):
    misc = m.Misc
    d = {"gdl90.address_type": m.Type, "gdl90.address": m.Address, "lat": repr(m.Latitude),
         "lon": repr(m.Longitude), "gdl90.pressure_alt_ft": m.Altitude, "gdl90.alt_raw": (m.Altitude + 1000) // 25,
         "gdl90.airborne": misc >> 3 & 1, "gdl90.extrapolated": misc >> 2 & 1, "gdl90.track_type": misc & 3,
         "gdl90.nic": m.NavIntegrityCat, "gdl90.nacp": m.NavAccuracyCat, "gdl90.speed_kt": m.HVelocity,
         "gdl90.vvel_fpm": m.VVelocity, "gdl90.vvel_raw": m.VVelocity // 64,
         "gdl90.track_raw": round(m.TrackHeading / (360.0 / 256)), "gdl90.emitter_category": m.EmitterCat,
         "callsign": m.CallSign, "gdl90.priority_status": m.Code}
    if (m.Altitude + 1000) % 25 or m.VVelocity % 64 or m.TrackHeading / (360.0 / 256) != d["gdl90.track_raw"]:
        raise SystemExit("golden-gdl90: a report field is not a whole step: %r" % (m,))
    return d


def model_of(m, args):
    if m is None:
        # the ForeFlight ID message: the reference decodes no message 101 of 39 bytes;
        # the model is the arguments its Encoder took
        return {"@kind": "foreflight-id", "gdl90.ff_version": 1, "gdl90.ff_short_name": args["nameShort"],
                "gdl90.ff_long_name": args["nameLong"], "gdl90.ff_reserved": args["capmask"] >> 8,
                "gdl90.ff_capabilities": args["capmask"] & 0xFF, "@absent": ["gdl90.ff_serial"]}
    kind = KIND[type(m).__name__]
    d = {"@kind": kind}
    if kind == "heartbeat":
        s1, s2, ts, (up, bl) = m.StatusByte1, m.StatusByte2, m.TimeStamp, m.MessageCounts
        d.update({"gdl90.hb_gps_valid": s1 >> 7 & 1, "gdl90.hb_maint_required": s1 >> 6 & 1,
                  "gdl90.hb_status1_bit5": s1 >> 5 & 1, "gdl90.hb_addr_talkback": s1 >> 4 & 1,
                  "gdl90.hb_status1_bits3_1": s1 >> 1 & 7, "gdl90.hb_uat_initialized": s1 & 1,
                  "gdl90.hb_time_bit16": ts >> 16 & 1, "gdl90.hb_status2_bits6_1": s2 >> 1 & 0x3F,
                  "gdl90.hb_utc_ok": s2 & 1, "gdl90.hb_time_low16": ts & 0xFFFF,
                  "gdl90.hb_msg_counts_raw": up << 11 | bl})
    elif kind in ("ownship", "traffic"):
        d.update(report_model(m))
    else:
        d.update({"gdl90.geo_alt_ft": m.Altitude, "gdl90.geo_fom_raw": m.VerticalMetrics})
    return {k: v if isinstance(v, (str, list)) else str(v) for k, v in d.items()}


def build(base):
    sys.path.insert(0, base)
    try:
        enc_mod = importlib.import_module("gdl90.encoder")
        messages = importlib.import_module("gdl90.messages")
        fcs = importlib.import_module("gdl90.fcs")
    finally:
        sys.path.remove(base)
    for mod in (enc_mod, messages, fcs):
        if not os.path.abspath(mod.__file__).startswith(os.path.abspath(base)):
            raise SystemExit("golden-gdl90: %s was not imported from the fetched files" % mod.__name__)
    inputs = [(body, None, "the rawdata of %s in gdl90/tests/test_decoder.py" % t) for t, body in test_frames(base).items()]
    enc = enc_mod.Encoder()
    for i, (meth, args) in enumerate(BUILD):
        frame = bytes(getattr(enc, meth)(**args))
        if frame[0] != 0x7E or frame[-1] != 0x7E:
            raise SystemExit("golden-gdl90: %s wrote no flags" % meth)
        inputs.append((frame[1:-1], args, "Encoder.%s with BUILD[%d] of tools/gen/golden-gdl90.py" % (meth, i)))
    vecs, count = {}, {}
    for body, args, origin in inputs:
        payload = unframe(body, fcs)
        decoded = messages.messageToObject(bytearray(payload))
        if decoded is None and payload[0] != 0x65:
            raise SystemExit("golden-gdl90: the reference does not decode %s" % origin)
        model = model_of(decoded, args)
        kind = model["@kind"]
        count[kind] = count.get(kind, 0) + 1
        name = "golden-%s-%d" % (kind, count[kind])
        vecs[name + ".json"] = {
            "name": name, "from": "gdl90", "to": "gdl90", "input": payload.hex(), "expect": payload.hex(),
            "model": model,
            "source": "gdl90 (github.com/%s) at %s: %s, unframed and its CRC checked with the reference's crcCheck. "
                      "Written by tools/gen/golden-gdl90.py; no engine is run." % (REPO, COMMIT[:7], origin),
            "reference": ("the arguments the reference's Encoder took (its decoder has no ForeFlight ID message)"
                          if decoded is None else "what the reference's messageToObject (MIT) decodes, under the "
                          "pack's keys; the alert status is not compared (tools/gen/golden-gdl90.py)"),
        }
    return vecs


def text(vec):
    return json.dumps(vec, indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="golden-gdl90", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--cache", default=os.path.join(os.path.expanduser("~"), ".cache", "golden-gdl90"))
    args = ap.parse_args(argv)
    vecs = build(fetch(args.cache))
    have = {n for n in os.listdir(OUT) if n.startswith("golden-") and n.endswith(".json")}
    if args.check:
        bad = sorted(n for n in set(vecs) | have
                     if n not in vecs or n not in have or open(os.path.join(OUT, n), encoding="utf-8").read() != text(vecs[n]))
        if bad:
            print("golden-gdl90: %d vector(s) differ from what the reference writes: %s" % (len(bad), ", ".join(bad[:10])),
                  file=sys.stderr)
            return 1
        print("golden-gdl90: --check: ok, %d vectors" % len(vecs))
        return 0
    for n in have - set(vecs):
        os.remove(os.path.join(OUT, n))
    for n, v in vecs.items():
        with open(os.path.join(OUT, n), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text(v))
    print("golden-gdl90: wrote %d vectors" % len(vecs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
