"""Vectors for ruling 23 of 0.28 on conformance-cbor-array, and for the pack
cose-sign1. Executed by build.py in its namespace (vec, H, Tag, M, Raw,
positional, CA, DCA, DG, G). Every message here is constructed: values chosen
for these vectors, none taken from an RFC 9052 example. Expected bytes are
hand-written structures encoded by cbor.py; never an engine."""

# ---------------------------------------------------------------- ruling 23, conformance-cbor-array
vec(DCA, "16-map-gap-written-empty-map.json", "map-gap-written-empty-map", CA, CA,
    "d283f6a0420aff", H(Tag(18, positional({2: b"\x0a\xff"}, CAW))),
    model={"probe.s2": "0aff", "@absent": ["probe.s1", "probe.n", "uid", "probe.tag"]},
    ref="Ruling 23: only [2] is present; the array is written up to [2]. [0] has nothing to write and no line walks into it: f6. [1] has nothing to write (the empty map read there holds no member, and Writing step 2 writes no empty map) and the lines [1].1 and [1].4 walk into it as a map: a0. Output d2 83 f6 a0 420aff.")
vec(DCA, "17-map-gap-from-context.json", "map-gap-from-context", CA, CA,
    "d280", H(Tag(18, positional({3: b"\xff"}, CAW))), context={"probe.tag": "ff"},
    ref="Ruling 23: probe.tag from the context writes [3]; [0] and [2] are scalar lines with nothing to write: f6; [1] is walked into as a map by [1].1 and [1].4: a0. Output d2 84 f6 a0 f6 41ff.")

# ---------------------------------------------------------------- cose-sign1
CS = "cose-sign1"; DCS = "packs/cose-sign1/vectors"
CREF = "packs/cose-sign1/pack.def and pack.md;"
# the lines walk into [1] as a map ([1].1, [1].3, [1].4, [1].5, [1].6); [0], [2], [3] are scalar fields
CSW = {1: "map"}
PROT = bytes.fromhex("a1013822")          # {1: -35}: alg ES384, encoded by hand: a1 01 3822
KID = b"k-01"                              # 6b2d3031
PAY = b"pos 7"                             # 706f732037
SIG = bytes(range(0xa0, 0xb0))             # 16 bytes a0..af, an opaque value
def cs(prot=PROT, unprot=None, pay=PAY, sig=SIG):
    p = {}
    if prot is not None: p[0] = prot
    if unprot is not None: p[1] = unprot
    if pay is not None: p[2] = pay
    if sig is not None: p[3] = sig
    return Tag(18, positional(p, CSW))
ALL = ["cose.protected", "cose.alg", "cose.content_format", "cose.kid", "cose.iv",
       "cose.partial_iv", "cose.payload", "cose.signature"]
def absent(*present): return [k for k in ALL if k not in present]
def cref(s): return CREF + " " + s

b1 = H(cs(unprot={4: KID}))
vec(DCS, "01-basic-round-trip.json", "basic-round-trip", CS, CS, b1, b1,
    model={"cose.protected": PROT.hex(), "cose.kid": KID.hex(), "cose.payload": PAY.hex(),
           "cose.signature": SIG.hex(),
           "@absent": absent("cose.protected", "cose.kid", "cose.payload", "cose.signature")},
    ref=cref("d2 (tag 18) 84: [0] 44a1013822 (protected bucket, kept as the bytes a1013822), [1] a1 04 446b2d3031 (kid k-01), [2] 45706f732037 (payload), [3] 50a0..af (signature). The input is canonical, so the output equals it."))

b2 = H(cs(unprot={4: KID}, pay=None))
vec(DCS, "02-detached-payload.json", "detached-payload", CS, CS, b2, b2,
    model={"cose.protected": PROT.hex(), "cose.kid": KID.hex(), "cose.signature": SIG.hex(),
           "@absent": absent("cose.protected", "cose.kid", "cose.signature")},
    ref=cref("[2] nil (f6) is absent (ruling 6 of 0.28); on write [2] is below the highest present position [3] and is a scalar line: f6 (Writing step 3, ruling 23 'otherwise')."))

u3 = {1: -8, 3: 60, 4: b"", 6: b"\x01"}
b3 = H(cs(prot=b"", unprot=u3, pay=b""))
vec(DCS, "03-several-headers-and-empty-strings.json", "several-headers-and-empty-strings", CS, CS, b3, b3,
    model={"cose.protected": "", "cose.alg": "-8", "cose.content_format": "60", "cose.kid": "",
           "cose.partial_iv": "01", "cose.payload": "", "cose.signature": SIG.hex(),
           "@absent": ["cose.iv"]},
    ref=cref("[0] 40 (empty protected bucket) and [2] 40 (empty payload) and kid 40 are present empty strings (bytes decode of an empty byte string); alg -8 is 27, content format 60 is 183c, partial IV 4101; members in key order 01 < 03 < 04 < 06: a4 01 27 03 183c 04 40 06 4101."))

