#!/usr/bin/env python3
"""The hand-written vectors of pack cot-protobuf: packs/cot-protobuf/vectors/01 to 08,
packs/cot-xml/vectors/19-full-event-to-cot-protobuf.json and
packs/geojson/vectors/90-to-cot-protobuf-no-position.json.

Each input is written here field by field; each expected output is computed with
the codec of tools/gen/proto2pack.py. Run after tools/gen/proto2pack-run.sh:

  python3 -I tools/gen/cot-protobuf-vectors.py <checkout>
"""
import glob, importlib.util, json, os, sys
sys.dont_write_bytecode = True
root = sys.argv[1]
spec = importlib.util.spec_from_file_location("p2p", os.path.join(root, "tools/gen/proto2pack.py"))
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
mods = {}
for p in sorted(glob.glob(os.path.join(root, "model", "*.def"))):
    m = g.load_module(open(p, encoding="utf-8").read()); mods[m["module"]] = m
pack = g.load_pack(open(os.path.join(root, "packs/cot-protobuf/pack.def"), encoding="utf-8").read(), mods)
xml = open(os.path.join(root, "packs/cot-xml/pack.def"), encoding="utf-8").read()
gj = open(os.path.join(root, "packs/geojson/pack.def"), encoding="utf-8").read()
S, V, D = "pstring", "pvarint", "pdouble"
T = 1614456000000
point = {10: (D, 30.0090027), 11: (D, -85.9578182), 12: (D, -42.6), 13: (D, 45.3), 14: (D, 99.5)}
ev = {1: (S, "a-f-G-U-C"), 5: (S, "J-01334"), 6: (V, T), 7: (V, T), 9: (S, "m-g"), **point,
      15: {2: {2: (S, "GATOR")}}}
A = {2: ev}
full = {1: {1: (V, 1), 2: (V, 1), 3: (S, "J-01334")},
        2: {1: (S, "a-f-G-U-C"), 2: (S, "Undefined"), 5: (S, "J-01334"), 6: (V, T), 7: (V, T), 8: (V, T + 180000),
            9: (S, "m-g"), **point,
            15: {1: (S, '<uid Droid="GATOR"/>'),
                 2: {1: (S, "*:-1:stcp"), 2: (S, "GATOR")},
                 3: {1: (S, "Cyan"), 2: (S, "Team Member")},
                 4: {1: (S, "GPS"), 2: (S, "GPS")},
                 5: {1: (V, 87)},
                 6: {1: (S, "GENERIC DEVICE"), 2: (S, "ATAK-CIV"), 3: (S, "29"), 4: (S, "4.5.1.13")},
                 7: {1: (D, 40.25), 2: (D, 270.0)}}}}
small = {1: (S, "a-f-G"), 5: (S, "J-1"), 9: (S, "m-g"), 10: (D, 1.0), 11: (D, 2.0), 12: (D, 3.0), 13: (D, 4.0), 14: (D, 5.0)}
differs = {2: {**small, 6: (V, T), 7: (V, T - 60000)}}
start_only = {2: {**small, 7: (V, T - 60000)}}
control = {1: {1: (V, 1), 2: (V, 1)}}
empty_control = {1: {}}

def hx(tree): return g.enc_tree(tree).hex()
def conv(h, to):
    ent, kind = g.engine_decode(pack, bytes.fromhex(h))
    if to == "cot-protobuf":
        return g.engine_encode(pack, ent, kind)[0].hex(), ent, kind
    return g.other_encode(xml if to == "cot-xml" else gj, mods, ent), ent, kind

cases = [
 ("01-event-to-cot-xml", A, "cot-xml", ["uid", "type", "time_ms", "how", "lat", "lon", "hae", "ce", "le", "callsign"]),
 ("02-event-to-geojson", A, "geojson", ["uid", "lat", "lon", "time_ms", "callsign"]),
 ("03-full-message-roundtrip", full, "cot-protobuf", None),
 ("04-full-message-to-cot-xml", full, "cot-xml", ["time_ms", "stale_ms", "course", "speed_ms"]),
 ("05-start-differs-time-is-written-at-both", differs, "cot-protobuf",
  ["time_ms", "takproto.cot_event_send_time", "takproto.cot_event_start_time"]),
 ("06-start-alone-fills-time", start_only, "cot-protobuf", ["time_ms", "takproto.cot_event_start_time"]),
 ("07-control-alone", control, "cot-protobuf", None),
 ("08-control-empty-member", empty_control, "cot-protobuf", []),
]
out = os.path.join(root, "packs/cot-protobuf/vectors")
for name, tree, to, keys in cases:
    h = hx(tree)
    exp, ent, kind = conv(h, to)
    model = {"@kind": kind}
    model.update({k: g.model_text(ent[k]) for k in (ent if keys is None else keys)})
    vec = {"name": name[3:], "from": "cot-protobuf", "to": to, "input": h, "expect": exp, "model": model}
    with open(os.path.join(out, name + ".json"), "w", encoding="utf-8") as fh:
        json.dump(vec, fh, indent=2); fh.write("\n")

# into cot-protobuf from the text formats
src = json.load(open(os.path.join(root, "packs/cot-xml/vectors/05-full-event-roundtrip.json"), encoding="utf-8"))["input"]
ent = g.other_decode(xml, mods, src)
b, kind = g.engine_encode(pack, ent, None)
assert kind == "cot_event"
back = g.other_encode(xml, mods, g.engine_decode(pack, b)[0])
assert back == src, back
vec = {"name": "full-event-to-cot-protobuf", "from": "cot-xml", "to": "cot-protobuf", "input": src, "expect": b.hex(),
       "model": {k: g.model_text(ent[k]) for k in ("time_ms", "stale_ms", "course", "speed_ms")}}
with open(os.path.join(root, "packs/cot-xml/vectors/19-full-event-to-cot-protobuf.json"), "w", encoding="utf-8") as fh:
    json.dump(vec, fh, indent=2); fh.write("\n")
nopos = '{"type":"Feature","geometry":null,"properties":{"type":"a-f-G-U-C","callsign":"GATOR"},"id":"J-01334"}'
ent = g.other_decode(gj, mods, nopos)
try:
    g.engine_encode(pack, ent, None); raise SystemExit("encoded")
except g.GenError as e:
    assert str(e) == "no-kind"
vec = {"name": "to-cot-protobuf-no-position", "from": "geojson", "to": "cot-protobuf", "input": nopos,
       "expect_error": "no-kind", "model": {"uid": "J-01334", "callsign": "GATOR"}}
with open(os.path.join(root, "packs/geojson/vectors/90-to-cot-protobuf-no-position.json"), "w", encoding="utf-8") as fh:
    json.dump(vec, fh, indent=2); fh.write("\n")
