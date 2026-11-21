"""Tests of tools/gen/zcl2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_zcl2pack*.py'

`fixtures/zcl2pack/input/` is a zigbee-herdsman-shaped tree written for these tests: a cluster
with attributes of four types (one, an array, that the pack cannot state), a command whose
parameter type is not a data type, one with a list parameter, and a response. `expected/` is the
tree the generator writes; after a deliberate change run once with GT_UPDATE_GOLDEN=1.
"""
import support

import os
import shutil
import tempfile
import unittest

import gtcheck
import zcl2pack as gen

FIXTURE = os.path.join(support.FIXTURES, "zcl2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")


class ZclCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        os.makedirs(os.path.join(self.root, "model"))
        shutil.copy(CORE_DEF, os.path.join(self.root, "model", "core.def"))

    def run_gen(self, *more, cluster="demoCluster=zcl-demo"):
        return support.run_main(gen.main, ["--out", self.root, "--herdsman", INPUT, "--cluster", cluster,
                                           "--source", "test"] + list(more))

    def test_golden(self):
        status, out, err = self.run_gen()
        self.assertEqual((status, err), (0, ""))
        support.assert_same_tree(self, EXPECTED, self.root, ignore=("model/core.def",))

    def test_loads_and_lists_skipped(self):
        self.assertEqual(self.run_gen()[0], 0)
        model = gtcheck.Model()
        model.load_dir(os.path.join(self.root, "model"))
        with open(os.path.join(self.root, "packs", "zcl-demo", "pack.def"), encoding="utf-8") as fh:
            text = fh.read()
        gtcheck.load_pack(text, model, "pack.def")
        self.assertIn("field  zcldemocluster.level  8  uint", text)
        with open(os.path.join(self.root, "packs", "zcl-demo", "pack.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("| command set |", md)
        self.assertIn("| command list |", md)

    def test_parser_reads_binary_literals(self):
        toks = gen.tokens("{a: 0b101, b: 0x1f, c: 7}", "t")
        p = gen.Parser(toks, "t")
        self.assertEqual(p.obj(), {"a": 5, "b": 31, "c": 7})

    def test_unknown_cluster(self):
        status, out, err = self.run_gen(cluster="nope=zcl-nope")
        self.assertEqual(status, 1)
        self.assertIn("no cluster nope", err)


if __name__ == "__main__":
    unittest.main()
