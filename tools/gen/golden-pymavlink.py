#!/usr/bin/env python3
"""golden-pymavlink: golden vectors for packs/mavlink2 from pymavlink, the
reference MAVLink implementation (shared-model hardening, item 2: meaning is
tested against a format's own reference encoder, not only engine agreement).

For each kind of packs/mavlink2/pack.def whose message pymavlink's common
dialect defines, it builds one MAVLink 2 frame with pymavlink and writes
packs/mavlink2/vectors/golden-<msgid>-<kind>.json:

  input, expect  the frame exactly as pymavlink serializes it, without the two
                 CRC bytes (the pack maps no CRC: its header comment says so),
                 as lower-case hex: a round trip
  model          "@kind", and every decoded key whose value follows from the
                 pymavlink value by the field's own line: uint and twos (the
                 integer), f32 and f64 (the IEEE value), sscale:1/N (the
                 integer over N), ascii (the text). A field with another
                 transform is in the frame and out of `model`.
  source         pymavlink, its version and dialect; no engine is run

The values: every byte of every field the pack's kind covers is non-zero (a
pattern by field and byte, avoiding each line's `absent` values), and the
extension fields after the kind's length are zero, so pymavlink's MAVLink 2
trailing-zero truncation stops exactly at the length the kind selects on.
A frame whose last fields are zero is truncated further and selects no kind
in the pack today (tools/gen/notes/golden-pymavlink.md).

Usage (pymavlink 2.4.50 importable; standard library otherwise):

  python3 -I tools/gen/golden-pymavlink.py            write the vectors
  python3 -I tools/gen/golden-pymavlink.py --check    exit 1 when a committed
                                                      vector differs (CI, with
                                                      pymavlink installed)
"""
import argparse
import json
import math
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACK = os.path.join(ROOT, "packs", "mavlink2", "pack.def")
OUT = os.path.join(ROOT, "packs", "mavlink2", "vectors")
PYMAVLINK = "2.4.50"
SYSID, COMPID, SEQ = 7, 9, 42

# kinds whose golden vector the engines do not pass yet; each is a finding
# for the pack, listed in tools/gen/notes/golden-pymavlink.md
SKIP_FILE = os.path.join(ROOT, "tools", "gen", "notes", "golden-pymavlink-skip.txt")


