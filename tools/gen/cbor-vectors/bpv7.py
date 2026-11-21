"""Vectors for the pack dtn-bpv7 (RFC 9171, Bundle Protocol 7, on the cbor
wire). Executed by build.py in its namespace (vec, H, enc, Raw, G, DG).
Every bundle here is constructed: endpoint numbers, names, times, flags and
payloads chosen for these vectors, none taken from an RFC 9171 example.
Block CRCs are computed by crc.py (RFC 9171 4.2.1: over the block's CBOR
encoding as sent, the CRC byte string zero-filled; big-endian). Expected
bytes are hand-written structures encoded by cbor.py; never an engine."""
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from crc import crc_bytes

BP = "dtn-bpv7"; DBP = "packs/dtn-bpv7/vectors"
BREF = "packs/dtn-bpv7/pack.def and pack.md; RFC 9171 4.1 (bundle), 4.3.1 (primary block), 4.3.2 (canonical block), 4.2.1 (CRC);"
def bref(s): return BREF + " " + s

def ipn(node, svc): return [2, [node, svc]]
def dtn(ssp): return [1, ssp]
DTN_NONE = [1, 0]

def seal(items, crct):
    """Append the CRC element of RFC 9171 4.2.1 when crct is 1 or 2: the CRC
    of the block encoded as it is sent (Raw elements as they stand) with the
    CRC byte string zero-filled."""
    if crct == 0: return list(items)
    n = 2 if crct == 1 else 4
    zeroed = enc(list(items) + [bytes(n)], canonical=False)
    return list(items) + [crc_bytes(crct, zeroed)]

def primary(flags, crct, dst, src, rpt, ct, seq, life, frag=None, version=7):
    items = [version, flags, crct, dst, src, rpt, [ct, seq], life]
    if frag: items += list(frag)
    return seal(items, crct)

def block(btype, num, flags, crct, data):
    return seal([btype, num, flags, crct, data], crct)

def indef(blocks):
    """The bundle as RFC 9171 4.1 sends it: an indefinite-length array."""
    return "9f" + "".join(enc(b, canonical=False).hex() for b in blocks) + "ff"

def defin(blocks): return H(blocks)

IPN_KEYS = ["bpv7.dst_ipn_node", "bpv7.dst_ipn_service", "bpv7.src_ipn_node",
            "bpv7.src_ipn_service", "bpv7.rpt_ipn_node", "bpv7.rpt_ipn_service"]
FRAG_KEYS = ["bpv7.fragment_offset", "bpv7.total_adu_length"]

def pmodel(kind, p, crct, frag=False):
    """Model of a primary block p (as a list, values plain) for a kind."""
    m = {"@kind": kind, "bpv7.version": str(p[0]), "bpv7.bundle_flags": str(p[1]),
         "bpv7.primary_crc_type": str(p[2]), "bpv7.dst_scheme": str(p[3][0]),
         "bpv7.src_scheme": str(p[4][0]), "bpv7.rpt_scheme": str(p[5][0]),
         "bpv7.creation_time_dtn_ms": str(p[6][0]), "bpv7.creation_seq": str(p[6][1])}
    absent = []
    if p[7] is None: absent.append("bpv7.lifetime_ms")
    else: m["bpv7.lifetime_ms"] = str(p[7])
    if kind in ("ipn", "fragment-ipn"):
        for k, (e, i) in zip(IPN_KEYS, [(3, 0), (3, 1), (4, 0), (4, 1), (5, 0), (5, 1)]):
            m[k] = str(p[e][1][i])
    else: absent += IPN_KEYS
    ci = 10 if frag else 8
    if frag:
        m["bpv7.fragment_offset"] = str(p[8]); m["bpv7.total_adu_length"] = str(p[9])
    else: absent += FRAG_KEYS
    if crct: m["bpv7.primary_crc"] = p[ci].hex()
    else: absent.append("bpv7.primary_crc")
    if absent: m["@absent"] = absent
    return m

HOP = enc([30, 3])            # hop count block data (4.4.3): limit 30, count 3 -> 82181e03
AGE = enc(120000)             # bundle age block data (4.4.2): 120000 ms -> 1a0001d4c0

