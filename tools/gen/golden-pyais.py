#!/usr/bin/env python3
"""golden-pyais: golden vectors for packs/ais from pyais, a reference AIS
(AIVDM) encoder and decoder (shared-model hardening, item 2: meaning is tested
against an implementation outside this project, not only engine agreement).

For the position reports (types 1, 2, 3, 4, 9, 18, 19, 21, 27) and the static
reports (types 5, 24 A and B) it encodes a message with pyais.encode_dict,
decodes that payload with pyais.decode, and writes
packs/ais/vectors/golden-<kind>-<n>.json:

  input, expect  the armored payload pyais writes (the sixth field of its
                 sentence): a round trip
  model          "@kind" and the values pyais decodes from that payload, under
                 the pack's keys: its latitude and longitude, its speed in knots
                 converted with 1 kn = 1852/3600 m/s, its course, and its other
                 fields as integers or text
  source         pyais and its version; no engine is run

Positions are chosen so that pyais's six-decimal latitude and longitude are the
exact value of the raw field (a raw count of 1/600000 minute that is a
multiple of 3, a count of 1/600 that is a multiple of 6); the script checks
this and refuses a point that is not.

Fields left out of the model: pyais reports the rate of turn as degrees per
minute, not the raw field the pack keys (`ais.turn`); the spare and reserved
bits; type 27's course, which the pack keeps raw (`ais.course_lr`).

Usage (pyais 3.3.1 and attrs 26.1.0 importable, as tools/gen/golden-pyais.txt
pins them with their hashes; standard library otherwise):

  python3 -I tools/gen/golden-pyais.py            write the vectors
  python3 -I tools/gen/golden-pyais.py --check    exit 1 when a committed
                                                  vector differs (CI)
"""
import argparse
import json
import os
import sys
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "packs", "ais", "vectors")
PYAIS = "3.3.1"

# raw latitude and longitude counts of 1/600000 minute (degrees x 600000), each a
# multiple of 3: every quadrant, near a pole and the antimeridian
POINTS = [
    (29028981, -74037231),      # 48.3816 N, 123.3953 W
    (-20321292, 90725175),      # 33.8688 S, 151.2092 E
    (24427665, -44403585),      # 40.7127 N, 74.0059 W
    (53931216, 107992593),      # 89.885 N, 179.98 E
]
# the same places for type 27, counts of 1/600 minute, multiples of 6
POINTS_LR = [(29028, -74034), (-20316, 90720), (24426, -44400)]

MMSI = [371798000, 503123456, 366999111, 257000123]
# pack kind for each pyais message type (type 24 by its part number)
KIND = {1: "position-a1", 2: "position-a2", 3: "position-a3", 4: "base-station", 5: "static-voyage",
        9: "sar-aircraft", 18: "position-b", 19: "position-b-ext", 21: "aid-to-nav", 27: "long-range"}

# pyais field -> pack key, for the fields both read the same way
COMMON = {"mmsi": "ais.mmsi", "accuracy": "ais.accuracy", "raim": "ais.raim", "second": "ais.second",
          "radio": "ais.radio", "heading": "ais.heading", "epfd": "ais.epfd", "dte": "ais.dte",
          "assigned": "ais.assigned", "lat": "lat", "lon": "lon", "course": "course"}
EXTRA = {
    1: {"status": "ais.nav_status", "maneuver": "ais.maneuver"},
    4: {"year": "ais.year", "month": "ais.month", "day": "ais.day", "hour": "ais.hour", "minute": "ais.minute"},
    5: {"ais_version": "ais.ais_version", "imo": "ais.imo", "callsign": "callsign", "shipname": "ais.shipname",
        "ship_type": "ais.shiptype", "to_bow": "ais.to_bow", "to_stern": "ais.to_stern", "to_port": "ais.to_port",
        "to_starboard": "ais.to_starboard", "month": "ais.eta_month", "day": "ais.eta_day",
        "hour": "ais.eta_hour", "minute": "ais.eta_minute", "draught": "ais.draught",
        "destination": "ais.destination"},
    9: {"alt": "ais.altitude"},
    18: {"cs": "ais.cs", "display": "ais.display", "dsc": "ais.dsc", "band": "ais.band", "msg22": "ais.msg22"},
    19: {"shipname": "ais.shipname", "ship_type": "ais.shiptype", "to_bow": "ais.to_bow", "to_stern": "ais.to_stern",
         "to_port": "ais.to_port", "to_starboard": "ais.to_starboard"},
    21: {"aid_type": "ais.aid_type", "name": "ais.name", "to_bow": "ais.to_bow", "to_stern": "ais.to_stern",
         "to_port": "ais.to_port", "to_starboard": "ais.to_starboard", "off_position": "ais.off_position",
         "virtual_aid": "ais.virtual_aid"},
    27: {"status": "ais.nav_status", "gnss": "ais.gnss"},
}
EXTRA[2] = EXTRA[3] = EXTRA[1]
# speed fields: the pack's unit is m/s; pyais reports knots
KNOTS_PER_UNIT = {1: Fraction(1, 10), 2: Fraction(1, 10), 3: Fraction(1, 10), 18: Fraction(1, 10),
                  19: Fraction(1, 10), 9: Fraction(1), 27: Fraction(1)}
