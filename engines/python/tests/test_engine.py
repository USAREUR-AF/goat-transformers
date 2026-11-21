"""Unit tests beyond the shared vectors: grammar, transforms, wires, residue."""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
sys.path.insert(0, SRC)
PACKS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "packs"))

from goat_transformers import (  # noqa: E402
    BadDirective, KeyTypeMismatch, DistributionRefused, DuplicateKey, InvalidModel, MissingDistribution, MissingSource,
    Engine, InvalidPack, MalformedWire, MissingRoot, TransformDecodeFailure,
    UnknownDirective, UnknownFormat, UnknownTransform, parse_model_text, parse_pack_text,
)
from goat_transformers.transforms import TRANSFORMS, format_float  # noqa: E402

# The test formats' keys, declared as a `core` module so the packs load.
CORE = """
module core
version 0.1.0
distribution public
source "unit tests"
key uid      string -
key type     string -
key lat      float  deg
key lon      float  deg
key n        int    -
key note     string -
key when     int    ms
key "my key" string -
"""

XML_PACK = """
format t-xml   # trailing comment
version 0.1.0
distribution public
source "unit tests"
wire xml
root ev
field uid   @uid          string
field n     a/b/@n        int
field note  a/c/#text     string
field when  @t            iso8601_ms
field type  @k            string
typemap X1 a-f-G
"""

GEO_PACK = """
format t-geo
version 0.1.0
distribution public
source "unit tests"
wire geojson
field uid  id               string
field lat  geometry.lat     float
field lon  geometry.lon     float
field n    properties.n     int
field "my key" "properties.has space" string
"""


class TestGrammar(unittest.TestCase):
    def test_parses(self):
        p = parse_pack_text(XML_PACK)
        self.assertEqual((p.name, p.wire, p.root), ("t-xml", "xml", "ev"))
        self.assertEqual([f.locator for f in p.fields], ["@uid", "a/b/@n", "a/c/#text", "@t", "@k"])
        self.assertEqual(p.native_to_cot, {"X1": "a-f-G"})

    def test_quoted_tokens(self):
        p = parse_pack_text(GEO_PACK)
        self.assertEqual(p.fields[-1].key, "my key")
        self.assertEqual(p.fields[-1].locator, "properties.has space")

    def test_unknown_directive(self):
        with self.assertRaises(UnknownDirective) as cm:
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire xml\nroot r\nbogus 1\n")
        self.assertEqual(cm.exception.format, "x")

    def test_unknown_transform(self):
        with self.assertRaises(UnknownTransform) as cm:
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire xml\nroot r\nfield a @a hexbin\n")
        self.assertEqual(cm.exception.locator, "@a")

    def test_missing_root(self):
        with self.assertRaises(MissingRoot):
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire xml\n")

    def test_bad_wire_and_locator(self):
        with self.assertRaises(InvalidPack):
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire protobuf\nfield a bad pstring\n")
        with self.assertRaises(InvalidPack):
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire xml\nroot r\nfield a point string\n")
        with self.assertRaises(InvalidPack):
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire geojson\nfield a geometry.z float\n")
        with self.assertRaises(InvalidPack):
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire xml\nroot r\nfield a @a\n")


class TestTransforms(unittest.TestCase):
    def test_float_format(self):
        self.assertEqual(format_float(30.0), "30")
        self.assertEqual(format_float(-42.6), "-42.6")
        self.assertEqual(format_float(0.1), "0.1")
        self.assertEqual(format_float(-0.0), "0")
        self.assertEqual(format_float(1e300), "1" + "0" * 300)
        self.assertEqual(TRANSFORMS["float"].decode("30.0090027"), 30.0090027)
        with self.assertRaises(ValueError):
            TRANSFORMS["float"].decode("nan")

    def test_iso(self):
        t = TRANSFORMS["iso8601_ms"]
        self.assertEqual(t.decode("2021-02-27T20:00:00.000Z"), 1614456000000)
        self.assertEqual(t.decode("2021-02-27T20:00:00Z"), 1614456000000)
        self.assertEqual(t.decode("2021-02-27T20:00:00.5Z"), 1614456000500)
        self.assertEqual(t.decode("2021-02-27T20:00:00.123987Z"), 1614456000123)
        self.assertEqual(t.encode(1614456000000), "2021-02-27T20:00:00.000Z")
        self.assertEqual(t.encode(-1), "1969-12-31T23:59:59.999Z")
        self.assertEqual(t.decode(t.encode(-1)), -1)
        # 0.6: the designator may be Z, z or an offset +hh:mm / -hh:mm, and the T
        # may be lowercase; the instant is converted to UTC. Encode still writes Z.
        self.assertEqual(t.decode("2021-02-27T21:00:00+01:00"), 1614456000000)
        self.assertEqual(t.decode("2021-02-27T20:00:00+00:00"), 1614456000000)
        self.assertEqual(t.decode("2021-02-27T03:00:00.250-17:00"), 1614456000250)
        self.assertEqual(t.decode("2021-02-27t20:00:00z"), 1614456000000)
        for bad in ("2021-02-30T00:00:00Z", "2021-02-27 20:00:00Z", "2021-02-27T20:00:00", "2021-02-27T20:00:00+0100",
                    "2021-02-27T20:00:00+01", "2021-02-27T20:00:00+24:00", "2021-02-27T20:00:00Z+01:00"):
            with self.assertRaises(ValueError, msg=bad):
                t.decode(bad)


