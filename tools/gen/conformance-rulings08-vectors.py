#!/usr/bin/env python3
"""Write the vectors that pin rulings 16 to 30 of spec 0.8 ("Stated, not yet
pinned by a vector"): the packs `conformance-seq-rulings-*`, vectors added to
`conformance-seq-json`, `conformance-derive-functions` and
`conformance-rules-protobuf`, and the load vectors from 262.

Every expected value here is worked out from the spec text and the pack
layouts. A message is written as the list of its bit fields in reading order,
(value, bit length), and `bits` lays them out most significant bit first;
where the bytes were also worked out on paper the script checks the two
agree. Nothing calls an engine.

Usage: tools/gen/conformance-rulings08-vectors.py <repository root>
"""
import json
import os
import sys

ROOT = sys.argv[1]
written = {}


def vec(pack, num, name, frm, to, inp, expect=None, error=None, model=None, context=None):
    d = {"name": name, "from": frm, "to": to, "input": inp}
    if context is not None:
        d["context"] = context
    if error:
        d["expect_error"] = error
    else:
        d["expect"] = expect
    if model:
        d["model"] = model
    path = os.path.join(ROOT, "packs", pack, "vectors", "%02d-%s.json" % (num, name))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.write("\n")
    written[pack] = written.get(pack, 0) + 1


def bits(fields, paper=None):
    """The bytes of a message given as (value, bit length) fields in reading
    order, most significant bit first, zero bits to the whole byte."""
    seq = []
    for v, n in fields:
        v &= (1 << n) - 1
        seq += [(v >> (n - 1 - i)) & 1 for i in range(n)]
    while len(seq) % 8:
        seq.append(0)
    out = bytearray()
    for i in range(0, len(seq), 8):
        b = 0
        for k in range(8):
            if seq[i + k]:
                b |= 0x80 >> k
        out.append(b)
    h = bytes(out).hex()
    if paper is not None:
        assert h == paper.replace(" ", ""), (h, paper)
    return h


def hx(s):
    return s.replace(" ", "")


SJ = "conformance-seq-json"
RB, RK, RL, RE = (
    "conformance-seq-rulings-b",
    "conformance-seq-rulings-kinds",
    "conformance-seq-rulings-lists",
    "conformance-seq-rulings-extent",
)
DF, RP = "conformance-derive-functions", "conformance-rules-protobuf"
# json-source vectors are owned by conformance-seq-json; 1 to 28 are written
# by conformance-seq-vectors.py
jn = [28]


def from_json(name, to, inp, expect=None, error=None, model=None):
    jn[0] += 1
    vec(SJ, jn[0], name, SJ, to, inp, expect, error, model)


# ==========================================================================
# conformance-seq-rulings-b: rulings 16, 19 and 22
# ==========================================================================
# Ruling 16. The entity holds none of w, val, qty: the byte is the default of
# the earliest key that has one, val 200, which the table writes as 2. No
# presence bit; the opt bit 0; y is its default 5.
b1 = bits([(1, 8), (0, 3), (0, 5), (2, 8), (0, 1), (5, 8)], paper="01 00 02 02 80")
from_json("ruling-16-none-held-default-of-the-earliest-key-that-has-one", RB, '{"n":1}', b1)
# the entity holds qty, the last of the three keys: a held key is written
# before the default of an earlier key
from_json("ruling-16-held-key-is-written-not-an-earlier-default", RB, '{"n":1,"qty":7}',
          bits([(1, 8), (0, 8), (7, 8), (0, 1), (5, 8)], paper="01 00 07 02 80"))
# val and qty are held: val is the earlier, 100 is 1 on the wire
from_json("ruling-16-earliest-held-key", RB, '{"n":1,"val":100,"qty":7}',
          bits([(1, 8), (0, 8), (1, 8), (0, 1), (5, 8)], paper="01 00 01 02 80"))
# decode fills all three keys from the byte, and w is then the earliest held
vec(RB, 1, "ruling-16-roundtrip-every-key-filled", RB, RB, b1, b1,
    model={"probe.w": "2", "probe.val": "200", "probe.qty": "2", "probe.y": "5"})
