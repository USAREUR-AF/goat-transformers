#!/usr/bin/env python3
"""golden-cantools: golden vectors for the CAN DBC packs (packs/dbc-*) from
cantools, a reference DBC implementation (shared-model hardening, item 2:
meaning is tested against an implementation outside this project).

For each dbc pack whose pack.def names one DBC file, it fetches that file from
GitHub at the commit the pack names, refuses it unless its SHA-256 equals the
one the pack's PROVENANCE.md records, loads it with cantools, and for up to
MAX_PER_PACK messages that the pack has a kind for (not multiplexed) writes
packs/<pack>/vectors/golden-<frame id>-<message>.json:

  input, expect  a Linux struct can_frame (can_id LE 32, len, three zero
                 bytes, data 8) whose data cantools encoded from raw signal
                 values: a round trip
  model          "@kind" and every signal, as cantools decodes the data: the
                 physical value (raw x scale + offset), or the value table's
                 text for a field the pack reads `via` a table, under the
                 pack's key <module>.<message>_<signal>
  source         cantools, its version, the DBC file and commit; no engine

Raw values: a pattern over each signal's raw range; a signal with a value
table takes one of its table's values.

Usage (cantools 45.1.1 importable, network for the DBC files once):

  python3 -I tools/gen/golden-cantools.py [--cache DIR]           write
  python3 -I tools/gen/golden-cantools.py --check [--cache DIR]   exit 1 when a
                                                                  committed vector differs
"""
import argparse
import glob
import hashlib
import json
import os
import re
import struct
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CANTOOLS = "45.1.1"
MAX_PER_PACK = 8
GAPS = []      # messages with a DBC signal the pack has no field for
SOURCE = re.compile(r'^source\s+"https://github\.com/([^/ ]+/[^/ ]+) (\S+\.dbc) at commit ([0-9a-f]{40})"', re.M)


def dbc_packs():
    """[(pack dir name, repo, path, commit, sha256)] of the single-DBC packs."""
    out = []
    for d in sorted(glob.glob(os.path.join(ROOT, "packs", "dbc-*"))):
        text = open(os.path.join(d, "pack.def"), encoding="utf-8").read()
        srcs = SOURCE.findall(text)
        if len(srcs) != 1:
            continue
        repo, path, commit = srcs[0]
        prov = open(os.path.join(d, "PROVENANCE.md"), encoding="utf-8").read()
        m = re.search(r"`%s`\s*\|\s*`([0-9a-f]{64})`" % re.escape(path), prov)
        if not m:
            continue
        out.append((os.path.basename(d), repo, path, commit, m.group(1)))
    return out


def fetch(repo, path, commit, sha, cache):
    os.makedirs(cache, exist_ok=True)
    local = os.path.join(cache, sha + ".dbc")
    if not os.path.exists(local):
        url = "https://raw.githubusercontent.com/%s/%s/%s" % (repo, commit, path)
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != sha:
            raise SystemExit("golden-cantools: %s at %s does not have the SHA-256 the pack records" % (path, commit))
        with open(local, "wb") as fh:
            fh.write(data)
    data = open(local, "rb").read()
    if hashlib.sha256(data).hexdigest() != sha:
        raise SystemExit("golden-cantools: cached %s has another SHA-256; delete %s" % (path, local))
    return local


def pack_kinds(pack):
    """{frame id: (kind, {key: field type})}. The identifier word is
    little-endian in the frame; a pack with `bit_order msb` compares it read
    most significant bit first across the four bytes, so its `when` value is
    that reading, turned back into the frame id here."""
    kinds, cur, msb = {}, None, False
    for line in open(os.path.join(ROOT, "packs", pack, "pack.def"), encoding="utf-8"):
        t = line.split()
        if not t:
            continue
        if t[0] == "bit_order":
            msb = t[1] == "msb"
        if t[0] == "kind":
            cur = [t[1], None, {}, None]
        elif cur and t[0] == "when" and t[1] == "0:0:32":
            v = int(t[2])
            cur[3] = int.from_bytes(v.to_bytes(4, "big"), "little") if msb else v
            kinds[cur[3]] = cur
        elif cur and t[0] == "field":
            cur[2][t[1]] = " ".join(t[3:])
    return {fid: (k[0], k[2]) for fid, k in kinds.items()}


