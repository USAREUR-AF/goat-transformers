#!/usr/bin/env python3
"""Write the vectors of the cfe-es, cfe-evs, cfe-sb, cfe-tbl and cfe-time packs.

Reads   tools/gen/cfe/layout.json, which tools/gen/cfe2pack.py writes from the C headers
        of nasa/cFE: for every kind its message ID, function code, C size and the
        offset, size and type of every payload member (and the raw key it has).
Writes  packs/cfe-<m>/vectors/gen-*.json and packs/cfe-<m>-be/vectors/gen-*.json, and the
        vectors whose input is a ccsds-space-packet message as
        packs/ccsds-space-packet/vectors/to-<pack>-gen-*.json:
          a round trip per kind: a packet serialized here, octet by octet, from the
            layout with values of this script's own (the primary header big-endian,
            the payload in the pack's byte order (little-endian for cfe-<m>,
            big-endian for cfe-<m>-be), implicit padding zero, a command's checksum
            chosen so that the XOR of every octet is 0xFF);
          the housekeeping telemetry packet to ccsds-space-packet (its 6 header octets);
          a bare primary header from ccsds-space-packet to the module's
            send-housekeeping command (a command with no payload);
          the same for the housekeeping telemetry packet where its payload holds a
            fixed-count array: transform-encode (ruling 5 of spec 0.7);
          an unknown function code on the command message ID: no-kind.

It reads no pack.def and runs no engine, and it needs no cFE checkout, so CI runs
it with --check. Python 3 standard library only.

Usage: python3 -I tools/gen/cfe-vectors.py [--out DIR] [--check]
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = ("written by tools/gen/cfe-vectors.py: the packet is serialized from tools/gen/cfe/layout.json "
       "(the C layout cfe2pack.py reads from nasa/cFE); no engine run")


def leaf_value(leaf, n):
    if leaf["type"] == "a":
        return ("T%d" % n)[:leaf["size"]]
    if leaf["type"] == "f":
        return [0.5, 1.25, -2.75, 3.5][n % 4]
    if leaf["type"] == "s":
        return -(n % 100) - 1
    return (n * 37 + 5) % (1 << min(8 * leaf["size"], 31))


def num_text(v):
    v = float(v)
    return str(int(v)) if v == int(v) else repr(v)


def fill(buf, body, base, counter, model, mod, order="little"):
    """Write every member of `body` at `base`; top-level values go into `model`."""
    for it in body:
        if "group" in it:
            for i in range(it["count"]):
                fill(buf, it["body"], base + it["offset"] + i * it["item_size"], counter, None, mod, order)
            if model is not None:
                model[mod + "." + it["group"] + ".#"] = str(it["count"])
            continue
        counter[0] += 1
        v = leaf_value(it, counter[0])
        o, size = base + it["offset"], it["size"]
        if it["type"] == "a":
            b = v.encode("ascii")
            buf[o:o + len(b)] = b
            mv = v
        elif it["type"] == "f":
            buf[o:o + size] = struct.pack(("<" if order == "little" else ">") + ("f" if size == 4 else "d"), v)
            mv = num_text(v)
        else:
            buf[o:o + size] = v.to_bytes(size, order, signed=it["type"] == "s")
            mv = str(v)
        if model is not None:
            model[mod + "." + it["key"]] = mv


def packet(msg, seq, mod, order="little"):
    size = msg["size"]
    buf = bytearray(size)
    buf[0:2] = msg["mid"].to_bytes(2, "big")
    buf[2:4] = ((3 << 14) | seq).to_bytes(2, "big")
    buf[4:6] = (size - 7).to_bytes(2, "big")
    model = {"@kind": msg["kind"], "ccsdssp.packet_type": "1" if msg["cmd"] else "0",
             "ccsdssp.apid": str(msg["mid"] & 0x7FF), "ccsdssp.sequence_flags": "3",
             "ccsdssp.data_length": str(size - 7)}
    if msg["cmd"]:
        buf[6] = msg["cc"] if msg["cc"] is not None else 0
        model["ccsdssp.sequence_count_or_name"] = str(seq)
    else:
        buf[6:10] = (1000000 + seq).to_bytes(4, "big")
        buf[10:12] = (0x8000).to_bytes(2, "big")
        model["ccsdssp.sequence_count"] = str(seq)
        model["cfemsg.time_seconds"] = str(1000000 + seq)
        model["cfemsg.time_subseconds"] = str(0x8000)
    fill(buf, msg["body"], 0, [0], model, mod, order)
    if msg["cmd"]:
        x = 0
        for j, b in enumerate(buf):
            if j != 7:
                x ^= b
        buf[7] = x ^ 0xFF
        model["cfemsg.checksum"] = str(buf[7])
        model["cfemsg.function_code"] = str(buf[6] & 0x7F)
    return buf, model


def vectors(fmt, msgs, source, order):
    m = fmt.split("-")[1]
    mod = "cfe" + m
    ref = "%s, modules/%s/config/default_cfe_%s_msgstruct.h and default_cfe_%s_msgdefs.h" % (source, m, m, m)
    V = {}
    rt = {}
    for i, msg in enumerate(msgs, 1):
        buf, model = packet(msg, 100 + i, mod, order)
        name = "gen-%03d-%s-roundtrip" % (i, msg["kind"].replace("_", "-"))
        rt[msg["kind"]] = buf
        V[name] = {"name": "gen-%s-roundtrip" % msg["kind"], "from": fmt, "to": fmt,
                   "input": buf.hex(), "expect": buf.hex(), "model": model, "source": SRC,
                   "reference": "%s; struct %s, message ID %s = 0x%04x%s; %d octets" % (
                       ref, msg["struct"], msg["mid_name"], msg["mid"],
                       "" if msg["cc"] is None else ", function code %s = %d" % (msg["cc_name"], msg["cc"]),
                       msg["size"])}
    hk = [x for x in msgs if not x["cmd"]][0]
    full = rt[hk["kind"]]
    k = hk["kind"].replace("_", "-")
    V["gen-%s-to-ccsds-space-packet" % k] = {
        "name": "gen-%s-to-ccsds-space-packet" % hk["kind"], "from": fmt, "to": "ccsds-space-packet",
        "input": full.hex(), "expect": full[:6].hex(), "source": SRC,
        "reference": "the primary header carries through the ccsdssp keys; ccsds-space-packet writes the 6 header octets only"}
    sh = [x for x in msgs if x["cmd"] and x["cc"] is None and not x["body"]][0]
    hdr = bytearray(6)
    hdr[0:2] = sh["mid"].to_bytes(2, "big")
    hdr[2:4] = ((3 << 14) | 42).to_bytes(2, "big")
    hdr[4:6] = (sh["size"] - 7).to_bytes(2, "big")
    V["gen-ccsds-space-packet-to-%s" % sh["kind"].replace("_", "-")] = {
        "name": "gen-ccsds-space-packet-to-%s" % sh["kind"], "from": "ccsds-space-packet", "to": fmt,
        "input": hdr.hex(), "expect": (hdr + bytes(sh["size"] - 6)).hex(), "source": SRC,
        "model": {"ccsdssp.packet_type": "1", "ccsdssp.apid": str(sh["mid"] & 0x7FF)},
        "reference": "encode selects the kind whose requires hold (packet type 1, apid %d); the function code "
                     "and checksum, absent from a bare primary header, are written as zero" % (sh["mid"] & 0x7FF)}
    if any("group" in it for it in hk["body"]):
        V["gen-ccsds-space-packet-to-%s-needs-its-arrays" % k] = {
            "name": "gen-ccsds-space-packet-to-%s-needs-its-arrays" % hk["kind"], "from": "ccsds-space-packet",
            "to": fmt, "input": full[:6].hex(), "expect_error": "transform-encode", "source": SRC,
            "reference": "the kind is selected (packet type 0, apid %d) but its payload holds fixed-count arrays, and "
                         "an absent list under a fixed count is transform-encode (ruling 5 of 0.7)" % (hk["mid"] & 0x7FF)}
    cmd = [x for x in msgs if x["cc"] is not None]
    used = {x["cc"] for x in cmd}
    bad = next(n for n in range(127) if n not in used)
    b = bytearray(8)
    b[0:2] = cmd[0]["mid"].to_bytes(2, "big")
    b[2:4] = (0xC000).to_bytes(2, "big")
    b[4:6] = (1).to_bytes(2, "big")
    b[6] = bad
    V["gen-unknown-function-code-is-no-kind"] = {
        "name": "gen-unknown-function-code-is-no-kind", "from": fmt, "to": fmt, "input": b.hex(),
        "expect_error": "no-kind", "source": SRC,
        "reference": "function code %d is not a command of %s on message ID 0x%04x" % (bad, m.upper(), cmd[0]["mid"])}
    return V


def build(out):
    layout = json.loads(out.read("tools/gen/cfe/layout.json"))
    written = {}
    for fmt, p in sorted(layout["packs"].items()):
        V = vectors(fmt, p["messages"], layout["source"], p["endian"])
        for name, v in V.items():
            own = "packs/%s/vectors/%s.json" % (fmt, name)
            if v["from"] == fmt:
                rel = own
            else:
                # a vector lives under the pack that owns its input: packs/<from>/vectors,
                # file and `name` to-<this pack>-<name>; the file an earlier run wrote under this
                # pack is removed (only that file)
                short = name.replace("gen-%s-to-" % v["from"], "gen-", 1)
                rel = "packs/%s/vectors/to-%s-%s.json" % (v["from"], fmt, short)
                # its name names the target pack too, as the file does: names are unique
                # within packs/<from>/vectors, where every cfe pack writes one
                v = dict(v, name="to-%s-%s" % (fmt, short))
                out.remove(own)
            out.write(rel, json.dumps(v, indent=2) + "\n")
            written[v["from"]] = written.get(v["from"], 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("cfe-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
