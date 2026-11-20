#!/usr/bin/env python3
"""Write the vectors of spec 0.43, the `cdr` wire: conversion vectors of the
packs `conformance-cdr` (XCDR 1, representation 0000) and `conformance-cdr2`
(XCDR 2, representation 0006), two geojson vectors (`cdr-NN-*`) and the load
vectors `wire-cdr-NN-*`.

Every byte is laid out by hand from the spec text ("# Version 0.43: the `cdr`
wire", rulings 1 to 20, and the sections they cite: 0.5 kinds and scales, 0.6
order inside `convert`, 0.7 groups, rulings 36 and 40 of 0.8, rulings 2, 4, 5
and 7 of 0.11). Nothing here computes an alignment: each layout below states
its padding bytes literally and asserts the offset it has reached after each
value (`at(n)`, offsets counted from the byte after the 4-byte header, RTPS
10.2). `check.py` in this directory is the second computation: it reads the
pack.def files, computes alignment, DHEADERs, kinds and transforms from the
rules, and re-reads every vector this script writes. Neither imports or calls
an engine.

Python 3 standard library only.

Usage: python3 -I tools/gen/cdr-vectors/gen.py [--out DIR] [--check]
                                               [--protobuf-source]
`--protobuf-source` also writes the vectors whose input is a
`conformance-groups-protobuf` message (the only loaded format that gives an
entity with `probe.gains` present and the scalar keys absent, which a context
then fills); they belong in packs/conformance-groups-protobuf/vectors/, outside
the directories this generator owns, so they are off by default.
"""
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import genio  # noqa: E402

C1 = "conformance-cdr"
C2 = "conformance-cdr2"
GJ = "geojson"
PB = "conformance-groups-protobuf"
MW, TD, TE, NK = "malformed-wire", "transform-decode", "transform-encode", "no-kind"

SRC = "constructed"


# --------------------------------------------------------------------------
# A byte buffer written by hand. Every pad is written by the caller; `at`
# states the offset the hand layout says has been reached.

class Buf:
    def __init__(self, ident, opts=b"\x00\x00", little=False):
        self.e = "<" if little else ">"
        self.head = bytes(ident) + bytes(opts)
        self.b = bytearray()

    def at(self, n):
        assert len(self.b) == n, "hand layout says offset %d, buffer is at %d" % (n, len(self.b))
        return self

    def pad(self, n, fill=0):
        self.b += bytes([fill]) * n
        return self

    def raw(self, data):
        self.b += data
        return self

    def put(self, fmt, v):
        self.b += struct.pack(self.e + fmt, v)
        return self

    def u8(self, v): return self.put("B", v)
    def u16(self, v): return self.put("H", v)
    def i16(self, v): return self.put("h", v)
    def u32(self, v): return self.put("I", v)
    def i32(self, v): return self.put("i", v)
    def u64(self, v): return self.put("Q", v)
    def i64(self, v): return self.put("q", v)
    def f32(self, v): return self.put("f", v)
    def f64(self, v): return self.put("d", v)

    def f64raw(self, hex8):            # 8 bytes given big-endian, written in the buffer's order
        d = bytes.fromhex(hex8)
        return self.raw(d if self.e == ">" else d[::-1])

    def f32raw(self, hex4):
        d = bytes.fromhex(hex4)
        return self.raw(d if self.e == ">" else d[::-1])

    def hex(self, trailing=b""):
        return (self.head + bytes(self.b) + trailing).hex()


ID1 = b"\x00\x00"        # conformance-cdr: representation 0000, big-endian
ID1LE = b"\x00\x01"
ID2 = b"\x00\x06"        # conformance-cdr2: representation 0006, big-endian
ID2LE = b"\x00\x07"

# lat through sscale:90/2147483647 (ruling 1 of 0.5: decode v*90/2147483647,
# encode x*2147483647/90 rounded half away from zero):
#   90  -> 90*2147483647 = 193273528230, /90 = 2147483647 exactly (7fffffff);
#          decode 2147483647*90 = 193273528230, /2147483647 = 90 exactly
#   -90 -> -2147483647 (80000001), and back to -90 exactly
#   0   -> 0
LAT90, LATM90 = 2147483647, -2147483647


# --------------------------------------------------------------------------
# Layout A: XCDR 1, kind plain (x = 1), uid "u1" (length 3), items
# [("ab", 2), ("c", 5)], nums [10, -20], gains [1.5, -0.25].
#   off 0  x uint8            01
#   off 1  1 pad byte (n is 2-aligned)
#   off 2  n int16 -2         fffe
#   off 4  y uint32 3e9       b2d05e00
#   off 8  z int64 -5         8-aligned under cdr 1 already: no pad
#   off 16 a float64 2.5      8-aligned already
#   off 24 uid: length 3, then 75 31 00         -> off 31
#   off 31 w bool 1                             -> off 32
#   off 32 c1 enum32 3; off 36 lat int32 7fffffff; off 40 const uint16 7 -> off 42
#   off 42 2 pad bytes; off 44 items count 2 (uint32)
#   off 48 label "ab": length 3, 61 62 00      -> off 55
#   off 55 1 pad byte; off 56 qty uint16 2     -> off 58
#   off 58 2 pad bytes; off 60 label "c": length 2, 63 00 -> off 66
#   off 66 qty 5 (2-aligned already)           -> off 68
#   off 68 nums count 2; 72 val 10; 76 val -20 -> off 80
#   off 80 gains 1.5 (3fc00000); 84 -0.25 (be800000) -> off 88
#   88 is a multiple of 4: no trailing padding, p = 0.

def layout_a(little=False, ident=ID1, opts=b"\x00\x00", x=1, w=1, a=None, const=7,
             pads=(0, 0, 0, 0), nums_count=2, c1=3):
    p = pads
    b = Buf(ident, opts, little)
    b.at(0).u8(x).pad(1, p[0]).at(2).i16(-2).at(4).u32(3000000000).at(8).i64(-5).at(16)
    if a is None:
        b.f64(2.5)
    else:
        b.f64raw(a)
    b.at(24).u32(3).raw(b"u1\x00").at(31).u8(w).at(32).i32(c1).at(36).i32(LAT90).at(40)
    b.u16(const).at(42).pad(2, p[1]).at(44).u32(2)
    b.at(48).u32(3).raw(b"ab\x00").at(55).pad(1, p[2]).at(56).u16(2).at(58)
    b.pad(2, p[3]).at(60).u32(2).raw(b"c\x00").at(66).u16(5).at(68)
    b.u32(nums_count).at(72).i32(10).at(76).i32(-20).at(80)
    b.f32(1.5).at(84).f32(-0.25).at(88)
    return b


