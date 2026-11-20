#!/usr/bin/env python3
"""Write the vectors of spec 0.15, value transforms: the packs
`conformance-transforms-*` and the load vectors from 500.

Every expected value here is worked out from the spec text (Version 0.15 and
the sections it refers to: 0.5 for `bits`, ruling 1 of 0.5 for float scale
arithmetic, ruling 3 of 0.1.1 for float text, 0.8 for sequential layouts, 0.9
for `absent`) and the pack layouts. Each vector states its values on paper:
the raw field values of a `bits` input, the model values they decode to, and
the expected bytes or text. A second computation checks every paper value:
the small codecs below (`uis_dec`, `smag_enc`, `chars_val`, `iscale_dec`,
`exact_text`, `fixed`, `seq` ...) follow the spec text with exact fractions
for the integer scales and IEEE doubles (Python floats) for the float scales,
and import nothing from an engine. Nothing calls an engine.

Inputs: none; every value is stated in this file. Writes, under --out, the
vector files named above. With --check nothing is written and the exit
status is 1 when a committed file differs from what this script writes.

Usage: python3 -I tools/gen/conformance-transforms-vectors.py [--out DIR] [--check]
"""
import json
import os
import re
import struct
import sys
from decimal import Decimal
from fractions import Fraction as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

TD = "transform-decode"
TE = "transform-encode"
I64_MIN = -(1 << 63)
I64_MAX = (1 << 63) - 1
CONSTRUCTED = "constructed"


class Fail(Exception):
    """A transform failure; args[0] is the error kind."""


# ------------------------------------------------------------------------------
# the arithmetic of the spec
# ------------------------------------------------------------------------------
def rnd(q):
    """round-half-away-from-zero of an exact value (Fraction, int or float)."""
    q = F(q)
    a = abs(q)
    n = (a.numerator * 2 + a.denominator) // (a.denominator * 2)   # floor(a + 1/2)
    return -n if q < 0 else n


def check_i64(v):
    if not I64_MIN <= v <= I64_MAX:
        raise Fail(TD)
    return v


def uis_dec(v, factor, offset=0):
    """uiscale / siscale decode of the integer v already read from the bits."""
    return check_i64(rnd(v * F(factor)) + offset)


def uis_enc(x, factor, offset, n, signed):
    v = rnd(F(x - offset) / F(factor))
    lo, hi = (-(1 << (n - 1)), (1 << (n - 1)) - 1) if signed else (0, (1 << n) - 1)
    if not lo <= v <= hi:
        raise Fail(TE)
    return v & ((1 << n) - 1)


def twos(v, n):
    return v - (1 << n) if v >> (n - 1) else v


def smag_dec(v, n):
    mag = v & ((1 << (n - 1)) - 1)
    return -mag if v >> (n - 1) else mag


def smag_enc(x, n):
    if abs(x) >= 1 << (n - 1):
        raise Fail(TE)
    return (1 << (n - 1)) | -x if x < 0 else x


def sscale_dec(v, num, den=1, offset=0.0):
    """ruling 1 of 0.5: in doubles, v * num / den, then + offset."""
    return float(v) * num / den + offset


def sscale_enc_q(x, num, den=1, offset=0.0):
    """ruling 1 of 0.5: in doubles, (x - offset) * den / num (before rounding)."""
    return (x - offset) * den / num


def f32_bits(x):
    try:
        return struct.unpack(">I", struct.pack(">f", x))[0]
    except OverflowError:
        raise Fail(TE)


def f32_val(b):
    v = struct.unpack(">f", struct.pack(">I", b))[0]
    if v != v or v in (float("inf"), float("-inf")):
        raise Fail(TD)
    return v


def f64_bits(x):
    return struct.unpack(">Q", struct.pack(">d", x))[0]


def f64_val(b):
    v = struct.unpack(">d", struct.pack(">Q", b))[0]
    if v != v or v in (float("inf"), float("-inf")):
        raise Fail(TD)
    return v


def finite(v, kind):
    if v != v or v in (float("inf"), float("-inf")):
        raise Fail(kind)
    return v


# ------------------------------------------------------------------------------
# character sets and octal
# ------------------------------------------------------------------------------
WIDTH = {"icao6": 6, "ais6": 6, "ascii7": 7}
PAD = {"icao6": 32, "ais6": 0, "ascii7": 0}


def char_of(cs, c):
    if cs == "icao6":
        if 1 <= c <= 26:
            return chr(64 + c)
        if c == 32 or 48 <= c <= 57:
            return chr(c)
        raise Fail(TD)
    if cs == "ais6":
        return chr(c + 64) if c < 32 else chr(c)
    if c == 0:
        return "\0"
    if 32 <= c <= 126:
        return chr(c)
    raise Fail(TD)


def code_of(cs, ch):
    o = ord(ch)
    if cs == "icao6":
        if 65 <= o <= 90:
            return o - 64
        if o == 32 or 48 <= o <= 57:
            return o
    elif cs == "ais6":
        if 64 <= o <= 95:
            return o - 64
        if 32 <= o <= 63:
            return o
    elif 32 <= o <= 126:       # ruling 17: NUL in the text is transform-encode
        return o
    raise Fail(TE)


def chars_codes(text, cs, count):
    if len(text) > count:
        raise Fail(TE)
    return [code_of(cs, ch) for ch in text] + [PAD[cs]] * (count - len(text))


def chars_val(codes, cs, msb):
    """The field value, as `uint` reads the field, that puts character i at
    bit i*w of the field: in msb the first character is the most significant,
    in lsb the least significant."""
    w = WIDTH[cs]
    n = len(codes)
    v = 0
    for i, c in enumerate(codes):
        v |= c << (w * (n - 1 - i) if msb else w * i)
    return v


def chars_dec(v, cs, count, msb):
    w = WIDTH[cs]
    codes = [(v >> (w * (count - 1 - i) if msb else w * i)) & ((1 << w) - 1) for i in range(count)]
    text = "".join(char_of(cs, c) for c in codes)
    if cs == "ascii7":
        text = text.rstrip("\0")
        if "\0" in text:
            raise Fail(TD)
    elif cs == "icao6":
        text = text.rstrip(" ")
    else:
        text = text.rstrip("@ ")
    return text


