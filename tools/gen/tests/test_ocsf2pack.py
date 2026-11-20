"""Tests of tools/gen/ocsf2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_ocsf2pack*.py'

fixtures/ocsf2pack/input/source is a synthetic stand-in for ocsf/ocsf-schema, written for
these tests: a dictionary with base types, an array and a json_t attribute; one category;
objects with `extends` and a profile `$include`; a base event that includes a profile; a
category class; and two event classes, one of which takes `device` out of the profile with
`profile: null`. fixtures/ocsf2pack/input/checkout is the part of a checkout the run reads.
fixtures/ocsf2pack/expected is the tree the run writes.
"""
import json
import os
import shutil
import tempfile
import unittest

import support

O = support.load_script("ocsf2pack.py")
FIXTURE = os.path.join(support.FIXTURES, "ocsf2pack")
INPUTS = ("model/core.def", "model/track.def", "tools/gen/notes/ocsf.md", "packs/geojson/pack.def",
          "packs/geojson/vectors/01-geojson-to-cot.json")


class Workspace(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="ocsf2pack-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = support.copy_tree(os.path.join(FIXTURE, "input", "source"), os.path.join(self.work, "src"))
        self.gt = support.copy_tree(os.path.join(FIXTURE, "input", "checkout"), os.path.join(self.work, "gt"))
        saved = O.CROSS
        self.addCleanup(setattr, O, "CROSS", saved)
        O.CROSS = ("placed",)

    def run_gen(self, *extra):
        return support.run_main(O.main, ["--no-commit-check"] + list(extra) + [self.src, self.gt])

    def read(self, *parts):
        with open(os.path.join(self.gt, *parts), encoding="utf-8") as fh:
            return fh.read()


class Ocsf2packTest(Workspace):
    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_gen()
        self.assertEqual((status, err), (0, ""))
        self.assertEqual(out, "ocsf-placed\nocsf-plain\n")
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.gt, ignore=INPUTS)

    def test_resolution(self):
        self.assertEqual(self.run_gen()[0], 0)
        plain = self.read("packs", "ocsf-plain", "pack.def")
        placed = self.read("packs", "ocsf-placed", "pack.def")
        # class_uid is the category's number times 1000 plus the class's
        self.assertIn("when    class_uid  7001\n", plain)
        self.assertIn("when    class_uid  7002\n", placed)
        self.assertIn("field  time_ms  time  int\n", plain)
        self.assertIn("field  uid  metadata.uid  string\n", plain)
        # the host profile's device and actor are left out, unless the class takes device out of it
        self.assertNotIn("device", plain)
        self.assertNotIn(" actor ", plain)
        self.assertIn("field  lat  device.location.lat  float\n", placed)
        self.assertIn("field  lon  device.location.long  float\n", placed)
        self.assertIn("device.uid", placed)          # through device extends _entity
        self.assertNotIn("labels", placed)            # a profile inside an object
        md = self.read("packs", "ocsf-plain", "pack.md")
        self.assertIn("| `device` | `host` |", md)
        self.assertIn("- `labels`: `metadata.labels`", md)
        prov = self.read("packs", "ocsf-placed", "PROVENANCE.md")
        for f in ("dictionary.json", "categories.json", "events/base_event.json", "events/cat/cat.json",
                  "events/cat/placed.json", "objects/device.json", "objects/_entity.json",
                  "profiles/host.json", "LICENSE", "NOTICE"):
            self.assertIn("| `%s` |" % f, prov)
        v = json.loads(self.read("packs", "geojson", "vectors", "gen-geojson-to-ocsf-placed.json"))
        self.assertIn('"location":{"lat":30.0090027,"long":-85.9578182}', v["expect"])

    def test_check_after_a_run_is_ok_and_writes_nothing(self):
        self.assertEqual(self.run_gen()[0], 0)
        before = support.tree(self.work)
        status, out, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        self.assertEqual(out, "")
        self.assertEqual(support.tree(self.work), before)

    def test_check_on_a_checkout_without_output_reports_and_creates_nothing(self):
        before = support.tree(self.work)
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/ocsf-plain/pack.def is missing", err)
        self.assertIn("packs/ocsf-plain/PROVENANCE.md is missing", err)
        self.assertEqual(support.tree(self.work), before)

    def test_only_and_refusals(self):
        self.assertEqual(self.run_gen("--only", "plain")[1], "ocsf-plain\n")
        self.assertEqual(self.run_gen("--only", "nope")[0], 2)
        with open(os.path.join(self.src, "events", "cat", "plain.json"), "w") as fh:
            fh.write('{"uid": 1, "name": "plain", "extends": "missing", "attributes": {}}')
        status, _, err = self.run_gen()
        self.assertEqual(status, 1)
        self.assertIn("plain extends missing, which is not defined", err)

    def test_a_source_at_another_commit_is_refused(self):
        status, _, err = support.run_main(O.main, [self.src, self.gt])
        self.assertEqual(status, 1)
        self.assertIn("not %s (tag %s)" % (O.COMMIT, O.TAG), err)


if __name__ == "__main__":
    unittest.main()