MODEL_A = {
    "@kind": "plain",
    "probe.x": "1", "probe.n": "-2", "probe.y": "3000000000", "probe.z": "-5", "probe.a": "2.5",
    "uid": "u1", "probe.w": "1", "probe.c1": "3", "lat": "90",
    "probe.items.#": "2",
    "probe.items[0].probe.label": "ab", "probe.items[0].probe.qty": "2",
    "probe.items[1].probe.label": "c", "probe.items[1].probe.qty": "5",
    "probe.nums.#": "2", "probe.nums[0].probe.val": "10", "probe.nums[1].probe.val": "-20",
    "probe.gains.#": "2", "probe.gains[0].probe.ratio": "1.5", "probe.gains[1].probe.ratio": "-0.25",
    "@absent": ["probe.c2"],
}


# Layout B: the entity of layout A under XCDR 2. Up to off 42 as A (z and a
# are 4-aligned under cdr 2, and 8 and 16 are multiples of 4: no pad).
#   off 42 2 pad bytes; off 44 DHEADER of items (ruling 8: the body is a
#          string and a uint16, not one primitive field)
#   off 48 count 2 (the DHEADER counts from here, ruling 9)
#   off 52 label "ab": length 3, 61 62 00      -> off 59
#   off 59 1 pad byte; off 60 qty 2            -> off 62
#   off 62 2 pad bytes; off 64 label "c": length 2, 63 00 -> off 70
#   off 70 qty 5                               -> off 72
#   DHEADER = 72 - 48 = 24 (0x18)
#   off 72 nums count 2, no DHEADER (one int32 field: primitive, ruling 8)
#   off 76 val 10; 80 val -20; off 84 gains 1.5, 88 -0.25 -> off 92, p = 0.

def layout_b(little=False, ident=ID2, dheader=24, cut=None):
    b = Buf(ident, b"\x00\x00", little)
    b.at(0).u8(1).pad(1).at(2).i16(-2).at(4).u32(3000000000).at(8).i64(-5).at(16).f64(2.5)
    b.at(24).u32(3).raw(b"u1\x00").at(31).u8(1).at(32).i32(3).at(36).i32(LAT90).at(40)
    b.u16(7).at(42).pad(2).at(44).u32(dheader).at(48).u32(2)
    b.at(52).u32(3).raw(b"ab\x00").at(59).pad(1).at(60).u16(2).at(62)
    b.pad(2).at(64).u32(2).raw(b"c\x00").at(70).u16(5).at(72)
    b.u32(2).at(76).i32(10).at(80).i32(-20).at(84).f32(1.5).at(88).f32(-0.25).at(92)
    return b


# Layout C: XCDR 1, kind other (x = 2), items [], nums [], c2 uint64.
#   off 0..42 as A but a = -0.125, c1 = -1 (enum32 is signed: ffffffff),
#   lat = -90 (80000001)
#   off 42 2 pad bytes; off 44 items count 0; off 48 nums count 0
#   off 52 gains 1.5, 56 -0.25 -> off 60
#   off 60 c2 uint64: align 8 under cdr 1, 60 is 4 mod 8 -> 4 pad bytes
#   off 64 c2 7fffffffffffffff (2^63-1, the largest uint64 the model holds)
#   -> off 72, p = 0.

def layout_c(c2=0x7FFFFFFFFFFFFFFF):
    b = Buf(ID1)
    b.at(0).u8(2).pad(1).at(2).i16(-2).at(4).u32(3000000000).at(8).i64(-5).at(16).f64(-0.125)
    b.at(24).u32(3).raw(b"u1\x00").at(31).u8(0).at(32).i32(-1).at(36).i32(LATM90).at(40)
    b.u16(7).at(42).pad(2).at(44).u32(0).at(48).u32(0).at(52)
    b.f32(1.5).at(56).f32(-0.25).at(60).pad(4).at(64).u64(c2).at(72)
    return b


MODEL_C = {
    "@kind": "other",
    "probe.x": "2", "probe.a": "-0.125", "probe.w": "0", "probe.c1": "-1", "lat": "-90",
    "probe.items.#": "0", "probe.nums.#": "0", "probe.gains.#": "2",
    "probe.c2": "9223372036854775807",
}


# Layout D: XCDR 2, kind other, items [], nums [7], c2 uint64.
#   off 0..42 as C
#   off 42 2 pad bytes; off 44 DHEADER 4 (the count alone); off 48 count 0
#   off 52 nums count 1; off 56 val 7 -> off 60
#   off 60 gains 1.5, 64 -0.25 -> off 68
#   off 68 c2 uint64: align 4 under cdr 2, 68 is 4 mod 8 and needs no pad
#   -> off 76, p = 0.

def layout_d():
    b = Buf(ID2)
    b.at(0).u8(2).pad(1).at(2).i16(-2).at(4).u32(3000000000).at(8).i64(-5).at(16).f64(-0.125)
    b.at(24).u32(3).raw(b"u1\x00").at(31).u8(0).at(32).i32(-1).at(36).i32(LATM90).at(40)
    b.u16(7).at(42).pad(2).at(44).u32(4).at(48).u32(0).at(52).u32(1).at(56).i32(7).at(60)
    b.f32(1.5).at(64).f32(-0.25).at(68).u64(0x7FFFFFFFFFFFFFFF).at(76)
    return b


# Layout E: XCDR 2, kind plain, the scalars of C with x = 1, items [] and
# nums [] (both present and empty), gains [1.5, -0.25].
#   off 42 2 pad bytes; off 44 DHEADER 4; off 48 count 0; off 52 nums count 0
#   off 56 gains 1.5, 60 -0.25 -> off 64, p = 0.

def layout_e():
    b = Buf(ID2)
    b.at(0).u8(1).pad(1).at(2).i16(-2).at(4).u32(3000000000).at(8).i64(-5).at(16).f64(-0.125)
    b.at(24).u32(3).raw(b"u1\x00").at(31).u8(0).at(32).i32(-1).at(36).i32(LATM90).at(40)
    b.u16(7).at(42).pad(2).at(44).u32(4).at(48).u32(0).at(52).u32(0).at(56)
    b.f32(1.5).at(60).f32(-0.25).at(64)
    return b


# Layout F: XCDR 1, kind plain, uid of 3 bytes given raw (with or without its
# NUL), items [] and nums [], lat 0, gains [1.5, -0.25].
#   off 24 length 3, the 3 bytes -> off 31; w -> 32; c1 0 -> 36; lat 0 -> 40;
#   const -> 42; 2 pad bytes; off 44 items count 0; off 48 nums count 0;
#   off 52 gains -> off 60, p = 0.

