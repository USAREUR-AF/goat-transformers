"""Rulings 16 to 30 of Version 0.8 (spec/engine-spec.md, "Stated, not yet
pinned by a vector"), and loading only named packs. The conformance vectors
pin the rulings; these tests pin the same points on packs of their own."""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "src"))
sys.path.insert(0, SRC)

from goat_transformers import (  # noqa: E402
    BadDirective, DistributionRefused, DistributionViolation, DuplicateModule, Engine, Entity, GTError, MalformedWire,
    MissingDistribution, MissingSource, UnknownFormat, UnknownModule,
)

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\n"
MODEL = (
    "module m\nversion 1\ndistribution public\nsource s\n"
    "key a int -\nkey b int -\nkey c int -\nkey s string -\nlist rows\n"
)
HEAD = "format x\nversion 1\ndistribution public\nsource s\nuses m\nwire bits\nlayout sequential\nbit_order msb\n"
GROUP = "group m.rows count 8\nfield m.b 8 uint\nend\n"


def engine(body, model=MODEL):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(model)
    eng.load(HEAD + body)
    return eng


class TestEnds(unittest.TestCase):
    def test_align_stops_at_the_end_of_the_input(self):  # ruling 20
        eng = engine("field m.a 4 uint\nalign 16\n")
        ent = eng.decode("x", "50")
        self.assertEqual(ent.fields, {"m.a": 5})
        self.assertEqual(eng.encode("x", ent), b"5000")  # written in full

    def test_align_stops_at_the_end_of_an_extent(self):  # ruling 20
        eng = engine("length 8\nfield m.a 4 uint\nalign 32\nend\nfield m.b 8 uint\n")
        self.assertEqual(eng.decode("x", "015007").fields, {"m.a": 5, "m.b": 7})

    def test_pad_and_const_past_the_end_of_the_input(self):  # ruling 20
        for line in ("pad 8\n", "const 8 1\n"):
            eng = engine("field m.a 8 uint\n" + line)
            with self.assertRaises(MalformedWire, msg=line):
                eng.decode("x", "05")

    def test_more_indicator_at_the_end_of_an_extent_reads_0(self):  # ruling 21
        eng = engine("length 8 bits\nfield m.a 8 uint\ngroup m.rows more\nfield m.b 7 uint\nend\nend\n")
        rows = eng.decode("x", "100589ff").lists["m.rows"]
        self.assertEqual([r.fields for r in rows], [{"m.b": 9}, {}])

    def test_fx_presence_at_the_end_of_an_extent(self):  # ruling 21
        eng = engine("length 8 bits\nfield m.a 8 uint\npresence f fx\nif f.1\nfield m.b 8 uint\nend\nend\n")
        self.assertEqual(eng.decode("x", "0805").fields, {"m.a": 5})  # the presence reads as 0
        with self.assertRaises(MalformedWire):  # its continuation octet would start at the end
            eng.decode("x", "10050100")


class TestListInTwoGroups(unittest.TestCase):  # ruling 23
    def test_different_blocks_load(self):
        engine("presence p 2\nif p.1\n" + GROUP + "end\nif p.2\n" + GROUP + "end\n")
        engine("opt\nopt\n" + GROUP + "end\nopt\n" + GROUP + "end\nend\n")

    def test_refused(self):
        for body in (
            GROUP + GROUP,
            "opt\n" + GROUP + GROUP + "end\n",
            GROUP + "opt\n" + GROUP + "end\n",
            "length 8\n" + GROUP + "end\nlength 8\n" + GROUP + "end\n",
            "opt\n" + GROUP + "opt\n" + GROUP + "end\nend\n",  # one block encloses the other
        ):
            with self.assertRaises(BadDirective, msg=body):
                engine(body)

    def test_item_kind_the_group_does_not_have(self):  # ruling 26
        eng = engine(
            "field m.a 8 uint\npresence p 2\npad 6\n"
            "if p.1 !p.2\ngroup m.rows count 8\nkind small\nwhen 8 1\nrequires m.b\nfield m.b 8 uint\n"
            "kind tiny\nwhen 8 0\nend\nend\n"
            "if p.2\ngroup m.rows count 8\nkind wide\nwhen 8 2\nrequires m.b\nfield m.b 16 uint\n"
            "kind none\nwhen 8 0\nend\nend\n"
        )
        ent = eng.decode("x", "0180010105")
        self.assertEqual(ent.lists["m.rows"][0].kind, ("x", "small"))
        self.assertEqual(eng.encode("x", ent), b"01c001020005")


