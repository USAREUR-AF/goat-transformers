#!/usr/bin/env python3
"""Write the vectors of spec 0.9, absent-value sentinels: the packs
`conformance-absent-*` and the load vectors from 315.

Every expected value here is worked out from the spec text (Version 0.9 and
the wire sections it refers to) and the pack layouts. Hex expectations are
written by hand and checked against a second computation by the small
encoders below (`fixed_msb`, `fixed_lsb`, `seq`, `pb_*`), which follow the
spec's bit order and protobuf encoding and import nothing from an engine.
Nothing calls an engine.

Usage: tools/gen/conformance-absent-vectors.py <repository root>
"""
import json
import os
import struct
import sys

ROOT = sys.argv[1]
written = {}
counters = {}


def vec(pack, name, frm, to, inp, expect=None, error=None, model=None, context=None):
    counters[pack] = counters.get(pack, 0) + 1
    d = {"name": name, "from": frm, "to": to, "input": inp}
    if context is not None:
        d["context"] = context
    if error:
        d["expect_error"] = error
    else:
        d["expect"] = expect
    if model:
        d["model"] = model
    path = os.path.join(ROOT, "packs", pack, "vectors", "%02d-%s.json" % (counters[pack], name))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.write("\n")
    written[pack] = written.get(pack, 0) + 1


def hx(s):
    return s.replace(" ", "")


def same(paper, computed):
    assert hx(paper) == computed, (hx(paper), computed)
    return computed


