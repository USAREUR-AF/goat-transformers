"""Tests of tools/gen/protojson2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_protojson2pack*.py'

`fixtures/protojson2pack/input/test.proto` is written for these tests: every scalar kind of the
JSON mapping, a hex and a base64 bytes field, an enum, a repeated message and a repeated scalar,
a map (not carried) and a type that stands inside itself. `expected/` is the tree the generator
writes; after a deliberate change run once with GT_UPDATE_GOLDEN=1 and review the diff.
"""
import support

import os
import shutil
import tempfile
import unittest

import protojson2pack as gen

FIXTURE = os.path.join(support.FIXTURES, "protojson2pack")
PROTO = os.path.join(FIXTURE, "input", "test.proto")
EXPECTED = os.path.join(FIXTURE, "expected")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")


class ProtoJsonCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        os.makedirs(os.path.join(self.root, "model"))
        shutil.copy(CORE_DEF, os.path.join(self.root, "model", "core.def"))

    def run_gen(self, *more, envelope="demo.v1.Report"):
        return support.run_main(gen.main, ["--out", self.root, "--proto", PROTO, "--envelope", envelope,
                                           "--format", "demo-json", "--module", "demojson", "--source", "test",
                                           "--hex-bytes", "trace_id"] + list(more))

    def test_golden(self):
        status, out, err = self.run_gen()
        self.assertEqual((status, err), (0, ""))
        support.assert_same_tree(self, EXPECTED, self.root, ignore=("model/core.def",))

    def test_mapping(self):
        self.assertEqual(self.run_gen()[0], 0)
        text = open(os.path.join(self.root, "packs", "demo-json", "pack.def"), encoding="utf-8").read()
        self.assertIn("field  demojson.trace_id  traceId  string", text)
        self.assertIn("field  demojson.points_time_unix_nano  timeUnixNano  string", text)
        self.assertIn("field  demojson.colour  colour  int", text)
        self.assertIn("field  demojson.points_valid  valid  bool", text)
        self.assertIn("group  demojson.tags  tags", text)
        self.assertNotIn("labels", text)
        md = open(os.path.join(self.root, "packs", "demo-json", "pack.md"), encoding="utf-8").read()
        self.assertIn("`demo.v1.Report.labels` | a map field", md)
        self.assertIn("`demo.v1.List.values` | the type stands inside itself", md)

    def test_check_mode(self):
        self.assertEqual(self.run_gen()[0], 0)
        self.assertEqual(self.run_gen("--check")[0], 0)
        os.remove(os.path.join(self.root, "packs", "demo-json", "pack.md"))
        status, out, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("pack.md is missing", err)

    def test_unknown_envelope(self):
        status, out, err = self.run_gen(envelope="demo.v1.Nothing")
        self.assertEqual(status, 1)
        self.assertIn("no message demo.v1.Nothing", err)


if __name__ == "__main__":
    unittest.main()