def octal_dec(v, n):
    return format(v, "0%do" % (n // 3))


def octal_enc(text, n):
    if len(text) != n // 3 or any(c not in "01234567" for c in text):
        raise Fail(TE)
    return int(text, 8)


# ------------------------------------------------------------------------------
# text-wire numbers
# ------------------------------------------------------------------------------
NUMBER = re.compile(r"(-?[0-9]+(?:\.[0-9]+)?)(?:[eE]([+-]?[0-9]+))?\Z")


def iscale_dec(text, factor, offset=0):
    m = NUMBER.match(text)
    if not m:
        raise Fail(TD)
    exp = int(m.group(2) or "0")
    if abs(exp) > 400:
        raise Fail(TD)
    r = F(m.group(1)) * F(10) ** exp
    return check_i64(rnd(r * F(factor)) + offset)


def exact_text(q):
    """The exact decimal of q in plain notation, or transform-encode when it
    does not terminate within 18 fraction digits."""
    q = F(q)
    k = 0
    while (q * 10 ** k).denominator != 1:
        k += 1
        if k > 18:
            raise Fail(TE)
    sign = "-" if q < 0 else ""
    a = abs(q)
    ip = a.numerator // a.denominator
    frac = a - ip
    if not frac:
        return sign + str(ip)
    digits = str(int(frac * 10 ** k)).rjust(k, "0").rstrip("0")
    return "%s%d.%s" % (sign, ip, digits)


def iscale_enc(x, factor, offset=0):
    return exact_text(F(x - offset) / F(factor))


def jfloat(x):
    """ruling 3 of 0.1.1: shortest round-trip decimal, plain notation, -0 as 0."""
    finite(x, TE)
    if x == 0:
        return "0"
    s = format(Decimal(repr(float(x))), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


# ------------------------------------------------------------------------------
# bits layouts
# ------------------------------------------------------------------------------
def fixed(nbytes, fields, msb):
    """fields: (bit offset, len, unsigned value, swap); bits no field covers are 0."""
    bitsv = [0] * (nbytes * 8)
    for pos, n, v, swap in fields:
        v &= (1 << n) - 1
        if swap:
            v = int.from_bytes(v.to_bytes(n // 8, "big")[::-1], "big")
        for i in range(n):
            bitsv[pos + i] = (v >> (n - 1 - i)) & 1 if msb else (v >> i) & 1
    out = bytearray(nbytes)
    for i, b in enumerate(bitsv):
        if b:
            out[i // 8] |= (0x80 >> (i % 8)) if msb else (1 << (i % 8))
    return bytes(out).hex()


def read(hexs, pos, n, msb, swap=False):
    """The field's value as `uint` reads it (the inverse of `fixed`)."""
    data = bytes.fromhex(hexs)
    v = 0
    for i in range(n):
        b = pos + i
        bit = (data[b // 8] >> ((7 - b % 8) if msb else (b % 8))) & 1
        v |= bit << ((n - 1 - i) if msb else i)
    if swap:
        v = int.from_bytes(v.to_bytes(n // 8, "big")[::-1], "big")
    return v


def seq(fields):
    """msb sequential: (value, len) in reading order, zero bits to the byte."""
    s = []
    for v, n in fields:
        v &= (1 << n) - 1
        s += [(v >> (n - 1 - i)) & 1 for i in range(n)]
    while len(s) % 8:
        s.append(0)
    return bytes(int("".join(map(str, s[i:i + 8])), 2) for i in range(0, len(s), 8)).hex()


def hx(s):
    return s.replace(" ", "")


def same(paper, computed):
    if isinstance(paper, str) and isinstance(computed, str):
        paper = hx(paper) if re.fullmatch(r"[0-9a-f ]+", paper) else paper
    assert paper == computed, (paper, computed)
    return computed


def fails(kind, fn, *args):
    try:
        fn(*args)
    except Fail as e:
        assert e.args[0] == kind, (kind, e.args[0])
        return kind
    raise AssertionError("expected %s from %s%r" % (kind, fn.__name__, args))


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written = {}
    counters = {}

    def vec(pack, name, frm, to, inp, expect=None, error=None, model=None, context=None,
            reference=None, source=CONSTRUCTED):
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
        d["source"] = source
        if reference:
            d["reference"] = reference
        sink.write("packs/%s/vectors/%02d-%s.json" % (pack, counters[pack], name),
                   json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[pack] = written.get(pack, 0) + 1

    B = "conformance-transforms-bits"
    BL = "conformance-transforms-bits-lsb"
    S = "conformance-transforms-seq"
    J = "conformance-transforms-json"
    JA = "conformance-transforms-json-absent"
    X = "conformance-transforms-xml"
    G = "conformance-transforms-geojson"
    ALL1 = (1 << 64) - 1

    # ==========================================================================
    # conformance-transforms-bits (fixed, msb): one kind per transform
    # ==========================================================================
    def k64(sel, v):
        return fixed(9, [(0, 8, sel, 0), (8, 64, v, 0)], True)

    # --- us: time_ms 0:8:64 uiscale:1/1000 ---------------------------------
    us_in, ms = 1614456000000500, 1614456000001        # 1614456000000.5 rounds away from zero
    same(ms, uis_dec(us_in, "1/1000"))
    us_out = same(1614456000001000, uis_enc(ms, "1/1000", 0, 64, False))
    vec(B, "uiscale-microseconds-half-rounds-away-from-zero", B, B, k64(0x10, us_in), k64(0x10, us_out),
        model={"@kind": "us", "time_ms": str(ms)},
        reference="1614456000000500 us x 1/1000 = 1614456000000.5, round half away from zero 1614456000001; "
                  "encode 1614456000001 / (1/1000) = 1614456000001000")
    same(1614456000000, uis_dec(1614456000000499, "1/1000"))
    same("1614456000", iscale_enc(1614456000000, 1000))
    vec(B, "uiscale-microseconds-to-json-seconds", B, J, k64(0x10, 1614456000000499), '{"sec":1614456000}',
        model={"time_ms": "1614456000000"},
        reference="1614456000000.499 rounds to 1614456000000 ms; json iscale:1000 writes 1614456000000/1000 exactly")
    vec(B, "uiscale-zero", B, B, same("10 0000000000000000", k64(0x10, 0)), "100000000000000000",
        model={"time_ms": "0"})
    big_ms = same(18446744073709552, uis_dec(ALL1, "1/1000"))     # 18446744073709551.615
    same("18446744073709.552", iscale_enc(big_ms, 1000))
    vec(B, "ruling-10-uiscale-reads-64-ones-as-unsigned", B, J, k64(0x10, ALL1), '{"sec":18446744073709.552}',
        model={"time_ms": "18446744073709552"},
        reference="ruling 10: v = 2^64-1 = 18446744073709551615; x 1/1000 rounds to 18446744073709552")
    fails(TE, uis_enc, big_ms, "1/1000", 0, 64, False)
    vec(B, "uiscale-roundtrip-of-64-ones-does-not-fit-on-encode", B, B, k64(0x10, ALL1), error=TE,
        reference="18446744073709552 x 1000 = 18446744073709552000 > 2^64-1")

    # --- uihalf: probe.n 0:8:64 uiscale:1/2:-1 ------------------------------
    n_all = same(I64_MAX, uis_dec(ALL1, "1/2", -1))
    vec(B, "ruling-10-offset-brings-the-result-into-int64", B, J, k64(0x11, ALL1), '{"n":%d}' % n_all,
        model={"@kind": "uihalf", "probe.n": str(n_all)},
        reference="ruling 10: (2^64-1)/2 = 9223372036854775807.5 rounds to 2^63, beyond int64; "
                  "the offset -1 gives 2^63-1, and only the final value is checked")
    same(I64_MAX - 1, uis_dec(ALL1 - 1, "1/2", -1))
    same(ALL1 - 1, uis_enc(I64_MAX - 1, "1/2", -1, 64, False))
    vec(B, "uiscale-offset-roundtrip-near-the-top", B, B, k64(0x11, ALL1 - 1), k64(0x11, ALL1 - 1),
        model={"probe.n": str(I64_MAX - 1)})
    same(-1, uis_dec(0, "1/2", -1))
    vec(B, "uiscale-offset-zero-bits", B, B, k64(0x11, 0), k64(0x11, 0), model={"probe.n": "-1"})
    same(1, uis_dec(3, "1/2", -1))      # 1.5 -> 2, -1
    same(4, uis_enc(1, "1/2", -1, 64, False))
    vec(B, "uiscale-half-rounds-up-then-offset", B, B, same("11 0000000000000003", k64(0x11, 3)),
        same("11 0000000000000004", k64(0x11, 4)), model={"probe.n": "1"},
        reference="3/2 = 1.5 rounds to 2, -1 gives 1; encode (1+1)/(1/2) = 4")
    fails(TE, uis_enc, I64_MAX, "1/2", -1, 64, False)
    vec(J, "to-bits-uiscale-quotient-2-to-the-64-does-not-fit", J, B, '{"n":9223372036854775807}', error=TE,
        reference="(2^63-1+1) / (1/2) = 2^64, which does not fit 64 bits unsigned")
    fails(TE, uis_enc, -2, "1/2", -1, 64, False)
    vec(J, "to-bits-uiscale-negative-quotient-does-not-fit", J, B, '{"n":-2}', error=TE,
        reference="(-2+1) / (1/2) = -2, below 0")

    # --- uione: probe.qty 0:8:64 uiscale:1 ----------------------------------
    fails(TD, uis_dec, ALL1, "1")
    vec(B, "ruling-10-64-ones-beyond-int64-is-transform-decode", B, B, k64(0x12, ALL1), error=TD,
        reference="ruling 10: uiscale reads 2^64-1, not -1 (ruling 2 of 0.5 does not apply)")
    fails(TD, uis_dec, 1 << 63, "1")
    vec(B, "uiscale-2-to-the-63-is-transform-decode", B, B, same("12 8000000000000000", k64(0x12, 1 << 63)),
        error=TD)
    vec(B, "uiscale-int64-max-roundtrip", B, B, same("12 7fffffffffffffff", k64(0x12, I64_MAX)),
        k64(0x12, I64_MAX), model={"@kind": "uione", "probe.qty": str(I64_MAX)})

    # --- si: x 0:8:8 siscale:1/2 | y 0:16:8 siscale:2:-3 | z 0:24:8 uiscale:3/2:10
    def si(x, y, z):
        return fixed(4, [(0, 8, 0x13, 0), (8, 8, x, 0), (16, 8, y, 0), (24, 8, z, 0)], True)

    def si_model(xr, yr, zr):
        return (uis_dec(twos(xr, 8), "1/2"), uis_dec(twos(yr, 8), "2", -3), uis_dec(zr, "3/2", 10))

    def si_out(x, y, z):
        return si(uis_enc(x, "1/2", 0, 8, True), uis_enc(y, "2", -3, 8, True), uis_enc(z, "3/2", 10, 8, False))

    same((3, 251, 393), si_model(0x05, 0x7f, 0xff))
    vec(B, "siscale-and-uiscale-positive-halves-and-maximums", B, B, same("13 05 7f ff", si(5, 0x7f, 0xff)),
        same("13 06 7f ff", si_out(3, 251, 393)),
        model={"@kind": "si", "probe.x": "3", "probe.y": "251", "probe.z": "393"},
        reference="x: 5/2 = 2.5 -> 3, encode 6; y: 127*2-3 = 251; z: 255*3/2 = 382.5 -> 383, +10 = 393, "
                  "encode 383*2/3 = 255.33 -> 255")
    same((-3, -259, 12), si_model(0xfb, 0x80, 0x01))
    vec(B, "ruling-4-siscale-negative-half-and-minimums", B, B, same("13 fb 80 01", si(0xfb, 0x80, 1)),
        same("13 fa 80 01", si_out(-3, -259, 12)),
        model={"probe.x": "-3", "probe.y": "-259", "probe.z": "12"},
        reference="ruling 4: x: -5/2 = -2.5 -> -3, encode -6 (fa); y: -128*2-3 = -259; z: 1*3/2 = 1.5 -> 2, +10 = 12")
    same((-1, -3, 10), si_model(0xff, 0, 0))
    vec(B, "siscale-minus-one-half-rounds-to-minus-one", B, B, same("13 ff 00 00", si(0xff, 0, 0)),
        same("13 fe 00 00", si_out(-1, -3, 10)),
        model={"probe.x": "-1", "probe.y": "-3", "probe.z": "10"},
        reference="ruling 4: -1/2 = -0.5 -> -1; y and z are their offsets")
    same(64, uis_dec(127, "1/2"))
    fails(TE, uis_enc, 64, "1/2", 0, 8, True)
    vec(B, "siscale-rounded-maximum-does-not-encode-back", B, B, same("13 7f 00 00", si(0x7f, 0, 0)), error=TE,
        reference="127/2 = 63.5 -> 64; encode 64*2 = 128 does not fit 8 bits two's complement")
    vec(J, "to-bits-siscale-encode-halves-both-signs", J, B, '{"x":-64,"y":0,"z":11}',
        same("13 80 02 01", si_out(-64, 0, 11)),
        reference="x: -64*2 = -128 (80); y: (0+3)/2 = 1.5 -> 2; z: (11-10)*2/3 = 0.67 -> 1")
    vec(J, "to-bits-ruling-4-siscale-encode-negative-half", J, B, '{"x":1,"y":-6,"z":10}',
        same("13 02 fe 00", si_out(1, -6, 10)),
        reference="y: (-6+3)/2 = -1.5 -> -2 (fe)")
    for name, inp, fn, args, why in (
            ("x-128", '{"x":64}', uis_enc, (64, "1/2", 0, 8, True), "64*2 = 128 > 127"),
            ("y-rounds-to-128", '{"x":0,"y":252}', uis_enc, (252, "2", -3, 8, True), "(252+3)/2 = 127.5 -> 128 > 127"),
            ("z-below-zero", '{"x":0,"z":9}', uis_enc, (9, "3/2", 10, 8, False), "(9-10)*2/3 = -0.67 -> -1 < 0"),
            ("z-256", '{"x":0,"z":394}', uis_enc, (394, "3/2", 10, 8, False), "(394-10)*2/3 = 256 > 255")):
        fails(TE, fn, *args)
        vec(J, "to-bits-integer-scale-out-of-range-" + name, J, B, inp, error=TE, reference=why)

    # --- si64: w 0:8:64 siscale:2 --------------------------------------------
    fails(TD, uis_dec, 1 << 62, "2")
    vec(B, "siscale-result-2-to-the-63-is-transform-decode", B, B, same("14 4000000000000000", k64(0x14, 1 << 62)),
        error=TD, reference="2^62 * 2 = 2^63, beyond int64")
    same(I64_MIN, uis_dec(twos(0xc000000000000000, 64), "2"))
    vec(B, "siscale-result-int64-min", B, B, same("14 c000000000000000", k64(0x14, 0xc000000000000000)),
        k64(0x14, uis_enc(I64_MIN, "2", 0, 64, True)), model={"@kind": "si64", "probe.w": str(I64_MIN)})
    fails(TD, uis_dec, twos(0xbfffffffffffffff, 64), "2")
    vec(B, "siscale-result-below-int64-min", B, B, same("14 bfffffffffffffff", k64(0x14, 0xbfffffffffffffff)),
        error=TD, reference="(-2^62-1) * 2 = -2^63-2")
    vec(J, "to-bits-siscale-64-encode-rounds-halves", J, B, '{"w":3}',
        same("14 0000000000000002", k64(0x14, uis_enc(3, "2", 0, 64, True))),
        reference="3/2 = 1.5 -> 2")
    vec(J, "to-bits-siscale-64-encode-rounds-negative-halves", J, B, '{"w":-3}',
        same("14 fffffffffffffffe", k64(0x14, uis_enc(-3, "2", 0, 64, True))),
        reference="-3/2 = -1.5 -> -2")
    vec(J, "to-bits-siscale-64-int64-max-encodes-to-a-value-that-does-not-decode", J, B,
        '{"w":9223372036854775807}', same("14 4000000000000000", k64(0x14, uis_enc(I64_MAX, "2", 0, 64, True))),
        reference="(2^63-1)/2 = 2^62-0.5 -> 2^62, which fits; decoding it gives 2^63")

    # --- smag: c1 0:8:8 smag | c2 0:16:12 smag absent 2048 | ratio 0:28:8 smscale:0.25
    def sm(c1, c2, r):
        return fixed(5, [(0, 8, 0x15, 0), (8, 8, c1, 0), (16, 12, c2, 0), (28, 8, r, 0)], True)

    same((-1, 2047, -1.75), (smag_dec(0x81, 8), smag_dec(0x7ff, 12), sscale_dec(smag_dec(0x87, 8), 0.25)))
    same((0x81, 0x7ff, 0x87), (smag_enc(-1, 8), smag_enc(2047, 12), smag_enc(rnd(sscale_enc_q(-1.75, 0.25)), 8)))
    sm_a = same("15 81 7f f8 70", sm(0x81, 0x7ff, 0x87))
    vec(B, "smag-and-smscale-roundtrip", B, B, sm_a, sm_a,
        model={"@kind": "smag", "probe.c1": "-1", "probe.c2": "2047", "probe.ratio": "-1.75"},
        reference="c1 81: sign 1, magnitude 1; c2 7ff: sign 0, 2047; ratio 87: -7 x 0.25")
    vec(B, "smag-to-json", B, J, sm_a, '{"c1":-1,"c2":2047,"ratio":-1.75}')
    same((0, 0.0), (smag_dec(0x80, 8), sscale_dec(smag_dec(0x80, 8), 0.25)))
    vec(B, "smag-negative-zero-decodes-0-and-encodes-sign-0", B, B, same("15 80 80 08 00", sm(0x80, 0x800, 0x80)),
        same("15 00 80 00 00", sm(smag_enc(0, 8), 2048, smag_enc(rnd(sscale_enc_q(0.0, 0.25)), 8))),
        model={"probe.c1": "0", "probe.ratio": "0", "@absent": ["probe.c2"]},
        reference="c1 80 and ratio 80: sign 1, magnitude 0, decode 0, encode with sign 0; "
                  "c2 800 is its sentinel, the raw bits (ruling 1), and is written back as the sentinel")
    same((-127, -2047, 31.75), (smag_dec(0xff, 8), smag_dec(0xfff, 12), sscale_dec(smag_dec(0x7f, 8), 0.25)))
    sm_c = same("15 ff ff f7 f0", sm(0xff, 0xfff, 0x7f))
    vec(B, "smag-largest-magnitudes", B, B, sm_c, sm_c,
        model={"probe.c1": "-127", "probe.c2": "-2047", "probe.ratio": "31.75"})
    for name, inp, fn, args in (
            ("plus-128", '{"c1":128}', smag_enc, (128, 8)),
            ("minus-128", '{"c1":-128}', smag_enc, (-128, 8)),
            ("12-bit-2048", '{"c1":0,"c2":2048}', smag_enc, (2048, 12))):
        fails(TE, fn, *args)
        vec(J, "to-bits-smag-magnitude-out-of-range-" + name, J, B, inp, error=TE,
            reference="a magnitude of 2^(len-1) or more")
    same(0, rnd(sscale_enc_q(-0.1, 0.25)))
    vec(J, "to-bits-ruling-15-smscale-rounding-to-0-writes-sign-0", J, B, '{"c1":-127,"ratio":-0.1}',
        same("15 ff 80 00 00", sm(smag_enc(-127, 8), 2048, smag_enc(0, 8))),
        reference="ruling 15: -0.1/0.25 = -0.4 rounds to 0, written with sign 0; c2 absent writes its sentinel")
    same(-2, rnd(sscale_enc_q(-0.375, 0.25)))
    vec(J, "to-bits-ruling-4-smscale-negative-half", J, B, '{"c1":0,"ratio":-0.375}',
        same("15 00 80 08 20", sm(0, 2048, smag_enc(-2, 8))),
        reference="-0.375/0.25 = -1.5 rounds to -2: sign 1, magnitude 2 (82)")
    vec(J, "to-bits-smag-negative-zero-float-and-zero-value", J, B, '{"c1":5,"c2":0,"ratio":-0}',
        same("15 05 00 00 00", sm(5, smag_enc(0, 12), smag_enc(rnd(sscale_enc_q(-0.0, 0.25)), 8))),
        reference="ratio -0: -0/0.25 = -0 rounds to the integer 0, sign 0; c2 0 is a value and is written as 0")
    fails(TE, smag_enc, rnd(sscale_enc_q(31.875, 0.25)), 8)
    vec(J, "to-bits-smscale-rounds-to-magnitude-128", J, B, '{"c1":0,"ratio":31.875}', error=TE,
        reference="31.875/0.25 = 127.5 rounds to 128, a magnitude of 2^7")

    # --- f32s: a 0:8:32 f32scale:0.5:10 ------------------------------------
    def f32k(b):
        return fixed(5, [(0, 8, 0x16, 0), (8, 32, b, 0)], True)

    same(10.75, f32_val(0x3fc00000) * 0.5 + 10)
    same(0x3fc00000, f32_bits((10.75 - 10) / 0.5))
    vec(B, "f32scale-roundtrip", B, B, same("16 3fc00000", f32k(0x3fc00000)), "163fc00000",
        model={"@kind": "f32s", "probe.a": "10.75"}, reference="single 1.5 x 0.5 + 10 = 10.75")
    fails(TD, f32_val, 0x7fc00000)
    vec(B, "f32scale-nan-on-the-wire", B, B, f32k(0x7fc00000), error=TD)
    fails(TD, f32_val, 0x7f800000)
    vec(B, "f32scale-infinity-on-the-wire", B, B, f32k(0x7f800000), error=TD)
    same(0x00000000, f32_bits((f32_val(0x80000000) * 0.5 + 10 - 10) / 0.5))
    vec(B, "f32scale-negative-zero-on-the-wire", B, B, f32k(0x80000000), same("16 00000000", f32k(0)),
        model={"probe.a": "10"}, reference="-0 x 0.5 + 10 = 10; (10-10)/0.5 = 0")
    fails(TE, f32_bits, (1e300 - 10) / 0.5)
    vec(J, "to-bits-f32scale-quotient-beyond-single-range", J, B, '{"a":1e300}', error=TE,
        reference="(1e300-10)/0.5 = 2e300, outside single range (ruling 23 of 0.5)")
    vec(J, "to-bits-f32scale-negative-quotient", J, B, '{"a":9}', same("16 c0000000", f32k(f32_bits((9 - 10) / 0.5))),
        reference="(9-10)/0.5 = -2")

    # --- f64s: hae 0:8:64 f64scale:10 ---------------------------------------
    same(25.0, f64_val(0x4004000000000000) * 10 + 0.0)
    vec(B, "f64scale-roundtrip", B, B, k64(0x17, 0x4004000000000000), k64(0x17, f64_bits((25.0 - 0.0) / 10)),
        model={"@kind": "f64s", "hae": "25"})
    vec(B, "f64scale-to-json", B, J, k64(0x17, 0x4004000000000000), '{"hae":25}')
    fails(TD, finite, f64_val(0x7fefffffffffffff) * 10 + 0.0, TD)
    vec(B, "f64scale-result-not-finite", B, B, same("17 7fefffffffffffff", k64(0x17, 0x7fefffffffffffff)), error=TD,
        reference="the largest double x 10 is infinite")
    same(0, f64_bits(f64_val(1 << 63) * 10 + 0.0))
    vec(B, "f64scale-negative-zero-plus-offset-0-is-zero", B, B, same("17 8000000000000000", k64(0x17, 1 << 63)),
        same("17 0000000000000000", k64(0x17, f64_bits((0.0 - 0.0) / 10))), model={"hae": "0"},
        reference="v x factor + offset in doubles: -0 x 10 = -0, then -0 + 0 = +0 (offset defaults to 0); "
                  "encode (0 - 0)/10 = +0")
    same(1 << 63, f64_bits((-0.0 - 0.0) / 10))
    vec(J, "to-bits-f64scale-negative-zero", J, B, '{"hae":-0}', same("17 8000000000000000", k64(0x17, 1 << 63)),
        reference="(x - offset)/factor in doubles: (-0 - 0)/10 = -0, the double -0")

    # --- via: label 0:8:8 uiscale:1/2 via lvl (1 low, 3 high) ---------------
    lvl = {1: "low", 3: "high"}
    same("high", lvl[uis_dec(5, "1/2")])
    vec(B, "ruling-2-via-sees-the-scaled-integer", B, B, "1805", same("18 06", fixed(2, [(0, 8, 0x18, 0), (8, 8, uis_enc(3, "1/2", 0, 8, False), 0)], True)),
        model={"@kind": "via", "probe.label": "high"},
        reference="ruling 2: 5/2 = 2.5 -> 3, the table maps 3 to high; encode high -> 3 -> 6")
    same("low", lvl[uis_dec(2, "1/2")])
    vec(B, "ruling-2-via-low", B, B, "1802", "1802", model={"probe.label": "low"})
    assert uis_dec(8, "1/2") not in lvl
    vec(B, "ruling-2-via-integer-with-no-entry", B, B, "1808", error=TD,
        reference="8/2 = 4 has no entry and int is not string (Version 0.6, Value tables)")
    vec(J, "to-bits-ruling-2-via-text-with-no-entry", J, B, '{"label":"mid"}', error=TE)
    vec(J, "to-bits-ruling-2-via-text-to-integer", J, B, '{"label":"low"}', "1802",
        reference="low -> 1 -> 1/(1/2) = 2")

    # --- octal: s2 0:8:12 octal | tag 0:24:63 octal --------------------------
    def octk(s2, tag):
        return fixed(11, [(0, 8, 0x19, 0), (8, 12, s2, 0), (24, 63, tag, 0)], True)

    same(("7777", "7" * 21), (octal_dec(0xfff, 12), octal_dec((1 << 63) - 1, 63)))
    o1 = same("19 fff0 fffffffffffffffe", octk(0xfff, (1 << 63) - 1))
    vec(B, "octal-all-ones-12-and-63-bits", B, B, o1, o1,
        model={"@kind": "octal", "probe.s2": "7777", "probe.tag": "7" * 21})
    o2 = same("19 0000 0000000000000000", octk(0, 0))
    vec(B, "octal-zero-with-leading-zeros", B, B, o2, o2, model={"probe.s2": "0000", "probe.tag": "0" * 21})
    same(("0010", "000000000000000000123"), (octal_dec(8, 12), octal_dec(0o123, 63)))
    o3 = same("19 0080 00000000000000a6", octk(8, 0o123))
    vec(B, "octal-leading-zeros", B, B, o3, o3, model={"probe.s2": "0010", "probe.tag": "000000000000000000123"},
        reference="s2 is 0x008, tag is 83 = 0o123 in the top 63 bits of the last 8 bytes (a6 = 83 << 1)")
    vec(J, "to-bits-octal-text", J, B, '{"s2":"1234"}', same("19 29c0 0000000000000000", octk(octal_enc("1234", 12), 0)),
        reference="0o1234 = 668 = 0x29c; tag absent writes zero bits")
    for name, inp, text, n in (("three-digits", '{"s2":"777"}', "777", 12),
                               ("five-digits", '{"s2":"77777"}', "77777", 12),
                               ("digit-8", '{"s2":"7778"}', "7778", 12),
                               ("empty", '{"s2":""}', "", 12),
                               ("63-bits-one-digit", '{"s2":"1234","tag":"7"}', "7", 63)):
        fails(TE, octal_enc, text, n)
        vec(J, "to-bits-octal-" + name, J, B, inp, error=TE,
            reference="encode takes exactly len/3 characters 0-7")

    # --- chars: s1 0:8:48 ais6 | callsign 0:56:48 icao6 | uid 0:104:35 ascii7
    def chk(s1, cs, uid):
        return fixed(18, [(0, 8, 0x1a, 0), (8, 48, s1, 0), (56, 48, cs, 0), (104, 35, uid, 0)], True)

    def cv(text, cs, count, msb=True):
        return chars_val(chars_codes(text, cs, count), cs, msb)

    def raw(codes, cs, msb=True):
        return chars_val(codes, cs, msb)

    a_s1, a_cs, a_id = cv(" A@B?_", "ais6", 8), cv("KLM1023", "icao6", 8), cv("AB12", "ascii7", 5)
    same((0x801002fdf000, 0x2cc371c32ce0, 0x83098b2000 >> 5), (a_s1, a_cs, a_id))
    c_a = same("1a 801002fdf000 2cc371c32ce0 83098b2000", chk(a_s1, a_cs, a_id))
    same((" A@B?_", "KLM1023", "AB12"), (chars_dec(a_s1, "ais6", 8, True), chars_dec(a_cs, "icao6", 8, True),
                                         chars_dec(a_id, "ascii7", 5, True)))
    vec(B, "chars-three-sets-roundtrip", B, B, c_a, c_a,
        model={"@kind": "chars", "probe.s1": " A@B?_", "callsign": "KLM1023", "uid": "AB12"},
        reference="ais6 codes 32 1 0 2 63 31 then padding 0 0: a leading space and an inner @ are kept; "
                  "icao6 K L M 1 0 2 3 and one padding space; ascii7 A B 1 2 and one NUL. "
                  "Character 0 is the most significant 6 or 7 bits")
    b_s1 = raw([1, 2, 32, 0, 32, 0, 0, 0], "ais6")
    b_cs = cv("A B", "icao6", 8)
    b_id = cv("A ", "ascii7", 5)
    same(("AB", "A B", "A "), (chars_dec(b_s1, "ais6", 8, True), chars_dec(b_cs, "icao6", 8, True),
                               chars_dec(b_id, "ascii7", 5, True)))
    c_b_in = same("1a 042800800000 0600a0820820 8280000000", chk(b_s1, b_cs, b_id))
    c_b_out = same("1a 042000000000 0600a0820820 8280000000", chk(cv("AB", "ais6", 8), b_cs, b_id))
    vec(B, "ruling-5-ais6-trailing-at-signs-and-spaces-in-any-mix", B, B, c_b_in, c_b_out,
        model={"probe.s1": "AB", "callsign": "A B", "uid": "A "},
        reference="ruling 5: ais6 A B space @ space @ @ @ decodes AB; icao6 keeps the inner space; "
                  "ascii7 removes only NULs, so its trailing space stays")
    empty = chk(cv("", "ais6", 8), cv("", "icao6", 8), cv("", "ascii7", 5))
    same("1a 000000000000 820820820820 0000000000", empty)
    vec(B, "ruling-13-all-padding-decodes-the-empty-text", B, B, empty, empty,
        model={"probe.s1": "", "callsign": "", "uid": ""},
        reference="ruling 13: ais6 all @ (0), icao6 all spaces (32), ascii7 all NUL: present and empty")
    vec(J, "to-bits-ruling-13-empty-text-encodes-all-padding", J, B, '{"s1":"","cs":"","id":""}', empty)
    fails(TD, chars_dec, 0, "icao6", 8, True)
    vec(B, "icao6-code-0-is-transform-decode", B, B, chk(0, 0, 0), error=TD,
        reference="icao6 code 0 is not in the set")
    g_cs = raw([27] + [32] * 7, "icao6")
    fails(TD, chars_dec, g_cs, "icao6", 8, True)
    vec(B, "icao6-code-27-is-transform-decode", B, B, same("1a 000000000000 6e0820820820 0000000000", chk(0, g_cs, 0)),
        error=TD)
    e_id = raw([0, 65, 0, 0, 0], "ascii7")
    fails(TD, chars_dec, e_id, "ascii7", 5, True)
    vec(B, "ascii7-nul-followed-by-a-character", B, B,
        same("1a 000000000000 820820820820 0104000000", chk(0, cv("", "icao6", 8), e_id)), error=TD)
    f_id = raw([127, 0, 0, 0, 0], "ascii7")
    fails(TD, chars_dec, f_id, "ascii7", 5, True)
    vec(B, "ascii7-code-127-is-transform-decode", B, B,
        same("1a 000000000000 820820820820 fe00000000", chk(0, cv("", "icao6", 8), f_id)), error=TD)
    vec(J, "to-bits-ruling-16-absent-chars-keys-write-zero-bits", J, B, '{"s1":"AB"}',
        same("1a 042000000000 000000000000 0000000000", chk(cv("AB", "ais6", 8), 0, 0)),
        reference="ruling 16: callsign and uid absent write zero bits, not padding (icao6 code 0 is not a character)")
    for name, inp, args in (
            ("ais6-lowercase", '{"s1":"a"}', ("a", "ais6", 8)),
            ("ais6-too-long", '{"s1":"ABCDEFGHI"}', ("ABCDEFGHI", "ais6", 8)),
            ("icao6-hyphen", '{"s1":"A","cs":"KLM-1"}', ("KLM-1", "icao6", 8)),
            ("icao6-at-sign", '{"s1":"A","cs":"@"}', ("@", "icao6", 8)),
            ("icao6-too-long", '{"s1":"A","cs":"ABCDEFGHI"}', ("ABCDEFGHI", "icao6", 8)),
            ("ruling-17-ascii7-nul", '{"s1":"A","id":"A\\u0000"}', ("A\0", "ascii7", 5)),
            ("ascii7-delete", '{"s1":"A","id":"\\u007f"}', ("\x7f", "ascii7", 5)),
            ("ascii7-too-long", '{"s1":"A","id":"ABCDEF"}', ("ABCDEF", "ascii7", 5))):
        fails(TE, chars_codes, *args)
        vec(J, "to-bits-chars-" + name, J, B, inp, error=TE)

    # --- adsb: when DF 17, TC 4 | val 0:8:24 uint | callsign 0:40:48 icao6 ---
    adsb_in = "8d4840d6202cc371c32ce0576098"
    same((17, 0x4840d6, 4), (read(adsb_in, 0, 5, True), read(adsb_in, 8, 24, True), read(adsb_in, 32, 5, True)))
    same("KLM1023", chars_dec(read(adsb_in, 40, 48, True), "icao6", 8, True))
    adsb_out = same("88 4840d6 20 2cc371c32ce0",
                    fixed(11, [(0, 5, 17, 0), (8, 24, 0x4840d6, 0), (32, 5, 4, 0), (40, 48, cv("KLM1023", "icao6", 8), 0)], True))
    vec(B, "icao6-published-adsb-identification-klm1023", B, B, adsb_in, adsb_out,
        model={"@kind": "adsb", "probe.val": "4735190", "callsign": "KLM1023"}, source="specification",
        reference="published message 8D4840D6202CC371C32CE0576098: The 1090 Megahertz Riddle, 2nd ed., "
                  "https://mode-s.org/1090mhz/, ADS-B chapter 2 (Aircraft identification). Bits 40-87 are the "
                  "codes 11 12 13 49 48 50 51 32. Encode writes the two when values and the mapped fields: "
                  "CA, the 3 bits after TC and the parity are not mapped and are 0, and the message is 11 bytes")
    adsb_nocs = same("88 4840d6 20 000000000000",
                     fixed(11, [(0, 5, 17, 0), (8, 24, 0x4840d6, 0), (32, 5, 4, 0)], True))
    vec(J, "to-bits-ruling-16-absent-icao6-callsign-writes-zero-bits", J, B, '{"val":4735190}', adsb_nocs,
        reference="ruling 16: the kind adsb is selected by requires probe.val; the absent callsign writes 48 zero bits")
    vec(B, "icao6-zero-bits-of-an-absent-callsign-do-not-decode", B, B, adsb_nocs, error=TD)

    # --- plain: s1 0:0:12 ais6 (the reviewer case) ---------------------------
    same("AB", chars_dec(read("0420", 0, 12, True), "ais6", 2, True))
    vec(B, "ais6-character-order-msb-first-character-first", B, B, "0420",
        same("0420", fixed(2, [(0, 12, cv("AB", "ais6", 2), 0)], True)),
        model={"@kind": "plain", "probe.s1": "AB"},
        reference="0:0:12 msb: bits 000001 000010, character 0 is the first six bits, A (1), then B (2)")

    # ==========================================================================
    # conformance-transforms-bits-lsb
    # ==========================================================================
    # --- smag: c1 0:8:8 | c2 0:20:8 | ratio 0:28:12 smscale:0.5 ---------------
    def lsm(c1, c2, r):
        return fixed(5, [(0, 8, 0x10, 0), (8, 8, c1, 0), (20, 8, c2, 0), (28, 12, r, 0)], False)

    same((-1, -5, -1.5), (smag_dec(0x81, 8), smag_dec(0x85, 8), sscale_dec(smag_dec(0x803, 12), 0.5)))
    l1 = same("10 81 50 38 80", lsm(smag_enc(-1, 8), smag_enc(-5, 8), smag_enc(rnd(sscale_enc_q(-1.5, 0.5)), 12)))
    vec(BL, "smag-sign-is-the-last-bit-of-the-field", BL, BL, l1, l1,
        model={"@kind": "smag", "probe.c1": "-1", "probe.c2": "-5", "probe.ratio": "-1.5"},
        reference="lsb: byte 81 is the value 0x81, whose most significant bit is the sign: -1. "
                  "c2 at bit 20 is 0x85 (low nibble in the high half of byte 2, high nibble in the low half of byte 3): -5. "
                  "ratio is 0x803: -3 x 0.5")
    vec(BL, "smag-negative-zero", BL, BL, same("10 80 00 08 80", lsm(0x80, 0x80, 0x800)), same("10 00 00 00 00", lsm(0, 0, 0)),
        model={"probe.c1": "0", "probe.c2": "0", "probe.ratio": "0"},
        reference="sign 1 with magnitude 0 decodes 0 and encodes with sign 0")

    # --- uis: time_ms 0:8:64 uiscale:1/1000 | n 0:72:16 uiscale:1:-5 swap -----
    def lus(us, n):
        return fixed(11, [(0, 8, 0x11, 0), (8, 64, us, 0), (72, 16, n, 1)], False)

    same((1, 253), (uis_dec(1000, "1/1000"), uis_dec(read("11e8030000000000000102", 72, 16, False, True), "1", -5)))
    l2 = same("11 e803000000000000 0102", lus(1000, uis_enc(253, "1", -5, 16, False)))
    vec(BL, "uiscale-little-endian-and-swapped", BL, BL, l2, l2,
        model={"@kind": "uis", "time_ms": "1", "probe.n": "253"},
        reference="time_ms: e8 03 is 1000 us; n: swap reverses 01 02 to 02 01, read low bit first 0x0102 = 258, -5")
    same(3, uis_dec(2500, "1/1000"))
    vec(BL, "uiscale-half-microseconds", BL, BL, same("11 c409000000000000 0000", lus(2500, 0)),
        same("11 b80b000000000000 0000", lus(uis_enc(3, "1/1000", 0, 64, False), uis_enc(-5, "1", -5, 16, False))),
        model={"time_ms": "3", "probe.n": "-5"}, reference="2500 us = 2.5 ms rounds to 3; encode 3000 us (0bb8)")
    same(-1, iscale_dec("-0.001", 1000))
    fails(TE, uis_enc, -1, "1/1000", 0, 64, False)
    vec(J, "to-lsb-uiscale-negative-time-does-not-fit", J, BL, '{"sec":-0.001}', error=TE,
        reference="time_ms -1: -1/(1/1000) = -1000 does not fit unsigned")

    # --- f32s: a 0:8:32 f32scale:0.5:10 | hae 0:40:64 f64scale:10 -------------
    def lf(a, h):
        return fixed(13, [(0, 8, 0x12, 0), (8, 32, a, 0), (40, 64, h, 0)], False)

    l3 = same("12 0000c03f 0000000000000440", lf(0x3fc00000, 0x4004000000000000))
    vec(BL, "float-scales-little-endian", BL, BL, l3, l3, model={"@kind": "f32s", "probe.a": "10.75", "hae": "25"})
    fails(TD, f64_val, 0x7ff8000000000000)
    vec(BL, "f64scale-nan-on-the-wire", BL, BL, same("12 0000c03f 000000000000f87f", lf(0x3fc00000, 0x7ff8000000000000)),
        error=TD)

    # --- chars: callsign 0:8:48 icao6 | uid 0:56:28 ascii7 | s1 0:84:12 ais6 ---
    def lch(cs, uid, s1):
        return fixed(12, [(0, 8, 0x13, 0), (8, 48, cs, 0), (56, 28, uid, 0), (84, 12, s1, 0)], False)

    same((0x833cb0c4d30b, 0x64c6141, 0x081),
         (cv("KLM1023", "icao6", 8, False), cv("AB12", "ascii7", 4, False), cv("AB", "ais6", 2, False)))
    l4 = same("13 0bd3c4b03c83 41614c 16 08", lch(0x833cb0c4d30b, 0x64c6141, 0x081))
    same(("KLM1023", "AB12", "AB"), (chars_dec(read(l4, 8, 48, False), "icao6", 8, False),
                                     chars_dec(read(l4, 56, 28, False), "ascii7", 4, False),
                                     chars_dec(read(l4, 84, 12, False), "ais6", 2, False)))
    vec(BL, "chars-lsb-first-character-in-the-low-bits", BL, BL, l4, l4,
        model={"@kind": "chars", "callsign": "KLM1023", "uid": "AB12", "probe.s1": "AB"},
        reference="lsb: character i is bits 6i to 6i+5 of the field, read low bit first, so the field value is "
                  "the sum of code_i << 6i: 0x833cb0c4d30b, written low byte first; s1 starts at bit 84, "
                  "the high half of byte 10")
    vec(BL, "to-msb-chars", BL, B, l4, same("1a 042000000000 2cc371c32ce0 83098b2000",
                                           chk(cv("AB", "ais6", 8), cv("KLM1023", "icao6", 8), cv("AB12", "ascii7", 5))),
        reference="the kind chars of the msb pack, selected by requires probe.s1; one padding character each")
    vec(B, "to-lsb-chars", B, BL, c_b_in,
        same("13 012880200882 411000 10 08", lch(cv("A B", "icao6", 8, False), cv("A ", "ascii7", 4, False),
                                                 cv("AB", "ais6", 2, False))),
        reference="the lsb kind chars, selected by requires callsign")
    vec(BL, "ruling-13-icao6-all-spaces-lsb", BL, BL, same("13 200882200882 000000 00 00", lch(cv("", "icao6", 8, False), 0, 0)),
        same("13 200882200882 000000 00 00", lch(cv("", "icao6", 8, False), 0, 0)),
        model={"callsign": "", "uid": "", "probe.s1": ""})

    # --- octal: tag 0:8:12 | s2 0:20:9 ----------------------------------------
    l5 = same("14 9c 72 14", fixed(4, [(0, 8, 0x14, 0), (8, 12, octal_enc("1234", 12), 0), (20, 9, octal_enc("507", 9), 0)], False))
    same(("1234", "507"), (octal_dec(read(l5, 8, 12, False), 12), octal_dec(read(l5, 20, 9, False), 9)))
    vec(BL, "octal-lsb", BL, BL, l5, l5, model={"@kind": "octal", "probe.tag": "1234", "probe.s2": "507"},
        reference="0o1234 = 0x29c written low bit first from bit 8; 0o507 = 0x147 from bit 20")

    # --- plain: s1 0:0:12 ais6 (the reviewer case) ----------------------------
    same("AB", chars_dec(read("8100", 0, 12, False), "ais6", 2, False))
    vec(BL, "ais6-character-order-lsb-first-character-first", BL, BL, "8100",
        same("8100", fixed(2, [(0, 12, cv("AB", "ais6", 2, False), 0)], False)),
        model={"@kind": "plain", "probe.s1": "AB"},
        reference="0:0:12 lsb: bits 0-5 of byte 81 are 000001 (A), bits 6-11 are 0 1 then four 0 read low bit first, 2 (B)")

    # ==========================================================================
    # conformance-transforms-seq (msb)
    # ==========================================================================
    def sq(us, c1, cs, s1, s2):
        f = [(us, 40), (c1, 6), (cs, 18)]
        f += [(0, 1)] if s1 is None else [(1, 1), (s1, 12)]
        return seq(f + [(s2, 9)])

    s_a = same("00000f4240 94 10 b1 b0 cf fc",
               sq(1000000, smag_enc(-5, 6), cv("AB1", "icao6", 3), cv("XY", "ais6", 2), octal_enc("777", 9)))
    same(1000, uis_dec(1000000, "1/1000"))
    vec(S, "ruling-3-transforms-in-a-sequential-layout", S, S, s_a, s_a,
        model={"time_ms": "1000", "probe.c1": "-5", "callsign": "AB1", "probe.s1": "XY", "probe.s2": "777"},
        reference="40 bits 1000000 us, c1 100101, callsign 000001 000010 110001, opt 1, s1 011000 011001, "
                  "s2 111111111, 2 zero bits")
    s_b = same("00000f4240 94 10 b1 7f c0",
               sq(1000000, smag_enc(-5, 6), cv("AB1", "icao6", 3), None, octal_enc("777", 9)))
    vec(S, "opt-block-left-out", S, S, s_b, s_b, model={"probe.c1": "-5", "@absent": ["probe.s1"]})
    s_c = same("00000f4240 94 10 b1 80 07 fc",
               sq(1000000, smag_enc(-5, 6), cv("AB1", "icao6", 3), cv("", "ais6", 2), octal_enc("777", 9)))
    vec(S, "ruling-13-empty-text-is-present-and-sets-the-opt-bit", S, S, s_c, s_c, model={"probe.s1": ""},
        reference="ruling 13: 12 bits of @ (0) decode the empty text, present, so the opt bit is 1")
    s_d = same("0000000000 0c 00 00 00 40", sq(0, smag_enc(3, 6), 0, None, octal_enc("001", 9)))
    vec(J, "to-seq-ruling-16-absent-icao6-key-writes-zero-bits", J, S, '{"c1":3,"s2":"001"}', s_d,
        reference="ruling 16 and Version 0.8: absent time_ms and callsign write zero bits; absent s1 leaves the opt block out")
    vec(S, "icao6-zero-bits-do-not-decode", S, S, s_d, error=TD)
    vec(J, "to-seq-empty-icao6-text-writes-spaces", J, S, '{"c1":0,"cs":"","s2":"000"}',
        same("0000000000 02 08 20 00 00", sq(0, 0, cv("", "icao6", 3), None, 0)))

    # ==========================================================================
    # conformance-transforms-json
    # ==========================================================================
    def jv(name, inp, out=None, error=None, model=None, reference=None, to=J):
        vec(J, name, J, to, inp, out, error=error, model=model, reference=reference)

    sec = same(1614456000001, iscale_dec("1614456000.0005", 1000))
    same("1614456000.001", iscale_enc(sec, 1000))
    jv("iscale-seconds-with-a-fraction-to-time-ms", '{"sec":1614456000.0005}', '{"sec":1614456000.001}',
       model={"time_ms": "1614456000001"},
       reference="1614456000.0005 x 1000 = 1614456000000.5 exactly, rounds to 1614456000001; encode /1000 exactly")
    for name, text in (("exponent", "1.6144560000005e9"), ("negative-exponent-capital-e", "16144560000005E-4")):
        same(sec, iscale_dec(text, 1000))
        jv("iscale-exponent-form-" + name, '{"sec":%s}' % text, '{"sec":1614456000.001}', model={"time_ms": str(sec)})
    same(-1, iscale_dec("-0.0005", 1000))
    jv("ruling-4-iscale-negative-half", '{"sec":-0.0005}', '{"sec":-0.001}', model={"time_ms": "-1"},
       reference="-0.0005 x 1000 = -0.5 rounds to -1")
    same("-0.5", iscale_enc(-500, 1000))
    jv("iscale-encode-negative-fraction", '{"sec":-0.5}', '{"sec":-0.5}', model={"time_ms": "-500"},
       reference="-500/1000 = -0.5: a sign, the integer digit 0, the fraction")
    for name, text in (("ruling-9-1e-400-is-0", "1e-400"), ("ruling-9-0e400-is-0", "0e400")):
        same(0, iscale_dec(text, 1000))
        jv(name, '{"sec":%s}' % text, '{"sec":0}', model={"time_ms": "0"})
    fails(TD, iscale_dec, "1e401", 1000)
    jv("iscale-exponent-above-400", '{"sec":1e401}', error=TD)
    fails(TD, iscale_dec, "1e400", 1000)
    jv("iscale-exponent-400-beyond-int64", '{"sec":1e400}', error=TD, reference="10^400 x 1000 is beyond int64")
    jv("iscale-string-member", '{"sec":"5"}', error=TD, reference="the member must be a number, as for float")

    for name, text, want in (
            ("ruling-7-exact-digits-above-2-to-the-53", "9007199254740993", 9007199254740993),
            ("ruling-7-exact-digits-with-a-fraction", "9007199254740993.4", 9007199254740993),
            ("ruling-7-exact-digits-exponent", "90071992547409925e-1", 9007199254740993),
            ("iscale-int64-max", "9223372036854775807", I64_MAX),
            ("iscale-int64-min", "-9223372036854775808", I64_MIN),
            ("ruling-4-iscale-half", "2.5", 3),
            ("ruling-4-iscale-negative-half-integer", "-2.5", -3),
            ("iscale-negative-zero", "-0", 0),
            ("iscale-exponent-with-plus", "1E+2", 100)):
        same(want, iscale_dec(text, 1))
        jv(name, '{"big":%s}' % text, '{"big":%d}' % want, model={"probe.big": str(want)})
    fails(TD, iscale_dec, "9223372036854775808", 1)
    jv("iscale-int64-max-plus-one", '{"big":9223372036854775808}', error=TD)

    same(7, iscale_dec("2", 3, 1))
    same("2", iscale_enc(7, 3, 1))
    jv("iscale-factor-and-offset", '{"th":2}', '{"th":2}', model={"probe.thirds": "7"},
       reference="2 x 3 + 1 = 7; (7-1)/3 = 2")
    same(-2, iscale_dec("-1", 3, 1))
    jv("iscale-factor-and-offset-negative", '{"th":-1}', '{"th":-1}', model={"probe.thirds": "-2"})
    same(3, iscale_dec("0.5", 3, 1))
    fails(TE, iscale_enc, 3, 3, 1)
    jv("iscale-quotient-two-thirds-does-not-terminate", '{"th":0.5}', error=TE,
       reference="0.5 x 3 = 1.5 rounds to 2, +1 = 3; encode (3-1)/3 = 2/3 has no finite decimal")
    same(-1, iscale_dec("-0.5", 3, 1))
    jv("ruling-4-iscale-negative-half-with-offset", '{"th":-0.5}', error=TE,
       reference="-0.5 x 3 = -1.5 rounds to -2, +1 = -1; encode (-1-1)/3 = -2/3")

    same(30.0090027, sscale_dec(300090027, 1, 10000000))
    same(300090027.0, sscale_enc_q(30.0090027, 1, 10000000))
    jv("scale-degrees-e7-to-degrees", '{"lat":300090027}', '{"lat":300090027}', model={"lat": "30.0090027"},
       reference="300090027 x 1 / 10000000 in doubles; encode x x 10000000 / 1")
    same("0.0000001", jfloat(sscale_dec(1, 1, 10000000)))
    same("1", jfloat(sscale_enc_q(1e-07, 1, 10000000)))
    jv("scale-small-result-in-plain-notation", '{"lat":1}', '{"lat":1}', model={"lat": "0.0000001"},
       reference="1 x 1 / 10000000 = 1e-7, which a model check writes 0.0000001; 1e-7 x 10000000 / 1 = 1 in doubles")
    same(25.0, sscale_dec(2.5, 10))
    jv("scale-factor-10", '{"ce":2.5}', '{"ce":2.5}', model={"ce": "25"})
    fails(TD, finite, sscale_dec(1e308, 10), TD)
    jv("ruling-14-scale-result-not-finite", '{"ce":1e308}', error=TD, reference="1e308 x 10 is infinite")
    same(135.0, sscale_dec(-4500, 1, 100, 180.0))
    jv("scale-offset", '{"crs":-4500}', '{"crs":-4500}', model={"course": "135"},
       reference="-4500 x 1 / 100 + 180 = 135; (135-180) x 100 / 1 = -4500")
    crs = sscale_dec(1, 1, 100, 180.0)
    same("180.01", jfloat(crs))
    same("0.9999999999990905", jfloat(sscale_enc_q(crs, 1, 100, 180.0)))
    jv("ruling-8-scale-is-not-rounded", '{"crs":1}', '{"crs":0.9999999999990905}', model={"course": "180.01"},
       reference="ruling 8 and ruling 1 of 0.5: 1 x 1 / 100 = 0.01, + 180 = 180.01 (the double nearest); "
                 "encode (180.01 - 180) x 100 / 1 = 0.9999999999990905 in doubles, written as float writes it")
    same(1614456000001000, uis_enc(sec, "1/1000", 0, 64, False))
    jv("to-bits-iscale-seconds-to-uiscale-microseconds", '{"sec":1614456000.0005}', k64(0x10, 1614456000001000),
       to=B, reference="1614456000001 ms, then / (1/1000)")

    # ==========================================================================
    # conformance-transforms-json-absent
    # ==========================================================================
    def ja(name, inp, out, model, reference=None):
        vec(JA, name, JA, JA, inp, out, model=model, reference=reference)

    ja("ruling-6-exponent-number-matches-the-sentinel", '{"cnt":1e2}', '{"cnt":100}', {"@absent": ["probe.cnt"]},
       "ruling 6: canonical text of 1e2 is 100, the sentinel; the absent key writes the first sentinel")
    ja("ruling-6-fraction-zero-matches-the-sentinel", '{"cnt":100.0}', '{"cnt":100}', {"@absent": ["probe.cnt"]})
    same(51, iscale_dec("101", "1/2"))
    same("102", iscale_enc(51, "1/2"))
    ja("ruling-6-other-number-goes-through-iscale", '{"cnt":101}', '{"cnt":102}', {"probe.cnt": "51"},
       "101/2 = 50.5 rounds to 51; encode 51 / (1/2) = 102")
    same("9007199254740992", jfloat(float(9007199254740993)))
    ja("ruling-6-sentinel-compared-through-a-double", '{"cnt":9007199254740992}', '{"cnt":100}',
       {"@absent": ["probe.cnt"]},
       "ruling 9 and ruling 19 of 0.9: the sentinel 9007199254740993 is held as 9007199254740992, the canonical "
       "text of the wire number 9007199254740992; iscale does not change the comparison (ruling 6)")
    ja("ruling-6-string-holding-the-sentinel", '{"cnt":"100"}', '{"cnt":100}', {"@absent": ["probe.cnt"]},
       "the sentinel check comes before the transform; a string member's text 100 equals it")
    ja("missing-member-writes-the-first-sentinel", '{}', '{"cnt":100}', {"@absent": ["probe.cnt"]})

    # ==========================================================================
    # conformance-transforms-xml
    # ==========================================================================
    def xv(name, inp, out=None, error=None, model=None, reference=None):
        vec(X, name, X, X, inp, out, error=error, model=model, reference=reference)

    same(1.25, sscale_dec(12.5, 1, 10))
    same("12.5", jfloat(sscale_enc_q(1.25, 1, 10)))
    same(1, iscale_dec("0.000003814697265625", 262144))
    same("0.000003814697265625", iscale_enc(1, 262144))
    same(-4, iscale_dec("-2.5", 1, -1))
    same("-3", iscale_enc(-4, 1, -1))
    x1 = ('<msg r="12.5" t="1614456000.001" big="9007199254740993" q18="0.000003814697265625">'
          '<pos lat="125000000"/><v>-3</v></msg>')
    xv("transforms-roundtrip", x1.replace('<v>-3</v>', '<v>-2.5</v>'), x1,
       model={"probe.ratio": "1.25", "time_ms": "1614456000001", "probe.big": "9007199254740993", "probe.x": "1",
              "lat": "12.5", "probe.z": "-4"},
       reference="q18: 2^-18 x 262144 = 1, written back with 18 fraction digits; v: round(-2.5) = -3, -1 = -4, "
                 "encode -4 + 1 = -3")
    vec(J, "to-xml-ruling-8-scale-writes-12-5", J, X, '{"ratio":1.25}', '<msg r="12.5"/>',
        reference="ruling 8: (1.25 - 0) x 10 / 1 = 12.5, not rounded")
    fails(TE, iscale_enc, 1, 524288)
    xv("iscale-quotient-with-19-fraction-digits", '<msg q19="0.0000019073486328125"/>', error=TE,
       reference="1 / 524288 = 2^-19 = 0.0000019073486328125: it terminates, but not within 18 fraction digits")
    for name, text in (("leading-space", " 5"), ("trailing-space", "5 "), ("plus-sign", "+5"),
                       ("bare-fraction", ".5"), ("bare-point", "5."), ("empty", ""), ("hex", "0x10")):
        fails(TD, iscale_dec, text, 1)
        xv("iscale-text-form-" + name, '<msg big="%s"/>' % text, error=TD,
           reference="on xml the text must have the number form exactly, without surrounding whitespace")
    xv("ruling-24-whitespace-element-text-is-text", '<msg><v>  </v></msg>', error=TD,
       reference="ruling 24 (and 0.11 ruling 1m): whitespace-only text is text, which iscale refuses")
    xv("ruling-24-empty-element-has-no-text", '<msg><v/></msg>', '<msg/>', model={"@absent": ["probe.z"]})
    fails(TD, iscale_dec, " 1", 1, -1)
    xv("ruling-24-element-text-read-untrimmed", '<msg><v> 1</v></msg>', error=TD,
       reference="ruling 24: text that is not only whitespace is read untrimmed by iscale")
    XW = "conformance-transforms-xml-when"
    for name, inp, kind in (
            ("ruling-24-when-present-holds-for-a-whitespace-element", "<msg><v>  </v></msg>", "t"),
            ("ruling-24-when-present-holds-for-an-empty-element", "<msg><v/></msg>", "t"),
            ("ruling-24-no-element-selects-the-other-kind", "<msg/>", "other")):
        vec(XW, name, XW, XW, inp, '<msg k="%s"/>' % kind,
            model={"@kind": kind, "@absent": ["probe.x", "probe.y"]},
            reference="ruling 24: when v/#text present holds when the element v exists, whatever its text; "
                      "the kind's const writes k; when present writes nothing and v is not residue "
                      "(ruling 6 of 0.1.1), so v is not written; probe.x and probe.y are absent")
    for name, text, want in (("leading-zeros", "007", 7), ("exponent-with-plus", "1E+2", 100),
                             ("negative-zero", "-0", 0), ("ruling-9-1e-400", "1e-400", 0)):
        same(want, iscale_dec(text, 1))
        xv("iscale-text-form-" + name, '<msg big="%s"/>' % text, '<msg big="%d"/>' % want,
           model={"probe.big": str(want)})

    # ==========================================================================
    # conformance-transforms-geojson
    # ==========================================================================
    def gj(lon, lat, alt, t, uid):
        return ('{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s,%s]},'
                '"properties":{"t":%s},"id":"%s"}' % (lon, lat, alt, t, uid))

    same(-85.9578182, sscale_dec(-859578182, 1, 10000000))
    same("-859578182", jfloat(sscale_enc_q(-85.9578182, 1, 10000000)))
    g1 = gj("-859578182", "30.0090027", "9007199254740993", "1614456000.001", "u1")
    vec(G, "ruling-7-exact-digits-on-a-coordinate-slot", G, G, g1.replace("1614456000.001", "1614456000.0005"), g1,
        model={"lon": "-85.9578182", "lat": "30.0090027", "probe.big": "9007199254740993", "time_ms": "1614456000001"},
        reference="ruling 7: alt iscale:1 keeps 9007199254740993; lon -859578182 x 1 / 10000000 and back in doubles")
    same(9007199254740993, iscale_dec("9.007199254740993e15", 1))
    vec(G, "ruling-7-exponent-form-on-a-coordinate-slot", G, G, gj("1", "2", "9.007199254740993e15", "0", "u2"),
        gj("1", "2", "9007199254740993", "0", "u2"), model={"probe.big": "9007199254740993", "lon": "0.0000001"})
    vec(G, "to-json-exact-digits-and-scales", G, J, gj("1", "12.5", "9007199254740993", "1614456000.0005", "u1"),
        '{"sec":1614456000.001,"big":9007199254740993,"lat":125000000,"id":"u1"}',
        reference="lat 12.5 x 10000000 / 1 = 125000000; lon has no member on json")
    fails(TE, finite, sscale_enc_q(1e308, 1, 10000000), TE)
    vec(G, "to-json-ruling-14-scale-encode-not-finite", G, J, gj("0", "1e308", "0", "0", "u3"), error=TE,
        reference="ruling 14: 1e308 x 10000000 / 1 is infinite")
    vec(G, "iscale-string-property", G, G,
        '{"type":"Feature","geometry":null,"properties":{"t":"1"},"id":"u4"}', error=TD,
        reference="on geojson the member must be a number, as for float")
    vec(G, "ruling-23-scale-refuses-a-string-property", G, G,
        '{"type":"Feature","geometry":null,"properties":{"t":0,"ce":"2.5"},"id":"u5"}', error=TD,
        reference="ruling 23: scale refuses a string member on geojson, although float there keeps its 0.1 typing")
    same(25.0, sscale_dec(2.5, 10))
    vec(G, "scale-on-a-property", G, G,
        '{"type":"Feature","geometry":null,"properties":{"t":0,"ce":2.5},"id":"u6"}',
        '{"type":"Feature","geometry":null,"properties":{"t":0,"ce":2.5},"id":"u6"}', model={"ce": "25"})

    # ruling 27: a mapped json number outside the double range is read by the field's transform
    assert float("1e400") == float("inf")
    for name, inp in (("int", '{"n":1e400}'), ("float", '{"a":1e400}'), ("negative-float", '{"a":-1e400}'),
                      ("scale", '{"ce":1e400}')):
        jv("ruling-27-number-outside-the-double-range-on-%s" % name, inp, error=TD,
           reference="ruling 27: a number outside the double range that a field maps is read by its transform; "
                     "int, float and scale fail with transform-decode")
    same(0, iscale_dec("1e-400", 1))
    jv("ruling-27-iscale-reads-a-number-below-the-double-range-exactly", '{"big":1e-400,"n":1}', '{"big":0,"n":1}',
       model={"probe.big": "0", "probe.n": "1"}, reference="ruling 27 and ruling 9: iscale reads 10^-400 exactly, rounds to 0")
    jv("ruling-27-unmapped-number-outside-the-double-range", '{"zz":1e400,"n":1}', error="malformed-wire",
       reference="ruling 27: a number outside the double range that no field maps stays malformed-wire (ruling 39 of 0.8)")
    jv("ruling-27-unmapped-member-of-a-group-item-outside-the-double-range", '{"items":[{"q":1,"zz":1e400}]}',
       error="malformed-wire",
       reference="ruling 27: no field reads items[].zz; a number outside the double range anywhere is malformed-wire")
    jv("ruling-27-number-in-an-unmapped-array-outside-the-double-range", '{"n":1,"arr":[1,1e400]}',
       error="malformed-wire", reference="ruling 27: arrays no field reads are included")
    jv("ruling-27-group-item-member-read-by-its-field", '{"items":[{"q":1e400}]}', error=TD,
       reference="ruling 27: a number outside the double range that a field maps, here an item's int, is transform-decode")
    same("0", jfloat(float("1e-400")))
    jv("ruling-27-underflow-is-inside-the-range-and-reads-0", '{"a":1e-400}', '{"a":0}', model={"probe.a": "0"},
       reference="ruling 27: a number that rounds to 0 is inside the double range and reads as 0")
    vec(G, "ruling-27-unmapped-number-outside-the-double-range-stays-residue", G, G,
        '{"type":"Feature","geometry":null,"properties":{"t":0,"zz":1e400},"id":"u7"}',
        '{"type":"Feature","geometry":null,"properties":{"t":0,"zz":"1e400"},"id":"u7"}',
        reference="ruling 27 and ruling 13 of 0.6: on geojson an unmapped number is residue with its text as "
                  "written, and comes back as a string")

    # ==========================================================================
    # load vectors from 500
    # ==========================================================================
    MODELS = [
        "module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\nkey lat float deg\n"
        "key callsign string -\nkey time_ms int ms\n",
        "module probe\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey label string -\nkey x int -\n"
        "key n int -\nkey a float -\nkey s1 string -\n",
    ]
    HEAD = 'format probe\nversion 0.15.0\ndistribution public\nsource "probe"\nuses probe\n'
    BITS = HEAD + "wire bits\nword_bytes 1\n"
    SEQB = HEAD + "wire bits\nlayout sequential\n"
    PB = HEAD + "wire protobuf\n"
    XML = HEAD + "wire xml\nroot msg\n"
    JS = HEAD + "wire json\n"
    GJ = HEAD + "wire geojson\n"
    lnum = [499]

    def L(name, pack, error="bad-directive", models=None):
        lnum[0] += 1
        full = "%d-transforms-%s" % (lnum[0], name)
        d = {"name": full, "models": models or MODELS, "pack": pack}
        if error:
            d["expect_error"] = error
        sink.write("packs/conformance/load-vectors/%s.json" % full, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written["load"] = written.get("load", 0) + 1

    def ok(name, pack, models=None):
        L(name, pack, None, models)

    # a transform on a wire it does not list
    L("uiscale-on-json", JS + "field probe.x x uiscale:1\n")
    L("smag-on-xml", XML + "field probe.x @x smag\n")
    L("chars-on-json", JS + "field probe.s1 s chars:ais6\n")
    L("octal-on-protobuf", PB + "field probe.s1 1 octal\n")
    L("f32scale-on-geojson", GJ + "field probe.a properties.a f32scale:1\n")
    L("iscale-on-bits", BITS + "field probe.x 0:0:8 iscale:1\n")
    L("scale-on-bits", BITS + "field probe.a 0:0:8 scale:1\n")
    L("iscale-on-protobuf", PB + "field probe.x 1 iscale:1\n")
    L("scale-on-protobuf", PB + "field probe.a 1 scale:1\n")
    ok("scale-and-iscale-on-text-wires-load",
       JS + "field probe.a a scale:0.1:-5.5\nfield probe.x x iscale:1/3:-7\n")
    ok("scale-on-a-geojson-slot-and-iscale-on-a-property-load", GJ + "field lat geometry.lat scale:1/10000000\n"
       "field probe.x properties.x iscale:1000\n")
    # a len the transform does not allow
    L("uiscale-len-65", BITS + "field probe.x 0:0:65 uiscale:1\n")
    L("siscale-len-65", BITS + "field probe.x 0:0:65 siscale:1\n")
    L("smag-len-1", BITS + "field probe.x 0:0:1 smag\n")
    L("smscale-len-1", BITS + "field probe.a 0:0:1 smscale:1\n")
    ok("uiscale-len-1-and-smag-len-2-and-64-load",
       BITS + "field probe.x 0:0:1 uiscale:1\nfield probe.n 0:1:2 smag\nfield probe.x 0:8:64 smag\n")
    L("f32scale-len-64", BITS + "field probe.a 0:0:64 f32scale:1\n")
    L("f64scale-len-32", BITS + "field probe.a 0:0:32 f64scale:1\n")
    L("chars-ais6-len-8", BITS + "field probe.s1 0:0:8 chars:ais6\n")
    L("chars-ascii7-len-6", BITS + "field probe.s1 0:0:6 chars:ascii7\n")
    L("chars-ais6-len-2046", BITS + "field probe.s1 0:0:2046 chars:ais6\n")
    L("chars-ascii7-len-2044", BITS + "field probe.s1 0:0:2044 chars:ascii7\n")
    ok("chars-longest-fields-load", BITS + "field probe.s1 0:0:2040 chars:icao6\nfield callsign 0:0:2037 chars:ascii7\n")
    L("octal-len-4", BITS + "field probe.s1 0:0:4 octal\n")
    L("octal-len-66", BITS + "field probe.s1 0:0:66 octal\n")
    ok("octal-len-3-and-63-load", BITS + "field probe.s1 0:0:3 octal\nfield callsign 0:3:63 octal\n")
    L("chars-in-a-sequential-layout-len-8", SEQB + "field probe.s1 8 chars:ais6\n")
    ok("transforms-in-a-sequential-layout-load", SEQB + "field probe.x 13 siscale:-1/10:5\nfield probe.n 7 smag\n"
       "field probe.s1 12 chars:ais6\nfield callsign 9 octal\nfield probe.a 32 f32scale:0.5\n")
    # factors
    L("factor-0", BITS + "field probe.x 0:0:8 uiscale:0\n")
    L("ruling-19-factor-minus-0", BITS + "field probe.x 0:0:8 uiscale:-0\n")
    L("factor-0-over-5", BITS + "field probe.x 0:0:8 uiscale:0/5\n")
    L("factor-0-point-000", BITS + "field probe.x 0:0:8 siscale:0.000\n")
    L("denominator-0", BITS + "field probe.x 0:0:8 uiscale:1/0\n")
    ok("ruling-19-factor-2-to-the-32-loads", BITS + "field probe.x 0:0:8 uiscale:4294967296\n"
       "field probe.n 0:8:8 uiscale:1/4294967296\n")
    L("ruling-19-factor-2-to-the-32-plus-1", BITS + "field probe.x 0:0:8 uiscale:4294967297\n")
    L("denominator-2-to-the-32-plus-1", BITS + "field probe.x 0:0:8 uiscale:1/4294967297\n")
    ok("ruling-9-huge-digits-that-reduce-to-fit-load",
       BITS + "field probe.x 0:0:8 uiscale:8589934592/2\n"
       "field probe.n 0:8:8 siscale:100000000000000000000000000000/100000000000000000000000000000\n"
       "field probe.x 0:16:8 uiscale:2.500000000000000000000000000000\n")
    L("ruling-9-fraction-that-reduces-to-2-to-the-32-plus-1", BITS + "field probe.x 0:0:8 uiscale:8589934594/2\n")
    L("ruling-9-decimal-with-a-denominator-above-2-to-the-32", BITS + "field probe.x 0:0:8 uiscale:0.0000000001\n")
    L("factor-with-an-exponent", BITS + "field probe.x 0:0:8 uiscale:1e3\n")
    L("factor-bare-fraction", BITS + "field probe.x 0:0:8 uiscale:.5\n")
    L("factor-bare-point", BITS + "field probe.x 0:0:8 uiscale:5.\n")
    L("factor-missing", BITS + "field probe.x 0:0:8 uiscale\n")
    L("factor-empty", BITS + "field probe.x 0:0:8 uiscale:\n")
    L("factor-two-slashes", BITS + "field probe.x 0:0:8 uiscale:1/2/3\n")
    L("three-parameters", BITS + "field probe.x 0:0:8 uiscale:1:2:3\n")
    L("iscale-factor-0", JS + "field probe.x x iscale:0\n")
    # offsets
    ok("ruling-19-offset-bounds-load", BITS + "field probe.x 0:0:8 uiscale:1:-9223372036854775807\n"
       "field probe.n 0:8:8 siscale:1:9223372036854775807\n")
    L("ruling-19-offset-minus-2-to-the-63", BITS + "field probe.x 0:0:8 uiscale:1:-9223372036854775808\n")
    L("offset-2-to-the-63", BITS + "field probe.x 0:0:8 siscale:1:9223372036854775808\n")
    L("offset-with-a-fraction", BITS + "field probe.x 0:0:8 uiscale:1:1.5\n")
    L("iscale-offset-with-a-fraction", XML + "field probe.x @x iscale:1:0.5\n")
    L("offset-with-plus", BITS + "field probe.x 0:0:8 uiscale:1:+5\n")
    # signs (ruling 11)
    ok("ruling-11-minus-before-the-numerator-loads", BITS + "field probe.x 0:0:8 siscale:-1/10\n"
       "field probe.n 0:8:8 uiscale:-0.5\n")
    L("ruling-11-minus-before-the-denominator", BITS + "field probe.x 0:0:8 siscale:1/-10\n")
    L("ruling-11-minus-on-both", BITS + "field probe.x 0:0:8 siscale:-1/-10\n")
    L("ruling-11-plus-before-the-numerator", BITS + "field probe.x 0:0:8 siscale:+1/10\n")
    L("ruling-11-plus-on-a-decimal", BITS + "field probe.x 0:0:8 uiscale:+2\n")
    # float scales read as sscale does (ruling 12)
    ok("ruling-12-smscale-and-f32scale-take-a-float-offset",
       BITS + "field probe.a 0:0:8 smscale:0.5:0.25\nfield probe.a 0:8:32 f32scale:0.5:0.25\n"
       "field probe.a 0:40:64 f64scale:1/3:-2.5\n")
    # character sets, swap, trim, absent
    L("unknown-character-set", BITS + "field probe.s1 0:0:48 chars:ascii9\n")
    L("character-set-missing", BITS + "field probe.s1 0:0:48 chars\n")
    L("character-set-empty", BITS + "field probe.s1 0:0:48 chars:\n")
    L("swap-with-chars", BITS + "field probe.s1 0:0:48 chars:ais6 swap\n")
    L("swap-with-octal", BITS + "field probe.s1 0:0:24 octal swap\n")
    ok("swap-with-integer-scales-loads", BITS + "field probe.x 0:0:16 uiscale:1 swap\n"
       "field probe.n 0:16:16 smag swap\n")
    L("ruling-18-trim-with-ascii7", BITS + "field probe.s1 0:0:49 chars:ascii7 trim\n")
    L("ruling-18-trim-with-ais6", BITS + "field probe.s1 0:0:48 chars:ais6 trim\n")
    L("ruling-18-trim-with-uiscale", BITS + "field probe.x 0:0:8 uiscale:1 trim\n")
    L("ruling-1-absent-on-chars-longer-than-64-bits", BITS + "field probe.s1 0:0:72 chars:ais6 absent 0\n")
    same(0x820820820820, cv("", "icao6", 8))
    ok("ruling-1-absent-on-chars-and-octal-loads", BITS + "field probe.s1 0:0:48 chars:icao6 absent %d\n" % 0x820820820820 +
       "field callsign 0:48:12 octal absent 0\nfield probe.x 0:64:8 smag absent 128\n")
    ok("ruling-2-via-on-a-scale-and-on-chars-loads", BITS + "map lvl 1 low\nmap cs AB alpha\n"
       "field probe.label 0:0:8 uiscale:1/2 via lvl\nfield probe.s1 0:8:12 chars:ais6 via cs\n")
    # rulings 20 to 26, added later
    assert lnum[0] == 570, lnum[0]
    L("ruling-25-scale-fraction-with-a-sign", JS + "field probe.a a scale:-1/10\n")
    ok("ruling-25-scale-negative-decimal-loads", JS + "field probe.a a scale:-0.1\n")
    L("ruling-25-smscale-fraction-with-a-sign", BITS + "field probe.a 0:0:8 smscale:-1/4\n")
    # ruling 25 as extended: every fraction factor of a float scale, and of the derive function scale:
    L("ruling-25-sscale-fraction-with-a-sign", BITS + "field probe.a 0:0:8 sscale:-1/10\n")
    L("ruling-25-uscale-fraction-with-a-sign", BITS + "field probe.a 0:0:8 uscale:-1/2\n")
    ok("ruling-25-derive-scale-signed-numerator-loads", JS + "field probe.a a float\n", models=[
        MODELS[0],
        "module probe\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey a float -\nkey scaled float -\n"
        "derive probe.scaled scale:-1/4 probe.a\n"])
    ok("ruling-25-sscale-negative-decimal-loads", BITS + "field probe.a 0:0:8 sscale:-0.1\n")
    # ruling 25 on the tlv wire of 0.13, whose uscale is "as on bits"
    L("ruling-25-uscale-fraction-with-a-sign-on-tlv",
      HEAD + "wire tlv\nfield probe.a 5:1 uscale:-1/10\n")
    # ruling 28: a transform of this version on tlv, refused after the file
    L("ruling-28-iscale-on-tlv", HEAD + "wire tlv\nfield probe.a 5:1 iscale:10\n")
    L("ruling-28-on-tlv-a-later-line-error-comes-first",
      HEAD + "wire tlv\nfield probe.a 5:1 scale:0.5\nbogus\n", "unknown-directive")
    assert lnum[0] == 580, lnum[0]
    return written


def main(argv=None):
    return genio.vector_main("conformance-transforms-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