# Ruling 19. `default probe.y 5` is written inside the `opt` block and y is a
# field after the block: the default is the message's, so y is 5 here and in
# every vector above. x is present: the opt bit is 1.
from_json("ruling-19-default-inside-a-block-is-the-message-s", RB, '{"n":1,"x":3}',
          bits([(1, 8), (0, 8), (2, 8), (1, 1), (3, 8), (5, 8)], paper="01 00 02 81 82 80"))
# Ruling 22. z is content of the block p.1 although it sits in a nested
# `if !p.2` that is not written: c1 sets p.2. The block p.1 is written and
# holds only its constant.
b6 = bits([(1, 8), (0b110, 3), (0, 5), (2, 8), (0, 1), (5, 8), (170, 8), (6, 8)], paper="01 c0 02 02 d5 03 00")
from_json("ruling-22-content-under-a-nested-condition-that-does-not-hold", RB, '{"n":1,"z":4,"c1":6}', b6)
# only c1: a `const` is not content, p.1 is 0
b8 = bits([(1, 8), (0b010, 3), (0, 5), (2, 8), (0, 1), (5, 8), (6, 8)], paper="01 40 02 02 83 00")
from_json("ruling-22-a-const-is-not-content", RB, '{"n":1,"c1":6}', b8)
# decoding b6 gives c1 and no z, so it is written back as b8
vec(RB, 2, "ruling-22-block-that-held-only-its-const-is-not-written-back", RB, RB, b6, b8, model={"probe.c1": "6"})
# only z: p.1, z, the constant
from_json("ruling-22-nested-condition-holds", RB, '{"n":1,"z":4}',
          bits([(1, 8), (0b100, 3), (0, 5), (2, 8), (0, 1), (5, 8), (4, 8), (170, 8)], paper="01 80 02 02 82 55 00"))
# c2 lies in an `opt` in a chain in a `length` in the block p.3: it sets p.3,
# the chain's fx bit and the opt bit. The length block is 7 + 1 + 1 + 7 bits.
b9 = bits([(1, 8), (0b001, 3), (0, 5), (2, 8), (0, 1), (5, 8), (2, 8), (1, 7), (1, 1), (1, 1), (3, 7)], paper="01 20 02 02 81 01 c1 80")
from_json("ruling-22-content-at-any-depth-of-length-chain-and-opt", RB, '{"n":1,"c2":3}', b9)
vec(RB, 3, "ruling-22-content-at-any-depth-roundtrip", RB, RB, b9, b9, model={"probe.c2": "3"})

# ==========================================================================
# conformance-seq-rulings-kinds: rulings 17, 18, 25 and 27
# ==========================================================================
# Ruling 17. Kind a, p.1 is 1 on the wire. No block of kind a names p.1; a
# block of kind b does, so the bit is one an `if` names and the message
# decodes. Encode writes it 0.
vec(RK, 1, "ruling-17-bit-named-only-in-another-kind", RK, RK, hx("01 80 01 05 03"), hx("01 00 01 05 03"),
    model={"@kind": "a", "probe.x": "5", "probe.z": "3"})
# p.2 is named only with `!`. It is 1: the block is not read. Encode writes
# the bit 0 (ruling 4) and with it the block, x as zero bits.
vec(RK, 2, "ruling-17-bit-named-only-with-not", RK, RK, hx("01 40 01 08"), hx("01 00 01 00 08"),
    model={"@kind": "a", "probe.z": "8"})
# Ruling 18. The `when` of kind a follows its `requires` and `default` lines.
# x selects kind a; z is its default 3.
from_json("ruling-18-when-after-requires-and-default", RK, '{"n":1,"x":5}', hx("01 00 01 05 03"))
# Ruling 27. Every item of recs starts with the nibble 9.
k4 = bits([(1, 8), (0, 8), (2, 8), (2, 8), (9, 4), (1, 4), (7, 8), (9, 4), (0, 4)], paper="01 00 02 02 91 07 90")
vec(RK, 3, "ruling-27-common-when-of-every-item-roundtrip", RK, RK, k4, k4,
    model={"@kind": "b", "probe.recs.#": "2", "probe.recs[0].@kind": "point", "probe.recs[0].probe.y": "7",
           "probe.recs[1].@kind": "empty"})
