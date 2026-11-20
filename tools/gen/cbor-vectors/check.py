"""Check the built vectors with cbor.py: inputs well formed or not as the
expected error says; expected outputs in core deterministic form; model values
read back through the pack's paths."""
import sys, os, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbor import *
WT = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
def P(i): return ("pos", i)
PATHS = {
 "conformance-cbor": {"uid": ([1], "text"), "probe.n": ([-1], "int"), "probe.val": ([2], "uint"),
   "probe.a": ([3], "float"), "probe.s2": ([4], "bytes"), "probe.x": (["flag"], "bool"),
   "time_ms": ([5], "epoch_s"), "probe.s1": ([6], "levels"), "lat": ([7, 1], "float"),
   "lon": ([7, 2], "float"), "probe.tag": ([8, ("pos", 1)], "text")},
 "conformance-cbor-kinds": {"uid": ([1], "text"), "probe.y": (["v"], "int"), "lat": ([7, 1], "float"),
   "lon": ([7, 2], "float"), "probe.s1": (["m"], "text"), "probe.val": ([3, 2], "uint"),
   "probe.x": ([4], "int"), "probe.n": ([2], "int")},
 "conformance-cbor-array": {"probe.s1": ([("pos", 0)], "bytes"), "probe.n": ([("pos", 1), 1], "int"),
   "uid": ([("pos", 1), 4], "bytes"), "probe.s2": ([("pos", 2)], "bytes"), "probe.tag": ([("pos", 3)], "bytes")},
 "cose-sign1": {"cose.protected": ([("pos", 0)], "bytes"), "cose.alg": ([("pos", 1), 1], "int"),
   "cose.content_format": ([("pos", 1), 3], "uint"), "cose.kid": ([("pos", 1), 4], "bytes"),
   "cose.iv": ([("pos", 1), 5], "bytes"), "cose.partial_iv": ([("pos", 1), 6], "bytes"),
   "cose.payload": ([("pos", 2)], "bytes"), "cose.signature": ([("pos", 3)], "bytes")},
 "conformance-cbor-group": {"probe.s2": ([("pos", 1)], "bytes")},
 "conformance-cbor-scope": {"probe.val": ([("pos", 1)], "uint"), "lat": ([("pos", 2), 1], "float"),
   "probe.s2": ([("pos", 3)], "bytes")},
 "dtn-bpv7": {"bpv7.version": ([P(0), P(0)], "uint"), "bpv7.bundle_flags": ([P(0), P(1)], "uint"),
   "bpv7.primary_crc_type": ([P(0), P(2)], "uint"), "bpv7.dst_scheme": ([P(0), P(3), P(0)], "uint"),
   "bpv7.src_scheme": ([P(0), P(4), P(0)], "uint"), "bpv7.rpt_scheme": ([P(0), P(5), P(0)], "uint"),
   "bpv7.dst_ipn_node": ([P(0), P(3), P(1), P(0)], "uint"), "bpv7.dst_ipn_service": ([P(0), P(3), P(1), P(1)], "uint"),
   "bpv7.src_ipn_node": ([P(0), P(4), P(1), P(0)], "uint"), "bpv7.src_ipn_service": ([P(0), P(4), P(1), P(1)], "uint"),
   "bpv7.rpt_ipn_node": ([P(0), P(5), P(1), P(0)], "uint"), "bpv7.rpt_ipn_service": ([P(0), P(5), P(1), P(1)], "uint"),
   "bpv7.creation_time_dtn_ms": ([P(0), P(6), P(0)], "uint"), "bpv7.creation_seq": ([P(0), P(6), P(1)], "uint"),
   "bpv7.lifetime_ms": ([P(0), P(7)], "uint"), "bpv7.fragment_offset": ([P(0), P(8)], "uint"),
   "bpv7.total_adu_length": ([P(0), P(9)], "uint"),
   # primary_crc stands at [0].[8] in kinds ipn and whole, [0].[10] in the fragment kinds
   "bpv7.primary_crc": {"ipn": ([P(0), P(8)], "bytes"), "whole": ([P(0), P(8)], "bytes"),
                        "fragment-ipn": ([P(0), P(10)], "bytes"), "fragment": ([P(0), P(10)], "bytes")}},
}
# Ruling 23: positions of a top array that the pack's lines walk into as a map
# (or array); a gap there is a0 (or 80), never f6. A group's own path is not
# walked into and is not listed.
WALKS = {"conformance-cbor-array": {1: "map"}, "cose-sign1": {1: "map"}, "dtn-bpv7": {0: "array"}}
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crc import crc_bytes
def bpv7_crcs(top):
    """RFC 9171 4.2.1 over each block of a bundle as its bytes stood: the CRC
    byte string is the block's last element, so its last n bytes are the CRC;
    zero them and recompute. Returns [(block index, ok)] for blocks with a CRC."""
    out = []
    if top.kind != "array": return out
    for i, b in enumerate(top.value):
        if b.kind != "array" or not b.value: continue
        ti = 2 if i == 0 else 3
        if len(b.value) <= ti or b.value[ti].kind != "uint" or b.value[ti].value not in (1, 2): continue
        n = 2 if b.value[ti].value == 1 else 4
        raw = b.raw
        out.append((i, crc_bytes(b.value[ti].value, raw[:-n] + bytes(n)) == raw[-n:]))
    return out