def parse_pack(path):
    """-> {kind: {"msgid", "length", "fields": [(key, byte, bits, kind_of, absent)]}}"""
    kinds, cur = {}, None
    for line in open(path, encoding="utf-8"):
        t = line.split()
        if not t or t[0].startswith("#"):
            continue
        if t[0] == "kind":
            cur = kinds.setdefault(t[1], {"msgid": None, "length": None, "fields": []})
        elif cur is None:
            continue
        elif t[0] == "when" and t[1] == "0:56:24":
            cur["msgid"] = int(t[2])
        elif t[0] == "when" and t[1] == "0:8:8":
            cur["length"] = int(t[2])
        elif t[0] == "field":
            word, bit, bits = (int(x) for x in t[2].split(":"))
            absent = set()
            if "absent" in t:
                absent = set(t[t.index("absent") + 1].split(","))
            cur["fields"].append((t[1], (bit - 80) // 8, bits, t[3], absent))
    return {k: v for k, v in kinds.items() if v["msgid"] is not None and v["length"] is not None}


CHAR = {"uint8_t": "B", "int8_t": "b", "uint16_t": "H", "int16_t": "h", "uint32_t": "I", "int32_t": "i",
        "uint64_t": "Q", "int64_t": "q", "float": "f", "double": "d", "char": "s", "uint8_t_mavlink_version": "B"}


def layout(cls):
    """[(name, byte offset, struct char, count)] in wire order, from the
    message's field types (definition order) and array lengths (wire order)."""
    types = dict(zip(cls.fieldnames, cls.fieldtypes))
    out, at = [], 0
    for name, n in zip(cls.ordered_fieldnames, cls.array_lengths):
        ch = CHAR[types[name]]
        count = n or 1
        out.append((name, at, ch, count))
        at += (1 if ch == "s" else struct.calcsize("<" + ch)) * count
    return out


def pattern_int(ch, idx, avoid):
    size = struct.calcsize("<" + ch)
    for k in range(64):
        bs = bytearray(((0x11 * ((idx + j + k) % 15 + 1)) & 0xFF) or 0x5A for j in range(size))
        if ch == "Q":                       # the shared model's int is 64-bit signed
            bs[-1] = (bs[-1] % 0x7F) or 0x3C
        bs = bytes(bs)
        v = struct.unpack("<" + ch, bs)[0]
        if str(v) not in avoid:
            return v
    raise ValueError("no value avoids %r" % avoid)


def pattern_float(ch, idx, avoid):
    for k in range(64):
        v = float(struct.unpack("<" + ch, struct.pack("<" + ch, 1.5 + 0.25 * ((idx + k) % 37) + 0.0078125))[0])
        bs = struct.pack("<" + ch, v)
        if all(b for b in bs[-1:]) and str(v) not in avoid and not math.isnan(v):
            return v
    raise ValueError("no float avoids %r" % avoid)


RANGES = os.path.join(ROOT, "tools", "model-ranges.json")


def ranges():
    """{key: (min, max)} of tools/model-ranges.json: tools/model-checks.py holds
    every decoded value to these, so a golden value must lie inside."""
    with open(RANGES, encoding="utf-8") as fh:
        return {k: (v.get("min"), v.get("max")) for k, v in json.load(fh)["keys"].items()
                if v.get("min") is not None or v.get("max") is not None}


def in_range_raw(f, ch, lo_hi):
    """A raw field value whose decoded value lies inside the key's range (a
    third of the way in, else the first of a few other points that fits the
    field), by the inverse of the field's own transform; None when the
    transform has no simple inverse or no point fits."""
    for frac in (0.318, 0.5, 0.618, 0.75, 0.9, 0.2, 0.1):
        raw = _raw_at(f, ch, lo_hi, frac)
        if raw is not None:
            return raw
    return None


def _raw_at(f, ch, lo_hi, frac):
    lo, hi = lo_hi
    if lo is not None and hi is not None:
        want = lo + (hi - lo) * frac
    elif hi is None:
        want = lo + max(1, abs(lo)) * frac
    else:
        want = hi - max(1, abs(hi)) * frac
    typ = f[3]
    if typ in ("f32", "f64"):
        return float(struct.unpack("<" + ch, struct.pack("<" + ch, want))[0]) if ch in "fd" else None
    if typ in ("uint", "twos"):
        raw = int(want)
    elif typ.startswith("sscale:1/") or typ.startswith("uiscale:1/"):
        raw = int(round(want * int(typ.split("/")[1])))
    elif typ.startswith("uiscale:") and typ.count(":") == 2:
        _, mul, off = typ.split(":")
        raw = int(round((want - int(off)) / int(mul)))
    else:
        return None
    if ch in "fd":
        return None
    bits = struct.calcsize("<" + ch) * 8
    lo_raw, hi_raw = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if ch.islower() else (0, (1 << bits) - 1)
    if ch == "Q":
        hi_raw = (1 << 63) - 1
    return raw if lo_raw <= raw <= hi_raw and str(raw) not in f[4] else None


def build(cls, kind):
    """-> (field values for pymavlink, {payload byte: key line}) for one kind."""
    by_byte = {f[1]: f for f in kind["fields"]}
    limits = ranges()
    values, idx = {}, 0
    for name, at, ch, n in layout(cls):
        inside = at < kind["length"]
        def one(offset, i):
            f = by_byte.get(offset)
            avoid = f[4] if f else set()
            if not inside:
                return 0.0 if ch in "fd" else 0
            if f and f[0] in limits:
                raw = in_range_raw(f, ch, limits[f[0]])
                if raw is not None:
                    return raw
            if ch in "fd":
                return pattern_float(ch, i, avoid)
            return pattern_int(ch, i, avoid)
        if ch == "s" and n == 1:            # one char
            values[name] = chr(0x41 + idx % 26) if inside else "\0"
            idx += 1
        elif ch == "s":                     # char[n]
            values[name] = "".join(chr(0x41 + (idx + j) % 26) for j in range(n)).encode() if inside else b""
            idx += 1
        elif n > 1:
            size = struct.calcsize("<" + ch)
            values[name] = [one(at + j * size, idx + j) for j in range(n)]
            idx += n
        else:
            values[name] = one(at, idx)
            idx += 1
    return values


def model_value(f, raw_bytes):
    key, _, bits, typ, absent = f
    if typ == "uint":
        v = int.from_bytes(raw_bytes, "little")
    elif typ == "twos":
        v = int.from_bytes(raw_bytes, "little", signed=True)
    elif typ in ("f32", "f64"):
        v = struct.unpack("<f" if typ == "f32" else "<d", raw_bytes)[0]
    elif typ.startswith("sscale:1/"):
        v = int.from_bytes(raw_bytes, "little", signed=True) / int(typ.split("/")[1])
    elif typ == "ascii":
        return raw_bytes.split(b"\0", 1)[0].decode("ascii")
    else:
        return None
    if str(v) in absent or (isinstance(v, int) and str(v) in absent):
        return None
    return repr(v) if isinstance(v, float) else str(v)


def vectors(skip=()):
    from pymavlink.dialects.v20 import common
    kinds = parse_pack(PACK)
    mav = common.MAVLink(None, srcSystem=SYSID, srcComponent=COMPID)
    out = {}
    for kname, kind in sorted(kinds.items(), key=lambda kv: (kv[1]["msgid"], kv[0])):
        cls = common.mavlink_map.get(kind["msgid"])
        if cls is None or kname in skip:
            continue
        values = build(cls, kind)
        msg = cls(**values)
        mav.seq = SEQ
        frame = msg.pack(mav)
        if frame[0] != 0xFD or frame[1] != kind["length"]:
            continue                        # cannot be built at the kind's length
        body = frame[:-2]                   # without the CRC
        payload = body[10:]
        model = {"@kind": kname}
        for f in kind["fields"]:
            if f[1] < 0:
                continue
            raw = payload[f[1]:f[1] + f[2] // 8]
            if len(raw) * 8 != f[2]:
                continue
            v = model_value(f, raw)
            if v is not None:
                model[f[0]] = v
        name = "golden-%05d-%s" % (kind["msgid"], kname.replace("_", "-"))
        out[name + ".json"] = {
            "name": name,
            "from": "mavlink2",
            "to": "mavlink2",
            "input": body.hex(),
            "expect": body.hex(),
            "model": model,
            "source": "pymavlink %s, dialect v20.common: %s(%s) packed by MAVLink.pack with sysid %d, compid %d, "
                      "seq %d; the two CRC bytes are left off (the pack maps no CRC). Written by "
                      "tools/gen/golden-pymavlink.py; no engine is run."
                      % (PYMAVLINK, cls.msgname, ", ".join(cls.fieldnames), SYSID, COMPID, SEQ),
            "reference": "MAVLink 2 serialization (https://mavlink.io/en/guide/serialization.html): fields in wire "
                         "order, little-endian, trailing zero bytes of the payload truncated; extension fields here "
                         "are zero, so the frame's LEN is the %d bytes the kind selects on. model holds the keys "
                         "whose values follow from the field lines of packs/mavlink2/pack.def." % kind["length"],
        }
    return out


def text(vec):
    return json.dumps(vec, indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="golden-pymavlink", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    skip = set()
    if os.path.exists(SKIP_FILE):
        skip = {l.split("#")[0].strip() for l in open(SKIP_FILE, encoding="utf-8")} - {""}
    try:
        vecs = vectors(skip)
    except ImportError:
        print("golden-pymavlink: pymavlink %s is not importable (pip install pymavlink==%s)" % (PYMAVLINK, PYMAVLINK),
              file=sys.stderr)
        return 1
    have = {n for n in os.listdir(OUT) if n.startswith("golden-") and n.endswith(".json")}
    if args.check:
        bad = sorted(n for n in set(vecs) | have
                     if n not in vecs or n not in have or open(os.path.join(OUT, n), encoding="utf-8").read() != text(vecs[n]))
        if bad:
            print("golden-pymavlink: %d vector(s) differ from what pymavlink writes: %s" % (len(bad), ", ".join(bad[:10])),
                  file=sys.stderr)
            return 1
        print("golden-pymavlink: --check: ok, %d vectors" % len(vecs))
        return 0
    for n in have - set(vecs):
        os.remove(os.path.join(OUT, n))
    for n, v in vecs.items():
        with open(os.path.join(OUT, n), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text(v))
    print("golden-pymavlink: wrote %d vectors" % len(vecs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
