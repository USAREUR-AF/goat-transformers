#!/usr/bin/env python3
"""Write the vectors of spec 0.8, sequential binary layouts: the packs
`conformance-seq-*` and the load vectors from 174.

Every expected value here is worked out from the spec text and the pack
layouts. A message is written as the list of its bit fields in reading order,
(value, bit length), and `bits` lays them out in the pack's bit order; where
the bytes were also worked out on paper the script checks the two agree.
Nothing calls an engine.

Inputs: none; every value is stated in this file. Writes, under --out, the
vector files named above. The same run always gives the same bytes. With
--check nothing is written and the exit status is 1 when a committed file
differs from what this script writes.

Usage: python3 -I tools/gen/conformance-seq-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402



def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
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
        sink.write("packs/%s/vectors/%s" % (pack, "%02d-%s.json" % (num, name)), json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[pack] = written.get(pack, 0) + 1


    def bits(fields, msb=True, paper=None):
        """The bytes of a message given as (value, bit length) fields in reading
        order, zero bits to the whole byte. msb: the first bit of a field is its
        most significant and goes to the highest free bit of the byte. lsb: the
        first bit is the least significant and goes to the lowest free bit."""
        seq = []
        for v, n in fields:
            if isinstance(v, str):
                assert n == 8 * len(v)
                for ch in v.encode():
                    seq += [(ch >> (7 - i)) & 1 if msb else (ch >> i) & 1 for i in range(8)]
                continue
            v &= (1 << n) - 1
            seq += [(v >> (n - 1 - i)) & 1 if msb else (v >> i) & 1 for i in range(n)]
        while len(seq) % 8:
            seq.append(0)
        out = bytearray()
        for i in range(0, len(seq), 8):
            b = 0
            for k in range(8):
                if seq[i + k]:
                    b |= (0x80 >> k) if msb else (1 << k)
            out.append(b)
        h = bytes(out).hex()
        if paper is not None:
            assert h == paper.replace(" ", ""), (h, paper)
        return h


    def hx(s):
        return s.replace(" ", "")


    SN = "conformance-seq-nested"
    SM, SF, SC, SG, SB, SL, SW, SK, SLS, SJ, GX = (
        "conformance-seq-msb",
        "conformance-seq-fx",
        "conformance-seq-chain",
        "conformance-seq-groups",
        "conformance-seq-groups-bare",
        "conformance-seq-length",
        "conformance-seq-whole",
        "conformance-seq-kinds",
        "conformance-seq-lsb",
        "conformance-seq-json",
        "conformance-groups-xml",
    )
    # json-source vectors are owned by conformance-seq-json and numbered here
    jn = [0]


    def from_json(name, to, inp, expect=None, error=None, model=None):
        jn[0] += 1
        vec(SJ, jn[0], name, SJ, to, inp, expect, error, model)


    # ==========================================================================
    # conformance-seq-msb: fields, const, pad, align, default, kinds, presence
    # <n>, `!`, opt
    # ==========================================================================
    HEAD = [(5, 8), (10, 4), (2, 4)]          # n 5, the constant 10, qty 2
    FLAGS = HEAD + [(1, 8)]                   # the `when` of kind flags
    # no presence bit: p 0000, 4 zero bits to the whole byte, opt 0, pad, val 9
    a1 = bits(FLAGS + [(0, 4), (0, 4), (0, 1), (0, 3), (9, 4)], paper="05 a2 01 00 09")
    vec(SM, 1, "flags-no-presence-bit-roundtrip", SM, SM, a1, a1,
        model={"@kind": "flags", "probe.n": "5", "probe.qty": "2", "probe.val": "9"})
    # p 1100: x 14 in 4 bits, y -2 in 8 bits; the cursor is then at bit 40, a whole
    # byte; opt 1 and the label "ok"; pad; val 6
    a2 = bits(FLAGS + [(0b1100, 4), (14, 4), (-2, 8), (1, 1), ("ok", 16), (0, 3), (6, 4)], paper="05 a2 01 ce fe b7 b5 86")
    vec(SM, 2, "flags-two-presence-bits-and-opt-roundtrip", SM, SM, a2, a2,
        model={"@kind": "flags", "probe.x": "14", "probe.y": "-2", "probe.label": "ok", "probe.val": "6"})
    # p 0011: the block naming p.3 and p.4 is read (z); the block `p.3 !p.4` is not
    a3 = bits(FLAGS + [(0b0011, 4), (0x44, 8), (0, 4), (0, 1), (0, 3), (9, 4)], paper="05 a2 01 34 40 09")
    vec(SM, 3, "if-naming-two-bits-roundtrip", SM, SM, a3, a3, model={"probe.z": "68", "probe.val": "9"})
    # p 0010: p.3 is 1 and p.4 is 0, so the block `p.3 !p.4` is read (w)
    a4 = bits(FLAGS + [(0b0010, 4), (0x55, 8), (0, 4), (0, 1), (0, 3), (9, 4)], paper="05 a2 01 25 50 09")
    vec(SM, 4, "if-with-a-negated-bit-roundtrip", SM, SM, a4, a4, model={"probe.w": "85", "probe.val": "9"})
    # kind plain: when 02 07; val 0x1234 with `swap` is 34 12; ratio -1.5 is -6
    # quarter units, 0xFFA in 12 bits; 4 zero bits to the whole byte
    a7 = bits([(1, 8), (10, 4), (0, 4), (2, 8), (7, 8), (0x34, 8), (0x12, 8), (-6, 12)], paper="01 a0 02 07 34 12 ff a0")
    vec(SM, 5, "plain-two-when-lines-swap-and-scale-roundtrip", SM, SM, a7, a7,
        model={"@kind": "plain", "probe.n": "1", "probe.qty": "0", "probe.val": "4660", "probe.ratio": "-1.5"})
    # the byte after the common lines is 3: no kind's first `when` holds
    vec(SM, 6, "no-kind-holds", SM, SM, hx("05 a2 03 00"), error="no-kind")
    # 02 holds for plain, its second `when` (07) does not
    vec(SM, 7, "second-when-of-a-kind-does-not-hold", SM, SM, hx("05 a2 02 08 34 12 ff a0"), error="no-kind")
    # the input ends where the `when` lines start: a `when` beyond the input does not hold
    vec(SM, 8, "when-beyond-the-input-does-not-hold", SM, SM, hx("05 a2"), error="no-kind")
    # p 0100: y needs bits 28 to 35 and the input has 32
    vec(SM, 9, "input-ends-inside-a-field", SM, SM, hx("05 a2 01 40"), error="malformed-wire")
    # the constant nibble is 5 on the wire (not checked), the bits `align` skips
    # are 1111 and the `pad` bits 111: all are ignored, and written canonically
    vec(SM, 10, "const-align-and-pad-bits-ignored-on-decode", SM, SM, hx("05 52 01 0f 79"), a1, model={"probe.val": "9"})
    vec(SM, 11, "to-json", SM, SJ, a2, '{"n":5,"qty":2,"val":6,"x":14,"y":-2,"label":"ok"}')

    # from json. No kind is named, so the first kind whose `requires` keys are
    # present is taken: plain needs probe.ratio. qty is absent: the default 3.
    from_json("to-msb-presence-computed-from-the-entity-default-qty", SM, '{"n":5,"val":6,"x":14,"y":-2,"label":"ok"}',
              bits([(5, 8), (10, 4), (3, 4), (1, 8), (0b1100, 4), (14, 4), (-2, 8), (1, 1), ("ok", 16), (0, 3), (6, 4)],
                   paper="05 a3 01 ce fe b7 b5 86"))
    # z and w both present: z sets p.3 and p.4, w sets p.3. p is 0011, so the
    # block `p.3 !p.4` is not written and w is not on the wire. val absent: zero bits.
    from_json("to-msb-negated-block-not-written-when-its-bit-is-1", SM, '{"n":5,"z":68,"w":85}',
              bits([(5, 8), (10, 4), (3, 4), (1, 8), (0b0011, 4), (0x44, 8), (0, 4), (0, 1), (0, 3), (0, 4)], paper="05 a3 01 34 40 00"))
    from_json("to-msb-kind-by-requires", SM, '{"n":1,"qty":0,"val":4660,"ratio":-1.5}', a7)
    # the label has three characters, the field holds two
    from_json("to-msb-text-longer-than-its-field", SM, '{"n":5,"label":"abc"}', error="transform-encode")

    # ==========================================================================
    # conformance-seq-fx: presence fx of one, two and three octets
    # ==========================================================================
    # octet 1: f.1 set, extension 0 = 1000000 0. x, then val (f.2 is 0)
    b1 = bits([(1, 8), (0b1000000, 7), (0, 1), (0x11, 8), (0x22, 8)], paper="01 80 11 22")
    vec(SF, 1, "one-octet-roundtrip", SF, SF, b1, b1, model={"probe.n": "1", "probe.x": "17", "probe.val": "34"})
    # f.1 and f.7 in octet 1 with the extension bit, f.8 in octet 2
    b2 = bits([(2, 8), (0b1000001, 7), (1, 1), (0b1000000, 7), (0, 1), (0x11, 8), (0x33, 8), (0x44, 8), (0x22, 8)], paper="02 83 80 11 33 44 22")
    vec(SF, 2, "two-octets-roundtrip", SF, SF, b2, b2, model={"probe.x": "17", "probe.y": "51", "probe.z": "68", "probe.val": "34"})
    # f.15 is the first bit of octet 3; octets 1 and 2 hold only their extension bit
    b3 = bits([(3, 8), (0, 7), (1, 1), (0, 7), (1, 1), (0b1000000, 7), (0, 1), (0x55, 8), (0x22, 8)], paper="03 01 01 80 55 22")
    vec(SF, 3, "three-octets-roundtrip", SF, SF, b3, b3, model={"probe.w": "85", "probe.val": "34"})
    # the input has a second octet that is all zero: encode does not write it
    vec(SF, 4, "trailing-zero-octet-not-written", SF, SF, hx("01 81 00 11 22"), b1, model={"probe.x": "17", "probe.val": "34"})
    # f.2 is 1 on the wire: the `!f.2` block is not read. No block names f.2
    # without `!`, so encode writes it 0, and the `!f.2` block is then written:
    # val is absent, zero bits.
    vec(SF, 5, "bit-named-only-with-not-is-written-0", SF, SF, hx("01 c0 11"), hx("01 80 11 00"), model={"probe.x": "17"})
    # the first octet says another follows and the input ends
    vec(SF, 6, "input-ends-inside-the-presence-octets", SF, SF, hx("01 81"), error="malformed-wire")
    vec(SF, 7, "to-json", SF, SJ, b3, '{"n":3,"val":34,"w":85}')
    from_json("to-fx-two-octets", SF, '{"n":2,"val":34,"x":17,"y":51,"z":68}', b2)
    # only w: three octets, the first two with only the extension bit; val absent
    from_json("to-fx-three-octets", SF, '{"n":3,"w":85}', hx("03 01 01 80 55 00"))
    # no presence bit is 1: one octet is still written
    from_json("to-fx-at-least-one-octet", SF, '{"n":9}', hx("09 00 00"))

    # ==========================================================================
    # conformance-seq-chain
    # ==========================================================================
    # chain 1 ends at its first fx: x 5, extension 0. val 7. chain 2: qty 1, extension 0.
    c1 = bits([(1, 8), (5, 7), (0, 1), (7, 8), (1, 7), (0, 1)], paper="01 0a 07 02")
    vec(SC, 1, "chain-ends-at-the-first-fx-roundtrip", SC, SC, c1, c1, model={"probe.x": "5", "probe.val": "7", "probe.qty": "1"})
    # ends at the second fx: y 6 in 3 bits, 4 pad bits, extension 0
    c2 = bits([(1, 8), (5, 7), (1, 1), (6, 3), (0, 4), (0, 1), (7, 8), (1, 7), (0, 1)], paper="01 0b c0 07 02")
    vec(SC, 2, "chain-ends-at-the-second-fx-roundtrip", SC, SC, c2, c2, model={"probe.x": "5", "probe.y": "6"})
    # every part: the constant 85, z 3, and the last fx line written 0; chain 2 with w
    c3 = bits([(1, 8), (5, 7), (1, 1), (6, 3), (0, 4), (1, 1), (85, 7), (1, 1), (3, 7), (0, 1), (7, 8), (1, 7), (1, 1), (0x99, 8)],
              paper="01 0b c1 ab 06 07 03 99")
    vec(SC, 3, "chain-every-part-roundtrip", SC, SC, c3, c3, model={"probe.x": "5", "probe.y": "6", "probe.z": "3", "probe.qty": "1", "probe.w": "153"})
    # the input ends chain 1 at its third fx, after the part that holds only the
    # constant. No line after the second fx would write a present key (z is
    # absent), so encode writes the second fx 0 and the constant part is not written.
    vec(SC, 4, "part-with-no-present-key-after-it-not-written", SC, SC, hx("01 0b c1 aa 07 02"), c2, model={"probe.x": "5", "probe.y": "6"})
    # after the first fx (1) the input ends
    vec(SC, 5, "input-ends-inside-a-chain", SC, SC, hx("01 0b"), error="malformed-wire")
    vec(SC, 6, "to-json", SC, SJ, c3, '{"n":1,"qty":1,"val":7,"x":5,"y":6,"z":3,"w":153}')
    # only z and w are present: every fx before z is 1 and the parts before it are
    # zero bits; the constant is written; in chain 2 qty is zero bits and fx is 1
    from_json("to-chain-fx-is-1-while-a-later-line-has-a-present-key", SC, '{"n":1,"z":3,"w":153}',
              bits([(1, 8), (0, 7), (1, 1), (0, 3), (0, 4), (1, 1), (85, 7), (1, 1), (3, 7), (0, 1), (0, 8), (0, 7), (1, 1), (0x99, 8)],
                   paper="01 01 01 ab 06 00 01 99"))
    from_json("to-chain-only-the-first-part", SC, '{"n":1,"x":5}', hx("01 0a 00 00"))

    # ==========================================================================
    # conformance-seq-groups: count, while, fx (nested, in opt), more (in opt)
    # ==========================================================================
    # nums count 0 and 4 zero bits; items: the ending 0 bit and 7 zero bits; recs: opt 0
    d1 = bits([(1, 8), (0, 4), (0, 4), (0, 1), (0, 7), (0, 1)], paper="01 00 00 00")
    vec(SG, 1, "no-item-in-any-list-roundtrip", SG, SG, d1, d1,
        model={"probe.nums.#": "0", "probe.items.#": "0", "probe.recs.#": "absent"})
    # nums 1 2 3. items: (1, qty 5, opt 1, subs 9 then 10) (1, qty 6, opt 0), then
    # the ending 0 bit. recs: opt 1, pad, (more 1, x 1) (more 0, x 2)
    d2 = bits([(1, 8), (3, 4), (1, 4), (2, 4), (3, 4),
               (1, 1), (5, 6), (1, 1), (9, 7), (1, 1), (10, 7), (0, 1),
               (1, 1), (6, 6), (0, 1),
               (0, 1), (0, 7),
               (1, 1), (0, 7), (1, 1), (1, 7), (0, 1), (2, 7)], paper="01 31 23 8b 13 14 8c 00 80 81 02")
    D2_MODEL = {"probe.n": "1", "probe.nums.#": "3", "probe.nums[2].probe.val": "3", "probe.items.#": "2",
                "probe.items[0].probe.qty": "5", "probe.items[0].probe.subs.#": "2", "probe.items[0].probe.subs[1].probe.val": "10",
                "probe.items[1].probe.qty": "6", "probe.items[1].probe.subs.#": "absent",
                "probe.recs.#": "2", "probe.recs[0].probe.x": "1", "probe.recs[1].probe.x": "2"}
    vec(SG, 2, "several-items-in-every-list-roundtrip", SG, SG, d2, d2, model=D2_MODEL)
    # one item in each: nums 7; one item, qty 1, no subs; one rec, x 5
    d3 = bits([(1, 8), (1, 4), (7, 4), (1, 1), (1, 6), (0, 1), (0, 1), (0, 7), (1, 1), (0, 7), (0, 1), (5, 7)], paper="01 17 82 00 80 05")
    vec(SG, 3, "one-item-in-every-list-roundtrip", SG, SG, d3, d3, model={"probe.nums.#": "1", "probe.items.#": "1", "probe.recs.#": "1"})
    # the count says three 4-bit items and four bits remain
    vec(SG, 4, "count-beyond-the-input", SG, SG, hx("01 30"), error="malformed-wire")
    # the item says subs follow and the input ends
    vec(SG, 5, "input-ends-before-a-nested-item", SG, SG, hx("01 00 8b"), error="malformed-wire")
    D2_JSON = '{"n":1,"items":[{"qty":5,"subs":[{"val":9},{"val":10}]},{"qty":6}],"nums":[1,2,3],"recs":[{"x":1},{"x":2}]}'
    vec(SG, 6, "to-json", SG, SJ, d2, D2_JSON)
    # xml: the items under body (qty as text, the sub values as attributes, the
    # pack's item constant k), then nums; recs has no place there
    vec(SG, 7, "to-xml", SG, GX, d2,
        '<msg><body><item k="i"><qty>5</qty><sub v="9"/><sub v="10"/></item><item k="i"><qty>6</qty></item></body><nums><n>1</n><n>2</n><n>3</n></nums></msg>')
    from_json("to-groups-several-items-in-every-list", SG, D2_JSON, d2)
    # an empty subs and an empty recs: each `opt` bit is 0 and its block is not
    # written. nums is absent: the count 0.
    from_json("to-groups-empty-list-in-opt-is-not-written", SG, '{"n":1,"items":[{"qty":5,"subs":[]}],"recs":[]}',
              bits([(1, 8), (0, 4), (0, 4), (1, 1), (5, 6), (0, 1), (0, 1), (0, 7), (0, 1)], paper="01 00 8a 00 00"))
    # sixteen nums do not fit the 4-bit count
    from_json("to-groups-count-does-not-fit", SG, '{"nums":[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,0]}', error="transform-encode")
    # from xml: n absent (zero bits); nums 4; one item, qty 5, one sub 9; no recs
    vec(GX, 14, "to-seq-groups", GX, SG, '<msg id="u"><body><item><qty>5</qty><sub v="9"/></item></body><nums><n>4</n></nums></msg>',
        bits([(0, 8), (1, 4), (4, 4), (1, 1), (5, 6), (1, 1), (9, 7), (0, 1), (0, 1), (0, 7), (0, 1)], paper="00 14 8b 12 00 00"))

    # ==========================================================================
    # conformance-seq-groups-bare: fx and more outside any if or opt block
    # ==========================================================================
    e1 = bits([(5, 7), (0, 1), (0, 1), (3, 7)], paper="0a 03")
    vec(SB, 1, "one-item-each-roundtrip", SB, SB, e1, e1, model={"probe.nums.#": "1", "probe.nums[0].probe.val": "5", "probe.recs.#": "1", "probe.recs[0].probe.x": "3"})
    e2 = bits([(1, 7), (1, 1), (2, 7), (1, 1), (3, 7), (0, 1), (1, 1), (1, 7), (0, 1), (2, 7)], paper="03 05 06 81 02")
    vec(SB, 2, "several-items-each-roundtrip", SB, SB, e2, e2, model={"probe.nums.#": "3", "probe.nums[2].probe.val": "3", "probe.recs.#": "2", "probe.recs[1].probe.x": "2"})
    # the first num says another follows and the input ends
    vec(SB, 3, "input-ends-after-an-fx-bit-of-1", SB, SB, hx("03"), error="malformed-wire")
    vec(SB, 4, "to-json", SB, SJ, e2, '{"nums":[1,2,3],"recs":[{"x":1},{"x":2}]}')
    from_json("to-bare-one-item-each", SB, '{"nums":[5],"recs":[{"x":3}]}', e1)
    from_json("to-bare-absent-fx-list", SB, '{"recs":[{"x":1}]}', error="transform-encode")
    from_json("to-bare-empty-fx-list", SB, '{"nums":[],"recs":[{"x":1}]}', error="transform-encode")
    from_json("to-bare-absent-more-list", SB, '{"nums":[1]}', error="transform-encode")
    from_json("to-bare-empty-more-list", SB, '{"nums":[1],"recs":[]}', error="transform-encode")

    # ==========================================================================
    # conformance-seq-length
    # ==========================================================================
    # block 1: 2 bytes and its own byte = 3; x 0x11; y 10 and 4 zero bits.
    # block 2: z 21 (5 bits), opt 1, w 9 (4 bits) = 10 bits, stated 10 - 2 = 8.
    # block 3: count 2, 7, 8, then the nested block (4 bits: qty 6) = 4 bytes.
    B1 = [(3, 8), (0x11, 8), (10, 4), (0, 4)]
    B2 = [(8, 6), (21, 5), (1, 1), (9, 4)]
    B3 = [(4, 8), (2, 8), (7, 8), (8, 8), (4, 4), (6, 4)]
    f1 = bits([(1, 8)] + B1 + B2 + B3, paper="01 03 11 a0 22 b9 04 02 07 08 46")
    F1_MODEL = {"probe.x": "17", "probe.y": "10", "probe.z": "21", "probe.w": "9", "probe.nums.#": "2", "probe.nums[1].probe.val": "8", "probe.qty": "6"}
    vec(SL, 1, "every-block-roundtrip", SL, SL, f1, f1, model=F1_MODEL)
    # Lines beyond an extent read as absent. Block 1 states 2: one byte, x only.
    # Block 2 states 3: 5 bits, z only, and the `opt` line is beyond the extent.
    # Block 3 states 0: nums and the nested block are beyond the extent, so the
    # list is absent. Encode writes every line: y as zero bits, the opt bit 0
    # (stated 6 - 2 = 4), the count 0 and the nested block with qty as zero bits.
    F2_OUT = bits([(1, 8), (3, 8), (0x11, 8), (0, 8), (4, 6), (21, 5), (0, 1), (0, 4), (2, 8), (0, 8), (4, 4), (0, 4)], paper="01 03 11 00 12 a0 02 00 40")
    vec(SL, 2, "lines-beyond-an-extent-read-as-absent", SL, SL,
        bits([(1, 8), (2, 8), (0x11, 8), (3, 6), (21, 5), (0, 5), (0, 8)], paper="01 02 11 0e a0 00"), F2_OUT,
        model={"probe.x": "17", "probe.z": "21", "probe.nums.#": "absent"})
    # block 3 states 1: the count 0 is inside the extent, the list is present and empty
    vec(SL, 3, "count-inside-the-extent-nested-block-beyond-it", SL, SL, hx("01 02 11 0e a0 01 00"), F2_OUT, model={"probe.nums.#": "0"})
    # Content of an extent no line reads is skipped. Block 1 states 5: four
    # bytes, of which x and y read 12 bits. Block 2 states 14: 16 bits, of which
    # z, the opt bit and w read 10; then 2 zero bits to the whole byte.
    vec(SL, 4, "unread-content-of-an-extent-is-skipped", SL, SL,
        bits([(1, 8), (5, 8), (0x11, 8), (10, 4), (0xF, 4), (0xEEEE, 16), (14, 6), (21, 5), (1, 1), (9, 4), (0x3F, 6), (0, 2)] + B3,
             paper="01 05 11 af ee ee 3a b9 fc 04 02 07 08 46"), f1, model=F1_MODEL)
    # block 2 states 1: an extent of 3 bits, and z needs 5
    vec(SL, 5, "line-runs-past-its-extent", SL, SL, bits([(1, 8)] + B1 + [(1, 6), (21, 5)], paper="01 03 11 a0 06 a0"), error="malformed-wire")
    # block 1 states 9: eight bytes, and two remain
    vec(SL, 6, "extent-beyond-the-input", SL, SL, hx("01 09 11 a0"), error="malformed-wire")
    # block 1 states 0: 0 - 1 is a negative length
    vec(SL, 7, "stated-length-below-plus", SL, SL, hx("01 00 11"), error="malformed-wire")
    F1_JSON = '{"n":1,"qty":6,"x":17,"y":10,"z":21,"w":9,"nums":[7,8]}'
    vec(SL, 8, "to-json", SL, SJ, f1, F1_JSON)
    from_json("to-length-every-block", SL, F1_JSON, f1)
    # block 3 would hold the count, 255 items and the nested block: 257 bytes do
    # not fit its 8-bit length
    from_json("to-length-does-not-fit", SL, '{"nums":[' + ",".join(["1"] * 255) + ']}', error="transform-encode")

    # ==========================================================================
    # conformance-seq-whole
    # ==========================================================================
    # four bytes: the length field holds 4 - 1 = 3. opt 1, y 5.
    g1 = bits([(1, 8), (3, 8), (0x11, 8), (1, 1), (5, 7)], paper="01 03 11 85")
    vec(SW, 1, "roundtrip", SW, SW, g1, g1, model={"probe.n": "1", "probe.x": "17", "probe.y": "5"})
    vec(SW, 2, "input-beyond-the-stated-length-is-ignored", SW, SW, hx("01 03 11 85 ff ff"), g1, model={"probe.y": "5"})
    # the field states five bytes and the input has four
    vec(SW, 3, "input-shorter-than-the-stated-length", SW, SW, hx("01 04 11 85"), error="malformed-wire")
    # the field states three bytes: the `opt` bit lies beyond the message
    vec(SW, 4, "line-beyond-the-stated-length", SW, SW, hx("01 02 11 85"), error="malformed-wire")
    # the field states one byte, and two are read before it is known
    vec(SW, 5, "stated-length-shorter-than-the-lines-read", SW, SW, hx("01 00 11 85"), error="malformed-wire")
    from_json("to-whole-length-of-the-message", SW, '{"n":1,"x":17,"y":5}', g1)
    # y absent: the opt bit 0 and zero bits to the whole byte; still four bytes
    from_json("to-whole-opt-not-written", SW, '{"n":1,"x":17}', hx("01 03 11 00"))

    # ==========================================================================
    # conformance-seq-kinds: items by kind
    # ==========================================================================
    POINT = [(5, 4), (1, 4), (0x22, 8)]
    ALT = [(6, 4), (3, 4), (258, 16)]
    TEXT = [(6, 4), (2, 4), (2, 8), ("hi", 16)]
    EMPTY = [(7, 4), (0, 4)]
    h1 = bits([(1, 8), (4, 8)] + POINT + ALT + TEXT + EMPTY, paper="01 04 51 22 63 01 02 62 02 68 69 70")
    vec(SK, 1, "items-of-every-kind-roundtrip", SK, SK, h1, h1,
        model={"probe.recs.#": "4", "probe.recs[0].@kind": "point", "probe.recs[0].probe.x": "5", "probe.recs[0].probe.y": "34",
               "probe.recs[1].@kind": "alt", "probe.recs[1].probe.y": "258", "probe.recs[2].@kind": "text",
               "probe.recs[2].probe.label": "hi", "probe.recs[3].@kind": "empty", "probe.recs[3].probe.x": "7"})
    # the kind code of the item is 4
    vec(SK, 2, "item-matches-no-kind", SK, SK, hx("01 01 54"), error="no-kind")
    # the count is 2 and the input ends after the first item
    vec(SK, 3, "input-ends-before-an-item", SK, SK, hx("01 02 51 22"), error="malformed-wire")
    vec(SK, 4, "to-json", SK, SJ, h1, '{"n":1,"recs":[{"x":5,"y":34},{"x":6,"y":258},{"x":6,"label":"hi"},{"x":7}]}')
    # from json no item names a kind: y selects point, label selects text, and an
    # item with neither is empty
    from_json("to-kinds-each-item-selects-by-requires", SK, '{"n":1,"recs":[{"x":5,"y":34},{"x":6,"label":"hi"},{"x":7}]}',
              bits([(1, 8), (3, 8)] + POINT + TEXT + EMPTY, paper="01 03 51 22 62 02 68 69 70"))

    # ==========================================================================
    # conformance-seq-lsb
    # ==========================================================================
    # byte 4: p.1 1, p.2 0, p.3 1 in bits 0-2, x 9 in bits 3-7. y -2. f: f.2 in
    # bit 1, extension (bit 7) 0. z. chain: c1 5, extension 0. nums: count 1 in
    # the low nibble, val 3 in the high. opt 1 in bit 0, then "A" from bit 1.
    i1 = bits([(1, 8), (2, 4), (10, 4), (0x1234, 16), (1, 1), (0, 1), (1, 1), (9, 5), (-2, 8),
               (0, 1), (1, 1), (0, 5), (0, 1), (0x44, 8), (5, 7), (0, 1), (1, 4), (3, 4), (1, 1), ("A", 8)],
              msb=False, paper="01 a2 34 12 4d fe 02 44 05 31 83 00")
    I1_MODEL = {"probe.n": "1", "probe.qty": "2", "probe.val": "4660", "probe.x": "9", "probe.y": "-2", "probe.z": "68",
                "probe.c1": "5", "probe.nums.#": "1", "probe.nums[0].probe.val": "3", "probe.label": "A"}
    vec(SLS, 1, "presence-chain-group-and-opt-roundtrip", SLS, SLS, i1, i1, model=I1_MODEL)
    # no p bit. f: octet 1 holds only the extension bit (0x80); f.9 is the second
    # bit of octet 2 (0x02). w. chain: c1 5 with the extension bit (0x85), c2 6
    # and the last fx written 0. nums: count 0. opt 0.
    i2 = bits([(2, 8), (0, 4), (10, 4), (0, 16), (0, 3), (0, 5), (0, 7), (1, 1), (0, 1), (1, 1), (0, 5), (0, 1), (0x55, 8),
               (5, 7), (1, 1), (6, 7), (0, 1), (0, 4), (0, 4), (0, 1)], msb=False, paper="02 a0 00 00 00 80 02 55 85 06 00 00")
    vec(SLS, 2, "two-presence-octets-and-both-chain-parts-roundtrip", SLS, SLS, i2, i2,
        model={"probe.w": "85", "probe.c1": "5", "probe.c2": "6", "probe.nums.#": "0"})
    # val needs 16 bits and 8 remain
    vec(SLS, 3, "input-ends-inside-a-field", SLS, SLS, hx("01 a2 34"), error="malformed-wire")
    vec(SLS, 4, "to-json", SLS, SJ, i2, '{"n":2,"qty":0,"val":0,"w":85,"c1":5,"c2":6,"nums":[]}')
    from_json("to-lsb-presence-chain-group-and-opt", SLS, '{"n":1,"qty":2,"val":4660,"x":9,"y":-2,"z":68,"c1":5,"label":"A","nums":[3]}', i1)
    # the msb pack and the lsb pack hold the same keys in different layouts: n 5,
    # qty 2 under the constant, val 9 in 16 bits; no presence bit, one presence
    # octet, the chain's first part and its extension 0, the count 0, the opt bit 0
    vec(SM, 12, "to-lsb", SM, SLS, a1,
        bits([(5, 8), (2, 4), (10, 4), (9, 16), (0, 3), (0, 5), (0, 7), (0, 1), (0, 7), (0, 1), (0, 4), (0, 4), (0, 1)],
             msb=False, paper="05 a2 09 00 00 00 00 00 00"))

    # ==========================================================================
    # conformance-seq-nested: presence, chain and `if` inside items; a presence of
    # the message named inside an item; a group inside `length` inside `if`
    # ==========================================================================
    # p 11. Two items. Item 0: q 110, qty 5; chain x 3 with the extension bit, y 4
    # and the last fx 0; val 0x21. Item 1: q 000, val 0x22 (11 bits), then 5 zero
    # bits to the whole byte. p.2: length 2; nums: (1, val 9), the ending 0 bit and
    # 7 zero bits to the whole byte of the block.
    k1 = bits([(1, 8), (0b11, 2), (0, 6), (2, 8),
               (0b110, 3), (5, 5), (3, 7), (1, 1), (4, 7), (0, 1), (0x21, 8),
               (0b000, 3), (0x22, 8), (0, 5),
               (2, 8), (1, 1), (9, 7), (0, 1), (0, 7)], paper="01 c0 02 c5 07 08 21 04 40 02 89 00")
    vec(SN, 1, "presence-chain-and-length-nested-roundtrip", SN, SN, k1, k1,
        model={"probe.items.#": "2", "probe.items[0].probe.qty": "5", "probe.items[0].probe.x": "3", "probe.items[0].probe.y": "4",
               "probe.items[0].probe.val": "33", "probe.items[1].probe.val": "34", "probe.nums.#": "1", "probe.nums[0].probe.val": "9"})
    # no presence bit and no item
    k2 = bits([(1, 8), (0, 2), (0, 6), (0, 8)], paper="01 00 00")
    vec(SN, 2, "no-presence-bit-roundtrip", SN, SN, k2, k2, model={"probe.items.#": "0", "probe.nums.#": "absent"})
    # p.2 is 1 and its block holds a list of no items (length 1: the ending 0 bit
    # and 7 unread bits). An empty list does not set a presence bit: encode writes
    # p.2 as 0 and the block is not written.
    vec(SN, 3, "empty-list-does-not-set-its-presence-bit", SN, SN, hx("01 40 00 01 00"), k2, model={"probe.nums.#": "0"})
    vec(SN, 4, "to-json", SN, SJ, k1, '{"n":1,"items":[{"qty":5,"val":33,"x":3,"y":4},{"val":34}],"nums":[9]}')
    from_json("to-nested-presence-chain-and-length", SN, '{"n":1,"items":[{"qty":5,"val":33,"x":3,"y":4},{"val":34}],"nums":[9]}', k1)
    # Only the second item has val: that sets p.1, so both items hold the val
    # byte and the first writes zero bits. Item 0: q 100, qty 5, val 00. Item 1:
    # q 000, val 0x22, 5 zero bits. No nums: p.2 is 0.
    from_json("to-nested-outer-presence-set-by-one-item", SN, '{"n":1,"items":[{"qty":5},{"val":34}]}',
              bits([(1, 8), (0b10, 2), (0, 6), (2, 8), (0b100, 3), (5, 5), (0, 8), (0b000, 3), (0x22, 8), (0, 5)], paper="01 80 02 85 00 04 40"))

    # ==========================================================================
    # Rulings for 0.8
    # ==========================================================================
    SR, DF = "conformance-seq-rulings", "conformance-derive-functions"
    # ruling 1: a presence bit that is 1 and that no `if` block names. fx pack:
    # f.1 and f.3 (octet a0); no block names f.3. lsb pack: p.2 (bit 1 of byte 4).
    vec(SF, 8, "ruling-01-presence-bit-no-if-names", SF, SF, hx("01 a0 11 22"), error="malformed-wire")
    vec(SLS, 5, "ruling-01-presence-bit-no-if-names", SLS, SLS, hx("01 a2 34 12 02 00 00 00 00 00"), error="malformed-wire")
    # ruling 2: only n is given. x has a default: p.1 is 1 and x is 7. qty has a
    # default: the opt bit is 1 and qty is 9. c2 has a default: the first fx is 1,
    # c1 is zero bits, c2 is 5, and the second fx is 0 (z is absent, no default).
    r1 = bits([(1, 8), (0b10, 2), (0, 6), (7, 8), (1, 1), (9, 7), (0, 7), (1, 1), (5, 7), (0, 1), (0, 8)], paper="01 80 07 89 01 0a 00")
    from_json("ruling-02-key-with-a-default-counts-as-present", SR, '{"n":1}', r1)
    # the input has no presence bit, opt 0 and the chain ending at its first fx
    # (c1 0, then w from bit 25); encode writes the defaults as above
    vec(SR, 1, "ruling-02-defaults-written-where-the-input-had-none", SR, SR, hx("01 00 00 00 00"), r1, model={"probe.c1": "0", "probe.w": "0"})
    # ruling 13: w is 1 on the wire; val is the same bits through the table, 100
    r3 = r1[:-2] + "01"
    vec(SR, 2, "ruling-13-also-fills-both-keys-roundtrip", SR, SR, r3, r3,
        model={"probe.w": "1", "probe.val": "100", "probe.x": "7", "probe.qty": "9", "probe.c2": "5"})
    vec(SR, 3, "ruling-13-to-json", SR, SJ, r3, '{"n":1,"qty":9,"val":100,"x":7,"w":1,"c1":0,"c2":5}')
    # only val is present: 200 is 2 on the wire
    from_json("ruling-13-also-key-written-when-the-field-key-is-absent", SR, '{"n":1,"val":200}', r1[:-2] + "02")
    # both present: the field's own key is the earlier
    from_json("ruling-13-earliest-present-key-is-written", SR, '{"n":1,"val":200,"w":3}', r1[:-2] + "03")
    # ruling 3: the chain's third part with its ending fx bit 1 (c2 5 and fx 1 =
    # 0b, z 1 and fx 1 = 03)
    vec(SR, 4, "ruling-03-last-fx-of-a-chain-is-1", SR, SR, hx("01 80 07 89 01 0b 03 00"), error="malformed-wire")
    # ruling 9: whole bytes after the last line are ignored
    vec(SC, 7, "ruling-09-input-beyond-the-last-line-is-ignored", SC, SC, c1 + "ffff", c1, model={"probe.qty": "1"})

    # The derive functions of 0.8. Every vector gives an empty context, so the
    # derivations run on a same-format conversion.
    # 12:00:00.123 is 43200.123 s after midnight; y and z are present, z is not
    # 0: any 1; x is 0: not 1; "311" parses; -42 as text
    vec(DF, 1, "every-function", DF, DF, '{"t":"2025-10-29T12:00:00.123Z","x":0,"z":2,"s1":"311","n":-42}',
        '{"t":"2025-10-29T12:00:00.123Z","x":0,"z":2,"s1":"311","n":-42,"ds":43200.123,"any":1,"notx":1,"parsed":311,"text":"-42"}',
        context={}, model={"@complete": True, "probe.ds": "43200.123", "probe.any1": "1"})
    # any: one argument present and it is 0
    vec(DF, 2, "any-of-present-arguments-all-zero", DF, DF, '{"y":0}', '{"y":0,"any":0}', context={})
    # any: no argument present, the target stays absent
    vec(DF, 3, "any-with-no-argument-present", DF, DF, '{"n":5}', '{"n":5,"text":"5"}', context={})
    # not of a value other than 0; text that is not a decimal integer leaves parse_int absent
    vec(DF, 4, "not-of-nonzero-and-parse-int-of-other-text", DF, DF, '{"x":5,"s1":"track-311"}', '{"x":5,"s1":"track-311","any":1,"notx":0}', context={})
    vec(DF, 5, "parse-int-negative", DF, DF, '{"s1":"-5"}', '{"s1":"-5","parsed":-5}', context={})
    # an instant before 1970: one millisecond before midnight
    vec(DF, 6, "day-seconds-before-1970", DF, DF, '{"t":"1969-12-31T23:59:59.999Z"}', '{"t":"1969-12-31T23:59:59.999Z","ds":86399.999}', context={})

    # ==========================================================================
    # Load vectors
    # ==========================================================================
    CORE = 'module core\nversion 0.1.0\ndistribution public\nsource "probe"\nkey uid string -\nkey type string -\nkey lat float deg\nkey lon float deg\nkey callsign string -\nkey time_ms int ms\n'
    PM = 'module probe\nversion 0.1.0\ndistribution public\nsource "probe"\nkey label string -\nkey qty int -\nkey x int -\nkey y int -\nkey a float -\nlist items "a list"\nlist subs "a nested list"\n'
    HEAD8 = 'format probe\nversion 0.8.0\ndistribution public\nsource "probe"\nuses probe\n'
    SEQ = HEAD8 + 'wire bits\nlayout sequential\nfield probe.qty 8 uint\n'
    FIX = HEAD8 + 'wire bits\nword_bytes 1\nfield probe.qty 0:0:8 uint\n'
    n = 174


    def L(name, pack, error=None, models=None):
        nonlocal n
        full = "%d-%s" % (n, name)
        d = {"name": full, "models": models if models is not None else [CORE, PM], "pack": pack}
        if error:
            d["expect_error"] = error
        sink.write("packs/conformance/load-vectors/%s.json" % full, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written["load"] = written.get("load", 0) + 1
        n += 1


    FX = 'field probe.x 8 uint\n'
    L("seq-every-construct-loads", SEQ + 'bit_order msb\nconst 4 10\npad 4\nalign 8\ndefault probe.x 1\n'
      'presence p 2\nif p.1\n  field probe.x 8 uint\nend\nif !p.2\n  field probe.y 8 twos\nend\n'
      'presence f fx\nif f.9 p.2\n  field probe.label 16 ascii trim\nend\n'
      'opt\n  field probe.a 16 sscale:1/4 swap\nend\n'
      'chain\n  field probe.x 7 uint\n  fx\n  field probe.y 7 uint\n  fx\nend\n'
      'length 8 bits plus -2\n  field probe.y 8 uint via t\nend\nlength 16 whole plus 1\n'
      'group probe.items count 8\n  field probe.x 8 uint\n  group probe.subs while\n    field probe.y 8 uint\n  end\nend\nmap t 1 2\n')
    L("seq-word-bytes", SEQ + 'word_bytes 1\n', "bad-directive")
    L("seq-optional-field-option", SEQ + 'field probe.x 8 uint optional\n', "bad-directive")
    # unbalanced blocks
    L("seq-if-without-end", SEQ + 'presence p 1\nif p.1\n  ' + FX, "bad-directive")
    L("seq-opt-without-end", SEQ + 'opt\n  ' + FX, "bad-directive")
    L("seq-chain-without-end", SEQ + 'chain\n  ' + FX + '  fx\n', "bad-directive")
    L("seq-length-without-end", SEQ + 'length 8\n  ' + FX, "bad-directive")
    L("seq-group-without-end", SEQ + 'group probe.items count 8\n  ' + FX, "bad-directive")
    L("seq-nested-block-without-end", SEQ + 'group probe.items count 8\n  opt\n    ' + FX + 'end\n', "bad-directive")
    L("seq-end-with-no-open-block", SEQ + 'opt\n  ' + FX + 'end\nend\n', "bad-directive")
    # `if` and the presence it names
    L("seq-if-names-an-unknown-presence", SEQ + 'presence p 2\nif q.1\n  ' + FX + 'end\n', "bad-directive")
    L("seq-if-names-a-bit-beyond-the-presence", SEQ + 'presence p 2\nif p.3\n  ' + FX + 'end\n', "bad-directive")
    L("seq-if-names-the-last-bit-loads", SEQ + 'presence p 2\nif p.2\n  ' + FX + 'end\n')
    L("seq-if-names-a-negated-bit-beyond-the-presence", SEQ + 'presence p 2\nif !p.3\n  ' + FX + 'end\n', "bad-directive")
    L("seq-if-names-any-bit-of-an-fx-presence-loads", SEQ + 'presence f fx\nif f.40\n  ' + FX + 'end\n')
    L("seq-if-before-its-presence-line", SEQ + 'if p.1\n  ' + FX + 'end\npresence p 2\n', "bad-directive")
    # a name is visible from its line to the end of the enclosing block
    L("seq-if-after-the-block-that-holds-its-presence", SEQ + 'opt\n  presence p 2\nend\nif p.1\n  ' + FX + 'end\n', "bad-directive")
    L("seq-if-after-the-group-that-holds-its-presence", SEQ + 'group probe.items count 8\n  presence p 2\nend\nif p.1\n  ' + FX + 'end\n', "bad-directive")
    L("seq-if-inside-a-nested-block-names-an-outer-presence-loads", SEQ + 'presence p 2\nopt\n  if p.1\n    ' + FX + '  end\nend\ngroup probe.items count 8\n  if p.2\n    ' + FX + '  end\nend\n')
    # positional locators
    L("seq-positional-field-locator", SEQ + 'field probe.x 0:8:8 uint\n', "bad-directive")
    L("seq-positional-const-locator", SEQ + 'const 0:8:8 1\n', "bad-directive")
    L("seq-positional-group-locator", SEQ + 'group probe.items 0:16 item 8 count 0:8:8\n  ' + FX + 'end\n', "bad-directive")
    # a sequential line in a fixed-layout pack
    L("fixed-layout-pad", FIX + 'pad 8\n', "bad-directive")
    L("fixed-layout-align", FIX + 'align 8\n', "bad-directive")
    L("fixed-layout-presence", FIX + 'presence p 2\n', "bad-directive")
    L("fixed-layout-if", FIX + 'if p.1\n', "bad-directive")
    L("fixed-layout-opt", FIX + 'opt\nend\n', "bad-directive")
    L("fixed-layout-chain", FIX + 'chain\nend\n', "bad-directive")
    L("fixed-layout-fx", FIX + 'fx\n', "bad-directive")
    L("fixed-layout-length", FIX + 'length 8\nend\n', "bad-directive")
    L("fixed-layout-sequential-field", FIX + 'field probe.x 8 uint\n', "bad-directive")
    L("fixed-layout-sequential-group", FIX + 'group probe.items while\n  field probe.x 0:0:8 uint\nend\n', "bad-directive")
    L("layout-fixed-loads", FIX + 'layout fixed\n')
    # kinds
    L("seq-kinds-load", SEQ + 'kind a\nwhen 8 1\nrequires probe.x\n' + FX + 'kind b\nwhen 4 2\nwhen 4 3\n')
    L("seq-when-without-kind", SEQ + 'when 8 1\n', "bad-directive")
    L("seq-when-value-does-not-fit", SEQ + 'kind a\nwhen 4 16\n', "bad-directive")
    L("seq-const-value-does-not-fit", SEQ + 'const 4 16\n', "bad-directive")
    L("seq-kinds-in-a-group-load", SEQ + 'group probe.items count 8\n  ' + FX + '  kind a\n  when 8 1\n  requires probe.y\n  field probe.y 8 uint\n  kind b\n  when 8 2\nend\n')
    L("seq-kind-declared-twice-in-a-group", SEQ + 'group probe.items count 8\n  kind a\n  when 8 1\n  kind a\n  when 8 2\nend\n', "duplicate-kind")
    L("seq-when-without-kind-in-a-group", SEQ + 'group probe.items count 8\n  when 8 1\n  ' + FX + 'end\n', "bad-directive")
    # the checks of earlier versions apply to sequential lines
    L("seq-bit-length-not-allowed-for-f32", SEQ + 'field probe.a 16 f32\n', "bad-directive")
    L("seq-swap-length-not-a-multiple-of-8", SEQ + 'field probe.x 12 uint swap\n', "bad-directive")
    L("seq-via-table-with-no-map-line", SEQ + 'field probe.x 8 uint via t\n', "bad-directive")
    L("seq-field-undeclared-key", SEQ + 'opt\n  field probe.nokey 8 uint\nend\n', "undeclared-key")
    L("seq-field-key-type-mismatch", SEQ + 'chain\n  field probe.label 8 uint\nend\n', "key-type-mismatch")
    L("seq-group-undeclared-list", SEQ + 'group probe.nolist while\n  ' + FX + 'end\n', "undeclared-key")
    L("seq-group-names-a-scalar-key", SEQ + 'group probe.x fx\n  ' + FX + 'end\n', "key-type-mismatch")
    L("seq-field-names-a-list", SEQ + 'field probe.items 8 uint\n', "key-type-mismatch")
    L("seq-requires-undeclared-key-in-a-group", SEQ + 'group probe.items count 8\n  kind a\n  requires probe.nokey\nend\n', "undeclared-key")
    L("seq-default-undeclared-key-in-a-block", SEQ + 'opt\n  ' + FX + '  default probe.nokey 1\nend\n', "undeclared-key")
    L("seq-map-inside-a-group", SEQ + 'group probe.items count 8\n  ' + FX + '  map t 1 2\nend\n', "bad-directive")
    L("seq-block-error-comes-before-missing-distribution", 'format probe\nversion 0.8.0\nsource "probe"\nuses probe\nwire bits\nlayout sequential\nopt\n  ' + FX, "bad-directive")

    # --- rulings for 0.8 and the model additions
    L("ruling-10-when-after-a-line-of-its-kind", SEQ + 'kind a\nwhen 8 1\n' + FX + 'when 8 2\n', "bad-directive")
    L("ruling-10-when-inside-a-block", SEQ + 'kind a\nopt\n  when 8 1\nend\n', "bad-directive")
    L("ruling-10-common-when-loads", SEQ + 'when 8 9\nkind a\nwhen 8 1\n')
    L("ruling-08-length-whole-loads", SEQ + 'length 16 bytes plus 2 whole\n')
    L("ruling-08-length-bits-whole", SEQ + 'length 16 bits whole\n', "bad-directive")
    L("ruling-11-kind-name-in-two-groups-loads", SEQ + 'group probe.items count 8\n  kind a\n  when 8 1\nend\ngroup probe.subs count 8\n  kind a\n  when 8 1\nend\n')
    L("ruling-11-kind-name-of-the-message-and-of-a-group-loads", SEQ + 'group probe.items count 8\n  kind a\n  when 8 1\nend\nkind a\nwhen 8 1\n')
    L("ruling-11-kind-name-twice-in-the-message", SEQ + 'kind a\nwhen 8 1\nkind a\nwhen 8 2\n', "duplicate-kind")
    L("ruling-12-presence-declared-twice-in-one-block", SEQ + 'presence p 2\npresence p 3\n', "bad-directive")
    L("ruling-12-presence-declared-in-common-and-in-a-kind", SEQ + 'presence p 2\nkind a\nwhen 8 1\npresence p 3\n', "bad-directive")
    L("ruling-12-presence-declared-in-two-kinds-loads", SEQ + 'kind a\nwhen 8 1\npresence p 2\nkind b\nwhen 8 2\npresence p 3\nif p.3\n  ' + FX + 'end\n')
    L("ruling-12-nested-block-hides-the-name-loads", SEQ + 'presence p 2\nopt\n  presence p 4\n  if p.4\n    ' + FX + '  end\nend\nif p.2\n  ' + FX + 'end\n')
    L("ruling-12-outer-name-is-back-after-the-nested-block", SEQ + 'presence p 2\nopt\n  presence p 4\nend\nif p.4\n  ' + FX + 'end\n', "bad-directive")
    L("ruling-13-also-loads", SEQ + 'field probe.x 8 uint\nalso probe.y\nalso probe.qty via t\nmap t 1 2\n')
    L("ruling-13-also-after-a-const", SEQ + 'const 8 1\nalso probe.y\n', "bad-directive")
    L("ruling-13-also-first-in-a-block", SEQ + 'opt\n  also probe.y\nend\n', "bad-directive")
    L("ruling-13-also-in-a-fixed-layout-pack", FIX + 'also probe.y\n', "bad-directive")
    L("ruling-13-also-via-table-with-no-map-line", SEQ + FX + 'also probe.y via t\n', "bad-directive")
    L("ruling-13-also-key-of-another-type", SEQ + FX + 'also probe.label\n', "key-type-mismatch")
    L("ruling-13-also-undeclared-key", SEQ + FX + 'also probe.nokey\n', "undeclared-key")
    L("ruling-14-presence-of-65-bits", SEQ + 'presence p 65\n', "bad-directive")
    L("ruling-14-const-of-65-bits", SEQ + 'const 65 1\n', "bad-directive")
    L("ruling-14-layout-sequential-on-json", HEAD8 + 'wire json\nlayout sequential\n', "bad-directive")
    # model modules that use another module
    OTHER = 'module other\nversion 0.1.0\ndistribution public\nsource "probe"\nuses probe\nkey o int -\nkey t string -\nkey f float -\n'
    JS8 = HEAD8 + 'wire json\nfield uid id string\n'
    L("model-uses-derive-argument-of-a-used-module-loads", JS8, None, [CORE, PM, OTHER + 'derive other.o copy probe.qty\n'])
    L("model-derive-argument-of-a-module-not-used", JS8, "bad-directive", [CORE, PM, OTHER.replace('uses probe\n', '') + 'derive other.o copy probe.qty\n'])
    L("model-derive-target-of-a-used-module", JS8, "bad-directive", [CORE, PM, OTHER + 'derive probe.qty copy other.o\n'])
    L("model-uses-a-module-not-loaded", JS8, "unknown-module", [CORE, OTHER, PM])
    PMC = PM.replace('distribution public', 'distribution controlled')
    L("model-public-module-uses-a-controlled-module", JS8, "distribution-violation", [CORE, PMC, OTHER])
    L("model-controlled-module-uses-a-public-module-loads", HEAD8.replace('distribution public', 'distribution controlled') + 'wire json\nfield uid id string\n', None,
      [CORE, PM, OTHER.replace('distribution public', 'distribution controlled')])
    L("derive-functions-of-0-8-load", JS8, None,
      [CORE, PM, OTHER + 'derive other.f day_seconds time_ms\nderive other.o any probe.x probe.y other.o\nderive other.o not probe.x\nderive other.o parse_int other.t\nderive other.t text_of probe.qty\n'])
    L("derive-day-seconds-of-a-float", JS8, "bad-directive", [CORE, PM, OTHER + 'derive other.f day_seconds probe.a\n'])
    L("derive-day-seconds-int-target", JS8, "bad-directive", [CORE, PM, OTHER + 'derive other.o day_seconds time_ms\n'])
    L("derive-any-of-a-string", JS8, "bad-directive", [CORE, PM, OTHER + 'derive other.o any probe.x probe.label\n'])
    L("derive-not-of-two-arguments", JS8, "bad-directive", [CORE, PM, OTHER + 'derive other.o not probe.x probe.y\n'])
    L("derive-parse-int-of-an-int", JS8, "bad-directive", [CORE, PM, OTHER + 'derive other.o parse_int probe.x\n'])
    L("derive-text-of-a-string", JS8, "bad-directive", [CORE, PM, OTHER + 'derive other.t text_of probe.label\n'])

    return written


def main(argv=None):
    return genio.vector_main('conformance-seq-vectors.py', __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
