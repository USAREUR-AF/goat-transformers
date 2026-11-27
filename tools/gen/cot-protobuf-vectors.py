#!/usr/bin/env python3
"""cot-protobuf-vectors: the hand-written vectors of pack cot-protobuf.

Reads, under --out: the model modules, packs/cot-protobuf/pack.def,
packs/cot-xml/pack.def, packs/geojson/pack.def and
packs/cot-xml/vectors/05-full-event-roundtrip.json.

Writes, under --out: packs/cot-protobuf/vectors/01 to 08,
packs/cot-xml/vectors/19-full-event-to-cot-protobuf.json and
packs/geojson/vectors/90-to-cot-protobuf-no-position.json.

Each input message is written here field by field; each expected output is
computed with the codec of tools/gen/proto2pack.py, which is written from the
specification and imports no engine. Run after tools/gen/proto2pack-run.sh:

  python3 -I tools/gen/cot-protobuf-vectors.py [--out <checkout>] [--check]

Guarantees: the same packs give the same bytes; with --check nothing is
written. Exit status: 0 done (with --check: every file is what this script
writes), 1 a pack that does not load, a conversion that does not hold or a
--check difference, 2 a usage error.

Python 3 standard library only.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio          # noqa: E402
import gtcheck        # noqa: E402
import proto2pack     # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
S, V, D = "pstring", "pvarint", "pdouble"
T = 1614456000000       # 2021-02-27T20:00:00Z in epoch milliseconds

# Messages as trees for proto2pack.enc_tree: {field number: (transform, value) | subtree}.
POINT = {10: (D, 30.0090027), 11: (D, -85.9578182), 12: (D, -42.6), 13: (D, 45.3), 14: (D, 99.5)}
EVENT = {2: {1: (S, "a-f-G-U-C"), 5: (S, "J-01334"), 6: (V, T), 7: (V, T), 9: (S, "m-g"), **POINT,
             15: {2: {2: (S, "GATOR")}}}}
FULL = {1: {1: (V, 1), 2: (V, 1), 3: (S, "J-01334")},
        2: {1: (S, "a-f-G-U-C"), 2: (S, "Undefined"), 5: (S, "J-01334"), 6: (V, T), 7: (V, T), 8: (V, T + 180000),
            9: (S, "m-g"), **POINT,
            15: {1: (S, '<uid Droid="GATOR"/>'),
                 2: {1: (S, "*:-1:stcp"), 2: (S, "GATOR")},
                 3: {1: (S, "Cyan"), 2: (S, "Team Member")},
                 4: {1: (S, "GPS"), 2: (S, "GPS")},
                 5: {1: (V, 87)},
                 6: {1: (S, "GENERIC DEVICE"), 2: (S, "ATAK-CIV"), 3: (S, "29"), 4: (S, "4.5.1.13")},
                 7: {1: (D, 40.25), 2: (D, 270.0)}}}}
SMALL = {1: (S, "a-f-G"), 5: (S, "J-1"), 9: (S, "m-g"), 10: (D, 1.0), 11: (D, 2.0), 12: (D, 3.0), 13: (D, 4.0),
         14: (D, 5.0)}
START_DIFFERS = {2: {**SMALL, 6: (V, T), 7: (V, T - 60000)}}
START_ONLY = {2: {**SMALL, 7: (V, T - 60000)}}
CONTROL = {1: {1: (V, 1), 2: (V, 1)}}
EMPTY_CONTROL = {1: {}}
# an unknown hae, ce and le: 9999999.0, as the TAK library writes it (pack.md of cot-protobuf)
UNKNOWN = 9999999.0
UNKNOWN_HEIGHT = {2: {**EVENT[2], 12: (D, UNKNOWN), 13: (D, UNKNOWN), 14: (D, UNKNOWN)}}

# (file name, message, target format, the keys `model` states; None: every decoded key)
CASES = [
    ("01-event-to-cot-xml", EVENT, "cot-xml",
     ["uid", "type", "time_ms", "how", "lat", "lon", "hae", "ce", "le", "callsign"]),
    ("02-event-to-geojson", EVENT, "geojson", ["uid", "lat", "lon", "time_ms", "callsign"]),
    ("03-full-message-roundtrip", FULL, "cot-protobuf", None),
    ("04-full-message-to-cot-xml", FULL, "cot-xml", ["time_ms", "stale_ms", "course", "speed_ms"]),
    ("05-start-differs-roundtrip-keeps-start", START_DIFFERS, "cot-protobuf",
     ["time_ms", "takproto.cot_event_send_time", "takproto.cot_event_start_time"]),
    ("06-start-alone-fills-time", START_ONLY, "cot-protobuf", ["time_ms", "takproto.cot_event_start_time"]),
    ("07-control-alone", CONTROL, "cot-protobuf", None),
    ("08-control-empty-member", EMPTY_CONTROL, "cot-protobuf", []),
    ("09-unknown-hae-ce-le-roundtrip", UNKNOWN_HEIGHT, "cot-protobuf", ["lat", "lon"]),
    ("10-unknown-hae-ce-le-to-geojson", UNKNOWN_HEIGHT, "geojson", ["lat", "lon"]),
]
NO_POSITION = '{"type":"Feature","geometry":null,"properties":{"type":"a-f-G-U-C","callsign":"GATOR"},"id":"J-01334"}'


def from_cot_protobuf(pack, others):
    """{relative path: vector} for the ten vectors out of cot-protobuf."""
    vectors = {}
    for name, tree, to, keys in CASES:
        message = proto2pack.enc_tree(tree).hex()
        ent, kind = proto2pack.engine_decode(pack, bytes.fromhex(message))
        if to == "cot-protobuf":
            expect = proto2pack.engine_encode(pack, ent, kind)[0].hex()
        else:
            expect = others[to].encode(ent)
        missing = [k for k in keys or () if k not in ent]
        if missing:
            raise proto2pack.GenError("vector %s: the pack does not decode %s" % (name, " ".join(missing)))
        if name.startswith(("09-", "10-")) and any(k in ent for k in ("hae", "ce", "le")):
            raise proto2pack.GenError("vector %s: 9999999 decodes as a value" % name)
        model = {"@kind": kind}
        model.update({k: proto2pack.model_text(ent[k]) for k in (ent if keys is None else keys)})
        vectors["packs/cot-protobuf/vectors/%s.json" % name] = {
            "name": name[3:], "from": "cot-protobuf", "to": to, "input": message, "expect": expect, "model": model}
    return vectors


def into_cot_protobuf(pack, others, full_event_xml):
    """{relative path: vector} for the two vectors into cot-protobuf: a full
    CoT XML event, which must come back as the same text, and a GeoJSON feature
    with no position, which no kind accepts."""
    xml, geojson = others["cot-xml"], others["geojson"]
    ent = xml.decode(full_event_xml)
    message, kind = proto2pack.engine_encode(pack, ent, None)
    if kind != "cot_event":
        raise proto2pack.GenError("the full CoT event encodes as kind %s, not cot_event" % kind)
    back = xml.encode(proto2pack.engine_decode(pack, message)[0])
    if back != full_event_xml:
        raise proto2pack.GenError("the full CoT event does not come back from cot-protobuf: %s" % back)
    vectors = {"packs/cot-xml/vectors/19-full-event-to-cot-protobuf.json": {
        "name": "full-event-to-cot-protobuf", "from": "cot-xml", "to": "cot-protobuf", "input": full_event_xml,
        "expect": message.hex(),
        "model": {k: proto2pack.model_text(ent[k]) for k in ("time_ms", "stale_ms", "course", "speed_ms")}}}

    try:
        proto2pack.engine_encode(pack, geojson.decode(NO_POSITION), None)
    except proto2pack.NoKind:
        pass
    else:
        raise proto2pack.GenError("a feature with no position encodes; the vector expects no-kind")
    vectors["packs/geojson/vectors/90-to-cot-protobuf-no-position.json"] = {
        "name": "to-cot-protobuf-no-position", "from": "geojson", "to": "cot-protobuf", "input": NO_POSITION,
        "expect_error": "no-kind", "model": {"uid": "J-01334", "callsign": "GATOR"}}
    return vectors


def generate(out):
    """Load the packs through `out`, compute the twelve vectors and write them."""
    model = proto2pack.load_model(out)
    rel = "packs/cot-protobuf/pack.def"
    pack = proto2pack.load_protobuf_pack(out.read(rel), model, rel)
    others = {}
    for fmt in ("cot-xml", "geojson"):
        rel = "packs/%s/pack.def" % fmt
        others[fmt] = proto2pack.OtherPack(out.read(rel), model, rel)
    full_event = json.loads(out.read("packs/cot-xml/vectors/05-full-event-roundtrip.json"))["input"]
    vectors = from_cot_protobuf(pack, others)
    vectors.update(into_cot_protobuf(pack, others, full_event))
    for rel, vec in vectors.items():
        out.write(rel, proto2pack.dump_vector(vec))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cot-protobuf-vectors.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    genio.add_arguments(ap, default_out=REPO, what="the checkout to read the packs from and write the vectors into")
    ap.add_argument("checkout", nargs="?", default=None, help="the same directory as --out, as a positional argument")
    args = ap.parse_args(argv)
    out = genio.Output(args.checkout or args.out, check=args.check)
    try:
        generate(out)
    except (proto2pack.GenError, gtcheck.CheckError) as e:
        print("cot-protobuf-vectors: %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("cot-protobuf-vectors: %s: %s" % (e.filename, e.strerror), file=sys.stderr)
        return 1
    return out.report("cot-protobuf-vectors")


if __name__ == "__main__":
    sys.exit(main())
