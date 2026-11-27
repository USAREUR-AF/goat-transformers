#!/usr/bin/env python3
"""golden-asterix: golden vectors for the ASTERIX category packs from
asterix_decoder (Croatia Control's ASTERIX decoder), a reference decoder whose
category definitions are its own XML files, written apart from the
asterix-specs transcription these packs are generated from (shared-model
hardening, item 2).

asterix_decoder decodes; it does not encode. The inputs are therefore the
recorded captures it ships (asterix/sample_data: cat034.raw, cat048.raw,
cat062cat065.raw, cat_034_048.pcap, cat_062_065.pcap; each refused unless its
SHA-256 is the one below). A pack reads one record per data block, so each
data block is split into single-record blocks by the record lengths the
decoder reports (CAT, then LEN, then the record's own bytes, unchanged), and
each block is decoded again by the decoder. The first PER_CAT blocks of each
category with a field set not seen before are written as
packs/asterix-cat<NNN>/vectors/golden-<n>.json:

  input, expect  the single-record block, lowercase hex: a round trip
  model          "@kind" and, under the pack's keys cat<NNN>.i<item>_<subfield>
                 (or cat<NNN>.i<item> for an item of one value), the values the
                 decoder gives: numbers as it scales them, Mode 1, 2 and 3/A
                 codes (octal text) and addresses (hex text) as the integer of
                 the raw field
  source         asterix_decoder, its version and the capture; no engine is run

Only items the pack and the decoder both name are compared, and an item is
left out where the decoder's edition lays it out differently from the pack's
(EDITION below, each with the reason). Repetitive and compound items are not
compared.

Usage (asterix_decoder 0.7.11 importable, as tools/gen/golden-asterix.txt pins
it with its hash; it builds against the expat headers):

  python3 -I tools/gen/golden-asterix.py            write the vectors
  python3 -I tools/gen/golden-asterix.py --check    exit 1 when a committed
                                                    vector differs (CI)
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DECODER = "0.7.11"
CAPTURES = {
    "cat034.raw": "a5d24d471cc0fac2554924cbd6aacbf532be96204b4fb335f6275b9a1a0e5766",
    "cat048.raw": "17481bd2955d046efc5aac1022b4f5879ab02456060c419503aded54bf2e5efd",
    "cat062cat065.raw": "2916c2c01ee66d316d51bf125e28f4133a38abb7b19ee5eef1a0d7f6aaf1a53d",
    "cat_034_048.pcap": "7f4e9a37641bfa27022ee95ba52f178e68260c1b7e83d6a0e4720a96b3a2cc3d",
    "cat_062_065.pcap": "fc250f563ec96369d10f960f870a305041b85e05842d987e68dbd3c4d079df13",
}
CATS = (34, 48, 62, 65)
# the pack and its module of each category: cat062 is read by the generated full-UAP pack
# (asterix-cat062 maps only the items one encoder writes)
PACK = {34: ("asterix-cat034", "cat034"), 48: ("asterix-cat048", "cat048"),
        62: ("asterix-cat062-full", "cat062full"), 65: ("asterix-cat065", "cat065")}
PER_CAT = 6
# (category, item, subfield) left out of the comparison, each with the reason
EDITION = {
    # the decoder's definition rounds the LSB of I034/120 latitude and longitude to
    # 0.00002145767 degrees; the exact LSB is 180/2^23 (2.1457672119140625e-05), which the
    # pack uses, so the decoder's values are off by about 1e-7 of the value
    (34, "I120", "LAT"): "decoder's LSB rounded", (34, "I120", "LON"): "decoder's LSB rounded",
    (34, "I120", "Lon"): "decoder's LSB rounded",
}
# records of the captures left out because their own bytes are not in the canonical form a round
# trip writes: a presence (FX) chain that ends in an all-zero octet, which the language's rule
# (presence fx: trailing all-zero octets are not written) drops. "<capture>:<block>.<record>"
NOT_CANONICAL = {
    # bytes 69-71 of the record: a compound item's primary subfield octets ff e1 00, the third
    # all zero; a round trip writes ff e0 and the block is one octet shorter
    "cat062cat065.raw:0.1": "a compound item's presence octets end in an all-zero octet",
}
# (category, item, subfield): factor from the decoder's unit to the pack key's unit
UNIT = {
    # the decoder reports I062/136 Measured Flight Level in feet (its scale 25 ft per LSB);
    # the pack's key holds flight levels (1/4 FL per LSB): FL = ft / 100
    (62, "I136", "MFL"): (1, 100),
}
OCTAL = re.compile(r"mode(3a|2|1)$")


def pcap_payloads(data):
    """The UDP payloads of a libpcap file (Ethernet or Linux cooked capture, IPv4)."""
    magic = struct.unpack("<I", data[:4])[0]
    e = "<" if magic in (0xA1B2C3D4, 0xA1B23C4D) else ">"
    link = struct.unpack(e + "I", data[20:24])[0]
    i, out = 24, []
    while i + 16 <= len(data):
        incl = struct.unpack(e + "I", data[i + 8:i + 12])[0]
        pkt = data[i + 16:i + 16 + incl]
        i += 16 + incl
        off = 14 if link == 1 else (16 if link == 113 else 0)
        if len(pkt) < off + 28 or pkt[off + 9] != 17:
            continue
        out.append(pkt[off + (pkt[off] & 15) * 4 + 8:])
    return out


def blocks(buf):
    i = 0
    while i + 3 <= len(buf):
        n = int.from_bytes(buf[i + 1:i + 3], "big")
        if n < 3 or i + n > len(buf):
            return
        yield buf[i:i + n]
        i += n


def single_records(asterix, block):
    """[(index, single-record block, record)] of a data block, split by the decoder's record lengths."""
    try:
        recs = asterix.parse(bytes(block))
    except Exception:
        return []
    out, i = [], 3
    for r in recs:
        n = r.get("len")
        if not n:
            return []
        rec = block[i:i + n]
        i += n
        nb = bytes([block[0]]) + (n + 3).to_bytes(2, "big") + rec
        parsed = asterix.parse(nb)
        if len(parsed) == 1:
            out.append((len(out), nb, parsed[0]))
    return out