def layout_f(uid3=b"u1\x00", w=1, c1=0):
    assert len(uid3) == 3
    b = Buf(ID1)
    b.at(0).u8(1).pad(1).at(2).i16(0).at(4).u32(0).at(8).i64(0).at(16).f64(0.0)
    b.at(24).u32(3).raw(uid3).at(31).u8(w).at(32).i32(c1).at(36).i32(0).at(40)
    b.u16(7).at(42).pad(2).at(44).u32(0).at(48).u32(0).at(52)
    b.f32(1.5).at(56).f32(-0.25).at(60)
    return b


# Layout G4: as F but the uid length is 4, bytes 61 00 62 00 ("a", NUL, "b", NUL).
#   off 24 length 4, 4 bytes -> off 32; w -> off 33; 3 pad bytes; c1 at 36;
#   lat at 40; const at 44 -> 46; 2 pad bytes; items count at 48; nums
#   count at 52; gains at 56 and 60 -> off 64.

def layout_g4():
    b = Buf(ID1)
    b.at(0).u8(1).pad(1).at(2).i16(0).at(4).u32(0).at(8).i64(0).at(16).f64(0.0)
    b.at(24).u32(4).raw(b"a\x00b\x00").at(32).u8(1).at(33).pad(3).at(36).i32(0).at(40).i32(0).at(44)
    b.u16(7).at(46).pad(2).at(48).u32(0).at(52).u32(0).at(56).f32(1.5).at(60).f32(-0.25).at(64)
    return b


# Layout G2: as F but the uid length is 2, bytes ff 00 (ff is not UTF-8).
#   off 24 length 2 -> off 30; w -> 31; 1 pad byte; c1 at 32; lat at 36;
#   const at 40 -> 42; 2 pad bytes; counts at 44 and 48; gains -> off 60.

def layout_g2():
    b = Buf(ID1)
    b.at(0).u8(1).pad(1).at(2).i16(0).at(4).u32(0).at(8).i64(0).at(16).f64(0.0)
    b.at(24).u32(2).raw(b"\xff\x00").at(30).u8(1).at(31).pad(1).at(32).i32(0).at(36).i32(0).at(40)
    b.u16(7).at(42).pad(2).at(44).u32(0).at(48).u32(0).at(52).f32(1.5).at(56).f32(-0.25).at(60)
    return b


# Layout G0: as F but the uid length is 0 (no bytes, not even the NUL).
#   off 24 length 0 -> off 28; w -> 29; 3 pad bytes; c1 at 32; lat at 36;
#   const at 40 -> 42; 2 pad bytes; counts at 44 and 48; gains -> off 60.

def layout_g0():
    b = Buf(ID1)
    b.at(0).u8(1).pad(1).at(2).i16(0).at(4).u32(0).at(8).i64(0).at(16).f64(0.0)
    b.at(24).u32(0).at(28).u8(1).at(29).pad(3).at(32).i32(0).at(36).i32(0).at(40)
    b.u16(7).at(42).pad(2).at(44).u32(0).at(48).u32(0).at(52).f32(1.5).at(56).f32(-0.25).at(60)
    return b


# --------------------------------------------------------------------------
# The vectors.

