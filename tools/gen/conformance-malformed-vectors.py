#!/usr/bin/env python3
"""Write the vectors of the packs `conformance-malformed-*`: input that is not
a well-formed message of its wire (spec/vector-format.md, "Malformed input").

Every expected value here is worked out from the spec text: a message cut
short, tags that do not balance, a length beyond the input and nesting beyond
the depth limit are `malformed-wire`; the well-formed message each pack starts
with, and nesting exactly at the limit, convert. Nothing calls an engine.

Usage: tools/gen/conformance-malformed-vectors.py <repository root>
"""
import json
import os
import sys

ROOT = sys.argv[1]
MAX_DEPTH = 64  # spec/vector-format.md, "Malformed input"
written = {}


def vec(wire, name, inp, expect=None):
    """One vector of `conformance-malformed-<wire>`, numbered in call order.
    Without `expect` the conversion must fail with `malformed-wire`."""
    pack = "conformance-malformed-" + wire
    num = written.get(pack, 0) + 1
    d = {"name": name, "from": pack, "to": pack, "input": inp}
    if expect is None:
        d["expect_error"] = "malformed-wire"
    else:
        d["expect"] = expect
    path = os.path.join(ROOT, "packs", pack, "vectors", "%02d-%s.json" % (num, name))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.write("\n")
    written[pack] = num


# --- xml -------------------------------------------------------------------
DOC = '<event uid="u1"><contact callsign="A"/></event>'
vec("xml", "well-formed-document", DOC, DOC)
vec("xml", "empty-input", "")
vec("xml", "cut-after-the-opening-angle", "<")
vec("xml", "cut-inside-the-tag-name", "<eve")
vec("xml", "cut-after-the-tag-name", "<event")
vec("xml", "cut-after-an-attribute-name", "<event uid")
vec("xml", "cut-after-the-equals-sign", "<event uid=")
vec("xml", "cut-inside-a-quoted-value", '<event uid="u1')
vec("xml", "cut-after-a-quoted-value", '<event uid="u1"')
vec("xml", "cut-inside-a-child-tag", '<event uid="u1"><contact callsign=')
vec("xml", "missing-closing-tag", '<event uid="u1"><contact callsign="A"/>')
vec("xml", "cut-after-the-angle-of-the-closing-tag", '<event uid="u1"><contact callsign="A"/><')
vec("xml", "cut-inside-the-closing-tag", '<event uid="u1"><contact callsign="A"/></event')
vec("xml", "closing-tag-of-another-name", '<event uid="u1"><contact callsign="A"/></evnt>')
vec("xml", "child-closed-by-its-parent-tag", '<event uid="u1"><contact callsign="A"></event>')
vec("xml", "crossed-tags", '<event uid="u1"><a><b></a></b></event>')
vec("xml", "closing-tag-with-no-opening-tag", "</event>")
vec("xml", "second-root-element", '<event uid="u1"/><event uid="u2"/>')
vec("xml", "text-after-the-root-element", '<event uid="u1"/>x')
vec("xml", "cut-inside-the-xml-declaration", '<?xml version="1.0"')
vec("xml", "attribute-value-with-no-quotes", "<event uid=u1/>")


def xml_nested(levels):
    """A document of `levels` nested elements, the root included."""
    inner = levels - 1
    return '<event uid="u1">' + "<a>" * inner + "</a>" * inner + "</event>"


# unmapped child elements are dropped on decode (ruling 6 of 0.1.1)
vec("xml", "nesting-at-the-depth-limit", xml_nested(MAX_DEPTH), '<event uid="u1"/>')
vec("xml", "nesting-beyond-the-depth-limit", xml_nested(MAX_DEPTH + 1))

# ruling 40: a document type declaration anywhere is refused
vec("xml", "doctype-before-the-root", '<!DOCTYPE event><event uid="u1"/>')
vec("xml", "doctype-after-the-root", '<event uid="u1"/><!DOCTYPE event>')
vec("xml", "doctype-inside-the-root", '<event uid="u1"><!DOCTYPE event></event>')
vec("xml", "doctype-that-declares-an-entity", '<!DOCTYPE event [<!ENTITY a "b">]><event uid="&a;"/>')
# ruling 40: a numeric character reference is digits only and names an allowed character
vec("xml", "character-reference-with-a-sign", '<event uid="&#+65;"/>')
vec("xml", "character-reference-beyond-the-last-character", '<event uid="&#x110000;"/>')
vec("xml", "character-reference-to-nul", '<event uid="&#0;"/>')
vec("xml", "decimal-character-reference", '<event uid="&#65;"/>', '<event uid="A"/>')
vec("xml", "hexadecimal-character-reference", '<event uid="&#x41;"/>', '<event uid="A"/>')