class TestIso8601S(unittest.TestCase):
    """Version 0.26: `iso8601_s`."""

    def test_decode_and_encode(self):
        t = TRANSFORMS["iso8601_s"]
        self.assertEqual(t.decode("2024-02-29T12:34:56.789Z"), 1709210096789)  # ruling 2: the fraction is read
        self.assertEqual(t.decode("2021-02-27T21:00:00+01:00"), 1614456000000)
        self.assertEqual(t.encode(1709210096789), "2024-02-29T12:34:56Z")  # ruling 4
        self.assertEqual(t.encode(999), "1970-01-01T00:00:00Z")  # ruling 3: dropped, never rounded
        self.assertEqual(t.encode(-1), "1969-12-31T23:59:59Z")
        self.assertEqual(t.encode(-62135596800000), "0001-01-01T00:00:00Z")
        self.assertEqual(t.encode(253402300799999), "9999-12-31T23:59:59Z")
        for bad in (-62135596800001, 253402300800000, "1", 1.5, True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                t.encode(bad)
        for bad in ("2021-02-30T00:00:00Z", "2021-02-27T20:00:00", " 2021-02-27T20:00:00Z"):
            with self.assertRaises(ValueError, msg=bad):
                t.decode(bad)

    def _pack(self, wire, line, root=""):
        return ('format t-s\nversion 0.1.0\ndistribution public\nsource "unit tests"\nwire %s\n%s%s\n'
                % (wire, root, line))

    def _load(self, text):
        return Engine([parse_pack_text(text)], models=[parse_model_text(CORE)])

    def test_line_checks(self):
        # ruling 1: valid on xml, geojson, json and text
        self._load(self._pack("xml", "field when @t iso8601_s", "root ev\n"))
        self._load(self._pack("geojson", "field when properties.t iso8601_s"))
        self._load(self._pack("json", "field when t iso8601_s"))
        # another wire, a parameter, a key of another type
        with self.assertRaises(BadDirective):
            self._load(self._pack("protobuf", "field when 1 iso8601_s"))
        with self.assertRaises(BadDirective):
            self._load(self._pack("json", "field when t iso8601_s:3"))
        with self.assertRaises(KeyTypeMismatch):
            self._load(self._pack("json", "field note t iso8601_s"))


class TestWires(unittest.TestCase):
    def setUp(self):
        self.e = Engine([parse_pack_text(XML_PACK), parse_pack_text(GEO_PACK)], models=[parse_model_text(CORE)])

    def test_xml_tolerance_and_canonical(self):
        src = (
            '﻿<?xml version="1.0" encoding="UTF-8"?>\n<!-- c -->\n'
            "<ev  k='X1' uid=\"u&amp;1\" t=\"2021-02-27T20:00:00Z\">\n  <a><c>hi &lt;there&gt;</c>"
            '<b n="7"></b></a>\n</ev>\n'
        )
        ent = self.e.decode("t-xml", src)
        self.assertEqual(ent["type"], "a-f-G")  # typemap
        self.assertEqual(ent["n"], 7)
        self.assertEqual(ent["note"], "hi <there>")
        out = self.e.encode("t-xml", ent).decode()
        self.assertEqual(
            out,
            '<ev uid="u&amp;1" t="2021-02-27T20:00:00.000Z" k="X1"><a><b n="7"/><c>hi &lt;there&gt;</c></a></ev>',
        )

    def test_xml_residue_roundtrip(self):
        src = (
            '<ev uid="u" extra="e&quot;x"><a><b n="1" z="9"/></a><detail><link uid="L1"/>'
            '<link uid="L2"/><flag/><remark>r1</remark></detail></ev>'
        )
        ent = self.e.decode("t-xml", src)
        # 0.1.1 ruling 6: unmapped attributes of the root element are residue;
        # unmapped child elements, and unmapped attributes on them, are dropped.
        self.assertEqual(ent.residue["t-xml"], {"@extra": 'e"x'})
        self.assertEqual(
            self.e.convert("t-xml", "t-xml", src).decode(), '<ev uid="u" extra="e&quot;x"><a><b n="1"/></a></ev>'
        )

    def test_xml_unmapped_type_kept(self):
        ent = self.e.decode("t-xml", '<ev k="ZZ"/>')
        self.assertEqual(ent["type"], "ZZ")
        self.assertEqual(ent.residue["t-xml"]["@k"], "ZZ")
        self.assertEqual(self.e.convert("t-xml", "t-xml", '<ev k="ZZ"/>').decode(), '<ev k="ZZ"/>')

    def test_xml_errors(self):
        with self.assertRaises(MissingRoot):
            self.e.decode("t-xml", "<other/>")
        for bad in ("<ev>", "<ev a='1' a='2'/>", "<ev></ew>", "<ev/>trailing", "<ev>&bogus;</ev>", ""):
            with self.assertRaises(MalformedWire, msg=bad):
                self.e.decode("t-xml", bad)
        with self.assertRaises(TransformDecodeFailure) as cm:
            self.e.decode("t-xml", '<ev uid="u"><a><b n="x"/></a></ev>')
        self.assertEqual(cm.exception.absent[0][0], "n")
        self.assertEqual(cm.exception.entity["uid"], "u")
        with self.assertRaises(UnknownFormat):
            self.e.decode("nope", "<ev/>")

    def test_geojson_residue_roundtrip(self):
        src = (
            '{"type":"Feature","geometry":{"type":"Point","coordinates":[1.5,2]},'
            '"properties":{"n":3,"has space":"s","q":[1,true,null,{"k":"v\\n"}],"r":1.0},"id":"g1","bbox":[0,0]}'
        )
        ent = self.e.decode("t-geo", src)
        self.assertEqual(ent["lat"], 2.0)
        self.assertEqual(ent["my key"], "s")
        self.assertEqual(
            self.e.convert("t-geo", "t-geo", src).decode(),
            '{"type":"Feature","geometry":{"type":"Point","coordinates":[1.5,2]},'
            '"properties":{"n":3,"has space":"s","q":[1,true,null,{"k":"v\\n"}],"r":"1.0"},"id":"g1","bbox":[0,0]}',
        )
        # 0.5 ruling 28: geojson keeps its 0.1 behaviour. Residue is the original
        # string value, so an unmapped number or boolean is written back as text.
        self.assertEqual(ent.residue["t-geo"]["properties.r"], "1.0")
        flag = '{"type":"Feature","geometry":null,"properties":{"f":true}}'
        self.assertEqual(
            self.e.convert("t-geo", "t-geo", flag).decode(),
            '{"type":"Feature","geometry":null,"properties":{"f":"true"}}',
        )

    def test_geojson_errors(self):
        for bad in ("[]", '{"type":"Point"}', '{"type":"Feature","geometry":{"type":"LineString"}}',
                    "{bad", '{"type":"Feature","x":NaN}'):
            with self.assertRaises(MalformedWire, msg=bad):
                self.e.decode("t-geo", bad)
        # 0.5 ruling 28: a member name given twice is accepted on geojson (refused on json).
        self.assertEqual(
            self.e.decode("t-geo", '{"type":"Feature","geometry":null,"properties":{},"id":"a","id":"a"}')["uid"], "a"
        )

    def test_residue_does_not_cross_formats(self):
        e = Engine.from_dir(PACKS)
        src = '<event uid="a" version="2.0"><point lat="1" lon="2"/></event>'
        out = e.convert("cot-xml", "geojson", src).decode()
        self.assertNotIn("version", out)
        self.assertEqual(
            out, '{"type":"Feature","geometry":{"type":"Point","coordinates":[2,1]},"properties":{},"id":"a"}'
        )


class TestCli(unittest.TestCase):
    def run_cli(self, *args, stdin=b""):
        env = dict(os.environ, PYTHONPATH=SRC)
        return subprocess.run(
            [sys.executable, "-m", "goat_transformers", *args], input=stdin, capture_output=True, env=env
        )

    def test_list_formats(self):
        r = self.run_cli("list-formats", "--packs", PACKS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"cot-xml\t", r.stdout)
        self.assertIn(b"geojson\t", r.stdout)

    def test_convert(self):
        r = self.run_cli("convert", "--from", "cot-xml", "--to", "geojson", "--packs", PACKS,
                         stdin=b'<event uid="a"/>')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b'{"type":"Feature","geometry":null,"properties":{},"id":"a"}')
        r = self.run_cli("convert", "--from", "cot-xml", "--to", "geojson", "--packs", PACKS, stdin=b"<x/>")
        self.assertEqual(r.returncode, 1)  # spec 0.23: a call failure exits 1, its kind first
        self.assertTrue(r.stderr.startswith(b"missing-root:"), r.stderr)
        self.assertEqual(r.stdout, b"")

    def test_models_and_max_distribution(self):
        models = os.path.normpath(os.path.join(PACKS, "..", "model"))
        r = self.run_cli("list-formats", "--packs", PACKS, "--models", models, "--max-distribution", "public")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"cot-xml\t", r.stdout)
        r = self.run_cli("list-formats", "--packs", PACKS, "--models", os.path.join(HERE, "no-such-dir"))
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stderr.startswith(b"unknown-module:"), r.stderr)