# the item starts with the nibble 8
vec(RK, 4, "ruling-27-item-that-fails-the-common-when", RK, RK, hx("01 00 02 01 81 07"), error="no-kind")
# no x: kind a is not selected; kind b requires nothing. The common `when`
# is written before each item's kind.
from_json("ruling-27-common-when-written-for-every-item", RK, '{"n":1,"recs":[{"y":7},{}]}', k4)
# Ruling 25. Kind c, p.1 is 0: an item of nums takes no bits. The count is 5
# and no bit is left: `malformed-wire`, though 5 items of no bits would fit.
vec(RK, 5, "ruling-25-count-larger-than-the-bits-left", RK, RK, hx("01 00 03 05"), error="malformed-wire")
# one more byte: 8 bits are left and the count is 5. Five items with no key;
# the byte is beyond the last line and ignored.
vec(RK, 6, "ruling-25-count-within-the-bits-left", RK, RK, hx("01 00 03 05 ff"), hx("01 00 03 05"),
    model={"@kind": "c", "probe.nums.#": "5"})
# p.1 is 1: an item is one byte
k8 = hx("01 80 03 02 07 08")
vec(RK, 7, "ruling-12-message-presence-named-inside-an-item-roundtrip", RK, RK, k8, k8,
    model={"probe.nums.#": "2", "probe.nums[1].probe.val": "8"})

# ==========================================================================
# conformance-seq-rulings-lists: rulings 23 and 26
# ==========================================================================
# p.1 only: the first group, one item of kind small. Encode: the list has an
# item, so both blocks have content and both bits are 1; the first block
# needs p.2 to be 0 and is not written. In the second group the item's kind
# `small` is not a kind: it selects by `requires`, x, which is kind wide.
l2 = hx("01 c0 01 02 00 05")
vec(RL, 1, "ruling-26-item-kind-the-group-does-not-have-selects-by-requires", RL, RL, hx("01 80 01 01 05"), l2,
    model={"probe.recs.#": "1", "probe.recs[0].@kind": "small", "probe.recs[0].probe.x": "5"})
vec(RL, 2, "ruling-23-second-group-of-the-list-roundtrip", RL, RL, l2, l2,
    model={"probe.recs.#": "1", "probe.recs[0].@kind": "wide", "probe.recs[0].probe.x": "5"})
# kind tiny, no x: wide requires x, none requires nothing
vec(RL, 3, "ruling-26-item-with-no-required-key-selects-the-kind-that-requires-none", RL, RL, hx("01 80 01 00"), hx("01 c0 01 00"),
    model={"probe.recs[0].@kind": "tiny"})
# a list of no items sets no bit (ruling 5)
vec(RL, 4, "ruling-23-empty-list-in-the-first-group", RL, RL, hx("01 80 00"), hx("01 00"), model={"probe.recs.#": "0"})
from_json("ruling-23-list-in-two-groups-written-once", RL, '{"n":1,"recs":[{"x":5}]}', l2)

# ==========================================================================
# conformance-seq-rulings-extent: rulings 20 and 21
# ==========================================================================
# Ruling 21. Each length is in bits and ends where the line under test
# starts; the bits after the extent are 1, so an engine that reads them
# gives another result. Decode is checked through the json mirror.
# while: x, one item (1, val 9); the next indicator bit starts at the end
e1 = bits([(1, 8), (1, 8), (16, 8), (5, 8), (1, 1), (9, 7), (0xFF, 8)], paper="01 01 10 05 89 ff")
vec(RE, 1, "ruling-21-while-indicator-at-the-end-reads-0", RE, SJ, e1, '{"n":1,"x":5,"nums":[9]}')
# encode writes every line: the ending 0 bit is inside the block, 17 bits
vec(RE, 2, "ruling-21-while-written-back-with-its-ending-bit", RE, RE, e1,
    bits([(1, 8), (1, 8), (17, 8), (5, 8), (1, 1), (9, 7), (0, 1)], paper="01 01 11 05 89 00"))
