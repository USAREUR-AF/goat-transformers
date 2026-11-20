"""Tests of tools/gen/yang2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_yang2pack*.py'

fixtures/yang2pack/input/source/models holds YANG modules written for these tests, stored
as `<name>.yang.txt` (the boundary gate admits no `.yang` file) and copied to `<name>.yang`
before each run: a device module with a submodule, groupings, a typedef with a range, a
date-and-time, a 64-bit counter, decimal64, an enumeration, an identityref, an empty leaf, a
union of a number and a string, leafrefs (relative and absolute), a leaf-list, a choice
with a shorthand case, anydata, a keyed list, a `uses` with an `augment`, an rpc; a module
that augments the list, a case and the rpc input; and a module whose augment is not applied.
fixtures/yang2pack/expected is the tree the run writes into the checkout.
"""
import os
import shutil
import tempfile
import unittest

import support

Y = support.load_script("yang2pack.py")
FIXTURE = os.path.join(support.FIXTURES, "yang2pack")
INPUTS = ("model/core.def", "model/track.def")


class YangTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="yang2pack-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = os.path.join(self.work, "src")
        for d, _, names in os.walk(os.path.join(FIXTURE, "input", "source")):
            rel = os.path.relpath(d, os.path.join(FIXTURE, "input", "source"))
            os.makedirs(os.path.join(self.src, rel), exist_ok=True)
            for n in names:
                shutil.copyfile(os.path.join(d, n), os.path.join(self.src, rel, n[:-4] if n.endswith(".txt") else n))
        self.gt = support.copy_tree(os.path.join(FIXTURE, "input", "checkout"), os.path.join(self.work, "gt"))

    def run_gen(self, *extra, module="ex-device", top="device"):
        argv = ["--source-root", self.src, "--search", "models", "--module", module, "--top", top,
                "--augment-module", "ex-ext", "--format", "ex-device", "--model-module", "exdevice",
                "--title", "Example device, written for the tests", "--license", "an example statement",
                "--source", "the yang2pack test fixture", "--repository", "none (written for the tests)",
                "--run-script", "tools/gen/tests/test_yang2pack.py", "--read-on", "2026-11-20",
                "--map", "ex-device:device.clock.now=time_ms",
                "--evidence", "ex-device:device.clock.now=the fixture's clock, written for the tests",
                "--model-dir", os.path.join(self.gt, "model"),
                "--names-file", os.path.join(self.gt, "tools", "gen", "names", "ex-device.json"),
                "--out", self.gt] + list(extra)
        return support.run_main(Y.main, argv)

    def read(self, *parts):
        with open(os.path.join(self.gt, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_gen()
        self.assertEqual((status, err), (0, ""))
        self.assertEqual(out, "ex-device: device, 3 leaves left out, 6 files read\n")
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.gt, ignore=INPUTS)

    def test_json_types_and_names(self):
        self.assertEqual(self.run_gen()[0], 0)
        pack = self.read("packs", "ex-device", "pack.def")
        lines = {tuple(ln.split()[1:]) for ln in pack.splitlines() if ln.strip().startswith(("field", "group"))}
        for loc, tr in (("ex-device:device.serial", "string"), ("ex-device:device.load", "int"),
                        ("ex-device:device.ratio", "string"), ("ex-device:device.mode", "string"),
                        ("ex-device:device.kind", "string"), ("ex-device:device.peer-serial", "string"),
                        ("ex-device:device.volts", "int"), ("ex-device:device.battery-pct", "int"),
                        ("ex-device:device.ex-ext:hertz", "int"), ("ex-device:device.frames", "int")):
            self.assertTrue(any(l[1:] == (loc, tr) for l in lines), (loc, tr))
        for loc, tr in (("name", "string"), ("config.mtu", "int"), ("config.enabled", "bool"),
                        ("state.counters.in-octets", "string"), ("state.counters.drops", "int"),
                        ("state.ex-ext:optics.power", "string"), ("state.ex-ext:optics.lanes", "int")):
            self.assertTrue(any(l[1:] == (loc, tr) for l in lines), (loc, tr))
        self.assertIn("field  time_ms  ex-device:device.clock.now  iso8601_ms\n", pack)
        for absent in ("maintenance", "extra", "added", "more", "force", "reboot"):
            self.assertNotIn(absent, pack)
        md = self.read("packs", "ex-device", "pack.md")
        self.assertIn("| `ex-device:device.maintenance` | type empty", md)
        self.assertIn("| `ex-device:device.vlan` | union of members with several JSON types (integer/string) |", md)
        self.assertIn("| `ex-device:device.extra` | anydata: its members are data |", md)
        self.assertIn("- `ex-ext`: `/exd:device/exo:added`", md)
        self.assertIn("- `ex-ext`: `/exd:reboot/exd:input`", md)

    def test_provenance(self):
        self.assertEqual(self.run_gen()[0], 0)
        prov = self.read("packs", "ex-device", "PROVENANCE.md")
        self.assertTrue(prov.startswith("SPDX licence of the sources: BSD-2-Clause."))
        self.assertIn("| `models` | `ex-device` | - |", prov)
        self.assertIn("| `models` | `ex-device-sub` | - |", prov)
        self.assertIn("Redistribution is permitted under the Simplified BSD License (an example statement).", prov)

    def test_check_after_a_run_is_ok_and_writes_nothing(self):
        self.assertEqual(self.run_gen()[0], 0)
        before = support.tree(self.work)
        status, out, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        self.assertEqual(out, "")
        self.assertEqual(support.tree(self.work), before)

    def test_check_without_output_reports_and_creates_nothing(self):
        before = support.tree(self.work)
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/ex-device/pack.def is missing", err)
        self.assertEqual(support.tree(self.work), before)

    def test_unknown_top_and_grouping_are_refused(self):
        status, _, err = self.run_gen(top="nothing")
        self.assertEqual(status, 1)
        self.assertIn("module ex-device has no top-level container or list nothing", err)
        path = os.path.join(self.src, "models", "ex-device-sub.yang")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("leaf frames { type uint32; }", "uses no-such-grouping;"))
        status, _, err = self.run_gen()
        self.assertEqual(status, 1)
        self.assertIn("models/ex-device-sub.yang:6: grouping no-such-grouping is not defined", err)

    def test_statement_grammar(self):
        top = Y.parse('module m {\n  description\n    "one\n     two  \n     three" + \'!\';\n'
                      '  leaf a { type string; } // c\n  /* b */ leaf "b" { type int8; }\n}\n', "t.yang")
        self.assertEqual(top.find("description").arg, "one\ntwo\nthree!")
        self.assertEqual([s.arg for s in top.find_all("leaf")], ["a", "b"])
        for bad, why in (('module m { leaf a { type string; }', "a block that does not end"),
                         ('module m { leaf "a" + b; }', "`+` joins quoted strings only"),
                         ('module m { description "x\\q"; }', "the escape \\q"),
                         ('container c { }', "not a module or submodule")):
            with self.assertRaises(Y.YangError) as cm:
                Y.parse(bad, "t.yang")
            self.assertIn(why, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
