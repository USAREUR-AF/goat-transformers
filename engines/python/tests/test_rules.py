"""Version 0.6, mapping rules (spec/engine-spec.md, "Version 0.6: mapping
rules"): constants, defaults, value tables, field options, one key at several
locators, a root per kind, derived keys, caller-supplied keys and the order
inside `convert`. The conformance vectors pin the same behaviour across
engines; these tests cover this engine's edges with synthetic packs."""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
sys.path.insert(0, SRC)
PACKS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "packs"))

from goat_transformers import (  # noqa: E402
    BadDirective, Engine, Entity, InvalidPack, KeyTypeMismatch, MalformedWire, MissingDistribution, MissingRoot,
    NoKind, TransformDecodeFailure, TransformEncodeFailure, UndeclaredKey, UnknownDirective, parse_model_text,
    parse_pack_text,
)

CORE = """
module core
version 0.1.0
distribution public
source "unit tests"
key uid    string -
key type   string -
key lat    float  deg
key lon    float  deg
key speed  float  m/s
key course float  deg
key name   string -
key n      int    -
key flag   int    -
"""

EXT = """
module ext
version 0.1.0
distribution public
source "unit tests"
key east   float -
key north  float -
key label  string -
key n2     int -
derive course     bearing  ext.east ext.north
derive speed      hypot    ext.east ext.north
derive ext.east   east_of  speed course
derive ext.north  north_of speed course
derive ext.label  join:-   uid name
derive ext.n2     offset:-2 n
"""

HEAD = "format %s\nversion 0.6.0\ndistribution public\nsource \"unit tests\"\nuses ext\n"


def engine(*packs):
    e = Engine()
    e.load_model(CORE)
    e.load_model(EXT)
    for p in packs:
        e.load(p)
    return e


JSON = HEAD % "j" + """wire json
const   schema  rules
const   rev     6
const   tag     =7
field   uid     id          string
field   lat     pos.lat     float
field   lat     pos.y       float
field   name    cls         int     via cls
field   n       state       string  via state
field   type    how         string  via how
default lon     -1
field   lon     pos.lon     float
default name    two
map cls   1   one
map cls   2   two
map cls   3   one
map cls   1   uno
map state on  1
map state off 0
map how   M   m-g
"""


class TestConstDefaultTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = engine(JSON)

    def rt(self, text, context=None):
        return self.e.convert("j", "j", text, context).decode()

    def test_const_written_typed_not_checked_not_residue(self):
        self.assertEqual(
            self.rt('{"schema":"other","rev":1,"id":"a","x":"keep"}'),
            # `pos` stands where the first line that addresses into it stands (0.5, canonical output).
            '{"schema":"rules","rev":6,"tag":"7","id":"a","pos":{"lon":-1},"cls":2,"x":"keep"}',
        )

    def test_default_is_used_on_encode_only(self):
        ent = self.e.decode("j", '{"id":"a"}')
        self.assertEqual(ent.fields, {"uid": "a"})
        self.e.encode("j", ent)
        self.assertEqual(ent.fields, {"uid": "a"})  # a default never changes the entity

    def test_table_both_ways_and_first_entry(self):
        ent = self.e.decode("j", '{"cls":1,"state":"off","how":"M"}')
        self.assertEqual(ent.fields, {"name": "one", "n": 0, "type": "m-g"})
        self.assertEqual(self.e.decode("j", '{"cls":3}')["name"], "one")
        self.assertIn('"cls":1', self.e.encode("j", Entity(fields={"name": "one"})).decode())
        self.assertIn('"state":"on"', self.e.encode("j", Entity(fields={"n": 1})).decode())

    def test_table_no_entry(self):
        # Same type on both sides: the value passes through. Otherwise it is a transform failure.
        self.assertEqual(self.e.decode("j", '{"how":"h-e"}')["type"], "h-e")
        with self.assertRaises(TransformDecodeFailure):
            self.e.decode("j", '{"cls":9}')
        with self.assertRaises(TransformDecodeFailure):
            self.e.decode("j", '{"state":"maybe"}')
        with self.assertRaises(TransformEncodeFailure):
            self.e.encode("j", Entity(fields={"name": "nine"}))
        with self.assertRaises(TransformEncodeFailure):
            self.e.encode("j", Entity(fields={"n": 5}))

    def test_one_key_at_several_locators(self):
        self.assertEqual(self.e.decode("j", '{"pos":{"y":2,"lat":1}}')["lat"], 1.0)
        self.assertEqual(self.e.decode("j", '{"pos":{"y":2}}')["lat"], 2.0)
        self.assertEqual(self.e.decode("j", '{"pos":{"lat":"north","y":2}}')["lat"], 2.0)
        with self.assertRaises(TransformDecodeFailure) as cm:
            self.e.decode("j", '{"pos":{"lat":"north","y":"south"}}')
        self.assertEqual([a[1] for a in cm.exception.absent], ["pos.lat", "pos.y"])
        self.assertIn('"pos":{"lat":3,"y":3,', self.e.encode("j", Entity(fields={"lat": 3.0})).decode())

    def test_load_checks(self):
        base = HEAD % "x" + "wire json\n"
        cases = [
            (base + "field name cls int via t\n", BadDirective),                         # no `map` line
            (base + "field lat cls int via t\nmap t 1 one\n", KeyTypeMismatch),           # model side string
            (base + "field name cls int via t\nmap t 1 100\n", KeyTypeMismatch),          # model side int
            (base + "default nokey 1\n", UndeclaredKey),
            (base + "default lat north\n", KeyTypeMismatch),
            (base + "const a present\n", BadDirective),
            (base + "field uid id string swap\n", BadDirective),
            (base + "field uid id string trim\n", BadDirective),
            (base + "field uid id string optional\n", BadDirective),
            (base + "field uid id string bogus\n", BadDirective),               # 0.6 ruling 12
            (base + "field lat cls float via t via t\nmap t 1 10\n", BadDirective),  # 0.6 ruling 12
            (base + "kind a\nroot r\n", BadDirective),
        ]
        bits = HEAD % "x" + "wire bits\nword_bytes 1\n"
        cases += [
            (bits + "field n 0:0:12 uint swap\n", BadDirective),
            (bits + "field n 0:0:16 uint trim\n", BadDirective),
            (bits + "const 0:0:4 16\n", BadDirective),
        ]
        for text, cls in cases:
            with self.assertRaises(cls, msg=text):
                engine(text)
        engine(base + "field lat zone string via t\nmap t n 45.5\nmap t s -45.5\n")
        engine(bits + "field name 0:0:32 ascii optional via t trim swap\nmap t AB ab\n")

    def test_whole_file_checks_follow_line_errors(self):
        # 0.5 ruling 25: a line error is raised as the file is read; the checks
        # that need the whole file come after it and before missing-distribution.
        bits = "format x\nversion 1\nwire bits\nword_bytes 1\nfield lat 0:0:16 f32\n"
        with self.assertRaises(UnknownDirective):
            parse_pack_text(bits + "bogus 1\n")
        with self.assertRaises(BadDirective):
            parse_pack_text(bits)
        with self.assertRaises(MissingDistribution):
            parse_pack_text("format x\nversion 1\nwire bits\nword_bytes 1\nfield lat 0:0:32 f32\n")


BITS = HEAD % "b" + """wire bits
word_bytes 1
bit_order msb
const  0:0:8   90
field  n       0:8:16   uint  swap
field  name    0:24:32  ascii trim optional
field  lat     0:56:32  f32   optional swap
"""

BITS_LSB = HEAD % "bl" + """wire bits
word_bytes 2
field  n     0:0:16  uint swap
field  name  1:0:32  ascii swap
field  lat   3:0:64  f64
"""


class TestFieldOptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = engine(BITS, BITS_LSB)

    def test_swap_trim_optional(self):
        ent = self.e.decode("b", "00 3412 41204220 00002040")
        self.assertEqual(ent.fields, {"n": 0x1234, "name": "A B", "lat": 2.5})
        self.assertEqual(self.e.encode("b", ent).decode(), "5a34124120420000002040")
        self.assertEqual(self.e.decode("b", "5a3412202020200000")["name"], "")

    def test_optional_beyond_input_is_absent(self):
        self.assertEqual(self.e.decode("b", "5a3412").fields, {"n": 0x1234})
        self.assertEqual(self.e.decode("b", "5a3412414243").fields, {"n": 0x1234})  # partly beyond
        self.assertEqual(self.e.decode("b", "5a341241424344ff").fields, {"n": 0x1234, "name": "ABCD"})
        self.assertEqual(self.e.convert("b", "b", "5a3412").decode(), "5a341200000000" + "00000000")
        with self.assertRaises(MalformedWire):
            self.e.decode("b", "5a34")

    def test_swap_in_lsb_is_big_endian(self):
        ent = self.e.decode("bl", "1234" "00004241" "000000000000f83f")
        self.assertEqual(ent.fields, {"n": 0x1234, "name": "AB", "lat": 1.5})
        self.assertEqual(self.e.encode("bl", ent).decode(), "1234" "00004241" "000000000000f83f")

    def test_not_a_number_and_infinity_on_the_wire(self):
        for bad in ("000000000000f87f", "000000000000f07f", "000000000000f0ff"):
            with self.assertRaises(TransformDecodeFailure, msg=bad):
                self.e.decode("bl", "1234" "00004241" + bad)
        with self.assertRaises(TransformDecodeFailure):
            self.e.decode("b", "5a3412414243440000807f")
        with self.assertRaises(TransformEncodeFailure):
            self.e.encode("b", Entity(fields={"lat": 1e39}))

    def test_ascii_encode_refuses_bytes_outside_printable_ascii(self):
        for bad in ("A\tB", "é"):
            with self.assertRaises(TransformEncodeFailure, msg=bad):
                self.e.encode("b", Entity(fields={"name": bad}))