# --------------------------------------------------------------------------
# bit helpers
# --------------------------------------------------------------------------
def fixed(nbytes, fields, msb):
    """fields: (bit offset, len, unsigned value, swap) written in order; a
    later entry overwrites the bits of an earlier one."""
    bitsv = [0] * (nbytes * 8)
    for pos, n, v, swap in fields:
        v &= (1 << n) - 1
        if swap:
            v = int.from_bytes(v.to_bytes(n // 8, "big")[::-1], "big")
        for i in range(n):
            # value bit for field bit i (0 = first bit of the field)
            b = (v >> (n - 1 - i)) & 1 if msb else (v >> i) & 1
            bitsv[pos + i] = b
    out = bytearray(nbytes)
    for i, b in enumerate(bitsv):
        if b:
            out[i // 8] |= (0x80 >> (i % 8)) if msb else (1 << (i % 8))
    return bytes(out).hex()


def seq(fields):
    """msb sequential: (value, len) in reading order, zero bits to the byte."""
    s = []
    for v, n in fields:
        v &= (1 << n) - 1
        s += [(v >> (n - 1 - i)) & 1 for i in range(n)]
    while len(s) % 8:
        s.append(0)
    out = bytearray()
    for i in range(0, len(s), 8):
        b = 0
        for k in range(8):
            if s[i + k]:
                b |= 0x80 >> k
        out.append(b)
    return bytes(out).hex()


def ascii_int(t):
    return int.from_bytes(t.encode(), "big")


# --------------------------------------------------------------------------
# protobuf helpers
# --------------------------------------------------------------------------
def varint(v):
    v &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def pb_v(f, v):
    return (varint(f << 3) + varint(v)).hex()


def pb_64(f, raw):
    return (varint(f << 3 | 1) + raw.to_bytes(8, "little")).hex()


def pb_32(f, raw):
    return (varint(f << 3 | 5) + raw.to_bytes(4, "little")).hex()


def pb_ld(f, payload_hex):
    p = bytes.fromhex(payload_hex)
    return (varint(f << 3 | 2) + varint(len(p)) + p).hex()


def pb_s(f, text):
    return pb_ld(f, text.encode().hex())


def zz(v):
    return (v << 1) ^ (v >> 63)


# ==========================================================================
# conformance-absent-bits (fixed, msb)
# ==========================================================================
AB = "conformance-absent-bits"
AL = "conformance-absent-bits-lsb"
AS = "conformance-absent-seq"
AP = "conformance-absent-protobuf"
AJ = "conformance-absent-json"
AX = "conformance-absent-xml"
AG = "conformance-absent-geojson"
ALL1 = (1 << 64) - 1


def msb(x, y, z, w1, w2, cs, c1, c2, n, val=None):
    f = [(0, 8, x, 0), (8, 16, y, 0), (24, 8, z, 0), (32, 8, w1, 0), (40, 8, w2, 0),
         (48, 16, cs, 0), (64, 8, c1, 0)]
    if c2 is not None:
        f.append((64, 4, c2, 0))       # written over c1's high four bits
    f.append((72, 64, n, 0))
    if val is None:
        return fixed(17, f, True)
    return fixed(18, f + [(136, 8, val, 0)], True)


b1 = same("ff 8000 05 2a 2a 0000 ff ffffffffffffffff ff", msb(255, 0x8000, 5, 42, 42, 0, 255, 15, ALL1, 255))
vec(AB, "every-field-holds-its-first-sentinel-roundtrip", AB, AB, b1, b1, model={
    "probe.z": "5", "probe.w": "42", "probe.c2": "15",
    "@absent": ["probe.x", "probe.y", "callsign", "probe.c1", "probe.n", "probe.val"]})

b2i = same("01 ffff 05 2a2a 4142 12 0000000000000001 03", msb(1, 0xFFFF, 5, 42, 42, ascii_int("AB"), 0x12, 1, 1, 3))
b2e = same("01 8000 05 2a2a 4142 12 0000000000000001 03", msb(1, 0x8000, 5, 42, 42, ascii_int("AB"), 0x12, 1, 1, 3))
vec(AB, "second-sentinel-reencodes-as-the-first", AB, AB, b2i, b2e, model={
    "probe.x": "1", "probe.z": "5", "callsign": "AB", "probe.c1": "18", "probe.c2": "1",
    "probe.n": "1", "probe.val": "3", "@absent": ["probe.y"]})

b3i = same("01 0001 00 2a2a 4142 12 0000000000000001 03", msb(1, 1, 0, 42, 42, ascii_int("AB"), 0x12, 1, 1, 3))
b3e = same("01 0001 07 2a2a 4142 12 0000000000000001 03", msb(1, 1, 7, 42, 42, ascii_int("AB"), 0x12, 1, 1, 3))
vec(AB, "default-wins-over-the-sentinel", AB, AB, b3i, b3e, model={"probe.y": "1", "@absent": ["probe.z"]})

b4i = same("01 0001 05 ff2a 4142 12 0000000000000001 03", msb(1, 1, 5, 255, 42, ascii_int("AB"), 0x12, 1, 1, 3))
b4e = same("01 0001 05 2a2a 4142 12 0000000000000001 03", msb(1, 1, 5, 42, 42, ascii_int("AB"), 0x12, 1, 1, 3))
vec(AB, "ruling-1-first-line-holds-the-sentinel-second-line-read", AB, AB, b4i, b4e, model={"probe.w": "42"})

b5i = same("01 0001 05 2a2a 4142 12 0000000000000001", msb(1, 1, 5, 42, 42, ascii_int("AB"), 0x12, 1, 1))
b5e = same("01 0001 05 2a2a 4142 12 0000000000000001 ff", msb(1, 1, 5, 42, 42, ascii_int("AB"), 0x12, 1, 1, 255))
vec(AB, "ruling-3-optional-beyond-the-input-writes-the-sentinel", AB, AB, b5i, b5e, model={
    "probe.n": "1", "@absent": ["probe.val"]})

b6i = same("ff 8000 05 ff 01 0000 ff ffffffffffffffff ff", msb(255, 0x8000, 5, 255, 1, 0, 255, 15, ALL1, 255))
vec(AB, "to-json-absent-keys-write-the-json-sentinels", AB, AJ, b6i,
    '{"id":"","alt":9999999,"lat":0,"label":"N/A","r":"N/A","code":"0","on":true,"cs":"NONE","a":0,"na":0,"s":"-","q":7,"c2":15}',
    model={"probe.w": "1", "probe.c2": "15", "probe.z": "5",
           "@absent": ["probe.x", "probe.y", "callsign", "probe.c1", "probe.n", "probe.val"]})

# ==========================================================================
# conformance-absent-bits-lsb
# ==========================================================================


def lsb(x, y, z, ratio, ce):
    return fixed(12, [(0, 16, x, 1), (16, 12, y, 0), (28, 4, z, 0), (32, 32, ratio, 0), (64, 32, ce, 1)], False)


NANQ = 0x7FC00000
NANQN = 0xFFC00000
l1 = same("1234 ffaf 0000c07f ffc00000", lsb(0x1234, 0xFFF, 10, NANQ, NANQN))
vec(AL, "every-field-holds-its-sentinel-roundtrip", AL, AL, l1, l1, model={
    "@absent": ["probe.x", "probe.y", "probe.z", "probe.ratio", "ce"]})
f15 = struct.unpack(">I", struct.pack(">f", 1.5))[0]
f25 = struct.unpack(">I", struct.pack(">f", 2.5))[0]
l2 = same("3412 2351 0000c03f 40200000", lsb(0x3412, 0x123, 5, f15, f25))
vec(AL, "swap-before-the-comparison-little-endian-reading-is-not-the-sentinel", AL, AL, l2, l2, model={
    "probe.x": "13330", "probe.y": "291", "probe.z": "5", "probe.ratio": "1.5", "ce": "2.5"})
l3 = same("3412 2351 0000c0ff 40200000", lsb(0x3412, 0x123, 5, NANQN, f25))
vec(AL, "nan-that-is-not-the-fields-sentinel", AL, AL, l3, error="transform-decode")
l4 = same("ff 8000 07 ff 00 0000 ff ffffffffffffffff ff", msb(255, 0x8000, 7, 255, 0, 0, 255, None, ALL1, 255))
vec(AL, "to-msb-bits-every-absent-key-writes-its-sentinel", AL, AB, l1, l4, model={
    "@absent": ["probe.x", "probe.y", "probe.z", "probe.ratio", "ce"]})

# ==========================================================================
# conformance-absent-seq
# ==========================================================================


def rec(label, qty):
    return [(1, 1), (label, 16), (qty, 8)]


s1i = same("ff 80 00 ff 01 00 ff ff 00 05 80 00 7f 80", seq(
    [(255, 8), (0b10, 2), (0, 6), (0, 8), (255, 8),       # x; p.1; y z
     (0, 7), (1, 1), (0x00FF, 16),                       # opt 1; n on the wire 00 ff (0xff00 after swap)
     (127, 7), (1, 1), (0, 7), (0, 1),                   # chain c1, fx 1, c2, fx 0
     (5, 8)] + rec(0, 255) + [(0, 1)]))
s1e = same("ff 00 00 fe 05 80 00 7f 80", seq(
    [(255, 8), (0b00, 2), (0, 6),                        # p.1 0, p.2 0: no block
     (0, 7), (0, 1),                                     # opt 0
     (127, 7), (0, 1),                                   # chain c1 sentinel, fx 0
     (5, 8)] + rec(0, 255) + [(0, 1)]))
vec(AS, "ruling-4-blocks-holding-only-sentinels-are-left-out", AS, AS, s1i, s1e, model={
    "probe.val": "5", "probe.recs.#": "1",
    "@absent": ["probe.x", "probe.y", "probe.z", "probe.w", "probe.n", "probe.c1", "probe.c2",
                "probe.recs[0].probe.label", "probe.recs[0].probe.qty"]})
s2 = same("01 c0 07 ff 2a 01 ff 00 ff 12 00 a0 a1 7f c0 00 00 c0", seq(
    [(1, 8), (0b11, 2), (0, 6), (7, 8), (255, 8), (42, 8),
     (0, 7), (1, 1), (0xFF00, 16),                       # n 255: 0x00ff, swapped on the wire ff 00
     (127, 7), (1, 1), (9, 7), (0, 1),
     (0, 8)] + rec(ascii_int("AB"), 255) + rec(0, 3) + [(0, 1)]))
vec(AS, "block-with-a-present-key-writes-the-sentinels-beside-it-roundtrip", AS, AS, s2, s2, model={
    "probe.x": "1", "probe.y": "7", "probe.w": "42", "probe.n": "255", "probe.c2": "9", "probe.val": "0",
    "probe.recs.#": "2", "probe.recs[0].probe.label": "AB", "probe.recs[1].probe.qty": "3",
    "@absent": ["probe.z", "probe.c1", "probe.recs[0].probe.qty", "probe.recs[1].probe.label"]})

# ==========================================================================
# conformance-absent-protobuf
# ==========================================================================
NAN64 = 0x7FF8000000000000
INF32 = 0x7F800000
SENT = same("08ffffffffffffffffff01 1001 19000000000000f87f 250000807f 2a043d4e2f41 3200",
            pb_v(1, ALL1) + pb_v(2, 1) + pb_64(3, NAN64) + pb_32(4, INF32) + pb_s(5, "=N/A") + pb_s(6, ""))
ITEM_S = same("420608ff0112012d", pb_ld(8, pb_v(1, 255) + pb_s(2, "-")))
TOP_ABSENT = ["probe.n", "probe.x", "hae", "probe.ratio", "probe.label", "uid"]
p1 = SENT + same("3a03000500", pb_ld(7, "000500")) + ITEM_S
vec(AP, "every-field-holds-its-sentinel-roundtrip", AP, AP, p1, p1, model={
    "@kind": "plain", "probe.nums.#": "3", "probe.nums[1].probe.val": "5", "probe.items.#": "1",
    "@absent": TOP_ABSENT + ["probe.nums[0].probe.val", "probe.nums[2].probe.val",
                             "probe.items[0].probe.qty", "probe.items[0].probe.label"]})
p2i = same("1002 2a034e2f41", pb_v(2, zz(1)) + pb_s(5, "N/A"))
p2e = same("08ffffffffffffffffff01 1002 19000000000000f87f 250000807f 2a034e2f41 3200",
           pb_v(1, ALL1) + pb_v(2, 2) + pb_64(3, NAN64) + pb_32(4, INF32) + pb_s(5, "N/A") + pb_s(6, ""))
vec(AP, "psint-raw-before-zigzag-and-pstring-keeps-the-equals-sign", AP, AP, p2i, p2e, model={
    "probe.x": "1", "probe.label": "N/A",
    "@absent": ["probe.n", "hae", "probe.ratio", "uid", "probe.nums", "probe.items"]})
p3i = same("3a0105 4200", pb_ld(7, "05") + pb_ld(8, ""))
vec(AP, "missing-places-and-an-empty-item-gain-the-sentinels", AP, AP, p3i, SENT + "3a0105" + ITEM_S, model={
    "probe.nums.#": "1", "probe.nums[0].probe.val": "5", "probe.items.#": "1",
    "@absent": TOP_ABSENT + ["probe.items[0].probe.qty", "probe.items[0].probe.label"]})
vec(AP, "ruling-15-wire-type-mismatch-before-the-sentinel", AP, AP,
    same("090000000000000000", pb_64(1, 0)), error="transform-decode")
vec(AP, "nan-that-is-not-the-fields-sentinel", AP, AP,
    same("19000000000000f8ff", pb_64(3, 0xFFF8000000000000)), error="transform-decode")
vec(AP, "ruling-16-sentinel-is-a-written-field-for-when-present", AP, AP, "4a00",
    SENT + same("4a020800", pb_ld(9, pb_v(1, 0))), model={"@kind": "sub", "@absent": ["probe.y"] + TOP_ABSENT})
vec(AP, "unpacked-input-item-without-value-written-packed-as-the-sentinel", AP, AP,
    same("3800 3805", pb_v(7, 0) + pb_v(7, 5)), SENT + same("3a020005", pb_ld(7, "0005")), model={
        "probe.nums.#": "2", "probe.nums[1].probe.val": "5", "@absent": ["probe.nums[0].probe.val"]})
vec(AP, "to-json-items-and-scalar-items-write-the-json-sentinels", AP, AJ, p1,
    '{"id":"","alt":9999999,"lat":0,"label":"N/A","r":"N/A","code":"0","on":false,"cs":"NONE","a":0,"na":0,"s":"-","q":7,"nums":[-1,5,-1],"items":[{"q":0,"name":""}]}')

# ==========================================================================
# conformance-absent-json
# ==========================================================================
EMPTY_J = '{"id":"","alt":9999999,"lat":0,"label":"N/A","r":"N/A","code":"0","on":false,"cs":"NONE","a":0,"na":0,"s":"-","q":7}'
j1i = '{"id":"","alt":9999999,"lat":0,"label":"N/A","r":"N/A","code":"0","on":false,"cs":"NONE","a":0,"na":0,"s":"-","q":5,"nums":[1,null,-1],"items":[{"q":0,"name":""},{}]}'
j1e = '{"id":"","alt":9999999,"lat":0,"label":"N/A","r":"N/A","code":"0","on":false,"cs":"NONE","a":0,"na":0,"s":"-","q":7,"nums":[1,-1,-1],"items":[{"q":0,"name":""},{"q":0,"name":""}]}'
vec(AJ, "every-field-holds-its-first-sentinel", AJ, AJ, j1i, j1e, model={
    "probe.s2": "-", "probe.nums.#": "3", "probe.nums[0].probe.val": "1", "probe.items.#": "2",
    "@absent": ["uid", "hae", "lat", "probe.label", "probe.ratio", "probe.tag", "probe.w", "callsign",
                "probe.a", "probe.neg_a", "probe.s1", "probe.qty",
                "probe.nums[1].probe.val", "probe.nums[2].probe.val",
                "probe.items[0].probe.qty", "probe.items[0].probe.label",
                "probe.items[1].probe.qty", "probe.items[1].probe.label"]})
vec(AJ, "second-sentinels-and-numbers-compared-by-canonical-text", AJ, AJ,
    '{"alt":9.999999e6,"lat":-999,"label":"-","r":0.5,"id":"u1","code":0,"on":true,"cs":"C","a":1,"na":-1,"s":"x","q":3}',
    '{"id":"u1","alt":9999999,"lat":0,"label":"N/A","r":0.5,"code":"0","on":true,"cs":"C","a":1,"na":-1,"s":"x","q":3}',
    model={"uid": "u1", "probe.ratio": "0.5", "probe.w": "1", "callsign": "C", "probe.a": "1",
           "probe.neg_a": "-1", "probe.s1": "x", "probe.s2": "x", "probe.qty": "3",
           "@absent": ["hae", "lat", "probe.label", "probe.tag"]})
vec(AJ, "string-holding-a-sentinel-on-a-number-field-is-absent", AJ, AJ,
    '{"alt":"9999999","lat":null,"r":"N/A","code":"0"}', EMPTY_J,
    model={"@absent": ["uid", "hae", "lat", "probe.ratio", "probe.tag", "probe.qty"]})
vec(AJ, "string-that-is-not-the-canonical-sentinel-on-a-float-field", AJ, AJ,
    '{"alt":"9999999.0"}', error="transform-decode")
vec(AJ, "ruling-6-context-and-a-derivation-fill-keys-left-absent", AJ, AJ,
    '{"id":"u1","alt":10,"lat":1,"label":"L","r":2,"code":"c","on":true,"cs":"NONE","a":2,"na":0,"s":"x","q":3}',
    '{"id":"u1","alt":10,"lat":1,"label":"L","r":2,"code":"c","on":true,"cs":"CTX","a":2,"na":-2,"s":"x","q":3}',
    context={"callsign": "CTX"},
    model={"@complete": True, "callsign": "CTX", "probe.neg_a": "-2", "probe.a": "2"})
vec(AJ, "ruling-16-present-key-of-a-later-line-wins-over-the-sentinel", AJ, AJ, '{"id":"u7"}',
    '{"id":"u7","alt":9999999,"lat":0,"label":"N/A","r":"N/A","code":"0","on":false,"cs":"NONE","a":0,"na":0,"s":"Z","q":7}',
    context={"probe.s2": "Z"}, model={"@complete": True, "probe.s2": "Z", "@absent": ["probe.s1"]})
vec(AJ, "to-msb-bits-present-values-equal-to-sentinels-are-written", AJ, AB,
    '{"x":255,"y":-32768,"on":true}',
    same("ff 8000 07 01 01 0000 ff ffffffffffffffff ff", msb(255, -32768, 7, 1, 1, 0, 255, None, ALL1, 255)),
    model={"probe.x": "255", "probe.y": "-32768", "probe.w": "1"})
vec(AJ, "to-msb-bits-ruling-16-overlap-and-ruling-1-second-line", AJ, AB, '{"c2":3}',
    same("ff 8000 07 ff 00 0000 3f ffffffffffffffff ff", msb(255, 0x8000, 7, 255, 0, 0, 255, 3, ALL1, 255)),
    model={"probe.c2": "3", "@absent": ["probe.c1", "probe.w"]})
vec(AJ, "to-lsb-bits-present-value-equal-to-the-sentinel-is-written", AJ, AL, '{"x":4660}',
    same("1234 ffaf 0000c07f ffc00000", lsb(4660, 0xFFF, 10, NANQ, NANQN)), model={"probe.x": "4660"})
vec(AJ, "to-protobuf-null-item-written-packed-as-the-sentinel", AJ, AP,
    '{"x":-1,"label":"=N/A","nums":[null,2]}',
    same("08ffffffffffffffffff01 1001 19000000000000f87f 250000807f 2a043d4e2f41 3200 3a020002",
         pb_v(1, ALL1) + pb_v(2, zz(-1)) + pb_64(3, NAN64) + pb_32(4, INF32) + pb_s(5, "=N/A")
         + pb_s(6, "") + pb_ld(7, "0002")),
    model={"probe.x": "-1", "probe.label": "=N/A", "probe.nums.#": "2", "probe.nums[1].probe.val": "2",
           "@absent": ["probe.nums[0].probe.val"]})
vec(AJ, "to-xml-scalar-item-without-value-written-as-the-sentinel", AJ, AX, '{"id":"u3","nums":[1,null]}',
    '<msg id="u3" mark="N/A" t="optional" s="-"><pos alt="9999999"/><name>a&amp;b</name><list><v>1</v><v>-1</v></list></msg>')
vec(AJ, "to-geojson-ruling-10-coordinate-sentinels-write-the-geometry", AJ, AG, '{"id":"u5","lat":0}',
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[181,91,9999999]},"properties":{"name":""},"id":"u5"}',
    model={"uid": "u5", "@absent": ["lat"]})

# ==========================================================================
# conformance-absent-xml
# ==========================================================================
x1 = '<msg id="" mark="N/A" t="optional" s="-"><pos alt="9999999"/><name>a&amp;b</name><list><v>-1</v><v>4</v></list></msg>'
vec(AX, "every-field-holds-its-sentinel-roundtrip", AX, AX, x1, x1, model={
    "probe.nums.#": "2", "probe.nums[1].probe.val": "4",
    "@absent": ["uid", "probe.label", "probe.tag", "probe.s1", "hae", "callsign", "probe.nums[0].probe.val"]})
vec(AX, "text-compared-as-written-references-resolved", AX, AX,
    '<msg id="u1" mark="=N/A" t="Optional" s=" -"><pos alt="9999999.0"/><name>a&#38;b</name></msg>',
    '<msg id="u1" mark="=N/A" t="Optional" s=" -"><pos alt="9999999"/><name>a&amp;b</name></msg>',
    model={"uid": "u1", "probe.label": "=N/A", "probe.tag": "Optional", "probe.s1": " -", "hae": "9999999",
           "@absent": ["callsign", "probe.nums"]})
vec(AX, "ruling-7-missing-places-gain-the-sentinels", AX, AX, '<msg id="u2"/>',
    '<msg id="u2" mark="N/A" t="optional" s="-"><pos alt="9999999"/><name>a&amp;b</name></msg>',
    model={"uid": "u2", "@absent": ["probe.label", "probe.tag", "probe.s1", "hae", "callsign", "probe.nums"]})

# ==========================================================================
# conformance-absent-geojson
# ==========================================================================
g1 = '{"type":"Feature","geometry":{"type":"Point","coordinates":[181,91,9999999]},"properties":{"name":""},"id":""}'
vec(AG, "every-field-holds-its-sentinel-roundtrip", AG, AG, g1, g1, model={
    "@absent": ["uid", "callsign", "lon", "lat", "hae"]})
vec(AG, "coordinates-compared-by-canonical-text", AG, AG,
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[181.0,9.1e1,9999999.0]},"properties":{"name":"N"},"id":"u2"}',
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[181,91,9999999]},"properties":{"name":"N"},"id":"u2"}',
    model={"uid": "u2", "callsign": "N", "@absent": ["lon", "lat", "hae"]})