def pack_fields(cat):
    """{key: transform} of the record kind's top-level `field` lines (not inside a group), and of
    the `also` keys beside them (a raw key the same place also carries)."""
    out, depth, last = {}, 0, None
    for line in open(os.path.join(ROOT, "packs", PACK[cat][0], "pack.def"), encoding="utf-8"):
        s = line.split("#")[0].strip()
        if s.startswith("group "):
            depth += 1
        elif s == "end" and depth:
            depth -= 1
        m = re.match(r"field\s+(\S+)\s+\S+\s+(\S+)", s)
        if m and depth == 0:
            out[m.group(1)] = last = m.group(2)
        a = re.match(r"also\s+(\S+)", s)
        if a and depth == 0 and last:
            out[a.group(1)] = last
    return out


def value_for(key, transform, val):
    """The decoder's value as the pack's key holds it, or None when they do not match in kind."""
    sub = key.rsplit("_", 1)[-1] if "_" in key.split(".", 1)[1] else ""
    if isinstance(val, bool):
        val = int(val)
    if transform.startswith(("uint", "twos")):
        if isinstance(val, str):
            if OCTAL.search(sub) or OCTAL.search(key):
                return str(int(val, 8)) if re.fullmatch(r"[0-7]+", val) else None
            if "addr" in key.lower():
                return str(int(val, 16)) if re.fullmatch(r"[0-9A-Fa-f]+", val) else None
            return None
        if isinstance(val, (int, float)) and float(val).is_integer():
            return str(int(val))
        return None
    if transform.startswith(("uscale", "sscale")):
        if isinstance(val, (int, float)):
            f = float(val)
            return str(int(f)) if f.is_integer() else repr(f)
        return None
    if transform.startswith(("chars", "string")):
        return val.rstrip() if isinstance(val, str) else None
    return None