def build_vectors():
    V = []          # (directory, file stem, dict)

    def vec(dirpack, num, name, frm, to, inp, expect=None, error=None, model=None, ref="",
            context=None, max_items=None, prefix=""):
        d = {"name": prefix + name, "from": frm, "to": to, "input": inp}
        if error is None:
            d["expect"] = expect
        else:
            d["expect_error"] = error
        if model:
            d["model"] = model
        if context is not None:
            d["context"] = context
        if max_items is not None:
            d["max_items"] = max_items
        d["source"] = SRC
        d["reference"] = ref
        V.append((dirpack, "%s%02d-%s" % (prefix, num, name), d))

    A = layout_a().hex()
    B = layout_b().hex()

    # ---- round trips, both versions, every type ----
    vec(C1, 1, "roundtrip-every-type", C1, C1, A, A, model=MODEL_A,
        ref="0.43 Types and Groups: uint8, int16, uint32 (3e9 with the top bit set reads unsigned), int64, "
            "float64, string, bool, enum32, int32 through sscale:90/2147483647 (7fffffff is 90 exactly), "
            "a const uint16, a seq of a struct, a seq of int32 and array:2 of float32, big-endian (0000); "
            "hand layout A in gen.py")
    vec(C2, 1, "roundtrip-every-type", C2, C2, B, B, model=MODEL_A,
        ref="0.43 rulings 8 and 9: under cdr 2 the seq of a struct takes a DHEADER at off 44 holding 24, "
            "the bytes from the count at off 48 through the last qty ending at off 72; the seq of int32 and "
            "the array of float32 take none; hand layout B in gen.py")

    # ---- byte order (ruling 19) ----
    vec(C1, 2, "little-endian-input-written-big-endian", C1, C1,
        layout_a(little=True, ident=ID1LE).hex(), A, model=MODEL_A,
        ref="0.43 The header and ruling 19: identifier 0001 has its low bit set, every multi-byte value is "
            "little-endian; encode writes representation 0000, big-endian")
    vec(C2, 2, "little-endian-input-written-big-endian", C2, C2,
        layout_b(little=True, ident=ID2LE).hex(), B, model=MODEL_A,
        ref="0.43 The header and ruling 19: 0007 is 0006 with the byte-order bit set, so it decodes, the "
            "DHEADER and counts little-endian too; encode writes 0006 and big-endian")

    # ---- kinds and the alignment of uint64 (ruling 3, Types) ----
    C = layout_c().hex()
    vec(C1, 3, "kind-other-uint64-after-four-pad-bytes", C1, C1, C, C, model=MODEL_C,
        ref="0.43 ruling 3 (when 1 2 reads probe.x) and Types (uint64 aligns to 8 under cdr 1): gains end "
            "at off 60, so 4 pad bytes stand before c2 at off 64; c2 = 2^63-1 is the largest uint64 that decodes")
    D = layout_d().hex()
    model_d = dict(MODEL_C)
    model_d.update({"probe.nums.#": "1", "probe.nums[0].probe.val": "7"})
    vec(C2, 3, "kind-other-uint64-at-four-mod-eight-no-pad", C2, C2, D, D, model=model_d,
        ref="0.43 Types (uint64 aligns to 4 under cdr 2): gains end at off 68, 4 mod 8, and c2 follows with "
            "no pad; the empty items still take a DHEADER of 4 (the count alone, ruling 9)")
    vec(C1, 4, "kind-other-to-cdr2-selects-plain-and-writes-x-1", C1, C2, C, layout_e().hex(),
        model={"@kind": "other", "probe.x": "2", "probe.c2": "9223372036854775807"},
        ref="0.5 Encode and 0.6 Order inside convert: a cross-format convert clears Entity.kind; the target's "
            "first kind with no requires, plain, is selected; 0.43 ruling 3 writes its when value 1 over "
            "probe.x, and c2, mapped only in kind other, is not written; items and nums are present and empty "
            "(count 0, ruling 6); hand layout E")
    vec(C1, 5, "x-3-selects-no-kind", C1, C1, layout_a(x=3).hex(), error=NK,
        ref="0.43 ruling 3 and 0.5 Decode step 2: probe.x = 3 matches neither when 1 1 nor when 1 2")

    vec(C1, 32, "x-3-and-four-trailing-bytes-is-structural", C1, C1, layout_a(x=3).hex(b"\x00" * 4), error=MW,
        ref="0.43 ruling 25: with x = 3 no kind holds, and no kind line is read, so 4 bytes remain after the "
            "common lines (step 2); the structural check ranks above no-kind")

    # ---- cross-version ----
    vec(C1, 6, "to-cdr2-adds-the-dheader", C1, C2, A, B, model=MODEL_A,
        ref="0.43 rulings 8 and 9: the same entity written under cdr 2 gains the DHEADER 24 before the items "
            "count and shifts the item fields by 4 (layout B)")
    vec(C2, 4, "to-cdr1-drops-the-dheader", C2, C1, B, A, model=MODEL_A,
        ref="0.43 Groups: only cdr 2 writes a DHEADER; layout B read, layout A written")

    # ---- counts (ruling 6) ----
    E = layout_e().hex()
    vec(C2, 5, "count-0-present-empty-lists", C2, C2, E, E,
        model={"@kind": "plain", "probe.items.#": "0", "probe.nums.#": "0", "probe.gains.#": "2",
               "lat": "-90", "probe.c1": "-1"},
        ref="0.43 ruling 6: a count of 0 decodes as a present, empty list; written back as a count of 0, "
            "after a DHEADER of 4 for items (ruling 9)")

    # ---- const (ruling 12) ----
    vec(C1, 7, "const-not-checked-on-decode-written-on-encode", C1, C1, layout_a(const=0x63).hex(), A,
        model=MODEL_A,
        ref="0.43 ruling 12: the const uint16 at off 40 holds 0063 on input and is not checked; encode "
            "writes 7 (0007)")

    # ---- padding and the header options ----
    vec(C1, 8, "alignment-padding-not-zero-is-skipped", C1, C1,
        layout_a(pads=(0xFF, 0xEE, 0xDD, 0xCC)).hex(), A, model=MODEL_A,
        ref="0.43 Types: the reader skips alignment bytes whatever they hold (ff at off 1, eeee at off 42, "
            "dd at off 55, cccc at off 58); the writer adds zero bytes")
    vec(C1, 9, "options-p-not-read", C1, C1, layout_a(opts=b"\x00\x02").hex(), A, model=MODEL_A,
        ref="0.43 ruling 5: decode never reads p; the body ends at off 88, a multiple of 4, so encode writes "
            "options 0000")
    vec(C1, 10, "three-trailing-zero-bytes-accepted", C1, C1,
        layout_a(opts=b"\x00\x03").hex(b"\x00\x00\x00"), A, model=MODEL_A,
        ref="0.43 Reading and writing step 2 and ruling 20: three zero bytes after a body of 88 bytes are "
            "accepted; output has no trailing bytes and p = 0")

    # ---- hex text (ruling 17) ----
    up = A.upper()
    spaced = up[:8] + " " + up[8:40] + "\t" + up[40:100] + "\n" + up[100:] + "\r\n"
    vec(C1, 11, "hex-whitespace-and-capitals", C1, C1, spaced, A,
        ref="0.43 ruling 17 and ruling 40 of 0.8: space, tab, line feed and carriage return are skipped, "
            "capital hex digits read; output is lowercase")
    vec(C1, 12, "hex-odd-digit-count", C1, C1, A[:-1], error=MW,
        ref="0.43 ruling 17 and ruling 36 of 0.8: an odd number of hex digits")

    # ---- malformed-wire ----
    vec(C1, 13, "shorter-than-the-header", C1, C1, "000000", error=MW,
        ref="0.43 ruling 18: 3 bytes")
    vec(C1, 14, "identifier-first-byte-wrong", C1, C1, layout_a(ident=b"\x01\x00").hex(), error=MW,
        ref="0.43 The header: the identifier's first byte 01 is not that of representation 0000")
    vec(C2, 6, "identifier-of-cdr1-refused", C2, C2, layout_b(ident=ID1).hex(), error=MW,
        ref="0.43 The header: the second byte 00 without its low bit is not 06, the second byte of "
            "representation 0006 without its low bit")
    vec(C1, 15, "input-ends-inside-int64", C1, C1, A[:2 * (4 + 12)], error=MW,
        ref="0.43 Reading and writing step 1 and ruling 3: the input ends at off 12, inside z (off 8 to 16), "
            "a common line")
    vec(C1, 16, "input-ends-inside-a-count", C1, C1, A[:2 * (4 + 70)], error=MW,
        ref="0.43 Reading and writing step 1: the input ends at off 70, inside the nums count (off 68 to 72)")
    vec(C2, 7, "input-ends-inside-a-dheader", C2, C2, B[:2 * (4 + 46)], error=MW,
        ref="0.43 Reading and writing step 1: the input ends at off 46, inside the DHEADER (off 44 to 48)")
    vec(C2, 8, "dheader-that-lies", C2, C2, layout_b(dheader=28).hex(), error=MW,
        ref="0.43 Groups: the DHEADER holds 28, the collection takes 24 bytes (off 48 to 72)")
    vec(C1, 17, "four-trailing-zero-bytes", C1, C1, layout_a().hex(b"\x00" * 4), error=MW,
        ref="0.43 Reading and writing step 2: at most 3 bytes may remain")
    vec(C1, 18, "trailing-byte-not-zero", C1, C1, layout_a().hex(b"\x01"), error=MW,
        ref="0.43 Reading and writing step 2: a remaining byte must be zero")
    vec(C1, 19, "count-larger-than-the-bytes-left", C1, C1, layout_a(nums_count=0x7FFFFFFF).hex(), error=MW,
        ref="0.43 Reading and writing step 4: the nums count 2147483647 at off 68 leaves 16 bytes, fewer "
            "than one per element")
    vec(C1, 20, "string-length-zero", C1, C1, layout_g0().hex(), error=MW,
        ref="0.43 Strings: a length of 0 (at off 24) is below 1")
    vec(C1, 21, "string-without-its-nul", C1, C1, layout_f(uid3=b"u1x").hex(), error=MW,
        ref="0.43 Strings: the uid's last byte (off 30) is 78, not 0")

    # ---- transform-decode ----
    vec(C1, 22, "bool-2", C1, C1, layout_a(w=2).hex(), error=TD,
        ref="0.43 Types: bool decodes 0 or 1; 2 at off 31 is transform-decode")
    vec(C1, 23, "float64-nan", C1, C1, layout_a(a="7ff8000000000000").hex(), error=TD,
        ref="0.43 ruling 7: a NaN read from the wire (probe.a at off 16)")
    vec(C1, 24, "string-with-a-nul-inside", C1, C1, layout_g4().hex(), error=TD,
        ref="0.43 Strings: length 4, bytes 61 00 62 00; the NUL at off 29 is before the last byte")
    vec(C1, 25, "string-not-utf-8", C1, C1, layout_g2().hex(), error=TD,
        ref="0.43 Strings: length 2, bytes ff 00; ff is not UTF-8")
    vec(C1, 26, "uint64-above-2-63-minus-1", C1, C1, layout_c(c2=0x8000000000000000).hex(), error=TD,
        ref="0.43 Types: uint64 8000000000000000 (2^63) at off 64 is above 2^63-1")

    # ---- ruling 11: structural before transform ----
    vec(C1, 27, "bool-2-and-four-trailing-bytes-is-structural", C1, C1,
        layout_a(w=2).hex(b"\x00" * 4), error=MW,
        ref="0.43 ruling 11: the four trailing bytes (step 2) win over the transform-decode of bool 2 at off 31, "
            "a line read before them")
    vec(C1, 28, "bool-2-and-a-count-too-large-is-structural", C1, C1,
        layout_a(w=2, nums_count=0x7FFFFFFF).hex(), error=MW,
        ref="0.43 ruling 11 and step 4: the nums count 2147483647 wins over bool 2 read before it")

    # ---- item limit (step 4, ruling 7 of 0.11) ----
    vec(C1, 29, "item-limit-6-holds-the-array-elements", C1, C1, A, A, max_items=6, model=MODEL_A,
        ref="0.43 Reading and writing step 4 and ruling 7 of 0.11: 2 items + 2 nums + 2 gains = 6 items")
    vec(C1, 30, "item-limit-5-refused-at-the-array", C1, C1, A, error=MW, max_items=5,
        ref="0.43 Reading and writing step 4 and ruling 7a of 0.11: the array's two elements count, so the "
            "sixth item goes over a limit of 5")

    # ---- to geojson ----
    vec(C1, 31, "to-geojson", C1, GJ, A,
        '{"type":"Feature","geometry":null,"properties":{},"id":"u1"}',
        model={"uid": "u1", "lat": "90"},
        ref="geojson pack: uid is id, lat is geometry.lat; lon is absent, so geometry is null (ruling 5 of "
            "0.1.1) and lat is not written; no probe key is mapped by geojson")

    # ---- geojson to cdr (prefix cdr-) ----
    gin = '{"type":"Feature","geometry":{"type":"Point","coordinates":[10,30]},"properties":{},"id":"g1"}'
    vec(GJ, 1, "to-conformance-cdr-absent-array-is-transform-encode", GJ, C1, gin, error=TE,
        model={"uid": "g1", "lat": "30", "lon": "10"}, prefix="cdr-",
        ref="0.43 Reading and writing step 3: the entity has no probe.gains, and an absent array:2 list is "
            "transform-encode; every other line encodes (absent keys write zero bits, absent seqs a count of 0)")
    vec(GJ, 2, "to-conformance-cdr2-absent-array-is-transform-encode", GJ, C2, gin, error=TE, prefix="cdr-",
        ref="0.43 Reading and writing step 3, as for conformance-cdr")
    V += build_tail()
    return V


