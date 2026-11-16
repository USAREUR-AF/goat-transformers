#!/usr/bin/env python3
"""Write the vectors that pin rulings 11 to 21 of spec 0.7 ("Stated, not yet
pinned by a vector").

Every expected value here is worked out from the spec text and the pack
layouts, with byte builders written for these packs alone. Nothing calls an
engine.

Usage: tools/gen/conformance-rulings07-vectors.py <repository root>
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


n = 146


def L(name, pack, error=None, models=None):
    global n
    full = "%d-%s" % (n, name)
    d = {"name": full, "models": models if models is not None else [CORE, PM], "pack": pack}
    if error:
        d["expect_error"] = error
    with open(os.path.join(ROOT, "packs", "conformance", "load-vectors", full + ".json"), "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.write("\n")
    written["load"] = written.get("load", 0) + 1
    n += 1


# protobuf byte builders
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


def pv(field, v):
    return varint(field << 3) + varint(v)


def ld(field, b):
    if isinstance(b, str):
        b = b.encode()
    return varint(field << 3 | 2) + varint(len(b)) + b


def hx(b):
    return bytes(b).hex()


GJ, GX, GP, GG, GM, GV, RB = (
    "conformance-groups-json",
    "conformance-groups-xml",
    "conformance-groups-protobuf",
    "conformance-groups-geojson",
    "conformance-groups-bits-msb",
    "conformance-groups-bits-var",
    "conformance-rulings-bits",
)
RP, RJ, RBITS = "conformance-groups-rulings-protobuf", "conformance-groups-rulings-json", "conformance-groups-rulings-bits"

# ==========================================================================
# Ruling 11: a scalar (`.`) item with no value
# ==========================================================================
# json: `null` decodes to an item with no keys and is written `null` again.
# Output order is line order: id, title (the common default), data.nums, names.
vec(GJ, 32, "ruling-11-scalar-item-null-roundtrip", GJ, GJ,
    '{"id":"u","names":["a",null,"b"],"data":{"nums":[1,null]}}',
    '{"id":"u","title":"NONE","data":{"nums":[1,null]},"names":["a",null,"b"]}',
    model={"probe.names.#": "3", "probe.names[0].probe.tag": "a", "probe.names[2].probe.tag": "b",
           "probe.nums.#": "2", "probe.nums[0].probe.val": "1"})
# xml: the item with no value is an empty element
vec(GJ, 33, "ruling-11-to-xml-empty-element", GJ, GX, '{"id":"u","names":["a",null]}', '<msg id="u"><name>a</name><name/></msg>')
# protobuf: a `pstring` item is an empty occurrence; in the packed field 3.1
# the item is left out (3 and 5 remain)
vec(GJ, 34, "ruling-11-to-protobuf-empty-occurrence-and-packed-item-left-out", GJ, GP,
    '{"id":"u","data":{"nums":[3,null,5]},"names":["a",null]}',
    hx(ld(1, "u") + ld(3, ld(1, varint(3) + varint(5))) + ld(4, "a") + ld(4, "")))
# a packed list whose items all lack the value writes nothing: neither field
# 3 (the container of nums) nor field 5 (ratios)
vec(GJ, 35, "ruling-11-to-protobuf-packed-list-of-no-values-writes-nothing", GJ, GP,
    '{"id":"u","data":{"nums":[null,null]},"ratios":[null]}', hx(ld(1, "u")))
x = '<msg id="u"><name>a</name><name/></msg>'
vec(GX, 13, "ruling-11-empty-element-is-an-item-with-no-keys", GX, GX, x, x,
    model={"probe.names.#": "2", "probe.names[0].probe.tag": "a"})
g = '{"type":"Feature","geometry":null,"properties":{},"id":"u","names":["p",null]}'
vec(GG, 8, "ruling-11-scalar-item-null-roundtrip", GG, GG, g, g, model={"probe.names.#": "2", "probe.names[0].probe.tag": "p"})

# ==========================================================================
# Ruling 12: an array element that is not an object, where the body addresses
# members, is an item with no keys. The item default (n 1) and the item const
# (kind) of the json pack are written in each.
# ==========================================================================
vec(GJ, 36, "ruling-12-element-that-is-not-an-object", GJ, GJ,
    '{"id":"u","items":[5,"x",[1],{"name":"a"}]}',
    '{"id":"u","title":"NONE","items":[{"n":1,"kind":"item"},{"n":1,"kind":"item"},{"n":1,"kind":"item"},{"name":"a","n":1,"kind":"item"}]}',
    model={"probe.items.#": "4", "probe.items[3].probe.label": "a", "probe.items[0].probe.subs.#": "absent"})
vec(GG, 9, "ruling-12-element-that-is-not-an-object", GG, GG,
    '{"type":"Feature","geometry":null,"properties":{"items":[7,{"name":"a"}]},"id":"u"}',
    '{"type":"Feature","geometry":null,"properties":{"items":[{},{"name":"a"}]},"id":"u"}',
    model={"probe.items.#": "2", "probe.items[1].probe.label": "a"})

# ==========================================================================
# Ruling 13: protobuf group paths
# ==========================================================================
# nums is the group at 3.1; here field 3 is a varint, not a submessage
vec(GP, 18, "ruling-13-group-path-prefix-is-not-a-submessage", GP, GP, hx(ld(1, "u") + pv(3, 5)), error="malformed-wire")
# field 3 occurs twice: the last occurrence is the container
vec(GP, 19, "ruling-13-last-occurrence-is-the-container", GP, GP,
    hx(ld(1, "u") + ld(3, ld(1, varint(1) + varint(2))) + ld(3, ld(1, varint(7)))), hx(ld(1, "u") + ld(3, ld(1, varint(7)))),
    model={"probe.nums.#": "1", "probe.nums[0].probe.val": "7"})
# inside an item: tag is at 3.1 of the item, and field 3 of the item is a varint
vec(RP, 1, "ruling-13-path-prefix-inside-an-item-is-not-a-submessage", RP, RP,
    hx(ld(1, "u") + ld(2, ld(1, "aa") + pv(3, 5))), error="malformed-wire")

# ==========================================================================
# Ruling 14: an absent list under a count locator writes a count of 0.
# The source maps probe.n and no list: n 5 in byte 0 (two-byte words, four
# bytes needed). The target maps probe.n on 0:0:8 and counts probe.items on
# the same bits: the count 0 is written over the 5.
# ==========================================================================
vec(RB, 5, "groups-ruling-14-absent-list-under-a-count-locator-writes-0", RB, GV, "05000000", "00", model={"probe.n": "5"})

# ==========================================================================
# Rulings 15 and 17: the pack conformance-groups-rulings-bits
# ==========================================================================
# msb source: byte 0 = n 5 << 2 | count 2; byte 1 = nums 3 and 12; two items
# (qty 7 "ab", qty 9 "cd"). Target byte 0: field n = 0x05, then const 0xAA,
# then `when` puts 5 in the low nibble (0xA5), then the count 2 in bits 0-1
# (0xA6). Items: qty, and val absent = 0.
vec(GM, 9, "ruling-15-order-of-writes-fields-const-when-counts", GM, RBITS,
    hx(bytes([0x16, 0x3C, 7]) + b"ab" + bytes([9]) + b"cd"), hx(bytes([0xA6, 7, 0, 9, 0])), model={"probe.n": "5", "probe.items.#": "2"})
r = hx(bytes([0xA5, 7, 9]))
vec(RBITS, 1, "one-item-roundtrip", RBITS, RBITS, r, r,
    model={"@kind": "k", "probe.n": "165", "probe.items.#": "1", "probe.items[0].probe.qty": "7", "probe.items[0].probe.val": "9"})
# the count is 1 and the input ends after the first byte of the item: the
# `optional` field does not make the item shorter
vec(RBITS, 2, "ruling-17-optional-inside-an-item-has-no-effect", RBITS, RBITS, hx(bytes([0xA5, 7])), error="malformed-wire")

# ==========================================================================
# Ruling 18: a list where a scalar key is expected
# ==========================================================================
vec(GJ, 37, "ruling-18-context-key-that-is-a-list", GJ, GJ, '{"id":"u"}', error="key-type-mismatch", context={"probe.items": "x"})

# ==========================================================================
# Ruling 19: typemap applies to the key `type` inside items
# ==========================================================================
p = hx(ld(1, "u") + ld(2, ld(1, "aa") + ld(3, ld(1, "x")) + ld(4, "T")) + ld(2, ld(4, "Z")))
vec(RP, 2, "ruling-19-typemap-inside-items-roundtrip", RP, RP, p, p,
    model={"probe.items.#": "2", "probe.items[0].type": "a-f-G", "probe.items[0].probe.tag": "x", "probe.items[1].type": "Z"})
# the code of each pack: T on protobuf, J on json; Z has no entry and passes through
vec(RP, 3, "ruling-19-to-json-code-of-each-pack", RP, RJ, p, '{"id":"u","items":[{"t":"J","name":"aa"},{"t":"Z"}]}')
j = '{"id":"u","items":[{"t":"J","name":"aa"},{"t":"K"}]}'
vec(RJ, 1, "ruling-19-typemap-inside-items-roundtrip", RJ, RJ, j, j,
    model={"probe.items[0].type": "a-f-G", "probe.items[1].type": "K"})
vec(RJ, 2, "ruling-19-to-protobuf-code-of-each-pack", RJ, RP, j, hx(ld(1, "u") + ld(2, ld(1, "aa") + ld(4, "T")) + ld(2, ld(4, "K"))))

# ==========================================================================
# Ruling 20: an absent list on xml creates no container element (the empty
# list is vector 17 of conformance-groups-json)
# ==========================================================================
vec(GJ, 38, "ruling-20-absent-lists-to-xml-create-no-container", GJ, GX, '{"id":"u1","cs":"C"}', '<msg id="u1"><head cs="C"/></msg>')

# ==========================================================================
# Load vectors
# ==========================================================================
CORE = 'module core\nversion 0.1.0\ndistribution public\nsource "probe"\nkey uid string -\nkey type string -\nkey lat float deg\nkey lon float deg\nkey callsign string -\nkey time_ms int ms\n'
PM = 'module probe\nversion 0.1.0\ndistribution public\nsource "probe"\nkey label string -\nkey qty int -\nkey tag string -\nlist items "a list"\nlist subs "a nested list"\n'
HEAD = 'format probe\nversion 0.7.0\ndistribution public\nsource "probe"\nuses probe\n'
JS = HEAD + 'wire json\nfield uid id string\n'
XS = HEAD + 'wire xml\nroot msg\nfield uid @id string\n'
PS = HEAD + 'wire protobuf\nfield uid 1 pstring\n'
BS = HEAD + 'wire bits\nword_bytes 1\nfield probe.qty 0:0:8 uint\n'
JG = 'group probe.items items\n  field probe.label name string\nend\n'

# ruling 13
L("ruling-13-protobuf-body-mixing-scalar-and-path", PS + 'group probe.items 2\n  field probe.label . pstring\n  field probe.tag 1 pstring\nend\n', "bad-directive")
L("ruling-13-protobuf-scalar-body-with-a-nested-group", PS + 'group probe.items 2\n  field probe.label . pstring\n  group probe.subs 3\n    field probe.tag 1 pstring\n  end\nend\n', "bad-directive")
L("ruling-13-protobuf-scalar-body-with-a-default-loads", PS + 'group probe.items 2\n  field probe.label . pstring\n  default probe.label x\nend\n')
# ruling 15: inside an item of 8 bits
L("ruling-15-item-const-beyond-item-bits", BS + 'group probe.items 0:16 item 8 count 0:8:8\n  field probe.qty 0:0:8 uint\n  const 0:4:8 1\nend\n', "bad-directive")
L("ruling-15-nested-count-locator-beyond-item-bits", BS + 'group probe.items 0:16 item 8 count 0:8:8\n  group probe.subs 0:16 item 8 count 0:4:8\n    field probe.qty 0:0:8 uint\n  end\nend\n', "bad-directive")
L("ruling-15-nested-count-locator-within-item-bits-loads", BS + 'group probe.items 0:16 item 8 count 0:8:8\n  group probe.subs 0:8 item 8 count 0:0:8\n    field probe.qty 0:0:8 uint\n  end\nend\n')
# ruling 16: subs is two 8-bit items from bit 8 (to bit 24); items starts at bit 16
L("ruling-16-fixed-count-group-reaching-a-counted-group", BS + 'group probe.subs 0:8 item 8 count 2\n  field probe.qty 0:0:8 uint\nend\ngroup probe.items 0:16 item 8 count 0:0:8\n  field probe.qty 0:0:8 uint\nend\n', "bad-directive")
L("ruling-16-fixed-count-group-ending-at-a-counted-group-loads", BS + 'group probe.subs 0:8 item 4 count 2\n  field probe.qty 0:0:4 uint\nend\ngroup probe.items 0:16 item 8 count 0:0:8\n  field probe.qty 0:0:8 uint\nend\n')
# ruling 18
L("ruling-18-default-names-a-list", JS + JG + 'default probe.items x\n', "key-type-mismatch")
L("ruling-18-default-inside-a-group-names-a-list", JS + 'group probe.items items\n  field probe.label name string\n  default probe.subs x\nend\n', "key-type-mismatch")
L("ruling-18-derive-argument-is-a-list", JS, "bad-directive", [CORE, PM + 'derive probe.tag copy probe.items\n'])
L("ruling-18-derive-target-is-a-list", JS, "bad-directive", [CORE, PM + 'derive probe.items copy probe.tag\n'])
L("ruling-18-const-on-the-item-itself-json", JS + 'group probe.items items\n  field probe.label . string\n  const . x\nend\n', "bad-directive")
L("ruling-18-const-on-the-item-itself-protobuf", PS + 'group probe.items 2\n  field probe.label . pstring\n  const . 1\nend\n', "bad-directive")
L("ruling-18-item-on-json", JS + 'group probe.items items item 8\n  field probe.label name string\nend\n', "bad-directive")
L("ruling-18-item-on-xml", XS + 'group probe.items body/item item 8\n  field probe.label @name string\nend\n', "bad-directive")
L("ruling-18-uses-inside-a-group", JS + 'group probe.items items\n  field probe.label name string\n  uses probe\nend\n', "bad-directive")
L("ruling-18-source-inside-a-group", JS + 'group probe.items items\n  field probe.label name string\n  source "probe"\nend\n', "bad-directive")
L("ruling-18-bit-order-inside-a-group", BS + 'group probe.items 0:16 item 8 count 0:8:8\n  field probe.qty 0:0:8 uint\n  bit_order msb\nend\n', "bad-directive")
# ruling 21
L("ruling-21-json-field-through-a-group-path", JS + JG + 'field probe.tag items.first string\n', "bad-directive")
L("ruling-21-json-field-through-a-nested-group-path", JS + 'group probe.items data.items\n  field probe.label name string\nend\nfield probe.tag data.items.x.y string\n', "bad-directive")
L("ruling-21-json-field-beside-a-group-path-loads", JS + 'group probe.items data.items\n  field probe.label name string\nend\nfield probe.tag data.count string\n')
L("ruling-21-xml-field-through-a-group-path", XS + 'group probe.items body/item\n  field probe.label @name string\nend\nfield probe.tag body/item/@first string\n', "bad-directive")
L("ruling-21-xml-field-below-a-group-path", XS + 'group probe.items body/item\n  field probe.label @name string\nend\nfield probe.tag body/item/note/#text string\n', "bad-directive")
L("ruling-21-xml-field-on-the-container-loads", XS + 'group probe.items body/item\n  field probe.label @name string\nend\nfield probe.tag body/@n string\n')
L("ruling-21-protobuf-field-through-a-group-path", PS + 'group probe.items 2\n  field probe.label 1 pstring\nend\nfield probe.tag 2.3 pstring\n', "bad-directive")
L("ruling-21-kind-field-through-a-common-group-path", JS + JG + 'kind a\nwhen k 1\nfield probe.tag items.first string\n', "bad-directive")
L("ruling-21-field-inside-an-item-through-a-nested-group-path", JS + 'group probe.items items\n  group probe.subs subs\n    field probe.tag t string\n  end\n  field probe.label subs.name string\nend\n', "bad-directive")

for k_, v_ in sorted(written.items()):
    print(k_, v_)