class TestModel(unittest.TestCase):
    def test_parses(self):
        m = parse_model_text(CORE)
        self.assertEqual((m.name, m.version, m.distribution, m.sources), ("core", "0.1.0", "public", ["unit tests"]))
        self.assertEqual(m.keys["lat"].type, "float")
        self.assertEqual((m.keys["lat"].unit, m.keys["uid"].unit), ("deg", None))
        self.assertIn("my key", m.keys)

    def test_module_errors(self):
        head = "module m\nversion 1\ndistribution public\nsource s\n"
        with self.assertRaises(UnknownDirective):
            parse_model_text(head + "bogus 1\n")
        for bad in ("key a.b int -\n", "key a bool -\n", "key a int\n"):
            with self.assertRaises(InvalidModel, msg=bad):
                parse_model_text(head + bad)
        with self.assertRaises(DuplicateKey):
            parse_model_text(head + "key a int -\nkey a int -\n")
        with self.assertRaises(MissingDistribution):
            parse_model_text("module m\nversion 1\nsource s\n")
        with self.assertRaises(MissingSource):
            parse_model_text("module m\nversion 1\ndistribution public\n")

    def test_limit(self):
        e = Engine(max_distribution="public")
        with self.assertRaises(DistributionRefused):
            e.load_model("module core\nversion 1\ndistribution controlled\nsource s\n")
        e.set_max_distribution("controlled")
        e.load_model("module core\nversion 1\ndistribution controlled\nsource s\n")
        with self.assertRaises(ValueError):
            e.set_max_distribution("secret")


class Capability(unittest.TestCase):
    """spec/engine-spec.md, Capability: carried and dropped keys of an ordered
    pair, in the source's order, and the grade."""

    def setUp(self):
        self.e = Engine.from_dir(PACKS, packs_only=["cot-xml", "geojson", "cot-protobuf"])

    def test_pair(self):
        c = self.e.capability("cot-xml", "geojson")
        a, b = self.e.model_keys("cot-xml"), set(self.e.model_keys("geojson"))
        self.assertEqual(c["carried"], [k for k in a if k in b])
        self.assertEqual(c["dropped"], [k for k in a if k not in b])
        self.assertEqual(c["grade"], "partial" if c["dropped"] else "full")

    def test_matrix_is_every_ordered_pair(self):
        m = self.e.capability_matrix()
        self.assertEqual(len(m), 6)
        self.assertEqual({(c["from"], c["to"]) for c in m},
                         {(a, b) for a in self.e.formats() for b in self.e.formats() if a != b})

    def test_unknown_format(self):
        with self.assertRaises(UnknownFormat):
            self.e.capability("cot-xml", "nope")


if __name__ == "__main__":
    unittest.main()