# --------------------------------------------------------------------------
# conformance-cdr-tail: cdr 1, representation 0001 (encode writes
# little-endian, identifier 0001), no group, no kind, `default probe.n 5`.
# Lines: y uint32, n int16, uid string, x uint8.
#   off 0 y; off 4 n; off 6 2 pad bytes; off 8 uid length; off 12 uid bytes;
#   x right after them (align 1). p = the bytes from the end of x to a
#   multiple of 4.

CT = "conformance-cdr-tail"


def layout_tail(uid, y, n, x, little=True, p=None, ident=None):
    """uid given with its NUL. The offsets are stated per uid length below."""
    ln = len(uid)
    end = 12 + ln + 1                      # x is the last byte
    pp = (-end) % 4 if p is None else p
    b = Buf(ident or (b"\x00\x01" if little else b"\x00\x00"), bytes([0, pp]), little)
    b.at(0).u32(y).at(4).i16(n).at(6).pad(2).at(8).u32(ln).at(12).raw(uid).at(12 + ln).u8(x).at(end)
    return b, end, pp


def build_tail():
    V = []

    def vec(dirpack, num, name, frm, to, inp, expect=None, error=None, model=None, context=None, ref="",
            prefix=""):
        d = {"name": prefix + name, "from": frm, "to": to, "input": inp}
        if error is None:
            d["expect"] = expect
        else:
            d["expect_error"] = error
        if model:
            d["model"] = model
        if context is not None:
            d["context"] = context
        d["source"] = SRC
        d["reference"] = ref
        V.append((dirpack, "%s%02d-%s" % (prefix, num, name), d))

    # uid "abc" (length 4): bytes off 12..16, x at 16 -> body 17 bytes, p = 3
    b, end, p = layout_tail(b"abc\x00", 7, -300, 200)
    assert (end, p) == (17, 3)
    t3 = b.hex(b"\x00" * 3)
    vec(CT, 1, "roundtrip-p-3-little-endian", CT, CT, t3, t3,
        model={"probe.y": "7", "probe.n": "-300", "uid": "abc", "probe.x": "200"},
        ref="0.43 The header and ruling 5: representation 0001 writes little-endian; the body is 17 bytes "
            "(x is the byte at off 16), so 3 zero bytes follow and the options are 0003")
    # uid "u" (length 2): x at 14 -> 15 bytes, p = 1
    b, end, p = layout_tail(b"u\x00", 4294967295, 32767, 0)
    assert (end, p) == (15, 1)
    t1 = b.hex(b"\x00")
    vec(CT, 2, "roundtrip-p-1-range-ends", CT, CT, t1, t1,
        model={"probe.y": "4294967295", "probe.n": "32767", "uid": "u", "probe.x": "0"},
        ref="0.43 ruling 5: body 15 bytes, p = 1; uint32 ffffffff and int16 7fff read little-endian")
    # the same entity sent big-endian (identifier 0000): decodes, written little-endian
    bb, _, _ = layout_tail(b"u\x00", 4294967295, 32767, 0, little=False, p=0)
    vec(CT, 3, "big-endian-input-written-little-endian", CT, CT, bb.hex(b"\x00"), t1,
        ref="0.43 The header and ruling 19: 0000 is 0001 without the byte-order bit, so it decodes big-endian; "
            "encode writes 0001, little-endian, and its own p = 1 (the input said 0)")
    # p of the input not read: uid "" (length 1): x at 13 -> 14 bytes, p = 2
    b, end, p = layout_tail(b"\x00", 1, 1, 1)
    assert (end, p) == (14, 2)
    t2 = b.hex(b"\x00\x00")
    bad_p, _, _ = layout_tail(b"\x00", 1, 1, 1, p=0)
    vec(CT, 4, "p-of-the-input-not-read", CT, CT, bad_p.hex(b"\x00\x00"), t2,
        model={"uid": ""},
        ref="0.43 ruling 5: the input states p = 0 with 2 trailing zero bytes; decode never reads p, encode "
            "writes 2 (body 14 bytes, the empty uid is length 1 and one NUL)")

    # geojson -> tail. Entity: uid g1, lat 30, lon 10; no probe key.
    gin = '{"type":"Feature","geometry":{"type":"Point","coordinates":[10,30]},"properties":{},"id":"g1"}'
    gnoid = '{"type":"Feature","geometry":{"type":"Point","coordinates":[10,30]},"properties":{}}'
    # y absent 0; n absent, default 5 (ruling 16); uid "g1" length 3, off 12..15;
    # x absent 0 at off 15 -> body 16, p = 0
    b, end, p = layout_tail(b"g1\x00", 0, 5, 0)
    assert (end, p) == (16, 0)
    vec(GJ, 3, "to-conformance-cdr-tail-default-written", GJ, CT, gin, b.hex(), prefix="cdr-",
        ref="0.43 ruling 16: probe.n is absent and default probe.n 5 applies, so 5 is written, not zero bits; "
            "y and x are absent and write zero bits (step 3); little-endian, representation 0001")
    b, _, _ = layout_tail(b"g1\x00", 0, -3, 0)
    vec(GJ, 4, "to-conformance-cdr-tail-context-before-default", GJ, CT, gin, b.hex(), context={"probe.n": "-3"},
        prefix="cdr-",
        ref="0.6 Order inside convert: the context fills probe.n (step 2) before encode looks for a default "
            "(step 4), so -3 (fdff) is written")
    vec(GJ, 5, "to-conformance-cdr-tail-context-uint8-300", GJ, CT, gin, error=TE, context={"probe.x": "300"},
        prefix="cdr-", ref="0.43 ruling 7: uint8 takes 0 to 255")
    vec(GJ, 6, "to-conformance-cdr-tail-context-int16-32768", GJ, CT, gin, error=TE, context={"probe.n": "32768"},
        prefix="cdr-", ref="0.43 ruling 7: int16 takes -32768 to 32767; the context value is used, not the default")
    vec(GJ, 7, "to-conformance-cdr-tail-context-string-with-u0000", GJ, CT, gnoid, error=TE,
        context={"uid": "a\u0000b"}, prefix="cdr-",
        ref="0.43 ruling 7: a string holding U+0000 is transform-encode (the input has no id, so the context "
            "supplies uid)")
    return V