def slug(text):
    """tools/gen/dbc2pack.py's identifier: lower case, runs of other
    characters as one underscore, x before a leading digit."""
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s if s and not s[0].isdigit() else "x" + s


def key_of(module, msg, sig):
    """The pack key of a signal, as dbc2pack names it: lat or lon for a
    latitude or longitude in degrees, else <module>.<message>_<signal>."""
    n = sig.name.lower()
    if (sig.unit or "").strip().lower() in ("deg", "degree", "degrees"):
        if n.endswith("latitude"):
            return "lat"
        if n.endswith("longitude"):
            return "lon"
    return "%s.%s_%s" % (module, slug(msg.name), slug(sig.name))


def resolve(module, msg, sig, fields):
    """key_of, else the pack's lat or lon for a signal whose name says
    latitude or longitude (dbc2pack also reads the signal's comment)."""
    k = key_of(module, msg, sig)
    if k in fields:
        return k
    n = sig.name.lower()
    if "latitude" in n and "lat" in fields:
        return "lat"
    if "longitude" in n and "lon" in fields:
        return "lon"
    return k


def ranges():
    with open(os.path.join(ROOT, "tools", "model-ranges.json"), encoding="utf-8") as fh:
        return {k: (v.get("min"), v.get("max")) for k, v in json.load(fh)["keys"].items()}


def ranged_raw(sig, lo_hi):
    """A raw value whose physical value (raw x scale + offset) lies inside
    the key's range (tools/model-checks.py holds every decoded value to it)."""
    lo, hi = lo_hi
    n = sig.length
    rlo, rhi = (-(1 << (n - 1)), (1 << (n - 1)) - 1) if sig.is_signed else (0, (1 << n) - 1)
    for frac in (0.318, 0.5, 0.618, 0.75, 0.9, 0.2, 0.1):
        if lo is not None and hi is not None:
            want = lo + (hi - lo) * frac
        elif lo is not None:
            want = lo + max(1, abs(lo)) * frac
        elif hi is not None:
            want = hi - max(1, abs(hi)) * frac
        else:
            return None
        raw = int(round((want - (sig.offset or 0)) / (sig.scale or 1)))
        if rlo <= raw <= rhi:
            return raw
    return None


def raw_value(sig, i):
    if sig.choices:
        keys = sorted(int(k) for k in sig.choices)
        return keys[i % len(keys)]
    n = sig.length
    lo, hi = (-(1 << (n - 1)), (1 << (n - 1)) - 1) if sig.is_signed else (0, (1 << n) - 1)
    v = (0x5A5A5A5A5A5A5A5A ^ (i * 0x9E3779B1)) & ((1 << n) - 1)
    if sig.is_signed and v > hi:
        v -= 1 << n
    return max(lo, min(hi, v))


