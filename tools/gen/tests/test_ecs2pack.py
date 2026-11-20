"""Tests of tools/gen/ecs2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_ecs2pack*.py'

fixtures/ecs2pack/input/source is a synthetic stand-in for elastic/ecs, written for these
tests: an `ecs_flat.yml` in the layout PyYAML writes (multi-line quoted descriptions, an
`otel` list, `normalize` lists) with a date, a keyword, a long, a geo_point, an array of
ip, a scaled_float, a free object, a nested field with children, and a boolean.
fixtures/ecs2pack/expected is the tree the run writes into the checkout.
"""
import json
import os
import shutil
import tempfile
import unittest

import support

E = support.load_script("ecs2pack.py")
FIXTURE = os.path.join(support.FIXTURES, "ecs2pack")
INPUTS = ("model/core.def", "model/track.def", "tools/gen/notes/ecs.md")


class EcsTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="ecs2pack-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = support.copy_tree(os.path.join(FIXTURE, "input", "source"), os.path.join(self.work, "src"))
        self.gt = support.copy_tree(os.path.join(FIXTURE, "input", "checkout"), os.path.join(self.work, "gt"))

    def run_gen(self, *extra):
        return support.run_main(E.main, ["--no-commit-check", "--no-cross"] + list(extra) + [self.src, self.gt])

    def read(self, *parts):
        with open(os.path.join(self.gt, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_gen()
        self.assertEqual((status, err), (0, ""))
        self.assertEqual(out, "ecs-event\n")
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.gt, ignore=INPUTS)

    def test_reading_and_types(self):
        fields = E.read_flat(os.path.join(self.src, "generated", "ecs", "ecs_flat.yml"))
        self.assertEqual(list(fields), ["@timestamp", "event.id", "event.sequence", "host.geo.location",
                                        "host.ip", "host.uptime_ratio", "labels", "threat.enrichments",
                                        "threat.enrichments.indicator.name",
                                        "threat.enrichments.matched.occurred", "user.changes.active"])
        self.assertEqual(fields["host.ip"]["normalize"], ["array"])
        self.assertEqual(fields["@timestamp"]["normalize"], [])
        self.assertEqual(self.run_gen()[0], 0)
        pack = self.read("packs", "ecs-event", "pack.def")
        for line in ("field  time_ms  @timestamp  iso8601_ms\n", "field  uid  event.id  string\n",
                     "field  lat  host.geo.location.lat  float\n", "field  lon  host.geo.location.lon  float\n",
                     "field  ecsevent.event_sequence  event.sequence  int\n",
                     "group  ecsevent.host_ip  host.ip\n",
                     "field  ecsevent.host_uptime_ratio  host.uptime_ratio  float\n",
                     "group  ecsevent.threat_enrichments  threat.enrichments\n",
                     "field  ecsevent.user_changes_active  user.changes.active  bool\n"):
            self.assertIn(line, pack)
        self.assertNotIn("labels", pack)
        md = self.read("packs", "ecs-event", "pack.md")
        self.assertIn("| `event` | `labels` | object whose member names are data", md)
        self.assertNotIn("written for the tests", md.split("## Mapped to shared keys")[1].split("## Notes")[0])

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
        self.assertIn("packs/ecs-event/pack.def is missing", err)
        self.assertIn("packs/ecs-event/PROVENANCE.md is missing", err)
        self.assertEqual(support.tree(self.work), before)

    def test_refusals(self):
        flat = os.path.join(self.src, "generated", "ecs", "ecs_flat.yml")
        with open(flat, "a", encoding="utf-8") as fh:
            fh.write("odd.field:\n  normalize: []\n  type: histogram\n")
        status, _, err = self.run_gen()
        self.assertEqual(status, 1)
        self.assertIn("type histogram is not one this program knows", err)
        with open(flat, "w", encoding="utf-8") as fh:
            fh.write("a:\n  normalize: [array]\n  type: keyword\n")
        status, _, err = self.run_gen()
        self.assertEqual(status, 1)
        self.assertIn("normalize in a form this reader does not take", err)
        status, _, err = support.run_main(E.main, [self.src, self.gt])
        self.assertEqual(status, 1)
        self.assertIn("not %s (tag %s)" % (E.COMMIT, E.TAG), err)


if __name__ == "__main__":
    unittest.main()