def walk(node, steps):
    for st in steps:
        if node is None: return None
        if isinstance(st, tuple):
            assert node.kind == "array"; node = node.value[st[1]] if st[1] < len(node.value) else None
        else:
            assert node.kind == "map"
            hit = [v for k, v in node.value if (k.kind in ("uint", "nint", "text") and k.value == st)
                   and ((k.kind == "text") == isinstance(st, str))]
            node = hit[0] if hit else None
    return node
def val(node, tr):
    if node is None or (node.kind == "simple" and node.value in (22, 23)): return None
    if tr == "text": return node.value
    if tr in ("int", "uint"): return str(node.value)
    if tr == "float": return float(node.value)
    if tr == "bytes": return node.value.hex()
    if tr == "bool": return {20: "0", 21: "1"}[node.value]
    if tr == "epoch_s": return str(node.value * 1000)
    if tr == "levels": return {1: "low", 2: "high"}[node.value]
bad = 0
for f in sorted(glob.glob(WT + "/packs/conformance-cbor*/vectors/*.json") + glob.glob(WT + "/packs/cose-sign1/vectors/*.json") + glob.glob(WT + "/packs/geojson/vectors/cbor-*.json") + glob.glob(WT + "/packs/geojson/vectors/cose-*.json")
                  + glob.glob(WT + "/packs/dtn-bpv7/vectors/*.json") + glob.glob(WT + "/packs/geojson/vectors/bpv7-*.json")):
    v = json.load(open(f)); tag = os.path.basename(os.path.dirname(os.path.dirname(f))) + "/" + os.path.basename(f)
    err = v.get("expect_error")
    if v["from"] != "geojson":
        try:
            h = v["input"]
            if len([c for c in h if c not in " \t\n\r"]) % 2 or any(c not in "0123456789abcdefABCDEF \t\n\r" for c in h): raise Malformed("hex text")
            top = dhex("".join(c for c in h if c not in " \t\n\r")); wf = True
        except Malformed as e:
            wf = False; why = str(e)
        if err == "malformed-wire" and not wf: print("ok  ", tag, "malformed:", why)
        elif err == "malformed-wire": print("ok? ", tag, "well formed; malformed by a 0.28 step")
        elif not wf: print("BAD ", tag, why); bad += 1
        if wf and v.get("model"):
            t = top
            while False: pass
            for k, want in v["model"].items():
                if k.startswith("@") or "[" in k or k.endswith(".#"): continue
                pk = PATHS[v["from"]][k]
                steps, tr = pk[v["model"]["@kind"]] if isinstance(pk, dict) else pk
                got = val(walk(t, steps), tr)
                if tr == "float": ok = got == float(want)
                else: ok = got == want
                if not ok: print("BAD ", tag, k, got, want); bad += 1
    if "expect" in v and v["to"] != "geojson":
        e = bytes.fromhex(v["expect"]); n = decode(e)
        if canon(n) != e: print("BAD ", tag, "expect not canonical"); bad += 1
        for pos, kind in WALKS.get(v["to"], {}).items():
            if n.kind == "array" and pos < len(n.value):
                el = n.value[pos]
                if el.kind == "simple" and el.value == 22:
                    print("BAD ", tag, "ruling 23: f6 at [%d], walked into as a %s" % (pos, kind)); bad += 1
                elif el.kind != ("map" if kind == "map" else "array"):
                    print("BAD ", tag, "[%d] is %s, lines walk into it as a %s" % (pos, el.kind, kind)); bad += 1
        if v["from"] == v["to"] and v["input"] == v["expect"]: pass
        if v["to"] == "dtn-bpv7":
            for i, ok in bpv7_crcs(n):
                if not ok: print("note", tag, "expect: CRC of block [%d] does not match its bytes" % i)
    if v["from"] == "dtn-bpv7" and wf:
        t = top
        for i, ok in bpv7_crcs(t):
            if not ok: print("BAD ", tag, "input: CRC of block [%d] does not match its bytes" % i); bad += 1
print("problems:", bad)