class TestParseInt(unittest.TestCase):  # ruling 28
    def test_texts(self):
        eng = Engine()
        eng.load_model(CORE)
        eng.load_model(MODEL + "derive m.a parse_int m.s\n")
        cases = {
            "007": 7, "-007": -7, "-0": 0, "0" * 30 + "1": 1,
            "9223372036854775807": 9223372036854775807, "-9223372036854775808": -9223372036854775808,
            "9223372036854775808": None, "-9223372036854775809": None,
            "+5": None, "": None, "-": None, " 5": None, "5 ": None, "1.0": None, "--1": None, "٣": None,
        }
        for text, want in cases.items():
            ent = Entity()
            ent.fields["m.s"] = text
            self.assertEqual(eng.complete(ent).fields.get("m.a"), want, repr(text))


class TestModuleCheckOrder(unittest.TestCase):  # ruling 29
    BODY = "uses nosuch\nkey k int -\nderive o.k copy o.nokey\n"

    def load(self, head, body=None, limit="public"):
        eng = Engine(max_distribution=limit)
        eng.load_model(CORE)
        eng.load_model("module o\nversion 1\n" + head + (self.BODY if body is None else body))

    def test_order(self):
        with self.assertRaises(MissingDistribution):
            self.load("")
        with self.assertRaises(MissingSource):
            self.load("distribution controlled\n")
        with self.assertRaises(DistributionRefused):
            self.load("distribution controlled\nsource s\n")
        with self.assertRaises(UnknownModule):
            self.load("distribution public\nsource s\n")
        with self.assertRaises(BadDirective):
            self.load("distribution public\nsource s\n", "key k int -\nderive o.k copy o.nokey\n")

    def test_violation_before_the_derive_checks_and_duplicate_after(self):
        eng = Engine()
        eng.load_model(CORE)
        eng.load_model(MODEL.replace("public", "controlled"))
        other = "module o\nversion 1\ndistribution public\nsource s\nuses m\nkey k int -\n"
        with self.assertRaises(DistributionViolation):
            eng.load_model(other + "derive o.k copy o.nokey\n")
        eng = Engine()
        eng.load_model(CORE)
        eng.load_model(MODEL)
        eng.load_model(other)
        with self.assertRaises(BadDirective):
            eng.load_model(other + "derive o.k copy o.nokey\n")
        with self.assertRaises(BadDirective):  # the target is a key of `core` or of the module itself
            eng.load_model(other.replace("module o", "module o2") + "derive m.a copy o2.k\n")
        with self.assertRaises(DuplicateModule):
            eng.load_model(other)