# ---------------------------------------------------------------- 01 ipn
P1 = primary(4, 1, ipn(977, 1), ipn(12, 7), ipn(12, 0), 785000000123, 42, 86400000)
HOP1 = block(10, 2, 0, 1, HOP)
PAY1 = block(1, 1, 0, 2, b"temp 21.5")
BUN1 = [P1, HOP1, PAY1]
vec(DBP, "01-ipn-round-trip.json", "ipn-round-trip", BP, BP, indef(BUN1), defin(BUN1),
    model=pmodel("ipn", P1, 1),
    ref=bref("9f, a primary block of 9 elements (version 7, flags 4, CRC type 1, ipn:977.1, ipn:12.7, ipn:12.0, creation [785000000123, 42], lifetime 86400000, CRC-16 %s), a hop count block (type 10, number 2, CRC type 1, data 82181e03, CRC-16 %s), a payload block (type 1, number 1, CRC type 2, data 'temp 21.5', CRC-32C %s), ff. Kind ipn: [0].[9] absent, all three scheme codes 2. The canonical blocks are residue [1] and [2]. Writing step 1 writes the outer array definite (83, no break); every block is canonical in the input and comes back byte for byte, so its CRC still holds."
        % (P1[8].hex(), HOP1[5].hex(), PAY1[5].hex())))

# ---------------------------------------------------------------- 02 fragment-ipn
TOP = 2**63 - 1
P2 = primary(1, 2, ipn(977, 1), ipn(31, 7), ipn(TOP, 0), 785000360000, 0, 3600000, frag=(1200, 5000))
PAY2 = block(1, 1, 0, 0, bytes(range(0x30, 0x40)))
BUN2 = [P2, PAY2]
vec(DBP, "02-fragment-ipn-round-trip.json", "fragment-ipn-round-trip", BP, BP, indef(BUN2), defin(BUN2),
    model=pmodel("fragment-ipn", P2, 2, frag=True),
    ref=bref("A fragment (flags 1, bit 0) with a primary block of 11 elements: offset 1200, total length 5000, CRC type 2 and CRC-32C %s; the report-to node is 2^63-1 (1b7fffffffffffffff), the largest value uint reads. Kind fragment-ipn: [0].[9] present and all scheme codes 2. Payload block with CRC type 0 (5 elements). Output 82 and the blocks unchanged." % P2[10].hex()))

# ---------------------------------------------------------------- 03 whole, dtn scheme
P3 = primary(0, 1, dtn("//gs-north/telemetry"), dtn("//probe-7/"), DTN_NONE, 0, 17, 600000)
AGE3 = block(7, 2, 0, 0, AGE)
PAY3 = block(1, 1, 0, 1, b"\x01\x02\x03\x04")
BUN3 = [P3, AGE3, PAY3]
vec(DBP, "03-whole-dtn-round-trip.json", "whole-dtn-round-trip", BP, BP, indef(BUN3), defin(BUN3),
    model=pmodel("whole", P3, 1),
    ref=bref("Endpoint IDs of the dtn scheme (code 1): dtn://gs-north/telemetry, dtn://probe-7/ and dtn:none (SSP the integer 0). Creation time 0 (unknown), so a bundle age block (type 7, data 1a0001d4c0 = 120000 ms) is present. Kind whole: no [0].[9], scheme codes not 2. The SSPs [0].[3].[1], [0].[4].[1], [0].[5].[1] are residue and come back as they stood; primary_crc at [0].[8] is CRC-16 %s." % P3[8].hex()))