vec(AG, "null-geometry-gains-the-coordinate-sentinels", AG, AG,
    '{"type":"Feature","geometry":null,"properties":{},"id":"u7"}',
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[181,91,9999999]},"properties":{"name":""},"id":"u7"}',
    model={"uid": "u7", "@absent": ["lon", "lat", "hae", "callsign"]})
vec(AG, "two-coordinates-alt-sentinel-written-third", AG, AG,
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[1.5,2.5]},"properties":{"name":"N"},"id":"u8"}',
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[1.5,2.5,9999999]},"properties":{"name":"N"},"id":"u8"}',
    model={"lon": "1.5", "lat": "2.5", "@absent": ["hae"]})
vec(AG, "to-json-present-value-equal-to-a-sentinel-is-written", AG, AJ,
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[0,0,10]},"properties":{"name":"N"},"id":"u6"}',
    '{"id":"u6","alt":10,"lat":0,"label":"N/A","r":"N/A","code":"0","on":false,"cs":"N","a":0,"na":0,"s":"-","q":7}',
    model={"lat": "0", "lon": "0", "hae": "10", "callsign": "N"})

# ==========================================================================
# load vectors from 315
# ==========================================================================
MODELS = [
    "module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\nkey type string -\nkey lat float deg\nkey lon float deg\nkey callsign string -\nkey time_ms int ms\n",
    "module probe\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey label string -\nkey qty int -\nkey x int -\nkey y int -\nkey a float -\nlist items \"a list\"\nlist subs \"a nested list\"\n",
]
HEAD = 'format probe\nversion 0.9.0\ndistribution public\nsource "probe"\nuses probe\n'
BITS = HEAD + "wire bits\nword_bytes 1\n"
SEQB = HEAD + "wire bits\nlayout sequential\n"
PB = HEAD + "wire protobuf\n"
XML = HEAD + "wire xml\nroot msg\n"
JS = HEAD + "wire json\n"
lnum = [314]


