"""Vectors for rulings 27 to 31 of 0.28. Executed by build.py in its
namespace (vec, H, M, Raw, kd, C, DC, positional). Values chosen for these
vectors. Expected bytes are hand-written structures encoded by cbor.py;
never an engine."""

SC = "conformance-cbor-scope"; DSC = "packs/conformance-cbor-scope/vectors"
SREF = ("packs/conformance-cbor-scope/pack.def (group probe.items [0] with probe.qty a.b int; "
        "probe.val [1] uint under const [1] 5; probe.s2 [3] bytes; kind located: when [4] 1, lat [2].1 float; kind bare: no when);")
def sref(s): return SREF + " " + s
# The const writes 5 at [1] in every output (constants are written on encode
# whether or not the input held them; not checked on decode, not residue).

# ---------------------------------------------------------------- ruling 27
vec(DSC, "01-two-step-body-path-round-trip.json", "two-step-body-path-round-trip", SC, SC,
    H([[{"a": {"b": 7}}], 5]), H([[{"a": {"b": 7}}], 5]),
    model={"@kind": "bare", "probe.items.#": "1", "probe.items[0].probe.qty": "7", "probe.val": "5"},
    ref=sref("The body line a.b reads 7 in the element {\"a\": {\"b\": 7}}; written back 82 81 a1 6161 a1 6162 07 05."))
vec(DSC, "02-two-step-body-path-through-a-scalar.json", "two-step-body-path-through-a-scalar", SC, SC,
    H([[{"a": 5}], 5]), error="malformed-wire",
    ref=sref("Ruling 27: the element {\"a\": 5} is a map, the type the body needs; the step a reaches the integer 5, and the next step b needs a map there: Reading step 8, malformed-wire, not an item with no keys."))
vec(DSC, "03-element-of-the-wrong-type-is-an-item-with-no-keys.json", "element-of-the-wrong-type-is-an-item-with-no-keys", SC, SC,
    H([[5], 5]), H([[{}], 5]),
    model={"@kind": "bare", "probe.items.#": "1", "probe.val": "5"},
    ref=sref("Ruling 27, the other case: the element itself (5) is not a map: an item with no keys (ruling 12 of 0.7), written as an empty map (Writing step 4, the body's paths begin with a text key): 82 81 a0 05."))

# ---------------------------------------------------------------- ruling 29
vec(DSC, "04-const-over-a-field-that-could-not-encode.json", "const-over-a-field-that-could-not-encode", SC, SC,
    "80", H(positional({1: 5})), context={"probe.val": "-3"},
    model={"@kind": "bare", "@absent": ["probe.val"]},
    ref=sref("Ruling 29: the context gives probe.val -3, which uint would refuse on encode (transform-encode); the line at [1] is under const [1] 5, so it is not encoded and raises no error; the const is written. [0], the group's path with the list absent, is f6 (ruling 23): 82 f6 05."))

# ---------------------------------------------------------------- ruling 30
vec(DSC, "05-gap-only-another-kind-walks-into.json", "gap-only-another-kind-walks-into", SC, SC,
    "80", H(positional({1: 5, 3: b"\x0a\xff"})), context={"probe.s2": "0aff"},
    model={"@kind": "bare", "@absent": ["probe.s2"]},
    ref=sref("Ruling 30: kind bare is selected (located's when [4] 1 fails on 80) and kept; [2] is walked into as a map only by located's lat line, which is not of the selected scope, so the gap at [2] is f6, not a0. [0] is f6 (group path, list absent), [1] the const 5, [3] from the context: 84 f6 05 f6 420aff."))
vec(DSC, "06-gap-the-selected-kind-walks-into.json", "gap-the-selected-kind-walks-into", SC, SC,
    H([None, 5, None, b"\x0a\xff", 1]), H([None, 5, {}, b"\x0a\xff", 1]),
    model={"@kind": "located", "probe.val": "5", "probe.s2": "0aff", "@absent": ["lat"]},
    ref=sref("The contrast to ruling 30: when [4] 1 selects located, whose lat line passes through null at [2] (ruling 12: absent, walked into, not written back); on write [2] is a gap the selected lines walk into as a map: a0 (ruling 23). [4] is the when value 1: 85 f6 05 a0 420aff 01."))

# ---------------------------------------------------------------- ruling 28 (conformance-cbor, top map residue)
nan_in = M([(0, 1), (10, Raw("fb7ff8000000000001")), (11, Raw("f97e00")),
            (12, Raw("fb7ff8000020000000")), (13, Raw("fbfff8000000000000"))])
nan_out = M([(0, 1), (10, Raw("fb7ff8000000000001")), (11, Raw("f97e00")),
             (12, Raw("fa7fc00001")), (13, Raw("f9fe00"))])
vec(DC, "74-nan-residue-keeps-sign-and-payload.json", "nan-residue-keeps-sign-and-payload", C, C,
    H(nan_in, canonical=False), H(nan_out),
    model={"@kind": "plain"},
    ref="Ruling 28: NaNs carried as residue keep sign and payload at the shortest width that holds them exactly (half when the low 42 bits of the double mantissa are 0, else single when the low 29 are 0). 10: fb7ff8000000000001 (payload bit 0) fits no narrower width: unchanged. 11: f97e00 stays f97e00. 12: fb7ff8000020000000 (mantissa 0x8000020000000, bit 29 set) -> single 0x7fc00001: fa7fc00001. 13: fbfff8000000000000 (negative quiet NaN) -> half 0xfe00: f9fe00.")

# ---------------------------------------------------------------- ruling 31 (conformance-cbor, map at 7)
vec(DC, "75-walked-into-container-left-empty-keeps-its-residue.json", "walked-into-container-left-empty-keeps-its-residue", C, C,
    H(M([(0, 1), (7, M([(1, None), (9, "z")]))])), H({0: 1, 7: {9: "z"}}),
    model={"@kind": "plain", "@absent": ["lat", "lon"]},
    ref="Ruling 31: lat (7.1) and lon (7.2) walk into the map at 7 and write no value (lat holds null and is absent, ruling 6; lon is missing), so no line writes at 7 (ruling 21 does not apply) and 7 takes its residue 7.9 back: a2 00 01 07 a1 09 617a. The null at 7.1 is a mapped item and is not written back.")