# ---------------------------------------------------------------- 04 fragment, dtn scheme, no CRC
P4 = primary(1, 0, dtn("//gs-north/archive"), dtn("//probe-7/"), dtn("//probe-7/"), 785000400000, 3, 7200000, frag=(2048, 4096))
PAY4 = block(1, 1, 0, 2, b"second half")
BUN4 = [P4, PAY4]
vec(DBP, "04-fragment-dtn-no-crc-round-trip.json", "fragment-dtn-no-crc-round-trip", BP, BP, indef(BUN4), defin(BUN4),
    model=pmodel("fragment", P4, 0, frag=True),
    ref=bref("A fragment (flags 1) whose primary block has CRC type 0 and so 10 elements (offset 2048, total 4096, no CRC). Kind fragment: [0].[9] present, scheme codes 1 so fragment-ipn does not hold. bpv7.primary_crc is absent and [0].[10] is not written (Writing step 3: up to the highest present position, [9]). Payload CRC-32C %s." % PAY4[5].hex()))

# ---------------------------------------------------------------- 05 mixed endpoint IDs
P5 = primary(4, 2, ipn(977, 1), dtn("//probe-7/"), ipn(12, 0), 785000500000, 1, 86400000)
PAY5 = block(1, 1, 0, 0, b"mixed")
BUN5 = [P5, PAY5]
vec(DBP, "05-mixed-eids-whole.json", "mixed-eids-whole", BP, BP, indef(BUN5), defin(BUN5),
    model=pmodel("whole", P5, 2),
    ref=bref("Destination and report-to ipn, source dtn: the when [0].[4].[0] 2 of kind ipn fails, so kind whole. The ipn SSPs 821903d101 and 820c00 and the dtn SSP are residue, written back unchanged. Primary CRC-32C %s." % P5[8].hex()))

# ---------------------------------------------------------------- 06 deterministic input
vec(DBP, "06-deterministic-input-equal-byte-for-byte.json", "deterministic-input-equal-byte-for-byte", BP, BP,
    defin(BUN1), defin(BUN1), model={"@kind": "ipn", "bpv7.primary_crc": P1[8].hex()},
    ref=bref("The bundle of vector 01 with a definite outer array (83, which RFC 9171 4.1 allows a receiver to accept): every item already in the core deterministic encoding, so the output equals the input byte for byte."))

# ---------------------------------------------------------------- 07 non-shortest heads
P7_in = primary(0, 1, ipn(977, 1), ipn(12, 7), ipn(12, 0), 785000600000, Raw("190005"), Raw("1b000000000036ee80"))
CRC7 = P7_in[8]
P7_out = [7, 0, 1, ipn(977, 1), ipn(12, 7), ipn(12, 0), [785000600000, 5], 3600000, CRC7]
PAY7_in = block(1, Raw("1801"), 0, 1, b"long heads")
PAY7_out = [1, 1, 0, 1, b"long heads", PAY7_in[5]]
need_p = crc_bytes(1, enc(P7_out[:8] + [bytes(2)]))
need_b = crc_bytes(1, enc(PAY7_out[:5] + [bytes(2)]))
assert need_p != CRC7 and need_b != PAY7_in[5]
vec(DBP, "07-non-shortest-heads-re-encoded.json", "non-shortest-heads-re-encoded", BP, BP,
    indef([P7_in, PAY7_in]), defin([P7_out, PAY7_out]),
    model={"@kind": "ipn", "bpv7.creation_seq": "5", "bpv7.lifetime_ms": "3600000",
           "bpv7.primary_crc": CRC7.hex()},
    ref=bref("Reading step 2: the sequence number 5 in a two-byte head (190005), the lifetime 3600000 in an eight-byte head (1b000000000036ee80), and the payload block number 1 in a one-byte head (1801, residue). The CRCs in the input (primary CRC-16 %s, payload CRC-16 %s) are computed over those bytes. Writing step 1 writes 05, 1a0036ee80 and 01 and carries the CRC values unchanged; over the re-encoded blocks the CRCs would be %s and %s, so both no longer match (ruling 1 of 0.28; pack.md, Output). The wire does not check CRCs."
        % (CRC7.hex(), PAY7_in[5].hex(), need_p.hex(), need_b.hex())))