def vectors(cache):
    import cantools
    out = {}
    limits = ranges()
    for pack, repo, path, commit, sha in dbc_packs():
        try:
            db = cantools.database.load_file(fetch(repo, path, commit, sha, cache), strict=False)
        except cantools.database.errors.Error:
            continue                        # cantools refuses the file (listed by --check's count)
        kinds = pack_kinds(pack)
        n = 0
        for msg in sorted(db.messages, key=lambda m: m.frame_id):
            if n >= MAX_PER_PACK:
                break
            if msg.is_multiplexed() or msg.frame_id not in kinds or msg.length > 8:
                continue
            kind, fields = kinds[msg.frame_id]
            module = next((f.split(".", 1)[0] for f in fields if "." in f), None)
            unmapped = [sg.name for sg in msg.signals if resolve(module, msg, sg, fields) not in fields]
            if unmapped:                    # a signal the pack drops: a finding, not a vector
                GAPS.append("%s %s: %s" % (pack, msg.name, ", ".join(unmapped)))
                continue
            raw = {}
            for i, sg in enumerate(msg.signals):
                k = resolve(module, msg, sg, fields)
                r = ranged_raw(sg, limits[k]) if k in limits and not sg.choices else None
                raw[sg.name] = r if r is not None else raw_value(sg, i)
            try:
                data = msg.encode(raw, scaling=False, strict=False, padding=False)
            except Exception:
                continue
            data = bytes(data).ljust(8, b"\0")
            frame = struct.pack("<IB3x", msg.frame_id, msg.length) + data
            # numbers without the value tables (a raw value that is also a table
            # entry would come back unscaled), names with them
            numbers = msg.decode(data[:msg.length], decode_choices=False, scaling=True)
            names = msg.decode(data[:msg.length], decode_choices=True, scaling=True)
            model = {"@kind": kind}
            for s in msg.signals:
                key = resolve(module, msg, s, fields)
                if key not in fields:
                    continue
                typ = fields[key]
                if " via " in " " + typ:
                    v = names[s.name]
                    if not hasattr(v, "name"):
                        continue
                    model[key] = str(v.name)
                elif typ.split()[0] in ("uint", "twos"):
                    model[key] = str(int(numbers[s.name]))
                else:
                    model[key] = repr(float(numbers[s.name]))
            name = "golden-%05d-%s" % (msg.frame_id, kind.replace("_", "-"))
            out[(pack, name + ".json")] = {
                "name": name,
                "from": pack,
                "to": pack,
                "input": frame.hex(),
                "expect": frame.hex(),
                "model": model,
                "source": "cantools %s: %s at %s (SHA-256 %s), message %s (frame id %d) encoded from raw signal values "
                          "and decoded with scaling and value tables. Written by tools/gen/golden-cantools.py; no "
                          "engine is run." % (CANTOOLS, path, commit, sha, msg.name, msg.frame_id),
                "reference": "The frame is a Linux struct can_frame (can_id little-endian, len, three zero bytes, "
                             "eight data bytes, the unused ones zero); model values are cantools' physical values "
                             "(raw x scale + offset) or the DBC value table's text, under the pack's keys.",
            }
            n += 1
    return out


def text(vec):
    return json.dumps(vec, indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="golden-cantools", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--cache", default=os.path.join(os.path.expanduser("~"), ".cache", "golden-cantools"))
    args = ap.parse_args(argv)
    try:
        vecs = vectors(args.cache)
    except ImportError:
        print("golden-cantools: cantools %s is not importable (pip install cantools==%s)" % (CANTOOLS, CANTOOLS),
              file=sys.stderr)
        return 1
    have = {(os.path.basename(os.path.dirname(os.path.dirname(p))), os.path.basename(p))
            for p in glob.glob(os.path.join(ROOT, "packs", "dbc-*", "vectors", "golden-*.json"))}
    path = lambda k: os.path.join(ROOT, "packs", k[0], "vectors", k[1])
    if args.check:
        bad = sorted("%s/%s" % k for k in set(vecs) | have
                     if k not in vecs or k not in have or open(path(k), encoding="utf-8").read() != text(vecs[k]))
        if bad:
            print("golden-cantools: %d vector(s) differ from what cantools writes: %s" % (len(bad), ", ".join(bad[:10])),
                  file=sys.stderr)
            return 1
        print("golden-cantools: --check: ok, %d vectors" % len(vecs))
        return 0
    for k in have - set(vecs):
        os.remove(path(k))
    for k, v in vecs.items():
        with open(path(k), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text(v))
    print("golden-cantools: wrote %d vectors in %d packs" % (len(vecs), len({k[0] for k in vecs})))
    for g in GAPS:
        print("golden-cantools: a signal the pack drops: %s" % g)
    return 0


if __name__ == "__main__":
    sys.exit(main())