IV = bytes.fromhex("1f2e3d4c5b6a798897a6b5c4")
u4_in = M([("x-app", True), ("1", 7), (-70000, "z"), (5, IV)])
u4_out = M([(5, IV), (-70000, "z"), ("1", 7), ("x-app", True)])
vec(DCS, "04-iv-and-residue-labels.json", "iv-and-residue-labels", CS, CS,
    H(cs(unprot=u4_in), canonical=False), H(cs(unprot=u4_out)),
    model={"cose.iv": IV.hex(), "cose.protected": PROT.hex(), "cose.payload": PAY.hex(),
           "cose.signature": SIG.hex(),
           "@absent": absent("cose.iv", "cose.protected", "cose.payload", "cose.signature")},
    ref=cref("IV (label 5) 4c1f2e..c4 is mapped. Residue in the map at [1], which the lines walk into: [1].-70000 (key 3a0001116f, 69999 = 0x1116f) and [1].x-app (65782d617070) are unmapped labels keyed by path, the text label \"1\" (6131) is not addressable and is keyed [1].#6131. Input members in reverse order; written back in key order 05 < 3a0001116f < 6131 < 65782d617070."))

i5 = ("d812" + "9f"
      + "5805" + "bf013822ff"
      + "bf" + "04" + "5f426b2d423031ff" + "01" + "390022" + "ff"
      + "5a00000005" + "706f732037"
      + "5f48" + SIG[:8].hex() + "48" + SIG[8:].hex() + "ff"
      + "ff")
PROT5 = bytes.fromhex("bf013822ff")
vec(DCS, "05-non-deterministic-input-written-deterministic.json", "non-deterministic-input-written-deterministic", CS, CS,
    i5, H(cs(prot=PROT5, unprot={1: -35, 4: KID})),
    model={"cose.protected": "bf013822ff", "cose.alg": "-35", "cose.kid": KID.hex(),
           "cose.payload": PAY.hex(), "cose.signature": SIG.hex(),
           "@absent": ["cose.content_format", "cose.iv", "cose.partial_iv"]},
    ref=cref("Reading step 2 and Writing step 1: tag 18 in a one-byte head (d812), an indefinite array (9f..ff), an indefinite unprotected map with keys out of order and alg -35 in a two-byte head (390022), kid in two chunks, the payload with a four-byte length head, the signature in two chunks; written d2 84, a2 01 3822 04 446b2d3031, 45706f732037, 50a0..af. The protected bucket's content bf013822ff (itself an indefinite map) is an opaque byte string and is written back byte for byte: 45bf013822ff."))

u6 = {2: [5, "x-app"], 4: KID}
b6 = H(cs(unprot=u6))
vec(DCS, "06-crit-as-residue.json", "crit-as-residue", CS, CS, b6, b6,
    model={"cose.kid": KID.hex(), "@absent": ["cose.alg", "cose.content_format", "cose.iv", "cose.partial_iv"]},
    ref=cref("crit (label 2) is mapped by no line: residue [1].2, its item 820565782d617070, written back in the map at [1] in key order 02 < 04."))

i7 = "d2" + H(Tag(18, [PROT, {4: KID}, Tag(24, PAY), SIG]))
vec(DCS, "07-double-tag-and-tag-on-the-payload.json", "double-tag-and-tag-on-the-payload", CS, CS,
    i7, b1,
    model={"cose.payload": PAY.hex(), "cose.kid": KID.hex()},
    ref=cref("Tags: the outermost tag is 18; the second d2 inside it is passed over; tag 24 (d818) on the payload is passed over and not written (ruling 2 of 0.28). Output is vector 01's message."))

b8 = H(cs(unprot={}))
vec(DCS, "08-empty-unprotected-map.json", "empty-unprotected-map", CS, CS, b8, b8,
    model={"cose.protected": PROT.hex(), "cose.payload": PAY.hex(), "cose.signature": SIG.hex(),
           "@absent": absent("cose.protected", "cose.payload", "cose.signature")},
    ref=cref("Ruling 23: [1] holds nothing to write and is below the highest present position [3]; the lines walk into it as a map, so it is written a0, not f6: d2 84 44a1013822 a0 45706f732037 50a0..af."))