# ---------------------------------------------------------------- 08 null lifetime
P8 = primary(4, 1, ipn(977, 1), ipn(12, 7), ipn(12, 0), 785000700000, 9, None)
PAY8 = block(1, 1, 0, 0, b"null life")
BUN8 = [P8, PAY8]
vec(DBP, "08-null-lifetime-written-null.json", "null-lifetime-written-null", BP, BP, indef(BUN8), defin(BUN8),
    model=pmodel("ipn", P8, 1),
    ref=bref("null (f6) at [0].[7]: bpv7.lifetime_ms is absent (Transforms: simple value 22 is absent; ruling 6). On write [0].[7] is below the highest present position [0].[8] (the CRC) and no line walks into it as a container: f6 (Writing step 3, ruling 23). So the primary block, and its CRC-16 %s computed over the f6, come back unchanged." % P8[8].hex()))

# ---------------------------------------------------------------- 09 unknown scheme code
P9 = primary(0, 2, [42, b"\xc0\xff\xee"], ipn(12, 7), ipn(12, 0), 785000800000, 2, 86400000)
PAY9 = block(1, 1, 0, 0, b"unknown scheme")
BUN9 = [P9, PAY9]
vec(DBP, "09-unknown-scheme-whole-with-residue.json", "unknown-scheme-whole-with-residue", BP, BP, indef(BUN9), defin(BUN9),
    model=pmodel("whole", P9, 2),
    ref=bref("Destination scheme code 42 (no scheme of RFC 9171 9.6) with a byte string SSP 43c0ffee: kind whole; bpv7.dst_scheme reads 42 and the SSP is residue [0].[3].[1], written back as it stood. Primary CRC-32C %s." % P9[8].hex()))

# ---------------------------------------------------------------- 10 tag 55799
vec(DBP, "10-self-described-tag-passed-over.json", "self-described-tag-passed-over", BP, BP,
    "d9d9f7" + indef(BUN1), defin(BUN1), model={"@kind": "ipn", "bpv7.dst_ipn_node": "977"},
    ref=bref("Tags: the self-described CBOR tag 55799 (d9d9f7) on the top item is passed over on decode and not written; the pack has no tag line. Output is vector 01's."))

# ---------------------------------------------------------------- 11 to geojson
vec(DBP, "11-to-geojson.json", "to-geojson", BP, G, indef(BUN1),
    '{"type":"Feature","geometry":null,"properties":{}}',
    model={"@kind": "ipn", "bpv7.src_ipn_node": "12"},
    ref=bref("dtn-bpv7 binds no core key (pack.md, Shared keys): geojson writes geometry null, no id and empty properties; residue is written only into its own format."))

# ---------------------------------------------------------------- errors
P12 = primary(4, 1, ipn(977, 1), ipn(12, 7), ipn(12, 0), 785000000123, 42, 86400000, version=6)
vec(DBP, "12-version-6-no-kind.json", "version-6-no-kind", BP, BP, indef([P12, PAY1]), error="no-kind",
    ref=bref("The common when [0].[0] 7 fails on version 6 (0.5 Decode step 1)."))

vec(DBP, "13-top-item-a-map.json", "top-item-a-map", BP, BP, H({0: P1, 1: PAY1}), error="malformed-wire",
    ref=bref("Reading step 6: the paths begin with positions, so the top item is an array; the input is a map (a2) with keys 0 and 1."))

P14 = {0: 7, 1: 4, 2: 0, 3: ipn(977, 1), 4: ipn(12, 7), 5: ipn(12, 0), 6: [785000000123, 42], 7: 86400000}
vec(DBP, "14-primary-block-a-map-no-kind.json", "primary-block-a-map-no-kind", BP, BP,
    indef([P14, PAY1]), error="no-kind",
    ref=bref("The primary block is a map (a8, keys 0 to 7) where the paths take [0].[i] steps. Reading step 7 comes before step 8: the common when [0].[0] 7 passes through a map where its next step is a position, so it does not hold, and a common when that fails is no-kind (0.5 Decode step 1), before step 8 would report malformed-wire."))

P15 = primary(4, 1, [2, "//gs-north/telemetry"], ipn(12, 7), ipn(12, 0), 785000000123, 42, 86400000)
vec(DBP, "15-ipn-scheme-text-ssp.json", "ipn-scheme-text-ssp", BP, BP, indef([P15, PAY1]), error="malformed-wire",
    ref=bref("Scheme code 2 at all three endpoint IDs, no [0].[9]: kind ipn is selected (its when lines test only the codes). Its line [0].[3].[1].[0] then meets a text string at [0].[3].[1] where its next step is a position: Reading step 8, malformed-wire."))