# --------------------------------------------------------------------------
# Vectors with a conformance-groups-protobuf input (written only with
# --protobuf-source). Input: uid (field 1) when stated, then probe.gains as
# two unpacked fixed32 occurrences of field 7 (tag 3d): 1.5 is 0000c03f and
# -0.25 is 000080be, little-endian. items and nums are absent.
#
# Expected conformance-cdr output with context c1 = -7 (layout P):
#   x: when 1 1 writes 1; n, y, z, a absent: zero bits; uid "u1" length 3
#   (or the context's); w absent 0; c1 -7 (fffffff9); lat absent 0; const 7;
#   items absent: count 0 (ruling 6); nums absent: count 0; gains 1.5, -0.25.
#   Offsets as layout F: off 44 items count, off 48 nums count, gains to off 60.

def pb_input(uid=b"u1"):
    out = b""
    if uid is not None:
        out += b"\x0a" + bytes([len(uid)]) + uid
    out += b"\x3d" + struct.pack("<f", 1.5) + b"\x3d" + struct.pack("<f", -0.25)
    return out.hex()


def layout_p(c1):
    b = Buf(ID1)
    b.at(0).u8(1).pad(1).at(2).i16(0).at(4).u32(0).at(8).i64(0).at(16).f64(0.0)
    b.at(24).u32(3).raw(b"u1\x00").at(31).u8(0).at(32).i32(c1).at(36).i32(0).at(40)
    b.u16(7).at(42).pad(2).at(44).u32(0).at(48).u32(0).at(52).f32(1.5).at(56).f32(-0.25).at(60)
    return b


def build_protobuf_source():
    V = []

    def vec(num, name, inp, context, expect=None, error=None, ref=""):
        d = {"name": "cdr-%02d-%s" % (num, name), "from": PB, "to": C1, "input": inp}
        if error is None:
            d["expect"] = expect
        else:
            d["expect_error"] = error
        d["context"] = context
        d["source"] = SRC
        d["reference"] = ref
        V.append((PB, "cdr-%02d-%s" % (num, name), d))

    vec(1, "to-conformance-cdr-absent-seqs-write-count-0", pb_input(), {"probe.c1": "-7"},
        expect=layout_p(-7).hex(),
        ref="0.43 ruling 6: absent seqs write a count of 0; ruling 3: when 1 1 writes probe.x = 1; Reading and "
            "writing step 3: absent keys write zero bits; enum32 -7 is fffffff9")
    vec(2, "context-enum32-2-31-is-transform-encode", pb_input(), {"probe.c1": "2147483648"}, error=TE,
        ref="0.43 ruling 7: enum32 is signed; 2^31 is outside it")
    vec(3, "context-int16-32768-is-transform-encode", pb_input(), {"probe.n": "32768"}, error=TE,
        ref="0.43 ruling 7: int16 takes -32768 to 32767")
    vec(4, "context-uint32-minus-1-is-transform-encode", pb_input(), {"probe.y": "-1"}, error=TE,
        ref="0.43 ruling 7: uint32 takes 0 to 2^32-1")
    vec(5, "context-bool-2-is-transform-encode", pb_input(), {"probe.w": "2"}, error=TE,
        ref="0.43 ruling 7: bool takes 0 and 1 only")
    vec(6, "context-string-with-u0000-is-transform-encode", pb_input(uid=None), {"uid": "a\u0000b"}, error=TE,
        ref="0.43 ruling 7: a string holding U+0000 is transform-encode")
    return V


