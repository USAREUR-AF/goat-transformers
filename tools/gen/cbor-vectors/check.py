"""Check the built vectors with cbor.py: inputs well formed or not as the
expected error says; expected outputs in core deterministic form; model values
read back through the pack's paths."""
import sys, os, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbor import *
WT = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
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
}
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
for f in sorted(glob.glob(WT + "/packs/conformance-cbor*/vectors/*.json") + glob.glob(WT + "/packs/geojson/vectors/cbor-*.json")):
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
                steps, tr = PATHS[v["from"]][k]
                got = val(walk(t, steps), tr)
                if tr == "float": ok = got == float(want)
                else: ok = got == want
                if not ok: print("BAD ", tag, k, got, want); bad += 1
    if "expect" in v and v["to"] != "geojson":
        e = bytes.fromhex(v["expect"]); n = decode(e)
        if canon(n) != e: print("BAD ", tag, "expect not canonical"); bad += 1
        if v["from"] == v["to"] and v["input"] == v["expect"]: pass
print("problems:", bad)