def model_of(cat, rec, fields):
    m, skipped = {"@kind": "record"}, 0
    for item, body in rec.items():
        if not re.fullmatch(r"I\d{3}", item) or not isinstance(body, dict):
            continue
        num = item[1:].lower()
        subs = {k: v for k, v in body.items() if isinstance(v, dict) and "val" in v}
        for sub, sv in subs.items():
            if (cat, item, sub) in EDITION:
                continue
            mod = PACK[cat][1]
            cands = ["%s.i%s_%s" % (mod, num, sub.lower())]
            if len(subs) == 1:
                cands.append("%s.i%s" % (mod, num))
            key = next((c for c in cands if c in fields), None)
            if key is None or sub.lower() in ("fx", "spare"):
                skipped += 1
                continue
            val = sv["val"]
            if (cat, item, sub) in UNIT and isinstance(val, (int, float)):
                num_, den_ = UNIT[(cat, item, sub)]
                val = float(Fraction(repr(float(val))) * num_ / den_)
            v = value_for(key, fields[key], val)
            if v is None:
                skipped += 1
                continue
            m[key] = v
    return m, skipped


def build(asterix):
    import asterix as _a  # noqa: F401
    base = os.path.join(os.path.dirname(asterix.__file__), "sample_data")
    vecs, seen_sets, count = {}, {c: set() for c in CATS}, {c: 0 for c in CATS}
    for name, sha in sorted(CAPTURES.items()):
        data = open(os.path.join(base, name), "rb").read()
        if hashlib.sha256(data).hexdigest() != sha:
            raise SystemExit("golden-asterix: %s does not have the recorded SHA-256" % name)
        bi = -1
        for payload in (pcap_payloads(data) if name.endswith(".pcap") else [data]):
            for block in blocks(payload):
                bi += 1
                for ri, nb, rec in single_records(asterix, block):
                    rid = "%s:%d.%d" % (name, bi, ri)
                    if rid in NOT_CANONICAL:
                        continue
                    cat = nb[0]
                    if cat not in CATS or count[cat] >= PER_CAT:
                        continue
                    items = tuple(sorted(k for k in rec if re.fullmatch(r"I\d{3}", k)))
                    if items in seen_sets[cat]:
                        continue
                    seen_sets[cat].add(items)
                    count[cat] += 1
                    model, _ = model_of(cat, rec, pack_fields(cat))
                    pack = PACK[cat][0]
                    vecs[(pack, "golden-%d.json" % count[cat])] = {
                        "name": "golden-%d" % count[cat], "from": pack, "to": pack,
                        "input": nb.hex(), "expect": nb.hex(), "model": model,
                        "source": "asterix_decoder %s: asterix.parse of a single-record block from its sample "
                                  "capture, record %s (block.record; the record's bytes unchanged, behind CAT and "
                                  "LEN). Written by tools/gen/golden-asterix.py; no engine is run." % (DECODER, rid),
                        "reference": "ASTERIX category %03d as asterix_decoder (Croatia Control, GPL-2.0, its own "
                                     "category definitions) decodes it; items named alike in both are compared." % cat,
                    }
    return vecs


def text(vec):
    return json.dumps(vec, indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="golden-asterix", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    try:
        import asterix
        from importlib.metadata import version
        if version("asterix_decoder") != DECODER:
            raise ImportError(version("asterix_decoder"))
    except ImportError as e:
        print("golden-asterix: asterix_decoder %s is not importable (%s); see tools/gen/golden-asterix.txt"
              % (DECODER, e), file=sys.stderr)
        return 1
    vecs = build(asterix)
    bad = []
    for cat in CATS:
        pack = PACK[cat][0]
        out = os.path.join(ROOT, "packs", pack, "vectors")
        want = {n: v for (p, n), v in vecs.items() if p == pack}
        have = {n for n in os.listdir(out) if n.startswith("golden-") and n.endswith(".json")}
        if args.check:
            bad += [pack + "/" + n for n in sorted(set(want) | have)
                    if n not in want or n not in have or open(os.path.join(out, n), encoding="utf-8").read() != text(want[n])]
            continue
        for n in have - set(want):
            os.remove(os.path.join(out, n))
        for n, v in want.items():
            with open(os.path.join(out, n), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text(v))
    if args.check:
        if bad:
            print("golden-asterix: %d vector(s) differ from what asterix_decoder writes: %s" % (len(bad), ", ".join(bad[:10])),
                  file=sys.stderr)
            return 1
        print("golden-asterix: --check: ok, %d vectors" % len(vecs))
        return 0
    print("golden-asterix: wrote %d vectors" % len(vecs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