# fx: x, val 9; the bit after the item starts at the end
vec(RE, 3, "ruling-21-fx-group-indicator-at-the-end-reads-0", RE, SJ,
    bits([(1, 8), (2, 8), (15, 8), (5, 8), (9, 7), (1, 1)], paper="01 02 0f 05 13"), '{"n":1,"x":5,"nums":[9]}')
# more: x, the bit 1, val 9; the bit before the second item starts at the
# end and reads 0: the second item is the last. Its line starts at the end
# and reads as absent (ruling 7): an item with no key, `null` on json.
vec(RE, 4, "ruling-21-more-indicator-at-the-end-reads-0", RE, SJ,
    bits([(1, 8), (3, 8), (16, 8), (5, 8), (1, 1), (9, 7), (0xFF, 8)], paper="01 03 10 05 89 ff"), '{"n":1,"x":5,"nums":[9,null]}')
# chain: c1; the first fx starts at the end
vec(RE, 5, "ruling-21-chain-fx-at-the-end-reads-0", RE, SJ,
    bits([(1, 8), (4, 8), (7, 8), (5, 7), (1, 1)], paper="01 04 07 0b"), '{"n":1,"c1":5}')
# chain: c1, fx 1, c2; the last fx starts at the end and reads 0 (a 1 there
# would be `malformed-wire` by ruling 3)
vec(RE, 6, "ruling-21-last-fx-of-a-chain-at-the-end-reads-0", RE, SJ,
    bits([(1, 8), (4, 8), (15, 8), (5, 7), (1, 1), (6, 7), (1, 1)], paper="01 04 0f 0b 0d"), '{"n":1,"c1":5,"c2":6}')
# presence: x; both presence fields start at the end and read as 0
vec(RE, 7, "ruling-21-presence-at-the-end-reads-0", RE, SJ,
    bits([(1, 8), (5, 8), (8, 8), (5, 8), (0xFF, 8)], paper="01 05 08 05 ff"), '{"n":1,"x":5}')
# x, p 00, the first octet of f with its extension bit 1: the next octet
# starts at the end
vec(RE, 8, "ruling-21-continuation-octet-of-an-fx-presence-at-the-end", RE, RE,
    bits([(1, 8), (5, 8), (18, 8), (5, 8), (0, 2), (0, 7), (1, 1), (0x3F, 6), (0xFF, 8)], paper="01 05 12 05 00 7f ff"), error="malformed-wire")
# skips: x; `const`, `pad`, `opt` and the nested `length` start at the end
# and read as absent; y is the byte after the extent
vec(RE, 9, "ruling-21-const-pad-opt-and-length-at-the-end-read-as-absent", RE, SJ,
    hx("01 06 08 05 07"), '{"n":1,"x":5,"y":7}')
# Ruling 20. x ends at bit 20 and the input at bit 24: `align 16` stops there
vec(RE, 10, "ruling-20-align-stops-at-the-end-of-the-input", RE, SJ, hx("01 07 50"), '{"n":1,"x":5}')
# encode writes zero bits to bit 32
vec(RE, 11, "ruling-20-align-written-in-full", RE, RE, hx("01 07 50"), hx("01 07 50 00"), model={"probe.x": "5"})
# the extent is one byte, bits 24 to 31; `align 64` stops at its end and y
# is the byte after it
vec(RE, 12, "ruling-20-align-stops-at-the-end-of-the-extent", RE, SJ, hx("01 08 01 50 07"), '{"n":1,"x":5,"y":7}')
# encode: the block runs from bit 24 to bit 64, 5 bytes
vec(RE, 13, "ruling-20-align-in-an-extent-written-in-full", RE, RE, hx("01 08 01 50 07"), hx("01 08 05 50 00 00 00 00 07"))
vec(RE, 14, "ruling-20-const-past-the-end-of-the-input", RE, RE, hx("01 09 05"), error="malformed-wire")
vec(RE, 15, "ruling-20-pad-past-the-end-of-the-input", RE, RE, hx("01 0a 05"), error="malformed-wire")