def L(name, pack, error="bad-directive"):
    lnum[0] += 1
    full = "%d-absent-%s" % (lnum[0], name)
    d = {"name": full, "models": MODELS, "pack": pack}
    if error:
        d["expect_error"] = error
    with open(os.path.join(ROOT, "packs", "conformance", "load-vectors", full + ".json"), "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.write("\n")
    written["load"] = written.get("load", 0) + 1


L("with-no-argument", BITS + "field probe.x 0:0:8 uint absent\n")
L("given-twice", BITS + "field probe.x 0:0:8 uint absent 1 absent 2\n")
L("empty-value-in-the-list", BITS + "field probe.x 0:0:8 uint absent 1,,2\n")
L("value-too-wide-for-the-field", BITS + "field probe.x 0:0:8 uint absent 256\n")
L("negative-value-on-bits", BITS + "field probe.x 0:0:8 uint absent -1\n")
L("bits-field-longer-than-64-bits", BITS + "field callsign 0:0:72 ascii absent 0\n")
L("empty-text-on-pvarint", PB + 'field probe.x 1 pvarint absent ""\n')
L("empty-text-with-another-value", XML + 'field callsign @cs string absent "",0\n')
L("equals-sign-alone-on-xml", XML + "field callsign @cs string absent =\n")
L("null-on-json", JS + "field probe.a alt float absent null\n")
L("zero-on-json-bool", JS + "field probe.x on bool absent 0\n")
L("optional-on-xml-string-loads", XML + "field callsign @cs string absent optional\n", None)
L("empty-text-on-xml-string-loads", XML + 'field callsign @cs string absent ""\n', None)
L("equals-sign-alone-on-pstring-loads", PB + "field callsign 1 pstring absent =\n", None)
L("all-ones-on-a-64-bit-field-loads", BITS + "field probe.x 0:0:64 uint absent 18446744073709551615\n", None)
L("value-too-wide-for-pfloat", PB + "field probe.a 1 pfloat absent 4294967296\n")
L("value-too-wide-for-pvarint", PB + "field probe.x 1 pvarint absent 18446744073709551616\n")
L("empty-text-on-bits", BITS + 'field probe.x 0:0:8 uint absent ""\n')
L("value-too-wide-in-a-sequential-layout", SEQB + "field probe.x 4 uint absent 16\n")
L("number-text-and-string-on-json-loads", JS + "field probe.a alt float absent 9999999.0,N/A\n", None)
L("in-a-kind-and-a-group-loads", PB + "group probe.items 2\n  field probe.qty . pvarint absent 0\nend\n"
  "kind k\nwhen 3 present\nfield probe.y 3.1 psint absent 1\n", None)

for k in sorted(written):
    print("%-32s %d" % (k, written[k]))