# --- json ------------------------------------------------------------------
DOC = '{"id":"u1","pos":{"lat":1.5},"label":"A"}'
vec("json", "well-formed-message", DOC, DOC)
vec("json", "empty-input", "")
vec("json", "cut-after-the-opening-brace", "{")
vec("json", "cut-inside-a-member-name", '{"i')
vec("json", "cut-after-a-member-name", '{"id"')
vec("json", "cut-after-a-colon", '{"id":')
vec("json", "cut-inside-a-string", '{"id":"u')
vec("json", "cut-inside-an-escape", '{"id":"u1\\')
vec("json", "cut-inside-a-unicode-escape", '{"id":"u1\\u00')
vec("json", "unclosed-object", '{"id":"u1"')
vec("json", "cut-after-a-comma", '{"id":"u1",')
vec("json", "unclosed-nested-object", '{"id":"u1","pos":{"lat":1.5}')
vec("json", "unclosed-array", '{"id":"u1","list":[1,2')
vec("json", "cut-inside-a-literal", '{"id":"u1","flag":tru')
vec("json", "cut-inside-a-number", '{"id":"u1","pos":{"lat":1.')
vec("json", "object-closed-by-a-bracket", '{"id":"u1"]')
vec("json", "second-value-after-the-object", '{"id":"u1"}{"id":"u2"}')


def json_nested(levels):
    """A message of `levels` nested objects, the message object included."""
    inner = levels - 1
    return '{"id":"u1","a":' + '{"a":' * (inner - 1) + '{"a":1}' + "}" * (inner - 1) + "}"


# the innermost member is a scalar no line maps: residue, written back
vec("json", "nesting-at-the-depth-limit", json_nested(MAX_DEPTH), json_nested(MAX_DEPTH))
vec("json", "nesting-beyond-the-depth-limit", json_nested(MAX_DEPTH + 1))

# ruling 40: half of a surrogate pair without its other half
vec("json", "lone-high-surrogate-escape", '{"id":"\\ud83d"}')
vec("json", "lone-low-surrogate-escape", '{"id":"\\ude00"}')
vec("json", "high-surrogate-escape-followed-by-another-escape", '{"id":"\\ud83d\\u0041"}')
vec("json", "surrogate-pair-escape", '{"id":"\\ud83d\\ude00"}', '{"id":"\U0001F600"}')

# --- geojson ---------------------------------------------------------------
DOC = '{"type":"Feature","geometry":{"type":"Point","coordinates":[2.5,1.5]},"properties":{"name":"A"},"id":"u1"}'
vec("geojson", "well-formed-feature", DOC, DOC)
vec("geojson", "empty-input", "")
vec("geojson", "cut-inside-a-string", '{"type":"Feature","geometry":null,"properties":{"name":"A')
vec("geojson", "cut-after-a-colon", '{"type":"Feature","geometry":')
vec("geojson", "cut-inside-the-coordinates", '{"type":"Feature","geometry":{"type":"Point","coordinates":[2.5,')
vec("geojson", "unclosed-feature", '{"type":"Feature","geometry":null,"properties":{"name":"A"},"id":"u1"')
# the Feature and `properties` are two levels; the arrays take it one beyond the limit
arrays = MAX_DEPTH + 1 - 2
vec(
    "geojson",
    "nesting-beyond-the-depth-limit",
    '{"type":"Feature","geometry":null,"properties":{"x":' + "[" * arrays + "]" * arrays + '},"id":"u1"}',
)

GEO = '{"type":"Feature","geometry":null,"properties":{},"id":"%s"}'
vec("geojson", "lone-high-surrogate-escape", GEO % "\\ud83d")
vec("geojson", "lone-low-surrogate-escape", GEO % "\\ude00")
vec("geojson", "surrogate-pair-escape", GEO % "\\ud83d\\ude00", GEO % "\U0001F600")

