"""Build the 0.28 cbor vectors. Expected values are hand-written structures
encoded by cbor.py (RFC 8949 4.2.1). Run: python3 -I build.py <worktree>"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cbor import *

WT = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
OUT = []   # (path, obj)
REF = "spec/engine-spec.md Version 0.28 (the cbor wire)"
SRC = "constructed"

def vec(dirpath, fname, name, frm, to, inp, expect=None, error=None, model=None,
        context=None, ref=""):
    o = {"name": name, "from": frm, "to": to, "input": inp}
    if error: o["expect_error"] = error
    else: o["expect"] = expect
    if model: o["model"] = model
    if context is not None: o["context"] = context
    o["source"] = SRC
    o["reference"] = REF + ": " + ref + " Derived without an engine by a standalone RFC 8949 codec."
    OUT.append((os.path.join(WT, dirpath, fname), o))

C = "conformance-cbor"; CA = "conformance-cbor-array"; G = "geojson"
DC = "packs/conformance-cbor/vectors"; DCA = "packs/conformance-cbor-array/vectors"
DG = "packs/geojson/vectors"

def base(**over):
    d = {0: 1, 1: "U-1", 2: 42, 3: 1.5, 4: b"\x0a\xff", 5: 1614456000, 6: 2,
         7: {1: 45.5, 2: -90.25}, 8: ["x", "T"], 9: [{"name": "aa", "n": 3}],
         -1: -7, "flag": True}
    for k, v in over.items():
        k = {"k0": 0, "k1": 1, "k2": 2, "k3": 3, "k4": 4, "k5": 5, "k6": 6, "k7": 7,
             "k8": 8, "k9": 9, "km1": -1, "flag": "flag"}[k]
        if v is DEL: d.pop(k)
        else: d[k] = v
    return d
DEL = object()
BASE_MODEL = {"@kind": "plain", "uid": "U-1", "probe.n": "-7", "probe.val": "42",
    "probe.a": "1.5", "probe.s2": "0aff", "probe.x": "1", "time_ms": "1614456000000",
    "probe.s1": "high", "lat": "45.5", "lon": "-90.25", "probe.tag": "T",
    "probe.items.#": "1", "probe.items[0].probe.label": "aa", "probe.items[0].probe.qty": "3"}

def withres(d, pairs):
    return M(list(d.items()) + pairs)

# ---------------------------------------------------------------- conformance-cbor
B = H(base())
vec(DC, "01-round-trip-every-transform.json", "round-trip-every-transform", C, C, B, B,
    model=BASE_MODEL,
    ref="every transform of the table once: text 1, int -1, uint 2, float 3 (1.5 = f93e00), bytes 4 (0aff), bool flag (f5 -> 1), epoch_s 5 (1614456000 s -> 1614456000000 ms), uint via levels 6 (2 -> high), floats 7.1/7.2 (45.5 = f951b0, -90.25 = f9d5a4), text at 8.[1] (8.[0] is residue), the group 9 of maps; when 0 1 selects plain. Input is canonical, so output equals input.")

rev = M([("flag", True), (-1, -7), (9, [M([("name", "aa"), ("n", 3)])]), (8, ["x", "T"]),
         (7, M([(2, -90.25), (1, 45.5)])), (6, 2), (5, 1614456000), (4, b"\x0a\xff"),
         (3, 1.5), (2, 42), (1, "U-1"), (0, 1)])
vec(DC, "02-member-order-is-bytewise-on-encoded-keys.json", "member-order-is-bytewise-on-encoded-keys", C, C,
    H(rev, canonical=False), B, model={"@kind": "plain", "uid": "U-1", "lat": "45.5"},
    ref="Writing step 1: members sorted by the bytewise order of their encoded keys (00 < 01 < ... < 09 < 20 (-1) < 64666c6167 (flag)), inside nested maps too (01 < 02; 616e (n) < 646e616d65 (name)); input members in reverse order; the order of the lines sets no member order.")

r3 = withres(base(), [(10, "r"), (24, 0), ("zz", -1), ("a-b", [1, 2])])
vec(DC, "03-residue-unmapped-members.json", "residue-unmapped-members", C, C,
    H(r3, canonical=False), H(r3),
    model={"@kind": "plain", "uid": "U-1"},
    ref="Residue: members 10, 24, zz and a-b are mapped by no line and are written back, each at its place in the key order: 0a < 1818 (24) < 20 (-1) < 627a7a (zz) < 63612d62 (a-b) < 64666c6167 (flag); a shorter text key sorts first whatever its letters.")

r4 = withres(base(), [("4", 1), ("a.b", 2), (b"\x01", 3), (1.0, 4), (True, 5), (None, 6)])
vec(DC, "04-residue-unaddressable-keys.json", "residue-unaddressable-keys", C, C,
    H(r4, canonical=False), H(r4),
    model={"@kind": "plain", "uid": "U-1"},
    ref="Paths: keys of another type (byte string 4101, float f93c00 = 1.0, true f5, null f6) and text keys the step grammar cannot write (\"4\" = 6134, \"a.b\" = 63612e62) are not addressable: residue keyed #<hex> (#6134, #63612e62, #4101, #f93c00, #f5, #f6) and written back in key order 4101 < 6134 < 63612e62 < 64666c6167 (flag) < f5 < f6 < f93c00. Reading step 4: 1, 1.0 and true are three keys, so uid still reads 1.")

d5 = base(k7=M([(1, 45.5), (2, -90.25), (3, "h"), ("x", 0), ("4", 9)]),
          k8=["x", "T", "z"])
r5 = withres(d5, [(11, M([(1, 2), ("q", [1, None])]))])
vec(DC, "05-residue-nested.json", "residue-nested", C, C, H(r5, canonical=False), H(r5),
    model={"@kind": "plain", "lat": "45.5", "lon": "-90.25", "probe.tag": "T"},
    ref="Residue: the map at 7 is walked into, so its unmapped members are residue (7.3, 7.x, 7.#6134); the array at 8 is walked into, so 8.[0] and 8.[2] are residue; the map at 11 is walked into by no line, so it is one residue entry with its whole item. All go back into their own map or array.")

# 06 residue re-encoded with shorter heads, narrower floats, definite lengths
pairs6 = list(base().items()) + [
    (10, Raw("190005")),                  # uint 5 in a two-byte head
    (11, Raw("fb3ff8000000000000")),      # 1.5 as a double
    (12, Raw("7f61616162ff")),  # "ab" in two chunks
    (13, Raw("d8011a00000005")),          # tag 1 in a one-byte head, 5 in a four-byte head
    (14, Raw("bf616201616102ff")),        # indefinite map {"b":1,"a":2}
    (Raw("180f"), 0),                     # key 15 in a one-byte head
]
exp6 = withres(base(), [(10, 5), (11, 1.5), (12, "ab"), (13, Tag(1, 5)),
                        (14, M([("b", 1), ("a", 2)])), (15, 0)])
vec(DC, "06-residue-re-encoded-deterministic.json", "residue-re-encoded-deterministic", C, C,
    H(M(pairs6), canonical=False), H(exp6),
    model={"@kind": "plain", "uid": "U-1"},
    ref="Residue and ruling 1 of 0.28: residue goes back re-encoded with the core deterministic encoding: 190005 -> 05, fb3ff8000000000000 -> f93e00, 7f61616162ff -> 626162, d8011a00000005 -> c105 (the tag is kept: residue is the item as it stood, tags included), bf616201616102ff -> a2616102616201 (definite, keys sorted), key 180f -> 0f.")

p7 = [(Raw("1800"), Raw("1801")), (1, "U-1"), (2, Raw("1b000000000000002a")),
      (3, Raw("fb3ff8000000000000")), (4, Raw("5a000000020aff")),
      (5, Raw("1b00000000603aa4c0")), (6, Raw("1802")),
      (7, M([(Raw("1801"), Raw("fa42360000")), (Raw("1802"), Raw("fbc056900000000000"))])),
      (8, ["x", "T"]), (9, [M([("name", "aa"), ("n", Raw("1803"))])]),
      (Raw("3800"), Raw("3806")), ("flag", True)]
vec(DC, "07-long-heads-and-wide-floats-read.json", "long-heads-and-wide-floats-read", C, C,
    H(M(p7), canonical=False), B, model=BASE_MODEL,
    ref="Reading step 2: heads longer than they need are read (key 0 as 1800 with value 1801 still satisfies when 0 1; 42 as 1b000000000000002a; key -1 as 3800 and -7 as 3806; bytes with a four-byte length); floats read at any width (45.5 as fa42360000, -90.25 as fbc056900000000000). Writing step 1 writes every head shortest and every float at the shortest exact width, so output is the canonical message of vector 01.")

def fl(a, lat, lon, ain, latin, lonin):
    inp = base(k3=Raw(ain), k7=M([(1, Raw(latin)), (2, Raw(lonin))]))
    return H(M(list(inp.items())), canonical=False), H(base(k3=a, k7={1: lat, 2: lon}))
i8, e8 = fl(100000.0, 2.0**-24, -0.0, "fb40f86a0000000000", "fb3e70000000000000", "fb8000000000000000")
vec(DC, "08-float-shortest-width-single-subnormal-half-negative-zero.json", "float-shortest-width-single-subnormal-half-negative-zero", C, C, i8, e8,
    model={"probe.a": "100000", "lat": "0.000000059604644775390625", "lon": "-0"},
    ref="float encode: the shortest of half, single and double that holds the value exactly, subnormal halves included: 100000.0 -> fa47c35000 (no half holds it), 2^-24 -> f90001 (the smallest subnormal half), -0.0 -> f98000; inputs given as doubles.")
i9, e9 = fl(0.1, 65504.0, 65520.0, "fb3fb999999999999a", "fb40effc0000000000", "fb40effe0000000000")
vec(DC, "09-float-shortest-width-double-half-max-single.json", "float-shortest-width-double-half-max-single", C, C, i9, e9,
    model={"probe.a": "0.1", "lat": "65504", "lon": "65520"},
    ref="float encode: 0.1 -> fb3fb999999999999a (no single holds it), 65504.0 -> f97bff (largest half), 65520.0 -> fa477ff000 (above the largest half; it does not round to a half infinity).")
i10, e10 = fl(1.5, 2.0**-25, 1e300, "fa3fc00000", "fb3e60000000000000", "fb7e37e43c8800759c")
vec(DC, "10-float-shortest-width-half-single-double.json", "float-shortest-width-half-single-double", C, C, i10, e10,
    model={"probe.a": "1.5", "lat": "0.0000000298023223876953125", "lon": "1e300"},
    ref="float encode: 1.5 read from a single (fa3fc00000) -> f93e00; 2^-25 -> fa33000000 (below the smallest half subnormal, a normal single); 1e300 -> fb7e37e43c8800759c.")

i11 = H(base(k3=3, k7={1: -2, 2: 2**53 + 1}))
e11 = H(base(k3=3.0, k7={1: -2.0, 2: float(2**53)}))
vec(DC, "11-float-reads-integer-items.json", "float-reads-integer-items", C, C, i11, e11,
    model={"probe.a": "3", "lat": "-2", "lon": "9007199254740992"},
    ref="float decode and ruling 3: an integer item reads as the nearest double, ties to even: 3 -> 3.0, -2 -> -2.0, 2^53+1 (1b0020000000000001) -> 2^53; float always writes a float: f94200, f9c000, fa5a000000.")

vec(DC, "12-int-refuses-a-float-item.json", "int-refuses-a-float-item", C, C,
    H(base(km1=1.0)), error="transform-decode",
    ref="Ruling 3: int refuses a float item even with no fraction: -1 holds f93c00 (1.0).")
vec(DC, "13-uint-above-2-63-minus-1.json", "uint-above-2-63-minus-1", C, C,
    H(base(k2=2**63)), error="transform-decode",
    ref="uint decode: above 2^63-1 is transform-decode: 2 holds 1b8000000000000000 (2^63).")
vec(DC, "14-int-below-minus-2-63.json", "int-below-minus-2-63", C, C,
    H(base(km1=-2**63 - 1)), error="transform-decode",
    ref="int decode: outside -2^63 to 2^63-1 is transform-decode: -1 holds 3b8000000000000000 (-2^63-1).")
e15 = H(base(km1=-2**63, k2=2**63 - 1, k5=-1))
m15 = {"probe.n": "-9223372036854775808", "probe.val": "9223372036854775807", "time_ms": "-1000"}
vec(DC, "15-integer-range-ends-and-negative-epoch.json", "integer-range-ends-and-negative-epoch", C, C, e15, e15, model=m15,
    ref="int at -2^63 (3b7fffffffffffffff) and uint at 2^63-1 (1b7fffffffffffffff) read and write back; epoch_s -1 (20) is -1000 ms and writes back as 20.")
vec(DC, "16-float-refuses-nan.json", "float-refuses-nan", C, C,
    H(base(k3=Raw("f97e00"))), error="transform-decode",
    ref="float decode: a NaN (f97e00) is transform-decode.")
vec(DC, "17-float-refuses-infinity.json", "float-refuses-infinity", C, C,
    H(base(k7={1: Raw("f97c00"), 2: -90.25})), error="transform-decode",
    ref="float decode: an infinity (f97c00 at 7.1) is transform-decode.")
vec(DC, "18-uint-refuses-a-negative-item.json", "uint-refuses-a-negative-item", C, C,
    H(base(k2=-1)), error="transform-decode",
    ref="uint takes major type 0; an item of another type than its transform takes is transform-decode: 2 holds 20 (-1).")
vec(DC, "19-text-refuses-a-byte-string.json", "text-refuses-a-byte-string", C, C,
    H(base(k1=b"U")), error="transform-decode",
    ref="text takes major type 3; 1 holds the byte string 4155.")
vec(DC, "20-bool-refuses-an-integer.json", "bool-refuses-an-integer", C, C,
    H(base(flag=1)), error="transform-decode",
    ref="bool takes simple value 20 or 21; flag holds 01.")
vec(DC, "21-via-value-with-no-entry.json", "via-value-with-no-entry", C, C,
    H(base(k6=3)), error="transform-decode",
    ref="0.6 value tables: uint 3 has no entry in levels, and the types differ (int native, string model): transform-decode.")
vec(DC, "22-epoch-s-refuses-a-float.json", "epoch-s-refuses-a-float", C, C,
    H(base(k5=1614456000.0)), error="transform-decode",
    ref="epoch_s takes major type 0 or 1; 5 holds the float 1614456000.0 (" + enc_float(1614456000.0).hex() + ").")

i23 = H(base(k9=[M([("name", "aa"), ("n", 1), ("z", 9)]), M([("n", 2), ("name", "bb")])]), canonical=False)
e23 = H(base(k9=[{"name": "aa", "n": 1}, {"name": "bb", "n": 2}]))
vec(DC, "23-group-of-maps.json", "group-of-maps", C, C, i23, e23,
    model={"probe.items.#": "2", "probe.items[0].probe.label": "aa", "probe.items[0].probe.qty": "1",
           "probe.items[1].probe.label": "bb", "probe.items[1].probe.qty": "2"},
    ref="Groups: one item per element, in order; group items carry no residue, so z inside the first item is dropped; each item's map is written with its keys sorted (616e < 646e616d65).")
e24 = H(base(k9=[]))
vec(DC, "24-group-empty-list.json", "group-empty-list", C, C, e24, e24,
    model={"probe.items.#": "0"},
    ref="Writing step 4: a present list that is empty writes 80.")
i25 = H(base(k9=[{"q": 1}, 7, {"name": "cc"}]))
e25 = H(base(k9=[{}, {}, {"name": "cc"}]))
vec(DC, "25-group-items-with-nothing-written.json", "group-items-with-nothing-written", C, C, i25, e25,
    model={"probe.items.#": "3", "probe.items[2].probe.label": "cc"},
    ref="Reading step 8: an element of the wrong type (7) is an item with no keys; an element whose members no line maps ({\"q\":1}) is an item with no keys (its content dropped); Writing step 4: an item with nothing written is a0.")

ind = ("bf" + "00" + "01" + "01" + "7f6155622d31ff"
       + "02" + "182a" + "03" + "f93e00" + "04" + "5f410a41ffff"
       + "05" + "1a603aa4c0" + "06" + "02"
       + "07" + "bf01f951b002f9d5a4ff"
       + "08" + "9f61786154ff"
       + "09" + "9fbf646e616d6562616161 6e03ffff".replace(" ", "")
       + "20" + "26" + "64666c6167" + "f5" + "ff")
vec(DC, "26-indefinite-lengths-read-written-definite.json", "indefinite-lengths-read-written-definite", C, C,
    ind, B, model=BASE_MODEL,
    ref="Reading step 2 and Writing step 1: an indefinite top map, text in chunks (7f6155622d31ff = U-1), bytes in chunks (5f410a41ffff = 0aff), indefinite map 7, array 8, group array and item map are read; every length is written definite: output is the canonical message of vector 01.")

# build 27 by hand to put a tag in front of map 7 and the group array and its element
t27 = ("d9d9f7" + "ad" + "00c601" + "01d82063552d31" + "02182a" + "03d864f93e00" + "04420aff"
       + "051a603aa4c0" + "0602" + "07d90064a201f951b002f9d5a4" + "08826178c16154"
       + "09c181d9ffffa2616e03646e616d65626161" + "0ac105" + "2026" + "64666c6167f5")
e27 = H(withres(base(), [(10, Tag(1, 5))]))
vec(DC, "27-tags-passed-over-at-depth.json", "tags-passed-over-at-depth", C, C, t27, e27,
    model=BASE_MODEL,
    ref="Tags: every tag on an item a line reads or walks into is passed over and not written: 55799 on the top map, 6 on the when value at 0 (the when still holds), 32 on uid, 100 in a one-byte head on probe.a, 100 in a two-byte head on map 7, 1 on the T at 8.[1], 1 on the group array, 65535 on its item; residue keeps its tag: 10 holds c105 and is written c105.")

vec(DC, "28-kind-other.json", "kind-other", C, C, H(base(k0=2)), H(base(k0=2)),
    model={"@kind": "other", "uid": "U-1"},
    ref="Kinds: when 0 2 selects other; the round trip keeps the kind and writes its when value 2 as an integer (02).")
vec(DC, "29-when-never-holds-on-a-float.json", "when-never-holds-on-a-float", C, C,
    H(base(k0=1.0)), error="no-kind",
    ref="Kinds: a when value 1 is an integer; it never holds on a float, so 0 = f93c00 (1.0) selects no kind.")
vec(DC, "30-when-on-text-of-the-digits.json", "when-on-text-of-the-digits", C, C,
    H(base(k0="1")), error="no-kind",
    ref="Kinds: when 0 1 holds only on an integer item; the text \"1\" (6131) is of another type.")
vec(DC, "31-when-never-holds-on-null.json", "when-never-holds-on-null", C, C,
    H(base(k0=None)), error="no-kind",
    ref="Kinds: a when value never holds on null (f6).")

vec(DC, "32-trailing-bytes.json", "trailing-bytes", C, C, B + "00", error="malformed-wire",
    ref="Reading step 1: bytes after the one data item (00) are malformed-wire.")
vec(DC, "33-text-length-past-input.json", "text-length-past-input", C, C,
    "a20001017bffffffffffffffff6162", error="malformed-wire",
    ref="Reading step 1: uid declares 2^64-1 bytes (7bffffffffffffffff) and two remain.")
vec(DC, "34-array-count-past-input.json", "array-count-past-input", C, C,
    "a20001089b00000000ffffffff", error="malformed-wire",
    ref="Reading step 1: the array at 8 declares 4294967295 elements and no byte remains.")
vec(DC, "35-invalid-utf8-split-across-chunks.json", "invalid-utf8-split-across-chunks", C, C,
    "a200010a7f61c361a9ff", error="malformed-wire",
    ref="Reading step 3: each chunk of an indefinite text string is valid UTF-8 on its own; c3 and a9 are two chunks, each invalid, although c3a9 joined is U+00E9. The item is residue (10): anywhere in the input.")
vec(DC, "36-duplicate-key-00-and-1800.json", "duplicate-key-00-and-1800", C, C,
    "a300011800010a01", error="malformed-wire",
    ref="Ruling 4 and Reading step 4: 00 and 1800 are both the integer 0: equal keys.")
vec(DC, "37-duplicate-text-key-definite-and-chunked.json", "duplicate-text-key-definite-and-chunked", C, C,
    "a30001627a7a017f617a617aff02", error="malformed-wire",
    ref="Reading step 4: two text keys are equal when their bytes are: 627a7a and the chunks 7f617a617aff are both zz.")
vec(DC, "38-duplicate-float-key-half-and-double.json", "duplicate-float-key-half-and-double", C, C,
    "a30001f93e0001fb3ff800000000000002", error="malformed-wire",
    ref="Reading step 4: other keys are equal when their core deterministic encodings are: f93e00 and fb3ff8000000000000 both encode as f93e00.")

def nest(n, inner):
    x = inner
    for _ in range(n): x = [x]
    return x
d64 = withres({0: 1}, [(10, nest(63, 0))])
vec(DC, "39-depth-64-converts.json", "depth-64-converts", C, C, H(d64), H(d64),
    model={"@kind": "plain"},
    ref="Reading step 5: the top map is level 1 and 63 nested arrays reach level 64; the scalar inside counts none: converts, residue written back.")
vec(DC, "40-depth-65-arrays.json", "depth-65-arrays", C, C,
    H(withres({0: 1}, [(10, nest(64, 0))])), error="malformed-wire",
    ref="Reading step 5: the top map and 64 nested arrays are 65 levels.")
vec(DC, "41-depth-65-a-tag-counts.json", "depth-65-a-tag-counts", C, C,
    H(withres({0: 1}, [(10, nest(63, Tag(1, 0)))])), error="malformed-wire",
    ref="Reading step 5: tags count one level each: the top map, 63 arrays and a tag are 65 levels.")
vec(DC, "42-top-item-is-an-array.json", "top-item-is-an-array", C, C,
    "820001", error="malformed-wire",
    ref="Reading step 6: every path of conformance-cbor decides a map; the top item is an array.")
vec(DC, "43-path-through-a-scalar.json", "path-through-a-scalar", C, C,
    H({0: 1, 7: 5}), error="malformed-wire",
    ref="Reading step 8: lat (7.1) needs a map at 7 and 7 holds the integer 5.")
vec(DC, "44-position-on-a-map.json", "position-on-a-map", C, C,
    H({0: 1, 8: {1: "T"}}), error="malformed-wire",
    ref="Reading step 8: probe.tag (8.[1]) needs an array at 8 and 8 holds a map.")
vec(DC, "45-group-path-at-a-map.json", "group-path-at-a-map", C, C,
    H({0: 1, 9: {}}), error="malformed-wire",
    ref="Reading step 8: a group path at an item that is not an array (a0) is malformed-wire.")
vec(DC, "46-reserved-additional-information.json", "reserved-additional-information", C, C,
    "a200010a1c", error="malformed-wire",
    ref="Reading step 1: 1c (major type 0, additional information 28) is not well formed (RFC 8949 3.1).")
vec(DC, "47-two-byte-simple-below-32.json", "two-byte-simple-below-32", C, C,
    "a200010af814", error="malformed-wire",
    ref="Reading step 1: f814 (a simple value below 32 in two bytes) is not well formed (RFC 8949 3.3, Appendix F).")
vec(DC, "48-break-outside-an-indefinite-item.json", "break-outside-an-indefinite-item", C, C,
    "a200010aff", error="malformed-wire",
    ref="Reading step 1: a break (ff) where an item stands is not well formed.")

# context-filled values that the encoders refuse
vec(DC, "49-bool-encode-of-2.json", "bool-encode-of-2", C, C, H({0: 1}), error="transform-encode",
    context={"probe.x": "2"},
    ref="bool encode: 21 for 1, 20 for 0, another value is transform-encode; probe.x 2 comes from the context.")
vec(DC, "50-uint-encode-of-a-negative.json", "uint-encode-of-a-negative", C, C, H({0: 1}), error="transform-encode",
    context={"probe.val": "-5"},
    ref="uint encode: a negative value is transform-encode.")
vec(DC, "51-bytes-encode-uppercase-hex.json", "bytes-encode-uppercase-hex", C, C, H({0: 1}), error="transform-encode",
    context={"probe.s2": "0AFF"},
    ref="bytes encode: the string must be an even number of lowercase hex digits.")
vec(DC, "52-bytes-encode-odd-digits.json", "bytes-encode-odd-digits", C, C, H({0: 1}), error="transform-encode",
    context={"probe.s2": "abc"},
    ref="bytes encode: an odd number of hex digits is transform-encode.")
vec(DC, "53-position-gap-written-null.json", "position-gap-written-null", C, C, H({0: 1}),
    H({0: 1, 8: positional({1: "T"})}), context={"probe.tag": "T"},
    ref="Writing step 3 and ruling 23: the array at 8 is written up to its highest present position, 1; position 0 has nothing to write and no line walks into it, so it is f6: 0882f66154.")
vec(DC, "54-to-geojson.json", "to-geojson", C, G, B,
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[-90.25,45.5]},"properties":{"time_ms":1614456000000},"id":"U-1"}',
    model={"uid": "U-1", "lat": "45.5", "lon": "-90.25", "time_ms": "1614456000000"},
    ref="cbor decode as vector 01; geojson writes uid as id, lat and lon as coordinates [lon, lat], time_ms in properties; probe keys are not mapped by geojson; residue is written only into its own format.")
vec(DC, "55-null-and-undefined-are-absent.json", "null-and-undefined-are-absent", C, G,
    H({0: 1, 1: None, 5: UNDEF, 7: {1: 45.5, 2: -90.25}}),
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[-90.25,45.5]},"properties":{}}',
    model={"@absent": ["uid", "time_ms"], "lat": "45.5"},
    ref="Transforms for cbor: the simple values 22 (null, at 1) and 23 (undefined, at 5) are absent; geojson then writes no id and an empty properties object.")
vec(DC, "56-group-path-at-null-is-an-absent-list.json", "group-path-at-null-is-an-absent-list", C, G,
    H({0: 1, 1: "U-1", 9: None}),
    '{"type":"Feature","geometry":null,"properties":{},"id":"U-1"}',
    model={"probe.items.#": "absent", "uid": "U-1"},
    ref="Reading step 8: a group path at null is an absent list (not malformed-wire); geojson writes geometry null with no lat and lon.")

# ---------------------------------------------------------------- conformance-cbor-array
AB = Tag(18, [b"\x01", {1: 5, 4: b"abc"}, b"\x0a\xff", b"\xff"])
ABH = H(AB)
AM = {"probe.s1": "01", "probe.n": "5", "uid": "616263", "probe.s2": "0aff", "probe.tag": "ff"}
vec(DCA, "01-round-trip.json", "round-trip", CA, CA, ABH, ABH, model=AM,
    ref="tag 18 encloses an array: [0] bytes, [1] map with 1 int and 4 bytes, [2] bytes, [3] bytes; output is d2 then the item (Writing step 5).")
vec(DCA, "02-tag-missing.json", "tag-missing", CA, CA, H(AB.item), error="malformed-wire",
    ref="Tags: with tag 18 the outermost tag of the input must be 18; the input has no tag.")
vec(DCA, "03-tag-different.json", "tag-different", CA, CA, H(Tag(19, AB.item)), error="malformed-wire",
    ref="Tags: the outermost tag is 19 (d3), not 18.")
vec(DCA, "04-other-tag-outside-tag-18.json", "other-tag-outside-tag-18", CA, CA, H(Tag(55799, AB)), error="malformed-wire",
    ref="Tags: the outermost tag must be 18; here it is 55799 (d9d9f7) and 18 is inside it.")
i5 = ("d812" + "d9d9f7" + "84" + "c24101" + "d864a2010504d818436162" + "63" + "420aff" + "41ff")
vec(DCA, "05-inner-tags-passed-over-long-tag-head.json", "inner-tags-passed-over-long-tag-head", CA, CA, i5, ABH, model=AM,
    ref="Tags: tag 18 read from a one-byte head (d812); the tags inside it (55799 on the array, 2 on [0], 100 on [1], 24 on uid) are passed over and not written; output d2 and the canonical item.")
vec(DCA, "06-top-item-is-a-map.json", "top-item-is-a-map", CA, CA, "d2a0", error="malformed-wire",
    ref="Reading step 6: the paths of conformance-cbor-array decide an array ([0]); the top item, tag passed over, is a map.")
# ruling 23: the lines of conformance-cbor-array walk into [1] as a map ([1].1, [1].4); [0], [2], [3] are scalars
CAW = {1: "map"}
vec(DCA, "07-null-position-written-null.json", "null-position-written-null", CA, CA, "d282f6a10105",
    H(Tag(18, positional({1: {1: 5}}, CAW))),
    model={"probe.n": "5", "@absent": ["probe.s1", "uid", "probe.s2", "probe.tag"]},
    ref="null at [0] is absent; Writing step 3: the array is written up to [1], the highest present position, and [0], which no line walks into as a container, is f6 (ruling 23).")
vec(DCA, "08-empty-top-array.json", "empty-top-array", CA, CA, "d280", "d280",
    model={"@absent": ["probe.s1", "probe.n", "uid", "probe.s2", "probe.tag"]},
    ref="Writing step 2: the top item is written empty; Writing step 5: d2 then 80.")
r9 = Tag(18, [b"\x01", M([(1, -5), (4, b"abc"), (-2, "r")]), b"\x0a\xff", b"\xff", "e"])
vec(DCA, "09-residue-element-and-member.json", "residue-element-and-member", CA, CA, H(r9), H(r9),
    model={"probe.n": "-5"},
    ref="Residue: position 4 of the top array ([4]) and member -2 of the map at [1] ([1].-2) are written back in place: [1] keys 01 < 04 < 21.")
vec(DCA, "10-path-through-a-scalar.json", "path-through-a-scalar", CA, CA, H(Tag(18, [b"\x01", 5])), error="malformed-wire",
    ref="Reading step 8: [1].1 needs a map at [1] and [1] holds 5.")
vec(DCA, "11-bytes-encode-uppercase.json", "bytes-encode-uppercase", CA, CA, "d280", error="transform-encode",
    context={"probe.s1": "0A"},
    ref="bytes encode: 0A is not lowercase hex.")
vec(DCA, "12-empty-byte-string.json", "empty-byte-string", CA, CA, H(Tag(18, [b"", {1: 0}])), H(Tag(18, [b"", {1: 0}])),
    model={"probe.s1": "", "probe.n": "0"},
    ref="bytes decode: an empty byte string (40) is the empty string, present; encode of an even number (0) of hex digits writes 40.")
vec(DCA, "13-to-geojson.json", "to-geojson", CA, G, ABH,
    '{"type":"Feature","geometry":null,"properties":{},"id":"616263"}',
    model={"uid": "616263"},
    ref="uid is bytes 616263, decoded to the lowercase hex text 616263, written as the geojson id; no lat or lon: geometry null.")

# ---------------------------------------------------------------- geojson -> conformance-cbor
vec(DG, "cbor-01-to-conformance-cbor.json", "cbor-01-to-conformance-cbor", G, C,
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[-90.25,45.5,12]},"properties":{"time_ms":1614456000500,"callsign":"C","extra":"x"},"id":"G-1"}',
    H({0: 1, 1: "G-1", 5: 1614456001, 7: {1: 45.5, 2: -90.25}}),
    model={"uid": "G-1", "lat": "45.5", "lon": "-90.25", "time_ms": "1614456000500"},
    ref="kind plain (first; neither kind has requires) writes when 0 1; uid at 1; epoch_s 1614456000500 / 1000 = 1614456000.5 rounded half away from zero = 1614456001 (1a603aa4c1); lat and lon in the map at 7 (f951b0, f9d5a4); hae, callsign and geojson residue are not written.")
vec(DG, "cbor-02-to-conformance-cbor-negative-time-no-position.json", "cbor-02-to-conformance-cbor-negative-time-no-position", G, C,
    '{"type":"Feature","geometry":null,"properties":{"time_ms":-1500}}',
    H({0: 1, 5: -2}),
    model={"time_ms": "-1500"},
    ref="epoch_s: -1.5 rounds half away from zero to -2 (21); Writing step 2: no line writes into 7, so no map is written there.")
vec(DG, "cbor-03-to-conformance-cbor-float-widths.json", "cbor-03-to-conformance-cbor-float-widths", G, C,
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[100000,0.1]},"properties":{"time_ms":1614456000499}}',
    H({0: 1, 5: 1614456000, 7: {1: 0.1, 2: 100000.0}}),
    model={"lat": "0.1", "lon": "100000", "time_ms": "1614456000499"},
    ref="epoch_s 1614456000.499 rounds to 1614456000; lat 0.1 -> fb3fb999999999999a, lon 100000 -> fa47c35000.")


# ---------------------------------------------------------------- rulings 6, 7, 11 of 0.28
r57 = withres({0: 1, 1: "U-1"}, [(10, None), (11, UNDEF)])
vec(DC, "57-unmapped-null-and-undefined-written-back.json", "unmapped-null-and-undefined-written-back", C, C,
    H(r57), H(r57), model={"@kind": "plain", "uid": "U-1"},
    ref="Ruling 6: an unmapped item holding null (10: f6) or undefined (11: f7) is residue and is written back as it stood.")
vec(DC, "58-mapped-null-and-undefined-not-written.json", "mapped-null-and-undefined-not-written", C, C,
    H({0: 1, 1: None, 2: UNDEF, 3: 1.5}), H({0: 1, 3: 1.5}),
    model={"@kind": "plain", "@absent": ["uid", "probe.val"], "probe.a": "1.5"},
    ref="Ruling 6: a mapped item holding null (uid at 1) or undefined (probe.val at 2) is absent and is not written back.")
vec(DC, "59-epoch-s-product-above-2-63-minus-1.json", "epoch-s-product-above-2-63-minus-1", C, C,
    H({0: 1, 5: 9223372036854776}), error="transform-decode",
    ref="Ruling 7: 9223372036854776 s is a valid integer item, but its time_ms 9223372036854776000 lies above 2^63-1: transform-decode.")
vec(DC, "60-epoch-s-product-below-minus-2-63.json", "epoch-s-product-below-minus-2-63", C, C,
    H({0: 1, 5: -9223372036854776}), error="transform-decode",
    ref="Ruling 7: -9223372036854776 s gives time_ms -9223372036854776000, below -2^63: transform-decode.")
e61 = H({0: 1, 5: 9223372036854775, -1: -1})
vec(DC, "61-epoch-s-product-range-ends.json", "epoch-s-product-range-ends", C, C, e61, e61,
    model={"time_ms": "9223372036854775000", "probe.n": "-1"},
    ref="Ruling 7: 9223372036854775 s gives 9223372036854775000 ms, inside the range; written back as 1b0020c49ba5e353f7.")
vec(DC, "62-hex-odd-digit-count.json", "hex-odd-digit-count", C, C, "a100010", error="malformed-wire",
    ref="Ruling 11 and spec/vector-format.md (Malformed input, the bits, protobuf and cbor row): hex text with an odd number of digits.")
vec(DC, "63-hex-with-whitespace.json", "hex-with-whitespace", C, C, "a1 00\t0\n1\r", "a10001",
    model={"@kind": "plain"},
    ref="Ruling 11: space, tab, line feed and carriage return in hex text are whitespace and are read past.")
vec(DC, "64-hex-with-a-form-feed.json", "hex-with-a-form-feed", C, C, "a100\f01", error="malformed-wire",
    ref="Ruling 11: a form feed is not whitespace of hex text: malformed-wire.")
vec(DCA, "14-trailing-null-positions-not-written.json", "trailing-null-positions-not-written", CA, CA,
    H(Tag(18, [b"\x01", {1: 5}, None, None])), H(Tag(18, positional({0: b"\x01", 1: {1: 5}}, CAW))),
    model={"probe.s1": "01", "probe.n": "5", "@absent": ["probe.s2", "probe.tag"]},
    ref="Ruling 6 and Writing step 3: null at the mapped positions [2] and [3] is absent and not written back; the array is written up to [1].")

# ---------------------------------------------------------------- conformance-cbor-kinds
K = "conformance-cbor-kinds"; DK = "packs/conformance-cbor-kinds/vectors"
CONSTS = {"v": -7, "s": "12", "ok": True, "t": "18446744073709551616"}
def kd(**kw):
    d = dict(CONSTS); d.update(kw); return d
k1 = M([(1, "K-1"), (2, 7), ("k", "track"), ("v", -7), ("s", "12"), ("ok", True), ("t", "18446744073709551616")])
vec(DK, "01-text-kind-and-constants.json", "text-kind-and-constants", K, K, H(k1), H(k1),
    model={"@kind": "text", "uid": "K-1", "probe.n": "7", "probe.y": "-7"},
    ref="Kinds: when k track holds on the text track (6574726163 6b); const -0007 is the integer -7 (26), const =12 the text 12 (623132, = stripped), const true the bool (f5); ruling 19: const 18446744073709551616 lies beyond 2^64-1 and is the text 7431383434...; key order 01 < 02 < 616b < 6173 < 6174 < 6176 < 626f6b.")
vec(DK, "02-constants-written-over-the-input.json", "constants-written-over-the-input", K, K,
    H(M([(1, "K-1"), ("k", "track"), ("v", 99), ("s", 12), ("ok", False), ("t", 5)])),
    H(M([(1, "K-1"), ("k", "track"), ("v", -7), ("s", "12"), ("ok", True), ("t", "18446744073709551616")])),
    model={"@kind": "text", "probe.y": "99"},
    ref="Constants (0.6): not checked on decode and not residue; on encode written with their type over any field: probe.y reads 99 at v, and v is written -7 (Writing step 1, a const value over a field); s 12 (integer) becomes the text 12, ok false becomes f5, t 5 becomes the text 18446744073709551616 (ruling 19).")
vec(DK, "03-constants-written-when-absent.json", "constants-written-when-absent", K, K,
    H({1: "K-1", "k": "track"}), H(kd(**{"k": "track"}) | {1: "K-1"}),
    model={"@kind": "text", "@absent": ["probe.y"]},
    ref="Constants are written on encode whether or not the input held them: v -7, s 12, ok true.")
vec(DK, "04-bool-when.json", "bool-when", K, K, H({2: 3, "b": True}), H(kd(b=True) | {2: 3}),
    model={"@kind": "flagged", "probe.n": "3"},
    ref="Kinds: when b true is a bool and holds on f5; the round trip writes b as f5.")
vec(DK, "05-bool-when-does-not-hold-on-1.json", "bool-when-does-not-hold-on-1", K, K,
    H({"b": 1}), error="no-kind",
    ref="Kinds: a bool when holds only on a bool item; b holds the integer 1, and no other kind holds.")
vec(DK, "06-text-when-does-not-hold-on-bytes.json", "text-when-does-not-hold-on-bytes", K, K,
    H({"k": b"track"}), error="no-kind",
    ref="Kinds: a when never holds on a byte string; k holds h'747261636b'.")
vec(DK, "07-two-step-when.json", "two-step-when", K, K, H({3: {1: 5, 2: 42}}), H(kd() | {3: {1: 5, 2: 42}}),
    model={"@kind": "deep", "probe.val": "42"},
    ref="Kinds: when 3.1 5 holds on the integer 5 in the map at 3; the encode writes the when value 5 at 3.1 beside the field at 3.2.")
vec(DK, "08-two-step-when-through-a-scalar-does-not-hold.json", "two-step-when-through-a-scalar-does-not-hold", K, K,
    H({3: 9, "k": "track"}), H(kd(k="track") | {3: 9}),
    model={"@kind": "text"},
    ref="Reading step 7: when 3.1 passes through the integer at 3 and does not hold (no error); kind text is selected; 3 is mapped by no line of text and is residue, written back 0309.")
vec(DK, "09-two-step-when-through-an-array-does-not-hold.json", "two-step-when-through-an-array-does-not-hold", K, K,
    H({3: [5], "k": "track"}), H(kd(k="track") | {3: [5]}),
    model={"@kind": "text"},
    ref="Reading step 7: when 3.1 needs a map at 3 and 3 holds an array: it does not hold; text is selected and 3 is residue.")
vec(DK, "10-when-present-walks-into-its-path.json", "when-present-walks-into-its-path", K, K,
    H({7: {1: 45.5, 9: "z"}}), H(kd() | {7: {1: 45.5, 9: "z"}}),
    model={"@kind": "located", "lat": "45.5", "@absent": ["lon"]},
    ref="Kinds and Residue: when 7 present holds on the map at 7; the fields lat and lon walk into it (ruling 15: the when does not), so the unmapped member 7.9 is residue and goes back into the map at 7.")
vec(DK, "11-when-present-leaves-its-item-residue-whole.json", "when-present-leaves-its-item-residue-whole", K, K,
    H({2: 5, 8: {1: [2, "a"]}}), H(kd() | {2: 5, 8: {1: [2, "a"]}}),
    model={"@kind": "marked", "probe.n": "5"},
    ref="Ruling 15: when 8 present holds and does not walk into its last item; no other line walks into 8, so the map at 8 is residue whole and is written back.")
vec(DK, "12-when-present-does-not-hold-on-null.json", "when-present-does-not-hold-on-null", K, K,
    H({7: None, "k": "track"}), H(kd(k="track") | {7: None}),
    model={"@kind": "text"},
    ref="Kinds: when 7 present does not hold on null; kind text is selected; ruling 6: 7 is mapped by no line of text, so its null is residue and is written back f6.")
vec(DK, "13-when-present-on-a-scalar-then-a-field-through-it.json", "when-present-on-a-scalar-then-a-field-through-it", K, K,
    H({7: 5}), error="malformed-wire",
    ref="Kinds: when 7 present holds on the integer 5; Reading step 8: lat (7.1) of the selected kind needs a map at 7: malformed-wire.")
vec(DK, "14-when-over-a-field-round-trip.json", "when-over-a-field-round-trip", K, K,
    H({"m": "fixed"}), H(kd(m="fixed")),
    model={"@kind": "overlay", "probe.s1": "fixed"},
    ref="Kinds: when m fixed holds; probe.s1 reads the same member; encode writes the when value at m.")
vec(DK, "15-integer-when-above-2-63-minus-1.json", "integer-when-above-2-63-minus-1", K, K,
    H({0: 2**64 - 1, 4: 3}), H(kd() | {0: 2**64 - 1, 4: 3}),
    model={"@kind": "big", "probe.x": "3"},
    ref="Ruling 8: when 0 18446744073709551615 is an integer; it holds on 1bffffffffffffffff and is written back as 1bffffffffffffffff.")
vec(DK, "16-integer-when-does-not-hold-on-2-63.json", "integer-when-does-not-hold-on-2-63", K, K,
    H({0: 2**63}), error="no-kind",
    ref="Kinds: when 0 18446744073709551615 holds only on that integer; 0 holds 2^63, and no other kind holds.")
vec(DK, "17-text-when-tags-passed-over.json", "text-when-tags-passed-over", K, K,
    H({"k": Tag(0, "track"), 2: Tag(1, 1)}), H(kd(k="track") | {2: 1}),
    model={"@kind": "text", "probe.n": "1"},
    ref="Kinds: a when holds on the item at its path, its tags passed over (tag 0 on track); the field's tag 1 is passed over and not written.")

# cross-format into the kinds pack: kind chosen by requires
vec(DC, "65-to-kinds-when-written-over-a-field.json", "to-kinds-when-written-over-a-field", C, K,
    H({0: 1, 1: "U-1", 6: 2}), H(kd(m="fixed") | {1: "U-1"}),
    model={"probe.s1": "high", "uid": "U-1"},
    ref="Encode picks the first kind whose requires hold: located needs lat (absent), overlay needs probe.s1 (high, via levels): selected. probe.s1 high is written at m and the when value fixed is written over it (Writing step 1; ruling 16 of 0.5). Constants v -7, s 12, ok true.")
vec(DC, "66-to-kinds-integer-when-written.json", "to-kinds-integer-when-written", C, K,
    H({0: 1, "flag": True}), H(kd() | {0: 2**64 - 1, 4: 1}),
    model={"probe.x": "1"},
    ref="Ruling 8: with only probe.x present, located, overlay and deep do not qualify and big does; its when value is written as the integer 18446744073709551615 (1bffffffffffffffff), probe.x 1 at 4.")
vec(DC, "67-to-kinds-two-step-when-written.json", "to-kinds-two-step-when-written", C, K,
    H({0: 1, 2: 42}), H(kd() | {3: {1: 5, 2: 42}}),
    model={"probe.val": "42"},
    ref="Encode selects deep (requires probe.val); the when value 5 is written at 3.1 and probe.val 42 at 3.2, in one map at 3 (a3... keys 01 < 02).")
vec(DG, "cbor-04-to-conformance-cbor-kinds-located.json", "cbor-04-to-conformance-cbor-kinds-located", G, K,
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[-90.25,45.5]},"properties":{},"id":"G-1"}',
    H(kd() | {1: "G-1", 7: {1: 45.5, 2: -90.25}}),
    model={"lat": "45.5", "lon": "-90.25"},
    ref="Encode selects located (requires lat); when 7 present writes nothing, lat and lon write the map at 7; constants written.")
vec(DG, "cbor-05-to-conformance-cbor-kinds-default-kind.json", "cbor-05-to-conformance-cbor-kinds-default-kind", G, K,
    '{"type":"Feature","geometry":null,"properties":{},"id":"G-2"}',
    H(kd(k="track") | {1: "G-2"}),
    model={"uid": "G-2"},
    ref="No kind with requires qualifies before text, which has none: text is selected and its when value is written as the text track at k.")

# ---------------------------------------------------------------- rulings 12 to 21 of 0.28
vec(DK, "18-dot-group-scalar-items.json", "dot-group-scalar-items", K, K,
    H({"k": "track", 9: [1, None, -2]}), H(kd(k="track") | {9: [1, None, -2]}),
    model={"@kind": "text", "probe.nums.#": "3", "probe.nums[0].probe.val": "1", "probe.nums[2].probe.val": "-2"},
    ref="Groups with a . body: each element is read by int; null is an item with no value, written f6 (Writing step 4).")
vec(DK, "19-dot-group-map-element.json", "dot-group-map-element", K, K,
    H({"k": "track", 9: [1, {}]}), error="transform-decode",
    ref="Ruling 14: a map element in a body of only . is read by int, which refuses it.")
vec(DK, "20-dot-group-array-element.json", "dot-group-array-element", K, K,
    H({"k": "track", 9: [[1]]}), error="transform-decode",
    ref="Ruling 14: an array element in a body of only . is read by int, which refuses it.")
vec(DC, "68-to-kinds-when-present-writes-nothing.json", "to-kinds-when-present-writes-nothing", C, K,
    H({0: 1, -1: 5}), H(kd() | {2: 5}),
    model={"probe.n": "5"},
    ref="Encode selects marked (requires probe.n; located, overlay, deep and big do not qualify); when 8 present writes nothing, so nothing stands at 8.")
vec(DC, "69-null-partway-down-a-path.json", "null-partway-down-a-path", C, G,
    H({0: 1, 1: "U-1", 7: None}),
    '{"type":"Feature","geometry":null,"properties":{},"id":"U-1"}',
    model={"uid": "U-1", "@absent": ["lat", "lon"]},
    ref="Ruling 12: lat (7.1) and lon (7.2) on null at 7 are absent, not malformed-wire; geojson writes geometry null.")
vec(DC, "70-unaddressable-key-hex-as-it-stood.json", "unaddressable-key-hex-as-it-stood", C, C,
    H(M([(0, 1), (Raw("780134"), 1)]), canonical=False), H(M([(0, 1), ("4", 1)])),
    model={"@kind": "plain"},
    ref="Ruling 16: the text key \"4\" written with a one-byte length head (780134) is residue #780134; on write the key is re-encoded as 6134.")
r71 = M([(0, 1), (-2**63 - 1, 2), (-2**63, 3)])
vec(DC, "71-integer-key-below-minus-2-63-is-residue.json", "integer-key-below-minus-2-63-is-residue", C, C,
    H(r71), H(r71), model={"@kind": "plain"},
    ref="Ruling 17: the key 3b8000000000000000 (-2^63-1) is not addressable and is residue; 3b7fffffffffffffff (-2^63) is an unmapped integer key and residue too; both written back, 3b7f... before 3b80....")
vec(DC, "72-a-line-writes-where-null-stood.json", "a-line-writes-where-null-stood", C, C,
    H({0: 1, 7: None}), H({0: 1, 7: {1: 45.5}}), context={"lat": "45.5"},
    ref="Ruling 12: lat at 7.1 on null at 7 is absent, so the context fills it; the null at 7 is walked into, not residue; the lat line writes the map at 7: 07a101f951b0.")
vec(DCA, "15-undefined-partway-down-a-path.json", "undefined-partway-down-a-path", CA, G,
    H(Tag(18, [b"\x01", UNDEF])),
    '{"type":"Feature","geometry":null,"properties":{}}',
    model={"probe.s1": "01", "@absent": ["uid", "probe.n"]},
    ref="Ruling 12: [1].1 and [1].4 on undefined at [1] are absent, not malformed-wire; geojson writes no id.")

vec(DK, "21-when-present-on-an-empty-map-writes-nothing.json", "when-present-on-an-empty-map-writes-nothing", K, K,
    H({7: {}}), H(kd()),
    model={"@kind": "located", "@absent": ["lat", "lon"]},
    ref="Kinds: when 7 present holds on an empty map and writes nothing on encode; Writing step 2: no line writes into 7 and no residue lies in it, so no map is written at 7.")
vec(DC, "73-null-walked-into-is-not-written-back.json", "null-walked-into-is-not-written-back", C, C,
    H({0: 1, 7: None}), H({0: 1}),
    model={"@kind": "plain", "@absent": ["lat", "lon"]},
    ref="Ruling 12: lat (7.1) and lon (7.2) pass through null at 7: they are absent, and the null is walked into, not residue, so 07f6 is not written back.")

exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ruling23_cose.py")).read())
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ruling23_group.py")).read())
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bpv7.py")).read())
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rulings27_31.py")).read())

for p, o in OUT:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(json.dumps(o, indent=2, ensure_ascii=False) + "\n")
print(len(OUT), "conversion vectors")
