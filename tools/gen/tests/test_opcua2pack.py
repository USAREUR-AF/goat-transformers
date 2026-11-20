"""Tests of tools/gen/opcua2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_opcua2pack*.py'

`fixtures/opcua2pack/input/Test.NodeSet2.xml` is a NodeSet written for these tests: an
enumeration, a structure with an optional String, a subtype of it with an array, a NodeId and an
optional LocalizedText, a union with a member the pack cannot carry (a Variant), and a structure
whose only field is a Variant. `expected/` is the tree the generator must write; after a
deliberate change run once with GT_UPDATE_GOLDEN=1 and review the diff.
"""
import support

import os
import shutil
import tempfile
import unittest

import gtcheck
import opcua2pack as gen

FIXTURE = os.path.join(support.FIXTURES, "opcua2pack")
NODESET = os.path.join(FIXTURE, "input", "Test.NodeSet2.xml")
EXPECTED = os.path.join(FIXTURE, "expected")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")


class OpcuaCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        os.makedirs(os.path.join(self.root, "model"))
        shutil.copy(CORE_DEF, os.path.join(self.root, "model", "core.def"))

    def run_gen(self, *more, nodeset=NODESET):
        return support.run_main(gen.main, ["--out", self.root, "--nodeset", nodeset,
                                           "--namespace", "urn:example:test", "--format", "opcua-test",
                                           "--module", "opcuatest", "--source", "test NodeSet"] + list(more))

    def test_golden(self):
        status, out, err = self.run_gen()
        self.assertEqual((status, err), (0, ""))
        support.assert_same_tree(self, EXPECTED, self.root, ignore=("model/core.def",))

    def test_check_mode(self):
        self.assertEqual(self.run_gen()[0], 0)
        status, out, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        with open(os.path.join(self.root, "packs", "opcua-test", "pack.def"), "a") as fh:
            fh.write("# edited\n")
        status, out, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("pack.def differs", err)

    def test_loads(self):
        self.assertEqual(self.run_gen()[0], 0)
        model = gtcheck.Model()
        model.load_dir(os.path.join(self.root, "model"))
        text = open(os.path.join(self.root, "packs", "opcua-test", "pack.def"), encoding="utf-8").read()
        pack = gtcheck.load_pack(text, model, "pack.def")
        self.assertEqual([k.name for k in pack.kinds], ["base", "choice", "derived"])

    def test_not_built_listed(self):
        self.assertEqual(self.run_gen()[0], 0)
        md = open(os.path.join(self.root, "packs", "opcua-test", "pack.md"), encoding="utf-8").read()
        self.assertIn("| Holder | a Variant field (BaseDataType) |", md)
        self.assertIn("| Choice.Anything | a Variant field (BaseDataType) |", md)

    def test_refuses_unknown_type(self):
        bad = os.path.join(self.root, "bad.xml")
        text = open(NODESET, encoding="utf-8").read().replace('DataType="ns=1;i=3001"', 'DataType="ns=1;i=3999"')
        open(bad, "w", encoding="utf-8").write(text)
        status, out, err = self.run_gen(nodeset=bad)
        self.assertEqual(status, 1)
        self.assertIn("is in no given NodeSet", err)
        self.assertFalse(os.path.exists(os.path.join(self.root, "packs")))

    def test_refuses_malformed_xml(self):
        bad = os.path.join(self.root, "bad.xml")
        open(bad, "w", encoding="utf-8").write("<UANodeSet")
        status, out, err = self.run_gen(nodeset=bad)
        self.assertEqual(status, 1)
        self.assertIn("not well-formed", err)


if __name__ == "__main__":
    unittest.main()