SPEED_KN = [12.3, 0.1, 25.6, 102.2]


def number(v):
    """A model value as the pack's canonical text: an integral number without a
    fraction, any other float in its shortest round-trip form."""
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def value(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if hasattr(v, "value"):          # pyais enums
        v = v.value
    if isinstance(v, str):
        return v
    return number(v)


def dearmor(text):
    """The bits of an armored AIS payload (ITU-R M.1371 six-bit ASCII armoring)."""
    out = []
    for ch in text:
        v = ord(ch) - 48
        if v > 40:
            v -= 8
        out.append(format(v, "06b"))
    return "".join(out)


def armor(bits):
    bits += "0" * (-len(bits) % 6)
    out = []
    for i in range(0, len(bits), 6):
        v = int(bits[i:i + 6], 2)
        out.append(chr(v + 48 if v < 40 else v + 56))
    return "".join(out)


def exact(deg, per_degree, field):
    """Refuse a point whose six-decimal value is not the exact raw count."""
    raw = Fraction(repr(deg)) * per_degree
    if raw.denominator != 1:
        raise SystemExit("golden-pyais: %s %r is not a whole count of 1/%d degree" % (field, deg, per_degree))


def messages():
    """(name, pyais fields) for every vector, in a fixed order."""
    out = []
    for i, (la, lo) in enumerate(POINTS):
        base = {"mmsi": MMSI[i], "lat": la / 600000, "lon": lo / 600000, "accuracy": i % 2, "raim": (i + 1) % 2,
                "second": 10 + i, "radio": 2249 + i}
        for t in (1, 2, 3):
            out.append(("%s-%d" % (KIND[t], i + 1), dict(base, type=t, status=i % 9, speed=SPEED_KN[i],
                                                         course=224.0 - 50 * i, heading=215 - 40 * i, maneuver=i % 3)))
        out.append(("%s-%d" % (KIND[4], i + 1), dict(base, type=4, year=2026, month=1 + i, day=10 + i, hour=i * 5,
                                                     minute=7 * i, epfd=1 + i % 3)))
        out.append(("%s-%d" % (KIND[9], i + 1), dict(base, type=9, alt=150 * (i + 1), speed=round(SPEED_KN[i]),
                                                     course=90.0 + 10 * i, dte=1, assigned=i % 2)))
        out.append(("%s-%d" % (KIND[18], i + 1), dict(base, type=18, speed=SPEED_KN[i], course=10.0 * (i + 1),
                                                      heading=12 * (i + 1), cs=1, display=0, dsc=1, band=1,
                                                      msg22=1, assigned=0)))
        out.append(("%s-%d" % (KIND[19], i + 1), dict(base, type=19, speed=SPEED_KN[i], course=33.3 * (i + 1),
                                                      heading=30 * i, shipname="GOLDEN %d" % (i + 1),
                                                      ship_type=36 + i, to_bow=10 + i, to_stern=5, to_port=2,
                                                      to_starboard=3, epfd=1, dte=0, assigned=0)))
        out.append(("%s-%d" % (KIND[21], i + 1), dict(base, type=21, aid_type=1 + i, name="LIGHT %d" % (i + 1),
                                                      to_bow=1, to_stern=1, to_port=1, to_starboard=1, epfd=1,
                                                      off_position=i % 2, virtual_aid=0, assigned=0)))
    for i, (la, lo) in enumerate(POINTS_LR):
        out.append(("%s-%d" % (KIND[27], i + 1), {"type": 27, "mmsi": MMSI[i], "lat": la / 600, "lon": lo / 600,
                                                  "accuracy": 1, "raim": 0, "status": i, "speed": 10 + i,
                                                  "course": 100 + i, "gnss": 0}))
    for i in range(3):
        out.append(("static-voyage-%d" % (i + 1), {"type": 5, "mmsi": MMSI[i], "ais_version": 0,
                                                   "imo": 9123456 + i, "callsign": "CALL%d" % i,
                                                   "shipname": "GOLDEN SHIP %d" % i, "ship_type": 70 + i,
                                                   "to_bow": 100, "to_stern": 20, "to_port": 10,
                                                   "to_starboard": 12, "epfd": 1, "month": 3 + i, "day": 15,
                                                   "hour": 6, "minute": 30, "draught": 7.5 + i,
                                                   "destination": "PORT %d" % i, "dte": 0}))
        out.append(("static-a-%d" % (i + 1), {"type": 24, "partno": 0, "mmsi": MMSI[i], "shipname": "B SHIP %d" % i}))
    return out


def build(pyais):
    vecs = {}
    for name, fields in messages():
        t = fields["type"]
        # encode_dict picks the class by `type` and writes the type field from `msg_type`
        sentences = pyais.encode_dict(dict(fields, msg_type=t), talker_id="AI", radio_channel="A")
        # a long message is several sentences; the pack's message is the whole payload, the parts joined
        payload = "".join(s.split(",")[5] for s in sentences)
        d = pyais.decode(*sentences).asdict()
        if d.get("msg_type") != t:
            raise SystemExit("golden-pyais: %s decodes as type %r" % (name, d.get("msg_type")))
        if "lat" in fields:
            # what pyais decodes must be the exact raw count, or its six decimals hide a rounding
            per = 600 if t == 27 else 600000
            exact(d["lat"], per, name + " lat")
            exact(d["lon"], per, name + " lon")
        kind = KIND.get(t) or ("static-a" if d.get("partno") == 0 else "static-b")
        model = {"@kind": kind}
        mapping = dict(COMMON, **EXTRA.get(t, {}))
        if t == 27:
            mapping.pop("course")
        if t == 24:
            mapping = {"mmsi": "ais.mmsi", "partno": "ais.part_no", "shipname": "ais.shipname"}
        for f, key in mapping.items():
            if f in d and d[f] is not None and f in fields:
                model[key] = value(d[f])
        if t in KNOTS_PER_UNIT and d.get("speed") is not None:
            # pyais reports knots; the pack's key is m/s: 1 kn = 1852/3600 m/s, one rounding
            model["speed_ms"] = number(float(Fraction(repr(float(d["speed"]))) * Fraction(1852, 3600)))
        expect, note = payload, ""
        if t == 21:
            # pyais writes the name extension (bits 272 on) as zeros; the pack keeps the 272 bits and
            # its pack.md states that a round trip drops the extension
            expect = armor(dearmor(payload)[:272])
            note = " The expected output is pyais's payload cut to its first 272 bits: the pack does not " \
                   "read the name extension and a round trip drops it (packs/ais/pack.md)."
        vecs["golden-%s.json" % name] = {
            "name": "golden-%s" % name, "from": "ais", "to": "ais", "input": payload, "expect": expect,
            "model": model,
            "source": "pyais %s: pyais.encode_dict(%s), then pyais.decode of that sentence for the model values. "
                      "Written by tools/gen/golden-pyais.py; no engine is run." % (PYAIS, json.dumps(fields, sort_keys=True)),
            "reference": "AIS message type %d as pyais (MIT, github.com/M0r13n/pyais) encodes and decodes it; speed "
                         "from pyais's knots at 1 kn = 1852/3600 m/s.%s" % (t, note),
        }
    return vecs


def text(vec):
    return json.dumps(vec, indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="golden-pyais", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    try:
        import pyais
        from importlib.metadata import version
        if version("pyais") != PYAIS:
            raise ImportError(version("pyais"))
    except ImportError as e:
        print("golden-pyais: pyais %s is not importable (%s); pip install --require-hashes -r tools/gen/golden-pyais.txt"
              % (PYAIS, e), file=sys.stderr)
        return 1
    vecs = build(pyais)
    have = {n for n in os.listdir(OUT) if n.startswith("golden-") and n.endswith(".json")}
    if args.check:
        bad = sorted(n for n in set(vecs) | have
                     if n not in vecs or n not in have or open(os.path.join(OUT, n), encoding="utf-8").read() != text(vecs[n]))
        if bad:
            print("golden-pyais: %d vector(s) differ from what pyais writes: %s" % (len(bad), ", ".join(bad[:10])),
                  file=sys.stderr)
            return 1
        print("golden-pyais: --check: ok, %d vectors" % len(vecs))
        return 0
    for n in have - set(vecs):
        os.remove(os.path.join(OUT, n))
    for n, v in vecs.items():
        with open(os.path.join(OUT, n), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text(v))
    print("golden-pyais: wrote %d vectors" % len(vecs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