# --- protobuf --------------------------------------------------------------
# field 1 "u1" (0a 02 75 31), field 2 varint 5 (10 05)
DOC = "0a0275311005"
vec("protobuf", "well-formed-message", DOC, DOC)
vec("protobuf", "varint-value-cut-after-a-continuation-byte", "0a0275311080")
vec("protobuf", "varint-value-missing", "0a02753110")
vec("protobuf", "tag-cut-after-a-continuation-byte", "0a02753180")
vec("protobuf", "length-beyond-the-input", "0a057531")
vec("protobuf", "length-missing", "0a")
vec("protobuf", "length-of-two-to-the-64-minus-1", "0affffffffffffffffff017531")
vec("protobuf", "length-beyond-the-input-in-a-field-no-line-maps", "0a0275314a0561")
vec("protobuf", "fixed64-cut-short", "0a02753119000000000000f0")
vec("protobuf", "fixed32-cut-short", "0a0275312d0000")
# field 4 is three bytes; inside it field 1 states five bytes and has one
vec("protobuf", "length-beyond-the-submessage", "0a02753122030a0541")
vec("protobuf", "varint-of-eleven-bytes", "0a02753110ffffffffffffffffffff01")
vec("protobuf", "hex-of-odd-length", "0a027531100")
vec("protobuf", "hex-with-a-character-that-is-not-a-hex-digit", "0a0275311g05")

# ruling 40. Field number 0: tag 00, varint 5
vec("protobuf", "field-number-0", "0a0275310005")
# field 7 with each wire type the wire does not have: tags 3b, 3c, 3e, 3f
vec("protobuf", "wire-type-3", "0a0275313b")
vec("protobuf", "wire-type-4", "0a0275313c")
vec("protobuf", "wire-type-3-then-4", "0a0275313b3c")
vec("protobuf", "wire-type-6", "0a0275313e00")
vec("protobuf", "wire-type-7", "0a0275313f00")
# field 2: nine continuation bytes, then a last byte that holds bits above bit 63
vec("protobuf", "ten-byte-varint-with-last-byte-2", "0a02753110ffffffffffffffffff02")
# the same with last byte 1 is the 64-bit value of all ones: time_ms -1 (ruling 15 of 0.5)
vec("protobuf", "ten-byte-varint-with-last-byte-1", "0a02753110ffffffffffffffffff01", "0a02753110ffffffffffffffffff01")
# field 6, the packed list: two bytes, 01 then a varint cut after a continuation byte
vec("protobuf", "truncated-varint-in-a-packed-field", "0a02753132020180")
# the packed list well-formed: 1 and 2
vec("protobuf", "packed-field", "0a02753132020102", "0a02753132020102")
vec("protobuf", "hex-with-a-form-feed", "0a027531\f1005")
vec("protobuf", "hex-with-space-tab-line-feed-carriage-return", "0a 02\t75\n31\r\n1005", DOC)

# --- bits ------------------------------------------------------------------
# two words of four bytes, least significant byte first: 1 and 2
DOC = "0100000002000000"
vec("bits", "well-formed-message", DOC, DOC)
vec("bits", "whitespace-in-the-hex-text-is-ignored", "01000000 02000000\n", DOC)
vec("bits", "input-one-byte-short", "01000000020000")
vec("bits", "input-one-word-short", "01000000")
vec("bits", "empty-input", "")
vec("bits", "hex-of-odd-length", "010000000200000")
vec("bits", "hex-of-odd-length-longer-than-the-message", "01000000020000000")
vec("bits", "hex-with-a-character-that-is-not-a-hex-digit", "01000000020000zz")
vec("bits", "hex-with-a-sign", "010000000200+100")
# ruling 40: whitespace in hex text is space, tab, line feed and carriage return only
vec("bits", "hex-with-space-tab-line-feed-carriage-return", "01 00\t00\n00\r\n02000000", DOC)
vec("bits", "hex-with-a-form-feed", "01000000\f02000000")
vec("bits", "hex-with-a-vertical-tab", "01000000\v02000000")
vec("bits", "hex-with-a-no-break-space", "01000000\u00a002000000")

for pack in sorted(written):
    print("%s: %d vectors" % (pack, written[pack]))