# --------------------------------------------------------------------------
# Load vectors.

CORE = ('module core\nversion 0.1.0\ndistribution public\nsource "probe"\n'
        'key uid string -\nkey lat float deg\n')
PROBE = ('module probe\nversion 0.1.0\ndistribution public\nsource "probe"\n'
         'key x int -\nkey n int -\nkey a float -\nkey label string -\nkey qty int -\nkey val int -\n'
         'list items "a list"\nlist nums "a list"\n')
HEAD = 'format probe-cdr\nversion 0.43.0\ndistribution public\nsource "probe"\nuses probe\n'
WIRE = 'wire cdr\ncdr 1\nrepresentation 0000\n'


def build_loads():
    L = []

    def lv(num, name, pack, error=None, ref=""):
        full = "wire-cdr-%02d-%s" % (num, name)
        d = {"name": full, "models": [CORE, PROBE], "pack": pack}
        if error:
            d["expect_error"] = error
        # `ref` is the derivation; load vectors carry no `reference` member
        # (spec/vector-format.md, Load vectors), so it stays in this source.
        L.append((full, d))

    BAD, UD, UT = "bad-directive", "unknown-directive", "unknown-transform"

    # ruling 10
    lv(1, "cdr-and-representation-before-wire-load",
       HEAD + 'cdr 2\nrepresentation 0006\nwire cdr\nfield probe.x uint8\n',
       ref="0.43 ruling 10: cdr and representation may stand before wire")
    lv(2, "missing-cdr-line", HEAD + 'wire cdr\nrepresentation 0000\nfield probe.x uint8\n', BAD,
       ref="0.43 ruling 10: a missing cdr is bad-directive after the file")
    lv(3, "missing-cdr-line-then-bogus", HEAD + 'wire cdr\nrepresentation 0000\nfield probe.x uint8\nbogus\n', UD,
       ref="0.43 ruling 10: the missing cdr is found after the file, so the line check of bogus wins")
    lv(4, "missing-representation-and-missing-format",
       'version 0.43.0\ndistribution public\nsource "probe"\nuses probe\nwire cdr\ncdr 1\nfield probe.x uint8\n',
       "missing-format",
       ref="ruling 5b of 0.11: after the file missing-format comes before the checks that need the whole file; "
           "0.43 ruling 10 puts the missing representation among those")
    lv(5, "representation-in-capitals", HEAD + 'wire cdr\ncdr 1\nrepresentation 00A6\nfield probe.x uint8\n', BAD,
       ref="0.43 ruling 10: <hex> is four lowercase hex digits")
    lv(6, "representation-of-three-digits-then-bogus",
       HEAD + 'wire cdr\ncdr 1\nrepresentation 000\nfield probe.x uint8\nbogus\n', UD,
       ref="0.43 ruling 10: the form of <hex> is checked after the file")
    lv(7, "cdr-with-two-arguments-then-bogus",
       HEAD + 'wire cdr\ncdr 1 2\nrepresentation 0000\nfield probe.x uint8\nbogus\n', BAD,
       ref="0.43 ruling 10: cdr joins 5e with one argument, checked as the line is read, before bogus")
    lv(8, "cdr-line-on-json-then-bogus",
       HEAD + 'wire json\ncdr 1\nfield probe.x x int\nbogus\n', UD,
       ref="0.43 ruling 10: cdr on another wire is bad-directive after the file; bogus is a line check")
    lv(9, "representation-line-on-json", HEAD + 'wire json\nrepresentation 0000\nfield probe.x x int\n', BAD,
       ref="0.43 ruling 10: representation on another wire is bad-directive")
    lv(10, "representation-not-checked-against-cdr",
       HEAD + 'wire cdr\ncdr 1\nrepresentation 0006\nfield probe.x uint8\n',
       ref="0.43 ruling 10: representation is not checked against cdr")
    lv(11, "unknown-type", HEAD + WIRE + 'field probe.n int128\n', BAD,
       ref="0.43 ruling 10: an unknown type is bad-directive after the file")
    lv(12, "unknown-type-then-bogus", HEAD + WIRE + 'field probe.n int128\nbogus\n', UD,
       ref="0.43 ruling 10: the type is checked after the file, so bogus wins")
    # ruling 4
    lv(13, "default-transform-named-and-scales-load",
       HEAD + WIRE + 'field probe.n int16 int\nfield probe.a uint16 uscale:1/2\nfield lat int32 sscale:90/2147483647\n'
                     'field probe.a octet uscale:1\nfield uid string string\n',
       ref="0.43 ruling 4: the type's default may be named; uscale and sscale on an integer type or octet")
    lv(14, "another-known-transform-then-bogus", HEAD + WIRE + 'field probe.n int16 float\nbogus\n', UD,
       ref="0.43 ruling 4: a known transform other than the default or a scale is bad-directive after the file")
    lv(15, "another-known-transform", HEAD + WIRE + 'field probe.n int16 float\n', BAD,
       ref="0.43 ruling 4")
    lv(16, "unknown-transform-then-bogus", HEAD + WIRE + 'field probe.n int16 frob\nbogus\n', UT,
       ref="0.43 ruling 4 and ruling 5b of 0.11 step 7: the name is a line check")
    lv(17, "scale-on-float32", HEAD + WIRE + 'field probe.a float32 uscale:1/2\n', BAD,
       ref="0.43 ruling 4: uscale and sscale only on int8 to uint64 or octet")
    # ruling 3 (and 12: const counted)
    K = "kind k\n"
    lv(18, "when-0-then-bogus", HEAD + WIRE + 'field probe.x uint8\n' + K + 'when 0 1\nbogus\n', UD,
       ref="0.43 ruling 3: when 0 is bad-directive after the file; bogus is a line check")
    lv(19, "when-0", HEAD + WIRE + 'field probe.x uint8\n' + K + 'when 0 1\n', BAD, ref="0.43 ruling 3")
    lv(20, "when-past-the-last-line", HEAD + WIRE + 'field probe.x uint8\nfield probe.n int16\n' + K + 'when 3 1\n',
       BAD, ref="0.43 ruling 3: two common lines, when 3")
    lv(21, "when-naming-a-group",
       HEAD + WIRE + 'field probe.x uint8\ngroup probe.nums seq\n  field probe.val int32\nend\n' + K + 'when 2 1\n',
       BAD, ref="0.43 ruling 3: line 2 is a group")
    lv(22, "when-naming-a-string", HEAD + WIRE + 'field uid string\n' + K + 'when 1 1\n', BAD,
       ref="0.43 ruling 3: line 1 is a string")
    lv(23, "when-naming-a-float", HEAD + WIRE + 'field probe.a float64\n' + K + 'when 1 1\n', BAD,
       ref="0.43 ruling 3: line 1 is a float64")
    lv(24, "when-counts-const-and-skips-group-bodies",
       HEAD + WIRE + 'field probe.x uint8\ngroup probe.items seq\n  field probe.label string\n  field probe.qty uint16\n'
                     'end\nconst uint16 7\nfield probe.n int16\n' + K + 'when 4 5\n' + 'kind j\nwhen 3 7\n',
       ref="0.43 rulings 3 and 12: lines are x 1, group 2, const 3, n 4; the body lines are not counted, so when 4 "
           "names n (int16) and when 3 the const (uint16)")
    # ruling 13
    lv(25, "absent-option-then-bogus", HEAD + WIRE + 'field probe.n int16 int absent 0\nbogus\n', UD,
       ref="0.43 ruling 13: absent is bad-directive after the file on cdr; its syntax and value pass the line checks")
    lv(26, "swap-option", HEAD + WIRE + 'field probe.n int16 int swap\n', BAD, ref="0.43 ruling 13")
    lv(27, "optional-option", HEAD + WIRE + 'field probe.n int16 int optional\n', BAD, ref="0.43 ruling 13")
    lv(28, "via-option-loads", HEAD + WIRE + 'map t 1 2\nfield probe.n int16 int via t\n',
       ref="0.43 ruling 13: via is a field option on cdr")
    # ruling 14
    lv(29, "group-with-no-wire-line-then-bogus", HEAD + WIRE + 'group probe.nums seq\nend\nbogus\n', UD,
       ref="0.43 ruling 14: an empty body is bad-directive after the file")
    lv(30, "group-with-no-wire-line", HEAD + WIRE + 'group probe.nums seq\nend\n', BAD, ref="0.43 ruling 14")
    lv(31, "array-0", HEAD + WIRE + 'group probe.nums array:0\n  field probe.val int32\nend\n', BAD,
       ref="0.43 ruling 14")
    lv(32, "array-0-then-bogus", HEAD + WIRE + 'group probe.nums array:0\n  field probe.val int32\nend\nbogus\n', UD,
       ref="0.43 ruling 14 and ruling 5b of 0.11: a group's options are checked after the file")
    lv(33, "nested-seq-in-array-loads",
       HEAD + WIRE + 'group probe.items array:3\n  field probe.label string\n  group probe.nums seq\n'
                     '    field probe.val int32\n  end\nend\n',
       ref="0.43 ruling 14: nested seq and array groups are allowed")
    # ruling 22
    lv(34, "cdr-3", HEAD + 'wire cdr\ncdr 3\nrepresentation 0000\nfield probe.x uint8\n', BAD,
       ref="0.43 ruling 22")
    lv(35, "cdr-3-then-bogus", HEAD + 'wire cdr\ncdr 3\nrepresentation 0000\nfield probe.x uint8\nbogus\n', UD,
       ref="0.43 ruling 22: after the file, so bogus wins")
    lv(36, "second-cdr-line-then-bogus", HEAD + WIRE + 'cdr 1\nfield probe.x uint8\nbogus\n', UD,
       ref="0.43 ruling 22: a second cdr line is found after the file")
    lv(37, "second-representation-line", HEAD + WIRE + 'representation 0000\nfield probe.x uint8\n', BAD,
       ref="0.43 ruling 22")
    # ruling 23
    lv(38, "scale-on-char8", HEAD + WIRE + 'field probe.a char8 uscale:1/2\n', BAD, ref="0.43 ruling 23")
    lv(39, "scale-on-enum8-then-bogus", HEAD + WIRE + 'field probe.a enum8 sscale:1/2\nbogus\n', UD,
       ref="0.43 ruling 23: after the file, so bogus wins")
    lv(40, "scale-on-bool", HEAD + WIRE + 'field probe.a bool uscale:1\n', BAD, ref="0.43 ruling 23")
    lv(41, "scale-on-int64-and-uint64-loads", HEAD + WIRE + 'field probe.a int64 sscale:1/2\nfield probe.a uint64 uscale:3\n',
       ref="0.43 ruling 23: int64 and uint64 are in the list")
    # ruling 24
    lv(42, "when-value-256-on-uint8", HEAD + WIRE + 'field probe.x uint8\n' + K + 'when 1 256\n', BAD,
       ref="0.43 ruling 24: 256 does not fit 8 bits")
    lv(43, "when-value-256-on-uint8-then-bogus", HEAD + WIRE + 'field probe.x uint8\n' + K + 'when 1 256\nbogus\n', UD,
       ref="0.43 ruling 24: after the file, so bogus wins")
    lv(44, "when-value-255-on-uint8-and-65535-on-int16-load",
       HEAD + WIRE + 'field probe.x uint8\nfield probe.n int16\n' + K + 'when 1 255\nkind j\nwhen 2 65535\n',
       ref="0.43 rulings 3 and 24: the value is unsigned of the line's size, so 65535 fits int16's 16 bits")
    # ruling 26
    lv(45, "third-token-via-begins-the-options", HEAD + WIRE + 'map t 1 2\nfield probe.n int16 via t\n',
       ref="0.43 ruling 26: via as the third token begins the options; the transform is int")
    lv(46, "third-token-optional-then-bogus", HEAD + WIRE + 'field probe.n int16 optional\nbogus\n', UD,
       ref="0.43 rulings 26 and 13: optional begins the options (not an unknown transform) and is refused after "
           "the file, so bogus wins")
    lv(47, "third-token-absent", HEAD + WIRE + 'field probe.n int16 absent 0\n', BAD,
       ref="0.43 rulings 26 and 13: absent with its value begins the options and is refused on cdr")
    return L


def build(out):
    written = {}
    for dirpack, stem, d in build_vectors():
        out.write("packs/%s/vectors/%s.json" % (dirpack, stem), json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[dirpack] = written.get(dirpack, 0) + 1
    if PROTOBUF_SOURCE:
        for dirpack, stem, d in build_protobuf_source():
            out.write("packs/%s/vectors/%s.json" % (dirpack, stem), json.dumps(d, indent=2, ensure_ascii=False) + "\n")
            written[dirpack] = written.get(dirpack, 0) + 1
    for stem, d in build_loads():
        out.write("packs/conformance/load-vectors/%s.json" % stem, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written["conformance/load-vectors"] = written.get("conformance/load-vectors", 0) + 1
    return written


PROTOBUF_SOURCE = False

if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--protobuf-source" in argv:
        argv.remove("--protobuf-source")
        PROTOBUF_SOURCE = True
    sys.exit(genio.vector_main("cdr-vectors/gen.py", __doc__, build, argv))
