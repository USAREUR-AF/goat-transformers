#!/usr/bin/env python3
"""Write the 0.7 group vectors and the 0.6 ruling vectors.

Every expected value here is worked out from the spec text and the pack
layouts, with byte builders written for these packs alone. Nothing calls an
engine.

Inputs: none; every value is stated in this file. Writes, under --out, the
vector files named above. The same run always gives the same bytes. With
--check nothing is written and the exit status is 1 when a committed file
differs from what this script writes.

Usage: python3 -I tools/gen/conformance-groups-vectors.py [--out DIR] [--check]
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402



def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written = {}

    def vec(pack, num, name, frm, to, inp, expect=None, error=None, model=None, context=None, extra=None, file=None):
        d = {"name": name, "from": frm, "to": to, "input": inp}
        if context is not None:
            d["context"] = context
        if error:
            d["expect_error"] = error
        else:
            d["expect"] = expect
        if model:
            d["model"] = model
        if extra:
            d.update(extra)
        sink.write("packs/%s/vectors/%s" % (pack, file or "%02d-%s.json" % (num, name)), json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[pack] = written.get(pack, 0) + 1


    def load(num, name, models, pack, error=None):
        full = "%d-%s" % (num, name)
        d = {"name": full, "models": models, "pack": pack}
        if error:
            d["expect_error"] = error
        sink.write("packs/conformance/load-vectors/%s.json" % full, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written["load"] = written.get("load", 0) + 1


    # --------------------------------------------------------------------------
    # protobuf byte builders
    # --------------------------------------------------------------------------
    def varint(n):
        n &= (1 << 64) - 1
        out = bytearray()
        while True:
            b = n & 0x7F
            n >>= 7
            if n:
                out.append(b | 0x80)
            else:
                out.append(b)
                return bytes(out)


    def tag(field, wt):
        return varint(field << 3 | wt)


    def pv(field, n):
        return tag(field, 0) + varint(n)


    def zz(n):
        return (n << 1) ^ (n >> 63)


    def ps(field, n):
        return pv(field, zz(n))


    def ld(field, b):
        if isinstance(b, str):
            b = b.encode()
        return tag(field, 2) + varint(len(b)) + b


    def pd(field, x):
        return tag(field, 1) + struct.pack("<d", x)


    def pf(field, x):
        return tag(field, 5) + struct.pack("<f", x)


    def hx(b):
        return bytes(b).hex()


    # --------------------------------------------------------------------------
    # The message every cross-wire vector carries: uid u1 and two items. The first
    # item has two subs; the second has none.
    #   item 0: label aa, qty 2, ratio 0.5, subs (x, 1) (y, 2)
    #   item 1: label bb, qty 3, ratio 1.25
    # --------------------------------------------------------------------------
    GJ, GX, GP, GB, GM, GG, GK = (
        "conformance-groups-json",
        "conformance-groups-xml",
        "conformance-groups-protobuf",
        "conformance-groups-bits",
        "conformance-groups-bits-msb",
        "conformance-groups-geojson",
        "conformance-groups-kinds",
    )

    # as a source on each wire
    J_SRC = '{"id":"u1","items":[{"name":"aa","n":2,"r":{"value":0.5},"kind":"item","subs":[{"t":"x","v":1},{"t":"y","v":2}]},{"name":"bb","n":3,"r":{"value":1.25},"kind":"item"}]}'
    X_SRC = '<msg id="u1"><body><item name="aa" r="0.5" k="i"><qty>2</qty><sub v="1">x</sub><sub v="2">y</sub></item><item name="bb" r="1.25" k="i"><qty>3</qty></item></body></msg>'
    P_ITEM0 = ld(1, "aa") + pv(2, 2) + pd(3, 0.5) + pv(4, 9) + ld(5, ld(1, "x") + ps(2, 1)) + ld(5, ld(1, "y") + ps(2, 2))
    P_ITEM1 = ld(1, "bb") + pv(2, 3) + pd(3, 1.25) + pv(4, 9)
    P_SRC = hx(ld(1, "u1") + ld(2, P_ITEM0) + ld(2, P_ITEM1))
    # bits: uid "u1" NUL-padded to 4 bytes, count 2, then 6 bytes per item:
    #   qty, label (2), ratio*4, [subs count | 0xA << 4], [sub0 | sub1 << 4]
    B_SRC = hx(b"u1\0\0" + bytes([2]) + bytes([2]) + b"aa" + bytes([2, 0xA2, 0x21]) + bytes([3]) + b"bb" + bytes([5, 0xA0, 0x00]))

    # as a target, from a source that carries tags (json, xml, protobuf)
    J_FULL = '{"id":"u1","title":"NONE","items":[{"name":"aa","n":2,"r":{"value":0.5},"kind":"item","subs":[{"t":"x","v":1},{"t":"y","v":2}]},{"name":"bb","n":3,"r":{"value":1.25},"kind":"item"}]}'
    X_FULL = X_SRC
    P_FULL = P_SRC
    B_FULL = B_SRC
    # as a target, from bits: no tags, and the second item's subs present and empty
    J_FROM_B = '{"id":"u1","title":"NONE","items":[{"name":"aa","n":2,"r":{"value":0.5},"kind":"item","subs":[{"v":1},{"v":2}]},{"name":"bb","n":3,"r":{"value":1.25},"kind":"item","subs":[]}]}'
    X_FROM_B = '<msg id="u1"><body><item name="aa" r="0.5" k="i"><qty>2</qty><sub v="1"/><sub v="2"/></item><item name="bb" r="1.25" k="i"><qty>3</qty></item></body></msg>'
    P_FROM_B = hx(
        ld(1, "u1")
        + ld(2, ld(1, "aa") + pv(2, 2) + pd(3, 0.5) + pv(4, 9) + ld(5, ps(2, 1)) + ld(5, ps(2, 2)))
        + ld(2, P_ITEM1)
    )

    ITEMS_MODEL = {
        "uid": "u1",
        "probe.items.#": "2",
        "probe.items[0].probe.label": "aa",
        "probe.items[0].probe.qty": "2",
        "probe.items[0].probe.ratio": "0.5",
        "probe.items[0].probe.subs.#": "2",
        "probe.items[0].probe.subs[0].probe.val": "1",
        "probe.items[0].probe.subs[1].probe.val": "2",
        "probe.items[1].probe.label": "bb",
        "probe.items[1].probe.qty": "3",
        "probe.items[1].probe.ratio": "1.25",
    }
    TAGS_MODEL = dict(ITEMS_MODEL)
    TAGS_MODEL.update({
        "probe.items[0].probe.subs[0].probe.tag": "x",
        "probe.items[0].probe.subs[1].probe.tag": "y",
        "probe.items[1].probe.subs.#": "absent",
    })

    # ==========================================================================
    # conformance-groups-json
    # ==========================================================================
    full = '{"id":"u1","title":"T","items":[{"name":"aa","n":2,"r":{"value":0.5},"kind":"item","subs":[{"t":"x","v":1},{"t":"y","v":2}]},{"name":"bb","n":3,"r":{"value":1.25},"kind":"item"}],"cs":"C","data":{"nums":[3,1,2]},"names":["p","q"],"ratios":[0.5,2]}'
    m = dict(TAGS_MODEL)
    m.update({
        "probe.label": "T",
        "callsign": "C",
        "probe.nums.#": "3",
        "probe.nums[0].probe.val": "3",
        "probe.nums[2].probe.val": "2",
        "probe.names.#": "2",
        "probe.names[1].probe.tag": "q",
        "probe.ratios.#": "2",
        "probe.ratios[1].probe.ratio": "2",
    })
    vec(GJ, 1, "several-items-nested-and-scalar-roundtrip", GJ, GJ, full, full, model=m)
    e = '{"id":"u2","title":"T","items":[],"data":{"nums":[]}}'
    vec(GJ, 2, "present-and-empty-list", GJ, GJ, e, e,
        model={"probe.items.#": "0", "probe.nums.#": "0", "probe.names.#": "absent", "probe.ratios.#": "absent"})
    vec(GJ, 3, "null-member-is-absent-list", GJ, GJ, '{"id":"u3","title":"T","items":null}', '{"id":"u3","title":"T"}',
        model={"probe.items.#": "absent"})
    # item 0 is `{}`, item 2 is `null`: both items hold nothing. The item default
    # (n 1) and the item const (kind) are written in each; the common default of
    # probe.label is written at `title` and in no item. The nested item `{}` has
    # nothing to write and stays `{}`. `kind` in item 1 is not checked on decode.
    vec(GJ, 4, "defaults-and-const-per-item-common-default-stays-out", GJ, GJ,
        '{"id":"u4","items":[{},{"name":"x","kind":"other","subs":[{}]},null]}',
        '{"id":"u4","title":"NONE","items":[{"n":1,"kind":"item"},{"name":"x","n":1,"kind":"item","subs":[{}]},{"n":1,"kind":"item"}]}',
        model={"probe.items.#": "3", "probe.items[1].probe.label": "x", "probe.items[1].probe.subs.#": "1",
               "probe.items[0].probe.subs.#": "absent"})
    # unmapped members inside an item are dropped (items carry no residue); the
    # unmapped top-level scalar `z` is residue; the unmapped top-level array is not carried
    vec(GJ, 5, "noncanonical-input-unmapped-item-members-dropped", GJ, GJ,
        '{ "z": 1, "items": [ {"subs": [{"v": 5, "t": "a", "w": 0}], "extra": 1, "r": {"unit": "x", "value": 0.25}, "n": 4, "name": "nm"} ],\n  "other": [1, 2], "id": "u5", "title": "T" }',
        '{"id":"u5","title":"T","items":[{"name":"nm","n":4,"r":{"value":0.25},"kind":"item","subs":[{"t":"a","v":5}]}],"z":1}',
        model={"probe.items.#": "1", "probe.items[0].probe.ratio": "0.25", "probe.items[0].probe.subs[0].probe.val": "5"})
    vec(GJ, 6, "list-member-not-an-array", GJ, GJ, '{"id":"u6","items":{"name":"x"}}', error="malformed-wire")
    vec(GJ, 7, "item-field-fails-its-transform", GJ, GJ, '{"id":"u7","items":[{"n":1},{"n":"two"}]}', error="transform-decode")
    vec(GJ, 8, "nested-item-field-fails-its-transform", GJ, GJ, '{"id":"u8","items":[{"subs":[{"v":1.5}]}]}', error="transform-decode")
    vec(GJ, 9, "scalar-item-of-the-wrong-type", GJ, GJ, '{"id":"u9","names":["a",5]}', error="transform-decode")
    # cross-wire
    vec(GJ, 10, "to-xml", GJ, GX, J_SRC, X_FULL, model=TAGS_MODEL)
    vec(GJ, 11, "to-protobuf", GJ, GP, J_SRC, P_FULL)
    vec(GJ, 12, "to-bits", GJ, GB, J_SRC, B_FULL)
    # bits msb: byte 0 = n (absent: 0) << 2 | count 1; byte 1 = nums 3 and 12 as
    # nibbles; item = qty 7, "ab"; one zero byte to the whole 16-bit word
    vec(GJ, 13, "to-bits-msb-fixed-count-and-count-locator", GJ, GM,
        '{"id":"u1","items":[{"name":"ab","n":7}],"data":{"nums":[3,12]}}', hx(bytes([0x01, 0x3C, 7]) + b"ab" + b"\0"))
    vec(GJ, 14, "to-geojson", GJ, GG, '{"id":"u1","items":[{"name":"aa","n":2,"subs":[{"t":"x","v":1},{"t":"y","v":2}]},{"name":"bb","n":3}],"names":["p"]}',
        '{"type":"Feature","geometry":null,"properties":{"items":[{"name":"aa","n":2,"subs":[{"t":"x","v":1},{"t":"y","v":2}]},{"name":"bb","n":3}]},"id":"u1","names":["p"]}')
    # scalar lists: nums inside submessage 3 as one packed field 1; names one
    # occurrence each; ratios packed doubles
    vec(GJ, 15, "scalar-lists-to-protobuf-packed", GJ, GP,
        '{"id":"u1","data":{"nums":[3,270,0]},"names":["p","qq"],"ratios":[0.5,-2]}',
        hx(ld(1, "u1") + ld(3, ld(1, varint(3) + varint(270) + varint(0))) + ld(4, "p") + ld(4, "qq")
           + ld(5, struct.pack("<d", 0.5) + struct.pack("<d", -2.0))))
    vec(GJ, 16, "scalar-lists-to-xml", GJ, GX, '{"id":"u1","data":{"nums":[3,270]},"names":["p","qq"]}',
        '<msg id="u1"><name>p</name><name>qq</name><nums><n>3</n><n>270</n></nums></msg>')
    # an empty list writes `[]` on json, nothing on xml and protobuf
    vec(GJ, 17, "empty-lists-to-xml-write-nothing", GJ, GX, '{"id":"u1","items":[],"names":[],"data":{"nums":[]}}', '<msg id="u1"/>')
    vec(GJ, 18, "empty-lists-to-protobuf-write-nothing", GJ, GP, '{"id":"u1","items":[],"names":[],"data":{"nums":[]},"ratios":[]}', hx(ld(1, "u1")))
    # bits: an empty list writes the count 0 and no item
    vec(GJ, 19, "empty-list-to-bits-writes-count-zero", GJ, GB, '{"id":"u1","items":[]}', hx(b"u1\0\0" + bytes([0])))
    # an absent list writes nothing: the count byte is part of the layout and stays 0
    vec(GJ, 20, "absent-list-to-bits", GJ, GB, '{"id":"u1"}', hx(b"u1\0\0" + bytes([0])))
    # four items do not fit the 2-bit count of the msb pack
    vec(GJ, 21, "to-bits-count-does-not-fit", GJ, GM,
        '{"items":[{"name":"aa","n":1},{"name":"bb","n":2},{"name":"cc","n":3},{"name":"dd","n":4}],"data":{"nums":[1,2]}}', error="transform-encode")
    # three nums for a group with the fixed count 2
    vec(GJ, 22, "to-bits-fixed-count-mismatch", GJ, GM, '{"data":{"nums":[1,2,3]}}', error="transform-encode")
    # ratio 100 is 400 on the wire, outside the 8-bit field of the item
    vec(GJ, 23, "to-bits-item-field-fails-its-transform", GJ, GB, '{"id":"u1","items":[{"name":"aa","r":{"value":100}}]}', error="transform-encode")
    # requires <list>: `listed` needs probe.items with at least one item
    vec(GJ, 24, "to-kinds-list-with-items-selects-listed", GJ, GK, '{"id":"u1","items":[{"name":"aa"},{"name":"bb"}],"names":["p"]}',
        '{"id":"u1","names":["p"],"shape":"listed","items":[{"name":"aa"},{"name":"bb"}]}')
    vec(GJ, 25, "to-kinds-empty-list-does-not-satisfy-requires", GJ, GK, '{"id":"u1","items":[]}', '{"id":"u1","shape":"bare"}')
    vec(GJ, 26, "to-kinds-absent-list-does-not-satisfy-requires", GJ, GK, '{"id":"u1","names":[]}', '{"id":"u1","names":[],"shape":"bare"}')
    # the item default of the target applies per item: item 1 has no qty
    vec(GJ, 27, "to-protobuf-item-default-and-const", GJ, GP, '{"id":"u1","items":[{"name":"aa","n":5},{"name":"bb"}]}',
        hx(ld(1, "u1") + ld(2, ld(1, "aa") + pv(2, 5) + pv(4, 9)) + ld(2, ld(1, "bb") + pv(2, 1) + pv(4, 9))))

    # ==========================================================================
    # conformance-groups-kinds
    # ==========================================================================
    k = '{"id":"k1","names":["p"],"shape":"listed","items":[]}'
    vec(GK, 1, "same-format-keeps-kind-with-empty-list", GK, GK, k, k, model={"@kind": "listed", "probe.items.#": "0", "probe.names.#": "1"})
    k = '{"id":"k2","shape":"listed","items":[{"name":"aa"}]}'
    vec(GK, 2, "group-in-a-kind-roundtrip", GK, GK, k, k, model={"@kind": "listed", "probe.items[0].probe.label": "aa"})
    # the group of kind `listed` is not read when `bare` is selected: `items` is an
    # array, not carried as residue
    vec(GK, 3, "group-of-another-kind-is-not-read", GK, GK, '{"id":"k3","shape":"bare","items":[{"name":"aa"}]}', '{"id":"k3","shape":"bare"}',
        model={"@kind": "bare", "probe.items.#": "absent"})
    vec(GK, 4, "to-groups-json", GK, GJ, '{"id":"k4","names":["p"],"shape":"listed","items":[{"name":"aa"}]}',
        '{"id":"k4","title":"NONE","items":[{"name":"aa","n":1,"kind":"item"}],"names":["p"]}')

    # ==========================================================================
    # conformance-groups-xml
    # ==========================================================================
    x = '<msg id="u1"><head cs="C"/><body><item name="aa" r="0.5" k="i"><qty>2</qty><sub v="1">x</sub><sub v="2">y</sub></item><item name="bb" r="1.25" k="i"><qty>3</qty></item></body><tail how="m-g"/><name>p</name><name>q</name><nums><n>3</n><n>1</n></nums></msg>'
    m = dict(TAGS_MODEL)
    m.update({"callsign": "C", "how": "m-g", "probe.names.#": "2", "probe.names[0].probe.tag": "p", "probe.nums.#": "2", "probe.nums[1].probe.val": "1"})
    vec(GX, 1, "several-items-nested-and-text-roundtrip", GX, GX, x, x, model=m)
    # Items are every `item` child of the FIRST `body`, in document order, whatever
    # lies between them; the second `body` is not read. `name` items are read
    # wherever they stand among the root's children. Output: `head`, `body`, `tail`,
    # then the `name` items, in line order; inside an item `qty` before the subs.
    vec(GX, 2, "sibling-order-and-position-among-other-elements", GX, GX,
        '<msg id="u2"><name>p</name><tail how="h-e"/><x/><name>q</name><body><note/><item name="a1"><qty>1</qty></item><other/><item name="a2"><sub>s</sub><qty>5</qty><sub v="7"/></item></body><body><item name="zz"/></body><head cs="C"/><name>r</name></msg>',
        '<msg id="u2"><head cs="C"/><body><item name="a1" k="i"><qty>1</qty></item><item name="a2" k="i"><qty>5</qty><sub>s</sub><sub v="7"/></item></body><tail how="h-e"/><name>p</name><name>q</name><name>r</name></msg>',
        model={"probe.items.#": "2", "probe.items[0].probe.label": "a1", "probe.items[1].probe.qty": "5",
               "probe.items[1].probe.subs.#": "2", "probe.items[1].probe.subs[0].probe.tag": "s",
               "probe.items[1].probe.subs[1].probe.val": "7", "probe.names.#": "3", "probe.names[2].probe.tag": "r"})
    # no `item` occurs: the list is absent, and nothing addresses `body` on encode
    vec(GX, 3, "no-item-occurs-list-absent", GX, GX, '<msg id="u3"><body/></msg>', '<msg id="u3"/>',
        model={"probe.items.#": "absent", "probe.names.#": "absent"})
    vec(GX, 4, "one-empty-item-default-and-const", GX, GX, '<msg id="u4"><body><item/></body></msg>',
        '<msg id="u4"><body><item k="i"><qty>1</qty></item></body></msg>', model={"probe.items.#": "1"})
    vec(GX, 5, "item-field-fails-its-transform", GX, GX, '<msg id="u5"><body><item><qty>1</qty></item><item><qty>x</qty></item></body></msg>', error="transform-decode")
    # a `name` with no text is an item that holds nothing
    vec(GX, 6, "text-items-one-without-text", GX, GX, '<msg id="u6"><name/><name>b</name></msg>', '<msg id="u6"><name/><name>b</name></msg>',
        model={"probe.names.#": "2", "probe.names[1].probe.tag": "b"})
    # ruling 11 of 0.6: a pack without kinds
    vec(GX, 7, "wrong-root-in-a-pack-without-kinds", GX, GX, '<mesg id="u7"/>', error="missing-root")
    vec(GX, 8, "to-json", GX, GJ, X_SRC, J_FULL, model=TAGS_MODEL)
    vec(GX, 9, "to-protobuf", GX, GP, X_SRC, P_FULL)
    vec(GX, 10, "to-bits", GX, GB, X_SRC, B_FULL)
    vec(GX, 11, "scalar-lists-to-json", GX, GJ, '<msg id="u1"><nums><n>3</n><n>270</n></nums><name>p</name><name>qq</name></msg>',
        '{"id":"u1","title":"NONE","data":{"nums":[3,270]},"names":["p","qq"]}')
    vec(GX, 12, "scalar-lists-to-protobuf", GX, GP, '<msg id="u1"><nums><n>3</n><n>270</n></nums><name>p</name><name>qq</name></msg>',
        hx(ld(1, "u1") + ld(3, ld(1, varint(3) + varint(270))) + ld(4, "p") + ld(4, "qq")))

    # ==========================================================================
    # conformance-groups-protobuf
    # ==========================================================================
    m = dict(TAGS_MODEL)
    vec(GP, 1, "several-items-nested-roundtrip", GP, GP, P_SRC, P_SRC, model=m)
    # Unpacked and packed input for one field decode alike, in wire order; output
    # is packed. nums (3.1): 3, then a packed occurrence 1 2, then 4. ratios (5):
    # two fixed64 occurrences. deltas (6): -1 and 2 as zig-zag varints, one
    # occurrence each. gains (7): one fixed32 occurrence then a packed pair.
    inp = (ld(1, "u1") + ld(3, pv(1, 3) + ld(1, varint(1) + varint(2)) + pv(1, 4))
           + pd(5, 0.5) + pd(5, -2.0) + ps(6, -1) + ps(6, 2)
           + pf(7, 1.5) + ld(7, struct.pack("<f", 0.25) + struct.pack("<f", -8.0)))
    out = (ld(1, "u1") + ld(3, ld(1, varint(3) + varint(1) + varint(2) + varint(4)))
           + ld(5, struct.pack("<d", 0.5) + struct.pack("<d", -2.0))
           + ld(6, varint(zz(-1)) + varint(zz(2)))
           + ld(7, struct.pack("<f", 1.5) + struct.pack("<f", 0.25) + struct.pack("<f", -8.0)))
    pm = {"probe.nums.#": "4", "probe.nums[0].probe.val": "3", "probe.nums[1].probe.val": "1", "probe.nums[2].probe.val": "2",
          "probe.nums[3].probe.val": "4", "probe.ratios.#": "2", "probe.ratios[1].probe.ratio": "-2",
          "probe.deltas.#": "2", "probe.deltas[0].probe.val": "-1", "probe.deltas[1].probe.val": "2",
          "probe.gains.#": "3", "probe.gains[0].probe.ratio": "1.5", "probe.gains[2].probe.ratio": "-8"}
    vec(GP, 2, "unpacked-and-packed-input-packed-output", GP, GP, hx(inp), hx(out), model=pm)
    vec(GP, 3, "packed-input-roundtrip", GP, GP, hx(out), hx(out), model=pm)
    # no occurrence, and one packed occurrence that holds no value: no item occurs, the lists are absent
    vec(GP, 4, "no-item-occurs-list-absent", GP, GP, hx(ld(1, "u4") + ld(5, b"")), hx(ld(1, "u4")),
        model={"probe.items.#": "absent", "probe.ratios.#": "absent", "probe.nums.#": "absent"})
    # an empty occurrence of field 2 is an item that holds nothing: the default qty
    # and the const are written. An empty occurrence of field 5 inside an item is a
    # nested item that holds nothing: an empty length-delimited occurrence.
    vec(GP, 5, "empty-items-default-and-const", GP, GP, hx(ld(1, "u5") + ld(2, b"") + ld(2, ld(5, b""))),
        hx(ld(1, "u5") + ld(2, pv(2, 1) + pv(4, 9)) + ld(2, pv(2, 1) + pv(4, 9) + ld(5, b""))),
        model={"probe.items.#": "2", "probe.items[1].probe.subs.#": "1", "probe.items[0].probe.subs.#": "absent"})
    # string items, one occurrence each, never packed; the empty string is an item
    s = hx(ld(1, "u6") + ld(4, "p") + ld(4, "") + ld(4, "qq"))
    vec(GP, 6, "string-items-one-occurrence-each", GP, GP, s, s,
        model={"probe.names.#": "3", "probe.names[1].probe.tag": "", "probe.names[2].probe.tag": "qq"})
    # field 2 of the second item is length-delimited where `pvarint` needs a varint
    vec(GP, 7, "item-field-fails-its-transform", GP, GP, hx(ld(1, "u7") + ld(2, pv(2, 1)) + ld(2, ld(2, "x"))), error="transform-decode")
    # non-canonical input: items and other fields interleaved, item fields out of order
    vec(GP, 8, "noncanonical-input-items-in-wire-order", GP, GP,
        hx(ld(2, pv(2, 7) + ld(1, "a1")) + ld(8, "C") + ld(2, ld(1, "a2")) + ld(1, "u8")),
        hx(ld(1, "u8") + ld(2, ld(1, "a1") + pv(2, 7) + pv(4, 9)) + ld(2, ld(1, "a2") + pv(2, 1) + pv(4, 9)) + ld(8, "C")),
        model={"probe.items.#": "2", "probe.items[0].probe.label": "a1", "probe.items[1].probe.label": "a2", "callsign": "C"})
    vec(GP, 9, "to-json", GP, GJ, P_SRC, J_FULL, model=TAGS_MODEL)
    vec(GP, 10, "to-xml", GP, GX, P_SRC, X_FULL)
    vec(GP, 11, "to-bits", GP, GB, P_SRC, B_FULL)
    vec(GP, 12, "scalar-lists-to-json", GP, GJ, hx(inp),
        '{"id":"u1","title":"NONE","data":{"nums":[3,1,2,4]},"ratios":[0.5,-2]}')
    vec(GP, 13, "scalar-lists-to-xml", GP, GX, hx(ld(1, "u1") + ld(3, ld(1, varint(3) + varint(270))) + ld(4, "p") + ld(4, "qq")),
        '<msg id="u1"><name>p</name><name>qq</name><nums><n>3</n><n>270</n></nums></msg>')

    # ==========================================================================
    # conformance-groups-bits (lsb)
    # ==========================================================================
    bm = dict(ITEMS_MODEL)
    bm["probe.items[1].probe.subs.#"] = "0"
    vec(GB, 1, "two-items-nested-roundtrip", GB, GB, B_SRC, B_SRC, model=bm)
    z = hx(b"u2\0\0" + bytes([0]))
    vec(GB, 2, "count-zero-list-present-and-empty", GB, GB, z, z, model={"uid": "u2", "probe.items.#": "0"})
    # the high nibble of item byte 4 is a const: 0 on input, 10 on output. One sub (value 9).
    vec(GB, 3, "one-item-const-written-over-input", GB, GB, hx(b"u3\0\0" + bytes([1, 7]) + b"ab" + bytes([4, 0x01, 0x09])),
        hx(b"u3\0\0" + bytes([1, 7]) + b"ab" + bytes([4, 0xA1, 0x09])),
        model={"probe.items.#": "1", "probe.items[0].probe.qty": "7", "probe.items[0].probe.label": "ab",
               "probe.items[0].probe.ratio": "1", "probe.items[0].probe.subs.#": "1", "probe.items[0].probe.subs[0].probe.val": "9"})
    # count 2, one item present
    vec(GB, 4, "input-ends-before-the-counted-items", GB, GB, hx(b"u4\0\0" + bytes([2, 7]) + b"ab" + bytes([4, 0xA0, 0])), error="malformed-wire")
    # input longer than the counted items is accepted and the rest ignored
    vec(GB, 5, "input-longer-than-the-counted-items", GB, GB, hx(b"u5\0\0" + bytes([1, 7]) + b"ab" + bytes([4, 0xA0, 0]) + b"\xff\xff"),
        hx(b"u5\0\0" + bytes([1, 7]) + b"ab" + bytes([4, 0xA0, 0])), model={"probe.items.#": "1"})
    # the label of the item holds byte 0x01
    vec(GB, 6, "item-field-fails-its-transform", GB, GB, hx(b"u6\0\0" + bytes([1, 7, 0x01, 0x62, 4, 0xA0, 0])), error="transform-decode")
    vec(GB, 7, "to-json", GB, GJ, B_SRC, J_FROM_B, model=bm)
    vec(GB, 8, "to-xml", GB, GX, B_SRC, X_FROM_B)
    vec(GB, 9, "to-protobuf", GB, GP, B_SRC, P_FROM_B)
    vec(GB, 10, "count-zero-to-json-writes-empty-array", GB, GJ, z, '{"id":"u2","title":"NONE","items":[]}')

    # ==========================================================================
    # conformance-groups-bits-msb
    # ==========================================================================
    # byte 0 = n 5 << 2 | count 1 = 0x15; byte 1 = nums 3, 12; item 07 "ab"; pad
    r = hx(bytes([0x15, 0x3C, 7]) + b"ab" + b"\0")
    mm = {"probe.n": "5", "probe.nums.#": "2", "probe.nums[0].probe.val": "3", "probe.nums[1].probe.val": "12",
          "probe.items.#": "1", "probe.items[0].probe.qty": "7", "probe.items[0].probe.label": "ab"}
    vec(GM, 1, "fixed-count-and-count-locator-roundtrip", GM, GM, r, r, model=mm)
    z = hx(bytes([0x14, 0x3C]))
    vec(GM, 2, "count-zero-one-word", GM, GM, z, z, model={"probe.n": "5", "probe.items.#": "0", "probe.nums.#": "2"})
    # three items: 2 + 9 = 11 bytes, padded to 12
    t = hx(bytes([0x17, 0x3C, 1]) + b"aa" + bytes([2]) + b"bb" + bytes([3]) + b"cc" + b"\0")
    vec(GM, 3, "three-items-padded-to-whole-words", GM, GM, t, t, model={"probe.items.#": "3", "probe.items[2].probe.label": "cc"})
    vec(GM, 4, "input-ends-before-the-counted-items", GM, GM, hx(bytes([0x15, 0x3C, 7, 0x61])), error="malformed-wire")
    # the item fits in 5 bytes, but the message is whole 16-bit words: 6 bytes
    vec(GM, 5, "input-not-whole-words", GM, GM, hx(bytes([0x15, 0x3C, 7]) + b"ab"), error="malformed-wire")
    vec(GM, 6, "to-json", GM, GJ, r, '{"title":"NONE","items":[{"name":"ab","n":7,"kind":"item"}],"data":{"nums":[3,12]}}')
    vec(GM, 7, "to-xml", GM, GX, r, '<msg><body><item name="ab" k="i"><qty>7</qty></item></body><nums><n>3</n><n>12</n></nums></msg>')

    # ==========================================================================
    # conformance-groups-geojson
    # ==========================================================================
    g = '{"type":"Feature","geometry":{"type":"Point","coordinates":[2,1]},"properties":{"items":[{"name":"aa","n":2,"subs":[{"t":"x","v":1},{"t":"y","v":2}]},{"name":"bb","n":3}]},"id":"u1","names":["p","q"]}'
    vec(GG, 1, "items-in-properties-and-top-level-scalars-roundtrip", GG, GG, g, g,
        model={"uid": "u1", "probe.items.#": "2", "probe.items[0].probe.subs[1].probe.tag": "y", "probe.items[1].probe.qty": "3",
               "probe.names.#": "2", "probe.names[0].probe.tag": "p"})
    g = '{"type":"Feature","geometry":null,"properties":{"items":[]},"id":"u2"}'
    vec(GG, 2, "present-and-empty-and-absent", GG, GG, g, g, model={"probe.items.#": "0", "probe.names.#": "absent"})
    vec(GG, 3, "null-member-is-absent-list", GG, GG, '{"type":"Feature","geometry":null,"properties":{"items":null},"id":"u3","names":null}',
        '{"type":"Feature","geometry":null,"properties":{},"id":"u3"}', model={"probe.items.#": "absent", "probe.names.#": "absent"})
    vec(GG, 4, "list-member-not-an-array", GG, GG, '{"type":"Feature","geometry":null,"properties":{"items":"x"},"id":"u4"}', error="malformed-wire")
    vec(GG, 5, "item-field-fails-its-transform", GG, GG, '{"type":"Feature","geometry":null,"properties":{"items":[{"n":"x"}]},"id":"u5"}', error="transform-decode")
    vec(GG, 6, "to-json", GG, GJ, '{"type":"Feature","geometry":null,"properties":{"items":[{"name":"aa","n":2,"subs":[{"t":"x","v":1}]},{"name":"bb"}]},"id":"u1","names":["p"]}',
        '{"id":"u1","title":"NONE","items":[{"name":"aa","n":2,"kind":"item","subs":[{"t":"x","v":1}]},{"name":"bb","n":1,"kind":"item"}],"names":["p"]}')

    # ==========================================================================
    # Rulings of 0.6
    # ==========================================================================
    RJ, RB = "conformance-rulings-json", "conformance-rulings-bits"
    # ruling 2: the kind's default of `callsign` (KIND) is used at the common field
    # `name` and at the kind field `alias`; `how` has a default, so at `slot` it is
    # the earliest line whose key is present and its default is written, though the
    # entity has probe.s1 for the later line.
    vec(RJ, 1, "ruling-02-kind-default-used-for-common-and-kind-fields", RJ, RJ, '{"k":1,"id":"a","s1":"x"}',
        '{"id":"a","name":"KIND","s1":"x","slot":"h-c","marker":"present","k":1,"alias":"KIND"}', model={"@kind": "named", "probe.s1": "x"})
    vec(RJ, 2, "ruling-02-common-default-in-a-kind-without-its-own", RJ, RJ, '{"k":2,"id":"a"}',
        '{"id":"a","name":"COMMON","slot":"h-c","marker":"present","k":2}', model={"@kind": "plain"})
    # ruling 2: `requires callsign` looks at the entity only. The entity has no
    # callsign, so `named` is not selected although a default exists; `plain` is.
    # ruling 7: probe.j1 is derived by `join` of the one argument probe.s1.
    vec("conformance-derive", 4, "ruling-02-07-requires-ignores-defaults-join-of-one-argument", "conformance-derive", RJ,
        '{"id":"u1","s1":"x"}', '{"id":"u1","name":"COMMON","s1":"x","slot":"h-c","j1":"x","marker":"present","k":2}')
    # ruling 3: `const marker =present` writes the text; the const is not checked on decode
    vec(RJ, 3, "ruling-03-const-eq-present-writes-the-text", RJ, RJ, '{"k":2,"id":"a","marker":"other"}',
        '{"id":"a","name":"COMMON","slot":"h-c","marker":"present","k":2}')
    # ruling 4: the entry `01` matches the wire integer 1; the all-integer table
    # `tens` on the float key `lat` reads its model side as float.
    # ruling 6: `t` is "1": the table gives F, then the typemap gives a-f-G; encode the reverse.
    vec(RJ, 4, "ruling-04-06-table-entries-canonicalised-table-then-typemap", RJ, RJ, '{"k":2,"id":"a","t":"1","lat":2,"cls":1}',
        '{"id":"a","name":"COMMON","slot":"h-c","t":"1","lat":2,"cls":1,"marker":"present","k":2}',
        model={"type": "a-f-G", "lat": "20", "track.class": "uas"})
    # ruling 4: `conf` is a string with no entry in `word`, whose model side is
    # float: the line fails, and `conf2` is not tried
    vec(RJ, 5, "ruling-04-table-miss-of-another-type-fails-later-line-not-tried", RJ, RJ, '{"k":2,"id":"a","conf":"medium","conf2":0.5}', error="transform-decode")
    vec(RJ, 6, "ruling-04-table-entry-found", RJ, RJ, '{"k":2,"id":"a","conf":"high"}',
        '{"id":"a","name":"COMMON","slot":"h-c","conf":"high","conf2":0.9,"marker":"present","k":2}', model={"track.confidence": "0.9"})
    # ruling 5: the transform of the first line fails (a number where `string` is
    # needed), the second line succeeds: no error. Encode: 0.5 has no entry in
    # `word` and the types differ, so the `conf` line fails.
    vec(RJ, 7, "ruling-05-earlier-line-fails-later-succeeds", RJ, "conformance-derive", '{"k":2,"id":"a","conf":5,"conf2":0.5,"s1":"x"}',
        '{"id":"a","s1":"x"}', model={"track.confidence": "0.5"})
    # ruling 5: the earlier line succeeds, the later fails: no error
    vec(RJ, 8, "ruling-05-earlier-line-succeeds-later-fails", RJ, RJ, '{"k":2,"id":"a","ce":3,"ce2":"bad"}',
        '{"id":"a","name":"COMMON","slot":"h-c","ce":3,"ce2":3,"marker":"present","k":2}', model={"ce": "3"})
    # ruling 10: an empty context counts as given, so a same-format conversion
    # applies the derivations (probe.j1 from probe.s1); with no context it does not
    vec(RJ, 9, "ruling-10-empty-context-counts-as-given", RJ, RJ, '{"k":2,"id":"a","s1":"x"}',
        '{"id":"a","name":"COMMON","s1":"x","slot":"h-c","j1":"x","marker":"present","k":2}', context={})
    vec(RJ, 10, "ruling-10-no-context-same-format-derives-nothing", RJ, RJ, '{"k":2,"id":"a","s1":"x"}',
        '{"id":"a","name":"COMMON","s1":"x","slot":"h-c","marker":"present","k":2}')
    # ruling 10: context keys are checked after decode. The decode fails, so that is the error.
    vec(RJ, 11, "ruling-10-decode-error-comes-before-context-check", RJ, RJ, '{"k":2,"id":"a","ce":"bad"}', error="transform-decode",
        context={"nosuch.key": "1"})
    vec(RJ, 12, "ruling-10-undeclared-context-key", RJ, RJ, '{"k":2,"id":"a"}', error="undeclared-key", context={"nosuch.key": "1"})
    # ruling 10: every context key is checked, also one the entity already has
    vec(RJ, 13, "ruling-10-context-key-the-entity-has-is-still-checked", RJ, RJ, '{"k":2,"id":"a","ce":3}', error="key-type-mismatch",
        context={"ce": "wide"})
    # ruling 8: 9223372036854775000 + 1000 overflows: probe.n_next stays absent
    vec("conformance-derive", 5, "ruling-08-integer-offset-overflow-leaves-target-absent", "conformance-derive", "conformance-derive",
        '{"id":"u1","n":9223372036854775000}', '{"id":"u1","n":9223372036854775000,"n_copy":9223372036854775000}', context={})
    # ruling 11: a root no kind has, in a pack with kinds and no pack-level root
    vec("conformance-rules-xml", 8, "ruling-11-root-of-no-kind-is-no-kind", "conformance-rules-xml", "conformance-rules-xml",
        '<event id="p1"/>', error="no-kind")
    # ruling 13: geojson residue. Numbers keep their text and come back as strings;
    # the array and the object come back as they were; null is dropped; of the two
    # `dup` members the last value is used at the first position.
    vec("conformance-geojson", 4, "ruling-13-residue-numbers-arrays-objects-null-duplicates", "conformance-geojson", "conformance-geojson",
        '{"type":"Feature","geometry":null,"properties":{"schema":"probe","rev":"1","n":1.50,"e":1e3,"dup":1,"arr":[1.0,{"a":null},"s"],"obj":{"x":2.50},"nul":null,"dup":"last"},"profile":"probe","id":"g"}',
        '{"type":"Feature","geometry":null,"properties":{"schema":"probe","rev":"1","n":"1.50","e":"1e3","dup":"last","arr":[1.0,{"a":null},"s"],"obj":{"x":2.50}},"profile":"probe","id":"g"}',
        model={"@kind": "v1"})
    # rulings 3 and 14 on bits: two bytes per word
    vec(RB, 1, "ruling-03-const-counts-toward-decode-length", RB, RB, "0700", error="malformed-wire")
    vec(RB, 2, "ruling-14-whole-words-up-to-the-furthest-required-bit", RB, RB, "070009", error="malformed-wire")
    # four bytes: probe.qty (inside word 1) is present, probe.val (word 2) is absent; encode writes three words
    vec(RB, 3, "ruling-14-optional-field-in-a-required-word-is-read", RB, RB, "07000933", "070009330000",
        model={"probe.n": "7", "probe.qty": "51"})
    # the const is not checked on decode (0 here) and is written as 9
    vec(RB, 4, "ruling-03-const-not-checked-and-written", RB, RB, "070000330500", "070009330500",
        model={"probe.n": "7", "probe.qty": "51", "probe.val": "5"})

    # ==========================================================================
    # Load vectors
    # ==========================================================================
    CORE = 'module core\nversion 0.1.0\ndistribution public\nsource "probe"\nkey uid string -\nkey type string -\nkey lat float deg\nkey lon float deg\nkey callsign string -\nkey time_ms int ms\n'
    PM = 'module probe\nversion 0.1.0\ndistribution public\nsource "probe"\nkey label string -\nkey qty int -\nkey tag string -\nlist items "a list"\nlist subs "a nested list"\n'
    HEAD = 'format probe\nversion 0.7.0\ndistribution public\nsource "probe"\nuses probe\n'
    JS = HEAD + 'wire json\nfield uid id string\n'
    BS = HEAD + 'wire bits\nword_bytes 1\nfield probe.qty 0:0:8 uint\n'
    n = 75


    def L(name, pack, error=None, models=None):
        nonlocal n
        load(n, name, models if models is not None else [CORE, PM], pack, error)
        n += 1


    L("group-and-nested-group-load", JS + 'group probe.items items\n  field probe.label name string\n  const kind item\n  default probe.qty 1\n  group probe.subs subs\n    field probe.tag t string\n  end\nend\n')
    L("list-and-key-of-one-name", JS, "duplicate-key", [CORE, PM + 'key items string -\n'])
    L("key-and-list-of-one-name", JS, "duplicate-key", [CORE, PM + 'list label\n'])
    L("list-declared-twice", JS, "duplicate-key", [CORE, PM + 'list items\n'])
    L("group-without-end", JS + 'group probe.items items\n  field probe.label name string\n', "bad-directive")
    L("nested-group-without-end", JS + 'group probe.items items\n  group probe.subs subs\n    field probe.tag t string\nend\n', "bad-directive")
    L("end-without-group", JS + 'end\n', "bad-directive")
    L("second-end-without-group", JS + 'group probe.items items\n  field probe.label name string\nend\nend\n', "bad-directive")
    L("when-inside-group", JS + 'kind a\ngroup probe.items items\n  when name x\nend\n', "bad-directive")
    L("requires-inside-group", JS + 'kind a\ngroup probe.items items\n  requires uid\nend\n', "bad-directive")
    L("kind-inside-group", JS + 'group probe.items items\n  kind a\nend\n', "bad-directive")
    L("root-inside-group", HEAD + 'wire xml\nroot msg\nfield uid @id string\ngroup probe.items item\n  root other\nend\n', "bad-directive")
    L("group-undeclared-list", JS + 'group probe.things items\n  field probe.label name string\nend\n', "undeclared-key")
    L("group-list-of-a-module-not-used", 'format probe\nversion 0.7.0\ndistribution public\nsource "probe"\nwire json\nfield uid id string\ngroup probe.items items\n  field uid name string\nend\n', "module-not-used")
    L("group-names-a-scalar-key", JS + 'group probe.label items\n  field probe.tag name string\nend\n', "key-type-mismatch")
    L("field-names-a-list", JS + 'field probe.items items string\n', "key-type-mismatch")
    L("field-inside-group-names-a-list", JS + 'group probe.items items\n  field probe.subs subs string\nend\n', "key-type-mismatch")
    L("field-inside-group-undeclared-key", JS + 'group probe.items items\n  field probe.nosuch name string\nend\n', "undeclared-key")
    L("default-inside-group-undeclared-key", JS + 'group probe.items items\n  field probe.label name string\n  default probe.nosuch 1\nend\n', "undeclared-key")
    L("field-inside-group-key-type-mismatch", JS + 'group probe.items items\n  field probe.qty n string\nend\n', "key-type-mismatch")
    L("count-on-json", JS + 'group probe.items items count 2\n  field probe.label name string\nend\n', "bad-directive")
    L("count-on-xml", HEAD + 'wire xml\nroot msg\nfield uid @id string\ngroup probe.items item count 2\n  field probe.label @name string\nend\n', "bad-directive")
    L("count-on-protobuf", HEAD + 'wire protobuf\nfield uid 1 pstring\ngroup probe.items 2 count 2\n  field probe.label 1 pstring\nend\n', "bad-directive")
    L("count-locator-on-geojson", HEAD + 'wire geojson\nfield uid id string\ngroup probe.items properties.items count properties.n\n  field probe.label name string\nend\n', "bad-directive")
    L("bits-group-with-count-locator-loads", BS + 'group probe.items 0:16 item 8 count 0:8:8\n  field probe.qty 0:0:8 uint\nend\n')
    L("bits-group-with-fixed-count-loads", BS + 'group probe.items 0:8 item 8 count 3\n  field probe.qty 0:0:8 uint\nend\n')
    L("bits-group-without-count", BS + 'group probe.items 0:16 item 8\n  field probe.qty 0:0:8 uint\nend\n', "bad-directive")
    L("bits-field-beyond-counted-group-start", BS + 'group probe.items 0:16 item 8 count 0:8:8\n  field probe.qty 0:0:8 uint\nend\nfield probe.qty 0:64:8 uint\n', "bad-directive")
    L("bits-field-reaching-into-counted-group-start", BS + 'field probe.qty 0:12:8 uint\ngroup probe.items 0:16 item 8 count 0:8:8\n  field probe.qty 0:0:8 uint\nend\n', "bad-directive")
    L("bits-const-beyond-counted-group-start", BS + 'group probe.items 0:16 item 8 count 0:8:8\n  field probe.qty 0:0:8 uint\nend\nconst 0:16:8 1\n', "bad-directive")
    L("bits-when-beyond-counted-group-start", BS + 'group probe.items 0:16 item 8 count 0:8:8\n  field probe.qty 0:0:8 uint\nend\nkind a\nwhen 0:24:8 1\n', "bad-directive")
    L("bits-kind-field-beyond-common-counted-group-start", BS + 'group probe.items 0:16 item 8 count 0:8:8\n  field probe.qty 0:0:8 uint\nend\nkind a\nfield probe.qty 0:32:8 uint\n', "bad-directive")
    L("bits-field-after-fixed-count-group-loads", BS + 'group probe.items 0:8 item 8 count 3\n  field probe.qty 0:0:8 uint\nend\nfield probe.qty 0:32:8 uint\n')
    L("bits-nested-field-beyond-nested-counted-group-start", BS + 'group probe.items 0:16 item 32 count 0:8:8\n  group probe.subs 0:8 item 4 count 0:0:8\n    field probe.qty 0:0:4 uint\n  end\n  field probe.qty 0:24:8 uint\nend\n', "bad-directive")
    L("list-mapped-twice-in-common", JS + 'group probe.items items\n  field probe.label name string\nend\ngroup probe.items more\n  field probe.label name string\nend\n', "bad-directive")
    L("list-mapped-in-common-and-in-a-kind", JS + 'group probe.items items\n  field probe.label name string\nend\nkind a\ngroup probe.items more\n  field probe.label name string\nend\n', "bad-directive")
    L("list-mapped-twice-in-one-group-body", JS + 'group probe.items items\n  group probe.subs a\n    field probe.tag t string\n  end\n  group probe.subs b\n    field probe.tag t string\n  end\nend\n', "bad-directive")
    L("list-mapped-in-two-kinds-loads", JS + 'kind a\nwhen k 1\ngroup probe.items items\n  field probe.label name string\nend\nkind b\nwhen k 2\ngroup probe.items more\n  field probe.label name string\nend\n')
    L("list-mapped-at-two-depths-loads", JS + 'group probe.items items\n  group probe.items inner\n    field probe.label name string\n  end\nend\n')
    L("requires-a-list-loads", JS + 'kind a\nrequires probe.items\ngroup probe.items items\n  field probe.label name string\nend\n')
    L("scalar-item-locator-outside-a-group", JS + 'field probe.label . string\n', "bad-directive")
    L("scalar-item-locator-loads", JS + 'group probe.items items\n  field probe.label . string\nend\n')
    L("xml-item-text-and-nested-group-load", HEAD + 'wire xml\nroot msg\nfield uid @id string\ngroup probe.items body/item\n  field probe.label "#text" string\n  const @k i\n  group probe.subs sub\n    field probe.tag @t string\n  end\nend\n')
    L("protobuf-scalar-and-submessage-groups-load", HEAD + 'wire protobuf\nfield uid 1 pstring\ngroup probe.items 2\n  field probe.label 1 pstring\n  const 3 1\n  group probe.subs 4.1\n    field probe.tag . pstring\n  end\nend\n')
    L("group-error-comes-before-missing-distribution", 'format probe\nversion 0.7.0\nsource "probe"\nuses probe\nwire json\nfield uid id string\ngroup probe.items items\n  field probe.label name string\n', "bad-directive")
    # rulings of 0.6
    L("ruling-03-const-present", JS + 'const marker present\n', "bad-directive")
    L("ruling-04-all-integer-table-on-float-key-loads", JS + 'field lat lat float via tens\nmap tens 1 10\nmap tens 2 20\n')
    L("ruling-02-default-not-of-the-key-type", JS + 'field lat lat float\ndefault lat north\n', "key-type-mismatch")
    L("ruling-12-unknown-field-option", JS + 'field lat lat float always\n', "bad-directive")
    L("ruling-12-repeated-field-option", BS + 'field probe.qty 0:8:8 uint optional optional\n', "bad-directive")
    L("ruling-12-repeated-via", JS + 'field lat lat float via a via a\nmap a 1 10\n', "bad-directive")
    DM = 'module probe\nversion 0.1.0\ndistribution public\nsource "probe"\nkey label string -\nkey tag string -\nkey qty int -\nkey n2 int -\nkey a float -\nlist items\n'
    L("ruling-07-join-of-one-argument-loads", JS, None, [CORE, DM + 'derive probe.tag join:- probe.label\n'])
    L("ruling-08-integer-offset-loads", JS, None, [CORE, DM + 'derive probe.n2 offset:5 probe.qty\n'])
    L("ruling-08-offset-not-an-integer-on-int-keys", JS, "bad-directive", [CORE, DM + 'derive probe.n2 offset:1.5 probe.qty\n'])
    L("ruling-08-offset-int-target-float-argument", JS, "bad-directive", [CORE, DM + 'derive probe.n2 offset:1 probe.a\n'])
    L("ruling-08-offset-float-target-int-argument", JS, "bad-directive", [CORE, DM + 'derive probe.a offset:1 probe.qty\n'])
    L("ruling-09-derive-check-before-missing-distribution", JS, "bad-directive",
      [CORE, 'module probe\nversion 0.1.0\nsource "probe"\nkey label string -\nderive probe.label nosuchfn probe.label\n'])
    L("ruling-09-derive-names-core-key-with-core-not-loaded", JS, "bad-directive",
      ['module probe\nversion 0.1.0\ndistribution public\nsource "probe"\nkey label string -\nderive probe.label copy uid\n', CORE])
    L("ruling-09-derive-names-core-key-with-core-loaded", JS + 'group probe.items items\n  field probe.label name string\nend\n', None,
      [CORE, DM + 'derive probe.label copy uid\n'])


    # ==========================================================================
    # Part D: canonical-track-v2 identifiers, remote-id Message Pack
    # ==========================================================================
    CT, DT, RID = "canonical-track-v2", "demo-track-json", "remote-id"
    REQ = '"apiVersion":"billie.dev/track-v2","kind":"Track","trackId":"t1","sourceId":"s1","trackGeneration":"1","observedAt":"2026-03-01T12:30:45.000Z","position":{"latitudeDeg":56.25,"longitudeDeg":21.5}'
    # vector 06, changed: the identifiers array is now carried, after the mapped members
    vec(CT, 6, "required-only-noncanonical-identifiers-carried", CT, CT,
        '{\n  "position": {"longitudeDeg": 21.5, "latitudeDeg": 56.25},\n  "observedAt": "2026-03-01T12:30:45Z",\n  "identifiers": [{"scheme": "icao24", "value": "4b1805"}],\n  "trackGeneration": "1",\n  "sourceId": "s1",\n  "trackId": "t1",\n  "kind": "Track",\n  "apiVersion": "billie.dev/track-v2"\n}',
        '{' + REQ + ',"identifiers":[{"scheme":"icao24","value":"4b1805"}]}',
        model={"@kind": "Track", "time_ms": "1772368245000", "track.identifiers.#": "1",
               "track.identifiers[0].track.id_scheme": "icao24", "track.identifiers[0].track.id_value": "4b1805"})
    ids = '{' + REQ + ',"identifiers":[{"scheme":"icao24","value":"4b1805"},{"scheme":"callsign","value":"BTI7"},{"scheme":"mode-s"}]}'
    vec(CT, 18, "identifiers-several-roundtrip", CT, CT, ids, ids,
        model={"track.identifiers.#": "3", "track.identifiers[1].track.id_scheme": "callsign",
               "track.identifiers[1].track.id_value": "BTI7", "track.identifiers[2].track.id_scheme": "mode-s"})
    e = '{' + REQ + ',"identifiers":[]}'
    vec(CT, 19, "identifiers-empty-array-is-kept", CT, CT, e, e, model={"track.identifiers.#": "0"})
    vec(CT, 20, "identifiers-absent-and-null", CT, CT, '{' + REQ + ',"identifiers":null}', '{' + REQ + '}', model={"track.identifiers.#": "absent"})
    vec(CT, 21, "identifiers-not-an-array", CT, CT, '{' + REQ + ',"identifiers":{"scheme":"icao24","value":"4b1805"}}', error="malformed-wire")
    vec(CT, 22, "identifiers-item-of-the-wrong-type", CT, CT, '{' + REQ + ',"identifiers":[{"scheme":"icao24","value":4}]}', error="transform-decode")
    # the list crosses to demo-track-json, which maps the same list
    vec(CT, 23, "identifiers-to-demo-track-json", CT, DT,
        '{' + REQ + ',"identifiers":[{"scheme":"icao24","value":"4b1805","note":"dropped"},{"scheme":"callsign","value":"BTI7"}]}',
        '{"id":"t1","time":"2026-03-01T12:30:45.000Z","lat":56.25,"lon":21.5,"track":{"source_id":"s1","generation":"1","identifiers":[{"scheme":"icao24","value":"4b1805"},{"scheme":"callsign","value":"BTI7"}]}}')
    vec(DT, 19, "identifiers-to-canonical-track-v2", DT, CT,
        '{"id":"t1","time":"2026-03-01T12:30:45.000Z","lat":56.25,"lon":21.5,"track":{"source_id":"s1","generation":"1","identifiers":[{"scheme":"icao24","value":"4b1805"},{"scheme":"callsign","value":"BTI7"}]}}',
        '{' + REQ + ',"identifiers":[{"scheme":"icao24","value":"4b1805"},{"scheme":"callsign","value":"BTI7"}]}',
        model={"track.identifiers.#": "2"})

    # remote-id Message Pack: f2 = type 0xF, version 2; 0x19 = 25; then the count
    BASIC_UP = bytes.fromhex("02145553532d456e7465727072697365000000000000000000")   # vector 08
    BASIC = bytes.fromhex("02223132333435363738393031323334353637383930000000")      # vector 01
    LOC = bytes.fromhex("122624160b42bf241b6ed1b4b69808ac0870086b53150e0200")        # vector 02


    def body(msg, a):
        return str(struct.unpack("<q", msg[a:a + 8])[0])


    SRC = {"source": "constructed"}
    p1 = hx(bytes([0xF2, 25, 1]) + BASIC_UP)
    vec(RID, 13, "message-pack-one-message-roundtrip", RID, RID, p1, p1,
        model={"@kind": "message-pack", "rid.msg_type": "15", "rid.proto_version": "2", "rid.pack_msg_size": "25",
               "rid.messages.#": "1", "rid.messages[0].rid.msg_type": "0", "rid.messages[0].rid.proto_version": "2",
               "rid.messages[0].rid.body_1_8": body(BASIC_UP, 1), "rid.messages[0].rid.body_9_16": body(BASIC_UP, 9),
               "rid.messages[0].rid.body_17_24": body(BASIC_UP, 17)},
        extra=dict(SRC, reference="Message Pack header (type 0xF, version 2, message size 25, one message) followed by the Basic ID message of unit_odid_wifi_beacon.cpp"))
    p2 = hx(bytes([0xF2, 25, 2]) + BASIC + LOC)
    vec(RID, 14, "message-pack-two-messages-roundtrip", RID, RID, p2, p2,
        model={"@kind": "message-pack", "rid.messages.#": "2", "rid.messages[0].rid.msg_type": "0", "rid.messages[1].rid.msg_type": "1",
               "rid.messages[1].rid.proto_version": "2", "rid.messages[1].rid.body_1_8": body(LOC, 1)},
        extra=dict(SRC, reference="Message Pack header followed by the Basic ID message of vector 01 and the Location message of vector 02"))
    p0 = hx(bytes([0xF2, 25, 0]))
    vec(RID, 15, "message-pack-no-message-roundtrip", RID, RID, p0, p0, model={"@kind": "message-pack", "rid.messages.#": "0"},
        extra=dict(SRC, reference="Message Pack header with the count 0"))
    vec(RID, 16, "message-pack-count-beyond-input", RID, RID, hx(bytes([0xF2, 25, 2]) + BASIC), error="malformed-wire",
        extra=dict(SRC, reference="Message Pack header with the count 2 followed by one message"))
    # ==========================================================================
    # Rulings for 0.7
    # ==========================================================================
    GV = "conformance-groups-bits-var"
    # ruling 4: items of variable size. Byte 0 is the count. An item is qty, the
    # number of subs, then one byte per sub, and never shorter than `item 24`:
    #   item 0: qty 7, subs 1 2 3   -> 07 03 01 02 03   (five bytes: runs past the 24 bits)
    #   item 1: qty 9, no sub       -> 09 00 00         (three bytes: the third is padding)
    #   item 2: qty 4, sub 5        -> 04 01 05         (three bytes)
    # Item 1 starts where the subs of item 0 end, at byte 6; item 2 at byte 9.
    VAR = hx(bytes([3]) + bytes([7, 3, 1, 2, 3]) + bytes([9, 0, 0]) + bytes([4, 1, 5]))
    vm = {"probe.n": "3", "probe.items.#": "3", "probe.items[0].probe.qty": "7", "probe.items[0].probe.subs.#": "3",
          "probe.items[0].probe.subs[0].probe.val": "1", "probe.items[0].probe.subs[2].probe.val": "3",
          "probe.items[1].probe.qty": "9", "probe.items[1].probe.subs.#": "0",
          "probe.items[2].probe.qty": "4", "probe.items[2].probe.subs.#": "1", "probe.items[2].probe.subs[0].probe.val": "5"}
    vec(GV, 1, "ruling-04-items-of-different-nested-counts-roundtrip", GV, GV, VAR, VAR, model=vm)
    # from json: item 1 has no `subs` member, so its list is absent: the count byte
    # stays 0 and the item is its 24 bits
    vec(GJ, 28, "ruling-04-to-bits-items-of-different-nested-counts", GJ, GV,
        '{"items":[{"n":7,"subs":[{"v":1},{"v":2},{"v":3}]},{"n":9},{"n":4,"subs":[{"v":5}]}]}', VAR)
    vec(GV, 2, "ruling-04-to-json", GV, GJ, VAR,
        '{"title":"NONE","items":[{"n":7,"kind":"item","subs":[{"v":1},{"v":2},{"v":3}]},{"n":9,"kind":"item","subs":[]},{"n":4,"kind":"item","subs":[{"v":5}]}]}')
    # two items of two subs each: 07 02 0a 0b | 09 02 0c 0d. Read with fixed
    # 3-byte items, item 1 would start at byte 4 (0b) and its qty would be 11.
    two = hx(bytes([2]) + bytes([7, 2, 10, 11]) + bytes([9, 2, 12, 13]))
    vec(GV, 3, "ruling-04-next-item-starts-where-the-nested-group-ends", GV, GV, two, two,
        model={"probe.items.#": "2", "probe.items[1].probe.qty": "9", "probe.items[1].probe.subs[1].probe.val": "13"})
    # the third byte of an item with no sub is covered by no field: zero on output
    vec(GV, 4, "ruling-04-padding-of-a-short-item-is-zero", GV, GV, hx(bytes([1, 9, 0, 0xFF])), hx(bytes([1, 9, 0, 0])))
    # item 0 says three subs, the input holds two
    vec(GV, 5, "ruling-04-input-ends-inside-the-nested-items", GV, GV, hx(bytes([1, 7, 3, 1, 2])), error="malformed-wire")
    # count 2; item 0 is five bytes, and the second item is missing
    vec(GV, 6, "ruling-04-input-ends-before-the-second-item", GV, GV, hx(bytes([2, 7, 3, 1, 2, 3])), error="malformed-wire")
    # ruling 2: the count locator 0:0:8 has no field of its own; probe.n is mapped
    # on the same bits. The entity has probe.n 5 and one item: the count 1 is
    # written over the 5. msb input: n 5, count 1, nums 3 12, item qty 7 "ab".
    vec(GM, 8, "ruling-02-count-written-over-a-field-on-its-bits", GM, GV, hx(bytes([0x15, 0x3C, 7]) + b"ab" + b"\0"), hx(bytes([1, 7, 0, 0])),
        model={"probe.n": "5"})
    # ruling 5: probe.nums is absent and the msb pack holds it with the fixed count 2
    vec(GJ, 29, "ruling-05-absent-list-under-a-fixed-count", GJ, GM, '{"id":"u1","items":[{"name":"ab","n":7}]}', error="transform-encode")
    # ruling 6: `.` on an element that is an object, and on one that is an array
    vec(GJ, 30, "ruling-06-scalar-item-that-is-an-object", GJ, GJ, '{"id":"u","names":["a",{"t":"b"}]}', error="transform-decode")
    vec(GJ, 31, "ruling-06-scalar-item-that-is-an-array", GJ, GJ, '{"id":"u","data":{"nums":[1,[2]]}}', error="transform-decode")
    # ruling 7: geojson items. `null` is absent, as on json (item 0 has no label).
    # Value types are geojson's: the string "4" reads as the int 4, the number 7
    # as the string "7", and 2.0 as the int 2.
    vec(GG, 7, "ruling-07-items-json-null-rule-geojson-value-types", GG, GG,
        '{"type":"Feature","geometry":null,"properties":{"items":[{"name":null,"n":"4"},{"name":7,"n":2.0}]},"id":"u7"}',
        '{"type":"Feature","geometry":null,"properties":{"items":[{"n":4},{"name":"7","n":2}]},"id":"u7"}',
        model={"probe.items.#": "2", "probe.items[0].probe.qty": "4", "probe.items[1].probe.label": "7", "probe.items[1].probe.qty": "2"})
    # ruling 8: packed payloads that do not fit their values, and an item that is
    # not a submessage where the body maps fields of it
    vec(GP, 14, "ruling-08-packed-doubles-of-nine-bytes", GP, GP, hx(ld(1, "u") + ld(5, struct.pack("<d", 0.5) + b"\0")), error="malformed-wire")
    vec(GP, 15, "ruling-08-packed-singles-of-three-bytes", GP, GP, hx(ld(1, "u") + ld(7, b"\0\0\0")), error="malformed-wire")
    vec(GP, 16, "ruling-08-packed-varints-cut-short", GP, GP, hx(ld(1, "u") + ld(6, b"\x02\x80")), error="malformed-wire")
    vec(GP, 17, "ruling-08-item-that-is-not-a-submessage", GP, GP, hx(ld(1, "u") + pv(2, 5)), error="malformed-wire")

    n = 134
    G8 = 'group probe.items 0:16 item 8 count 0:8:8\n  field probe.qty 0:0:8 uint\nend\n'
    L("ruling-02-count-locator-reaching-the-group-start", BS + 'group probe.items 0:16 item 8 count 0:12:8\n  field probe.qty 0:0:8 uint\nend\n', "bad-directive")
    L("ruling-02-count-locator-on-the-bits-of-a-field-loads", BS + 'group probe.items 0:8 item 8 count 0:0:8\n  field probe.qty 0:0:8 uint\nend\n')
    L("ruling-03-second-group-beyond-a-counted-group", BS + G8 + 'group probe.subs 0:64 item 8 count 2\n  field probe.qty 0:0:8 uint\nend\n', "bad-directive")
    L("ruling-03-second-group-at-the-start-of-a-counted-group", BS + G8 + 'group probe.subs 0:16 item 8 count 2\n  field probe.qty 0:0:8 uint\nend\n', "bad-directive")
    L("ruling-03-group-before-a-counted-group-loads", BS + 'group probe.subs 0:8 item 4 count 2\n  field probe.qty 0:0:4 uint\nend\ngroup probe.items 0:24 item 8 count 0:16:8\n  field probe.qty 0:0:8 uint\nend\n')
    L("ruling-04-item-field-beyond-item-bits", BS + 'group probe.items 0:16 item 8 count 0:8:8\n  field probe.qty 0:4:8 uint\nend\n', "bad-directive")
    L("ruling-04-nested-fixed-count-group-beyond-item-bits", BS + 'group probe.items 0:16 item 16 count 0:8:8\n  field probe.qty 0:0:8 uint\n  group probe.subs 0:8 item 8 count 2\n    field probe.qty 0:0:8 uint\n  end\nend\n', "bad-directive")
    L("ruling-04-nested-fixed-count-group-within-item-bits-loads", BS + 'group probe.items 0:16 item 16 count 0:8:8\n  field probe.qty 0:0:8 uint\n  group probe.subs 0:8 item 4 count 2\n    field probe.qty 0:0:4 uint\n  end\nend\n')
    L("ruling-04-nested-locator-counted-group-may-run-past-item-bits", BS + 'group probe.items 0:16 item 16 count 0:8:8\n  group probe.subs 0:8 item 8 count 0:0:8\n    field probe.qty 0:0:8 uint\n  end\nend\n')
    L("ruling-09-map-inside-a-group", JS + 'group probe.items items\n  field probe.label name string\n  map t 1 a\nend\n', "bad-directive")
    L("ruling-09-typemap-inside-a-group", JS + 'group probe.items items\n  field probe.label name string\n  typemap F a-f-G\nend\n', "bad-directive")
    L("ruling-09-map-after-the-group-loads", JS + 'group probe.items items\n  field probe.label name string via t\nend\nmap t 1 a\n')

    return written


def main(argv=None):
    return genio.vector_main('conformance-groups-vectors.py', __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