b9 = H(cs(unprot={}, pay=None))
vec(DCS, "09-empty-unprotected-map-and-detached-payload.json", "empty-unprotected-map-and-detached-payload", CS, CS, b9, b9,
    model={"cose.protected": PROT.hex(), "cose.signature": SIG.hex(),
           "@absent": absent("cose.protected", "cose.signature")},
    ref=cref("Ruling 23: two gaps below [3]: [1], walked into as a map, is a0; [2], a scalar line, is f6: d2 84 44a1013822 a0 f6 50a0..af."))

body1 = H(cs(unprot={4: KID}).item)
vec(DCS, "10-tag-17.json", "tag-17", CS, CS, "d1" + body1, error="malformed-wire",
    ref=cref("Tags: with tag 18 the outermost tag must be 18; d1 is tag 17 (COSE_Mac0)."))
vec(DCS, "11-no-tag.json", "no-tag", CS, CS, body1, error="malformed-wire",
    ref=cref("Tags: with tag 18 the input must begin with tag 18; the bare array (untagged COSE_Sign1) has none."))
i12 = "d284" + "44a1013822" + "a2" + "04426b2d" + "04423031" + "45706f732037" + "50" + SIG.hex()
vec(DCS, "12-duplicate-kid-label.json", "duplicate-kid-label", CS, CS, i12, error="malformed-wire",
    ref=cref("Reading step 4: the unprotected map a2 holds the key 04 twice (kid 6b2d and kid 3031): equal keys."))
i13 = "d2a4" + "0044a1013822" + "01a0" + "0245706f732037" + "0350" + SIG.hex()
vec(DCS, "13-map-under-tag-18.json", "map-under-tag-18", CS, CS, i13, error="malformed-wire",
    ref=cref("Reading step 6: the paths of cose-sign1 begin with positions, so the top item is an array; under tag 18 stands a map (a4, keys 0 to 3)."))
vec(DCS, "14-trailing-byte.json", "trailing-byte", CS, CS, b1 + "00", error="malformed-wire",
    ref=cref("Reading step 1: a byte (00) after the one data item."))

for n, slug, u, why in [
        (15, "alg-as-text", {1: "ES384", 4: KID}, "alg [1].1 is read by int; it holds the text ES384 (654553333834), major type 3"),
        (16, "kid-as-text", {4: "k-01"}, "kid [1].4 is read by bytes; it holds the text k-01 (646b2d3031), major type 3"),
        (17, "content-type-as-text", {3: "application/cbor"}, "content type [1].3 is read by uint; it holds a text string, major type 3"),
        (18, "content-type-negative", {3: -1}, "content type [1].3 is read by uint, which takes major type 0; it holds -1 (20), major type 1")]:
    vec(DCS, "%02d-%s.json" % (n, slug), slug, CS, CS, H(cs(unprot=u)), error="transform-decode",
        ref=cref("Transforms for cbor: an item of another type than its transform takes is transform-decode: " + why + "."))

vec(DCS, "19-to-geojson.json", "to-geojson", CS, G, b1,
    '{"type":"Feature","geometry":null,"properties":{}}',
    model={"cose.kid": KID.hex(), "cose.signature": SIG.hex()},
    ref=cref("No line of cose-sign1 binds a core key; geojson writes geometry null, no id and empty properties; residue is written only into its own format."))

# ---------------------------------------------------------------- geojson -> cose-sign1
GJ = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-90.25,45.5]},"properties":{},"id":"G-1"}'
vec(DG, "cose-01-to-cose-sign1-from-context.json", "cose-01-to-cose-sign1-from-context", G, CS, GJ,
    H(cs(unprot=None, pay=None)),
    model={"uid": "G-1", "lat": "45.5", "lon": "-90.25"},
    context={"cose.protected": PROT.hex(), "cose.signature": SIG.hex()},
    ref=cref("convert step 2: the context fills cose.protected and cose.signature; no core key is mapped by cose-sign1, so uid, lat and lon are not written. Writing step 3 and ruling 23: [3] is the highest present position; [1] is walked into as a map by the header lines: a0; [2] is a scalar line: f6. Output d2 84 44a1013822 a0 f6 50a0..af."))
vec(DG, "cose-02-to-cose-sign1-nothing-to-write.json", "cose-02-to-cose-sign1-nothing-to-write", G, CS, GJ,
    "d280", model={"uid": "G-1"},
    ref=cref("No line of cose-sign1 writes a key geojson decodes: Writing step 2 writes the top item empty, step 5 writes tag 18 before it: d2 80."))