class TestRulings31To34(unittest.TestCase):
    def test_derive_refused_on_its_own_text_is_a_line_error(self):  # ruling 32; ruling 5b of 0.11
        head = "module o\nversion 1\n"  # no distribution, no source
        for line in ("derive o.k nosuch o.a", "derive o.k copy:1 o.a", "derive o.k scale o.a", "derive o.k scale:x o.a",
                     "derive o.k copy o.a o.b", "derive o.k hypot o.a", "derive o.k join:-"):
            eng = Engine()
            eng.load_model(CORE)
            with self.assertRaises(BadDirective, msg=line):  # right after the file, before missing-distribution
                eng.load_model(head + line + "\n")
            eng = Engine()
            eng.load_model(CORE)
            with self.assertRaises(GTError, msg=line) as cm:  # 0.11: a later unknown directive comes first
                eng.load_model(head + line + "\nbogus 1\n")
            self.assertEqual(cm.exception.code, "unknown-directive", line)
        eng = Engine()
        eng.load_model(CORE)
        with self.assertRaises(MissingDistribution):  # an undeclared key waits for its place in ruling 29
            eng.load_model(head + "derive o.k copy o.nokey\n")

    def test_later_group_of_a_list_wins_on_decode(self):  # ruling 33
        eng = engine("presence p 2\npad 6\nif p.1\n" + GROUP + "end\nif p.2\n" + GROUP + "end\n")
        rows = eng.decode("x", "c001050107").lists["m.rows"]
        self.assertEqual([r.fields for r in rows], [{"m.b": 7}])

    def test_group_whose_first_indicator_is_at_the_end_is_absent(self):  # ruling 34
        for how in ("more", "while"):
            eng = engine("length 8 bits\nfield m.a 8 uint\ngroup m.rows %s\nfield m.b 7 uint\nend\nend\n" % how)
            ent = eng.decode("x", "0805")
            self.assertEqual((ent.fields, "m.rows" in ent.lists), ({"m.a": 5}, False), how)


class TestPacksOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = cls.tmp.name
        cls.packs = os.path.join(root, "packs")
        files = {
            "model/core.def": CORE,
            "model/m.def": MODEL + "uses n\n",
            "model/n.def": "module n\nversion 1\ndistribution public\nsource s\nkey k int -\n",
            "model/z.def": "module z\nversion 1\ndistribution public\nsource s\nkey k int -\n",
            "packs/x/pack.def": HEAD + "field m.a 8 uint\n",
            "packs/y/pack.def": "format y\nversion 1\ndistribution public\nsource s\nuses z\nwire json\nfield z.k k int\n",
            "packs/w/pack.def": "format w\nversion 1\ndistribution public\nsource s\nwire json\nfield uid id string\n",
        }
        for rel, text in files.items():
            path = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_named_packs_and_the_modules_they_need(self):
        eng = Engine.from_dir(self.packs, packs_only=["x"])
        self.assertEqual(eng.formats(), ["x"])
        self.assertEqual(sorted(eng.models), ["core", "m", "n"])  # `n` because `m` uses it; not `z`
        eng = Engine.from_dir(self.packs, packs_only=["w", "y", "w"])
        self.assertEqual((eng.formats(), sorted(eng.models)), (["w", "y"], ["core", "z"]))
        self.assertEqual(eng.convert("w", "w", b'{"id":"a"}'), b'{"id":"a"}')

    def test_everything_without_it(self):
        eng = Engine.from_dir(self.packs)
        self.assertEqual((eng.formats(), sorted(eng.models)), (["w", "x", "y"], ["core", "m", "n", "z"]))

    def test_unknown_name(self):
        for name in ("nosuch", "", "..", os.path.join("x", "..", "y")):
            with self.assertRaises(UnknownFormat, msg=name):
                Engine.from_dir(self.packs, packs_only=[name])

    def test_cli(self):
        env = dict(os.environ, PYTHONPATH=SRC)
        cmd = [sys.executable, "-m", "goat_transformers", "list-formats", "--packs", self.packs]
        r = subprocess.run(cmd + ["--packs-only", "y,w"], capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([ln.split(b"\t")[0] for ln in r.stdout.splitlines()], [b"w", b"y"])
        # spec 0.23: a name is used as given, so " w" is no pack directory; a call failure exits 1
        for only in ("y, w", "nosuch"):
            r = subprocess.run(cmd + ["--packs-only", only], capture_output=True, env=env)
            self.assertEqual((r.returncode, r.stdout), (1, b""), only)
            self.assertTrue(r.stderr.startswith(b"unknown-format:"), r.stderr)
        r = subprocess.run(
            [sys.executable, "-m", "goat_transformers", "convert", "--from", "w", "--to", "w", "--packs", self.packs,
             "--packs-only", "w"],
            input=b'{"id":"a"}', capture_output=True, env=env,
        )
        self.assertEqual((r.returncode, r.stdout), (0, b'{"id":"a"}'), r.stderr)


if __name__ == "__main__":
    unittest.main()