XML = HEAD % "x" + """wire xml
field   uid   @id        string
const   @v    1
default name  NONE
kind     track
root     trk
requires lat lon
field    lat   pos/@lat  float
field    lon   pos/@lon  float
field    name  n/#text   string
kind     marked
root     note
requires speed
when     @mark present
field    speed @s        float
kind     tagged
root     note
field    type  @mode     string
when     @mode fixed
kind     plain
root     item
"""


class TestRootPerKind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = engine(XML)

    def kind(self, text):
        return self.e.decode("x", text).kind[1]

    def test_root_selects_the_kinds_considered(self):
        self.assertEqual(self.kind('<trk id="a"/>'), "track")
        self.assertEqual(self.kind('<note mark="" id="a"/>'), "marked")
        self.assertEqual(self.kind('<note mode="fixed"/>'), "tagged")
        self.assertEqual(self.kind("<item/>"), "plain")
        for bad in ("<other/>", '<note mode="loose"/>'):
            with self.assertRaises(NoKind, msg=bad):
                self.e.decode("x", bad)

    def test_encode_writes_the_kinds_root_const_and_default(self):
        out = self.e.encode("x", Entity(fields={"uid": "a", "lat": 1.5, "lon": 2.0})).decode()
        self.assertEqual(out, '<trk id="a" v="1"><pos lat="1.5" lon="2"/><n>NONE</n></trk>')
        self.assertEqual(self.e.encode("x", Entity(fields={"uid": "a"})).decode(), '<note id="a" v="1" mode="fixed"/>')

    def test_when_present_does_not_map_its_member(self):
        # 0.5 ruling 27: the scalar a `when ... present` names is residue and is written back.
        text = '<note mark="m" id="a" s="2"/>'
        self.assertEqual(self.e.decode("x", text).residue["x"], {"@mark": "m"})
        self.assertEqual(self.e.convert("x", "x", text).decode(), '<note id="a" v="1" s="2" mark="m"/>')

    def test_pack_root_rules(self):
        head = HEAD % "y" + "wire xml\n"
        with self.assertRaises(MissingRoot):
            parse_pack_text(head + "kind a\nroot r\nkind b\n")  # kind b has no root and the pack has none
        p = parse_pack_text(head + "root item\nkind a\nroot alpha\nkind b\n")
        self.assertEqual([k.root for k in p.kinds], ["alpha", None])
        e = engine(head + "root item\nfield uid @id string\nkind a\nroot alpha\nkind b\n")
        self.assertEqual(e.decode("y", "<alpha/>").kind[1], "a")
        self.assertEqual(e.decode("y", "<item/>").kind[1], "b")
        self.assertEqual(e.encode("y", Entity(kind=("y", "b"))).decode(), "<item/>")


FLAT = HEAD % "f" + """wire json
field uid        id     string
field name       name   string
field n          n      int
field speed      speed  float
field course     course float
field ext.east   east   float
field ext.north  north  float
field ext.label  label  string
field ext.n2     n2     int
"""

OTHER = HEAD % "g" + """wire json
field uid        id     string
field speed      v      float
field course     c      float
field ext.label  label  string
"""


class TestDeriveAndContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = engine(FLAT, OTHER)

    def test_derive_load_checks(self):
        head = "module m\nversion 1\ndistribution public\nsource s\nkey a float -\nkey b float -\nkey i int -\nkey s string -\n"
        core = parse_model_text(CORE)
        for good in ("derive m.b neg m.a\n", "derive m.b hypot m.a lat\n", "derive m.s join:, uid name\n",
                     "derive m.s join:, uid\n",  # 0.6 ruling 7: one or more arguments
                     "derive m.i offset:3 n\n", "derive m.b scale:1/3 m.a\n", "derive m.i copy n\n"):
            self.assertEqual(len(parse_model_text(head + good, core=core).derives), 1, good)
        for bad in ("derive m.b cube m.a\n", "derive m.b hypot m.a\n", "derive m.b neg m.zz\n", "derive m.i neg m.a\n",
                    "derive m.i copy m.a\n", "derive m.b neg ext.east\n", "derive m.i offset:0.5 n\n",
                    "derive m.b scale:x m.a\n", "derive m.b offset:1 n\n", "derive m.s join:,\n",
                    "derive m.b scale m.a\n", "derive m.b neg:1 m.a\n"):
            with self.assertRaises(BadDirective, msg=bad):
                parse_model_text(head + bad, core=core)

    def test_complete(self):
        ent = self.e.complete(Entity(fields={"ext.east": 3.0, "ext.north": 4.0, "n": 5}))
        self.assertEqual(ent["speed"], 5.0)
        self.assertAlmostEqual(ent["course"], 36.86989764584402, places=9)
        self.assertEqual(ent["ext.n2"], 3)
        self.assertNotIn("ext.label", ent.fields)  # an argument is absent
        ent = self.e.complete(Entity(fields={"ext.east": -40.25, "ext.north": 0.0}))
        self.assertEqual((ent["course"], ent["speed"]), (270.0, 40.25))
        ent = self.e.complete(Entity(fields={"ext.east": 0.0, "ext.north": 0.0}))
        self.assertEqual(ent["speed"], 0.0)
        self.assertNotIn("course", ent.fields)  # bearing: absent when both are 0
        ent = self.e.complete(Entity(fields={"ext.east": 1e200, "ext.north": 1e200}))
        self.assertNotIn("speed", ent.fields)   # a result that is not finite leaves the target absent
        ent = self.e.complete(Entity(fields={"speed": 10.0, "course": 90.0}))
        self.assertAlmostEqual(ent["ext.east"], 10.0, places=9)
        self.assertAlmostEqual(ent["ext.north"], 0.0, places=9)
        ent = self.e.complete(Entity(fields={"speed": 1.0, "ext.east": 3.0, "ext.north": 4.0}))
        self.assertEqual(ent["speed"], 1.0)     # a present target is kept

    def test_decode_alone_does_not_derive(self):
        self.assertEqual(self.e.decode("f", '{"east":3,"north":4}').fields, {"ext.east": 3.0, "ext.north": 4.0})

    def test_convert_order(self):
        src = '{"id":"u","east":3,"north":4}'
        # Same format, no context: nothing is filled or derived.
        self.assertEqual(self.e.convert("f", "f", src).decode(), src)
        # Same format with a context: the context fills absent keys, then the derivations run.
        self.assertEqual(
            self.e.convert("f", "f", src, {"name": "N", "uid": "ignored"}).decode(),
            '{"id":"u","name":"N","speed":5,"course":36.86989764584402,"east":3,"north":4,"label":"u-N"}',
        )
        # Another format: derived even with no context.
        self.assertEqual(self.e.convert("f", "g", src).decode(), '{"id":"u","v":5,"c":36.86989764584402}')

    def test_context_checks(self):
        src = '{"id":"u"}'
        with self.assertRaises(UndeclaredKey) as cm:
            self.e.convert("f", "f", src, {"nosuchkey": "1"})
        self.assertTrue(str(cm.exception).startswith("undeclared-key:"))
        for bad in ({"n": "soon"}, {"n": "1.5"}, {"speed": "fast"}, {"n": 1.5}, {"name": 3}, {"n": True}):
            with self.assertRaises(KeyTypeMismatch, msg=bad) as cm:
                self.e.convert("f", "f", src, bad)
            self.assertTrue(str(cm.exception).startswith("key-type-mismatch:"))
        self.assertEqual(
            self.e.convert("f", "f", src, {"n": "7", "speed": 2, "ext.label": "L"}).decode(),
            '{"id":"u","n":7,"speed":2,"label":"L","n2":5}',
        )


class TestCliSet(unittest.TestCase):
    def test_set(self):
        env = dict(os.environ, PYTHONPATH=SRC)
        src = (
            b'<event uid="J-1" type="a-f-G" time="2021-02-27T20:00:00.000Z"><point lat="1" lon="2" hae="3" ce="4" le="5"/>'
            b"</event>"
        )
        base = [sys.executable, "-m", "goat_transformers", "convert", "--packs", PACKS, "--from", "cot-xml", "--to", "cot-xml"]
        r = subprocess.run(base + ["--set", "stale_ms=1614456030000", "--set", "how=m-g"], input=src,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b'stale="2021-02-27T20:00:30.000Z" how="m-g"', r.stdout)
        r = subprocess.run(base + ["--set", "nosuchkey=1"], input=src, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn(b"undeclared-key:", r.stderr)


if __name__ == "__main__":
    unittest.main()