P16 = primary(4, 1, ipn(2**63, 1), ipn(12, 7), ipn(12, 0), 785000000123, 42, 86400000)
vec(DBP, "16-ipn-node-2-63-transform-decode.json", "ipn-node-2-63-transform-decode", BP, BP,
    indef([P16, PAY1]), error="transform-decode",
    ref=bref("Kind ipn; the destination node is 2^63 (1b8000000000000000): uint decode above 2^63-1 is transform-decode (pack.md, Limitations)."))

P17 = primary(2**64 - 1, 1, ipn(977, 1), ipn(12, 7), ipn(12, 0), 785000000123, 42, 86400000)
vec(DBP, "17-flags-2-64-minus-1-transform-decode.json", "flags-2-64-minus-1-transform-decode", BP, BP,
    indef([P17, PAY1]), error="transform-decode",
    ref=bref("The bundle processing control flags are 2^64-1 (1bffffffffffffffff), a well-formed CBOR unsigned integer: the common uint line at [0].[1] refuses it above 2^63-1."))

vec(DBP, "18-byte-after-break.json", "byte-after-break", BP, BP, indef(BUN1) + "00", error="malformed-wire",
    ref=bref("Reading step 1: a byte (00) after the break that closes the bundle."))

vec(DBP, "19-no-break.json", "no-break", BP, BP, indef(BUN1)[:-2], error="malformed-wire",
    ref=bref("Reading step 1: the indefinite-length bundle array is not closed by a break; the input ends inside it, so it is not a well-formed item."))

# ---------------------------------------------------------------- geojson -> dtn-bpv7
GJB = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-90.25,45.5]},"properties":{},"id":"G-1"}'
vec(DG, "bpv7-01-to-dtn-bpv7-nothing-to-write.json", "bpv7-01-to-dtn-bpv7-nothing-to-write", G, BP, GJB,
    H([[7]]), model={"uid": "G-1", "lat": "45.5", "lon": "-90.25"},
    ref=bref("No bpv7 key: Encode step 2 takes the first kind whose requires keys are present, whole (no requires). Only the common when [0].[0] 7 writes (Encode step 4): the primary block [7] in the top array, 81 81 07 (pack.md, Shared keys)."))

CTX = {"bpv7.bundle_flags": "4", "bpv7.primary_crc_type": "0",
       "bpv7.dst_ipn_node": "977", "bpv7.dst_ipn_service": "1",
       "bpv7.src_ipn_node": "12", "bpv7.src_ipn_service": "7",
       "bpv7.rpt_ipn_node": "12", "bpv7.rpt_ipn_service": "0",
       "bpv7.creation_time_dtn_ms": "785000000123", "bpv7.creation_seq": "42",
       "bpv7.lifetime_ms": "86400000"}
vec(DG, "bpv7-02-to-dtn-bpv7-ipn-from-context.json", "bpv7-02-to-dtn-bpv7-ipn-from-context", G, BP, GJB,
    H([[7, 4, 0, ipn(977, 1), ipn(12, 7), ipn(12, 0), [785000000123, 42], 86400000]]),
    model={"uid": "G-1"}, context=CTX,
    ref=bref("The context gives the six node and service keys, so Encode step 2 skips fragment-ipn and fragment (no bpv7.total_adu_length) and selects ipn. The scheme codes are not in the context: the when lines of ipn write 2 at [0].[3].[0], [0].[4].[0] and [0].[5].[0], and the common when writes 7 at [0].[0]. CRC type 0 and no bpv7.primary_crc: a primary block of 8 elements, no canonical block: 81 88 07 04 00 %s %s %s %s %s (785000000123 = 0xb6c5a56a7b)." % tuple(H(x) for x in (ipn(977, 1), ipn(12, 7), ipn(12, 0), [785000000123, 42], 86400000))))