# ==========================================================================
# Ruling 28: parse_int. An empty context, so the derivations run.
# ==========================================================================
def pi(num, name, text, parsed=None):
    inp = json.dumps({"s1": text}, separators=(",", ":"))
    out = inp if parsed is None else inp[:-1] + ',"parsed":%s}' % parsed
    vec(DF, num, name, DF, DF, inp, out, context={})


pi(7, "ruling-28-leading-zeros", "007", "7")
pi(8, "ruling-28-minus-and-leading-zeros", "-007", "-7")
pi(9, "ruling-28-minus-zero", "-0", "0")
pi(10, "ruling-28-plus-sign-is-not-accepted", "+5")
pi(11, "ruling-28-largest-64-bit-integer", "9223372036854775807", "9223372036854775807")
pi(12, "ruling-28-one-beyond-the-largest", "9223372036854775808")
pi(13, "ruling-28-smallest-64-bit-integer", "-9223372036854775808", "-9223372036854775808")
pi(14, "ruling-28-one-beyond-the-smallest", "-9223372036854775809")
pi(15, "ruling-28-minus-alone", "-")
pi(16, "ruling-28-empty-text", "")
pi(17, "ruling-28-space-before-the-digits", " 5")
pi(18, "ruling-28-space-after-the-digits", "5 ")
pi(19, "ruling-28-exponent", "1e3")
pi(20, "ruling-28-two-minus-signs", "--5")

# ==========================================================================
# Ruling 30: a path prefix that is not a submessage, outside a group. `lat`
# is at 4.1; field 4 is a varint (tag 0x20, value 5).
# ==========================================================================
vec(RP, 11, "ruling-30-path-prefix-outside-a-group-is-not-a-submessage", RP, RP, hx("0a 01 75 20 05"), error="malformed-wire")

# ==========================================================================
# Load vectors
# ==========================================================================
CORE = 'module core\nversion 0.1.0\ndistribution public\nsource "probe"\nkey uid string -\nkey type string -\nkey lat float deg\nkey lon float deg\nkey callsign string -\nkey time_ms int ms\n'
PM = 'module probe\nversion 0.1.0\ndistribution public\nsource "probe"\nkey label string -\nkey qty int -\nkey x int -\nkey y int -\nkey a float -\nlist items "a list"\nlist subs "a nested list"\n'
HEAD8 = 'format probe\nversion 0.8.0\ndistribution public\nsource "probe"\nuses probe\n'
SEQ = HEAD8 + 'wire bits\nlayout sequential\nfield probe.qty 8 uint\n'
JS8 = HEAD8 + 'wire json\nfield uid id string\n'
n = 262


def L(name, pack, error=None, models=None, limit=None):
    global n
    full = "%d-%s" % (n, name)
    d = {"name": full, "models": models if models is not None else [CORE, PM], "pack": pack}
    if limit:
        d["max_distribution"] = limit
    if error:
        d["expect_error"] = error
    with open(os.path.join(ROOT, "packs", "conformance", "load-vectors", full + ".json"), "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.write("\n")
    written["load"] = written.get("load", 0) + 1
    n += 1


FX = 'field probe.x 8 uint\n'
G = 'group probe.items count 8\n  field probe.x 8 uint\nend\n'
# ruling 18
L("ruling-18-when-after-requires-and-default-loads", SEQ + 'kind a\nrequires probe.x\ndefault probe.x 1\nwhen 8 1\n' + FX)
L("ruling-18-when-after-a-default-and-a-field", SEQ + 'kind a\ndefault probe.x 1\n' + FX + 'when 8 1\n', "bad-directive")
# ruling 23
L("ruling-23-list-in-two-if-blocks-loads", SEQ + 'presence p 2\nif p.1\n' + G + 'end\nif p.2\n' + G + 'end\n')
L("ruling-23-list-in-two-opt-blocks-loads", SEQ + 'opt\n' + G + 'end\nopt\n' + G + 'end\n')
L("ruling-23-list-in-an-if-and-an-opt-block-loads", SEQ + 'presence p 2\nif p.1\n' + G + 'end\nopt\n' + G + 'end\n')
L("ruling-23-list-in-two-groups-of-one-block", SEQ + 'opt\n' + G + G + 'end\n', "bad-directive")
L("ruling-23-list-in-two-groups-outside-any-block", SEQ + G + G, "bad-directive")
L("ruling-23-one-group-of-the-list-outside-any-block", SEQ + G + 'opt\n' + G + 'end\n', "bad-directive")
L("ruling-23-list-in-two-length-blocks", SEQ + 'length 8\n' + G + 'end\nlength 8\n' + G + 'end\n', "bad-directive")
L("ruling-23-list-in-two-parts-of-a-chain", SEQ + 'chain\n' + G + 'fx\n' + G + 'end\n', "bad-directive")
L("ruling-23-list-in-the-common-lines-and-in-a-kind", SEQ + G + 'kind a\nwhen 8 1\n' + G, "bad-directive")
L("ruling-23-list-in-two-kinds-loads", SEQ + 'kind a\nwhen 8 1\n' + G + 'kind b\nwhen 8 2\n' + G)
SUBS = '  group probe.subs count 8\n    field probe.y 8 uint\n  end\n'
L("ruling-23-list-in-two-groups-of-an-item", SEQ + 'group probe.items count 8\n' + SUBS + SUBS + 'end\n', "bad-directive")
L("ruling-23-list-in-two-opt-blocks-of-an-item-loads", SEQ + 'group probe.items count 8\n  opt\n' + SUBS + '  end\n  opt\n' + SUBS + '  end\nend\n')
# ruling 24: header and table directives inside a block
HEADERS = [("format", 'format other'), ("version", 'version 2'), ("distribution", 'distribution public'), ("source", 'source "probe"'),
           ("uses", 'uses probe'), ("wire", 'wire bits'), ("layout", 'layout sequential'), ("bit-order", 'bit_order msb'),
           ("map", 'map t 1 2'), ("typemap", 'typemap A a-f-G')]
for word, line in HEADERS:
    L("ruling-24-%s-inside-an-opt-block" % word, SEQ + 'opt\n  ' + FX + '  ' + line + '\nend\n', "bad-directive")
L("ruling-24-format-inside-an-if-block", SEQ + 'presence p 1\nif p.1\n  ' + FX + '  format other\nend\n', "bad-directive")
L("ruling-24-map-inside-a-chain", SEQ + 'chain\n  ' + FX + '  map t 1 2\nend\n', "bad-directive")
L("ruling-24-wire-inside-a-length-block", SEQ + 'length 8\n  ' + FX + '  wire bits\nend\n', "bad-directive")
L("ruling-24-version-inside-a-sequential-group", SEQ + 'group probe.items count 8\n  ' + FX + '  version 2\nend\n', "bad-directive")
for word, line in [("format", 'format other'), ("version", 'version 2'), ("wire", 'wire json'), ("distribution", 'distribution public'),
                   ("layout", 'layout fixed'), ("typemap", 'typemap A a-f-G')]:
    L("ruling-24-%s-inside-a-json-group" % word, JS8 + 'group probe.items items\n  field probe.label name string\n  ' + line + '\nend\n', "bad-directive")
# ruling 27
L("ruling-27-when-before-the-first-kind-of-a-group-loads", SEQ + 'group probe.items count 8\n  when 8 9\n  kind a\n  when 8 1\n  kind b\n  when 8 2\nend\n')
# ruling 29: a chain is one block for presence names
L("ruling-29-presence-of-a-chain-part-named-in-a-later-part-loads", SEQ + 'chain\n  presence p 2\n  fx\n  if p.1\n    ' + FX + '  end\nend\n')
L("ruling-29-presence-declared-in-two-parts-of-a-chain", SEQ + 'chain\n  presence p 2\n  fx\n  presence p 2\nend\n', "bad-directive")
L("ruling-29-presence-of-a-chain-named-after-the-chain", SEQ + 'chain\n  presence p 2\n  fx\nend\nif p.1\n  ' + FX + 'end\n', "bad-directive")
L("ruling-29-chain-hides-an-outer-presence-name-loads", SEQ + 'presence p 2\nchain\n  presence p 4\n  if p.4\n    ' + FX + '  end\nend\nif p.2\n  ' + FX + 'end\n')
# ruling 29: the order of the checks for a module. Each module below fails
# the named check and every check after it in the order.
BODY = 'uses nosuch\nkey o int -\nkey t string -\nderive other.o copy other.nokey\n'
PUB = 'module other\nversion 0.1.0\ndistribution public\nsource "probe"\n'
CTL = PUB.replace('public', 'controlled')
L("ruling-29-module-missing-distribution-comes-first", JS8, "missing-distribution", [CORE, PM, 'module other\nversion 0.1.0\n' + BODY], "public")
L("ruling-29-module-missing-source-before-distribution-refused", JS8, "missing-source",
  [CORE, PM, 'module other\nversion 0.1.0\ndistribution controlled\n' + BODY], "public")
L("ruling-29-module-distribution-refused-before-unknown-module", JS8, "distribution-refused", [CORE, PM, CTL + BODY], "public")
L("ruling-29-module-unknown-module-before-the-derive-checks", JS8, "unknown-module", [CORE, PM, PUB + BODY])
PMC = PM.replace('distribution public', 'distribution controlled')
L("ruling-29-module-distribution-violation-before-the-derive-checks", JS8, "distribution-violation",
  [CORE, PMC, PUB + BODY.replace('nosuch', 'probe')])
OTHER = PUB + 'uses probe\nkey o int -\nkey t string -\n'
L("ruling-29-module-derive-check-before-duplicate-module", JS8, "bad-directive", [CORE, PM, OTHER, OTHER + 'derive other.o copy other.nokey\n'])
L("ruling-29-module-loaded-twice", JS8, "duplicate-module", [CORE, PM, OTHER, OTHER])
L("ruling-29-derive-target-is-a-key-of-core-loads", JS8, None, [CORE, PM, OTHER + 'derive callsign copy other.t\n'])
L("ruling-29-derive-target-is-a-key-of-a-used-module", JS8, "bad-directive", [CORE, PM, OTHER + 'derive probe.label copy other.t\n'])
# ruling 30: ruling 21 of 0.7, a field at exactly the group's own path
JG = 'group probe.items items\n  field probe.label name string\nend\n'
L("ruling-30-json-field-at-the-group-path-loads", JS8 + JG + 'field probe.label items string\n')
L("ruling-30-geojson-field-at-the-group-path-loads", HEAD8 + 'wire geojson\nfield uid id string\ngroup probe.items properties.items\n  field probe.label name string\nend\nfield probe.label properties.items string\n')
L("ruling-30-protobuf-field-at-the-group-path-loads", HEAD8 + 'wire protobuf\nfield uid 1 pstring\ngroup probe.items 2\n  field probe.label 1 pstring\nend\nfield probe.label 2 pstring\n')
XG = HEAD8 + 'wire xml\nroot msg\nfield uid @id string\ngroup probe.items body/item\n  field probe.label @name string\nend\n'
L("ruling-30-xml-attribute-of-the-group-element", XG + 'field probe.label body/item/@first string\n', "bad-directive")
L("ruling-30-xml-text-of-the-group-element", XG + 'field probe.label body/item/#text string\n', "bad-directive")

for k_, v_ in sorted(written.items()):
    print(k_, v_)
