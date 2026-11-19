"""Tests of tools/gen/sds-run.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_sds_run*.py'

fixtures/sds-run/input/sources/sds is a synthetic stand-in for a checkout of
spacedatastandards.org, written for these tests: a LICENSE, a NOTICE and one
standard `TST` (`lib/fbjson/TST/main.fb.schema.json`, draft 2019-09 with
`x-flatbuffer-*` annotations, an enum, an array and a union). The test makes it a
git checkout with a fixed author, committer and date, so its commit is the same on
every run, and writes its SHA-256 manifest. fixtures/sds-run/input/checkout is the
part of a goat-transformers checkout the run reads. fixtures/sds-run/expected is
the tree the run writes into the checkout.
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

import support

S = support.load_script("sds-run.py")
FIXTURE = os.path.join(support.FIXTURES, "sds-run")
INPUTS = ("model/core.def", "model/track.def", "tools/gen/notes/sds.md")
FILES = ("LICENSE", "NOTICE", "lib/fbjson/TST/main.fb.schema.json")
GIT_ENV = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture", "GIT_COMMITTER_NAME": "fixture",
           "GIT_COMMITTER_EMAIL": "fixture", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
           "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1"}


def git(repo, *args):
    done = subprocess.run(["git", "-C", repo] + list(args), env=dict(os.environ, **GIT_ENV),
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class Workspace(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="sds-run-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = support.copy_tree(os.path.join(FIXTURE, "input", "sources", "sds"),
                                     os.path.join(self.work, "sds"))
        self.gt = support.copy_tree(os.path.join(FIXTURE, "input", "checkout"), os.path.join(self.work, "checkout"))
        git(self.src, "init", "-q", "-b", "main")
        git(self.src, "add", "-A")
        git(self.src, "commit", "-q", "-m", "fixture")
        self.commit = git(self.src, "rev-parse", "HEAD")
        self.manifest = os.path.join(self.work, "sds-sha256.txt")
        self.write_manifest()
        saved = (S.COMMIT, S.UID, S.POSITION, S.CROSS, S.SKIPPED)
        self.addCleanup(self.restore, saved)
        S.COMMIT = self.commit
        S.UID = {"TST": "ID"}
        S.POSITION = {}
        S.CROSS = set()
        S.SKIPPED = {}

    def write_manifest(self, override=None):
        with open(self.manifest, "w", encoding="utf-8") as fh:
            for rel in FILES:
                h = (override or {}).get(rel) or sha(os.path.join(self.src, rel))
                fh.write("%s  %s\n" % (h, rel))

    @staticmethod
    def restore(saved):
        S.COMMIT, S.UID, S.POSITION, S.CROSS, S.SKIPPED = saved

    def run_sds(self, *extra):
        return support.run_main(S.main, list(extra) + ["--manifest", self.manifest, self.src, self.gt])


class SdsRunTest(Workspace):
    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_sds()
        self.assertEqual((status, err), (0, ""))
        self.assertEqual(out, "sds-tst\n")
        # the commit is fixed by the fixture's git settings; the expected tree names it
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.gt, ignore=INPUTS)

    def test_check_after_a_run_is_ok_and_writes_nothing(self):
        self.assertEqual(self.run_sds()[0], 0)
        before = support.tree(self.work)
        status, out, err = self.run_sds("--check")
        self.assertEqual(status, 0, err)
        self.assertEqual(out, "")
        self.assertIn("jsonschema2pack: --check: ok", err)
        self.assertIn("sds-run (PROVENANCE.md): --check: ok, 1 file(s)", err)
        self.assertEqual(support.tree(self.work), before)

    def test_check_names_a_changed_provenance_and_a_changed_pack(self):
        self.assertEqual(self.run_sds()[0], 0)
        for rel in ("packs/sds-tst/PROVENANCE.md", "packs/sds-tst/pack.def"):
            with open(os.path.join(self.gt, rel), "a", encoding="utf-8") as fh:
                fh.write("# changed\n")
        before = support.tree(self.work)
        status, _, err = self.run_sds("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/sds-tst/PROVENANCE.md differs", err)
        self.assertIn("packs/sds-tst/pack.def differs", err)
        self.assertEqual(support.tree(self.work), before)

    def test_check_on_a_checkout_without_output_creates_nothing(self):
        before = support.tree(self.work)
        status, _, err = self.run_sds("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/sds-tst/pack.def is missing", err)
        self.assertIn("packs/sds-tst/PROVENANCE.md is missing", err)
        self.assertEqual(support.tree(self.work), before)

    def test_a_source_at_another_commit_is_refused(self):
        S.COMMIT = "0" * 40
        status, _, err = self.run_sds()
        self.assertEqual(status, 1)
        self.assertIn("is at %s, not %s" % (self.commit, "0" * 40), err)

    def test_only_runs_the_named_standards_and_refuses_an_unknown_name(self):
        status, out, err = self.run_sds("--only", "TST")
        self.assertEqual((status, out, err), (0, "sds-tst\n", ""))
        before = support.tree(self.gt)
        status, _, err = self.run_sds("--only", "TST,NOPE")
        self.assertEqual(status, 2)
        self.assertIn("--only names a standard the manifest does not list or SKIPPED holds: NOPE", err)
        self.assertEqual(support.tree(self.gt), before)

    def test_a_skipped_standard_is_not_written(self):
        S.SKIPPED = {"TST": "skipped for the test"}
        before = support.tree(self.gt)
        status, out, err = self.run_sds()
        self.assertEqual((status, out), (0, ""), err)
        self.assertEqual(support.tree(self.gt), before)

    def test_a_file_whose_sha256_differs_is_refused_before_anything_is_written(self):
        self.write_manifest({"lib/fbjson/TST/main.fb.schema.json": "0" * 64})
        before = support.tree(self.gt)
        status, _, err = self.run_sds()
        self.assertEqual(status, 1)
        self.assertIn("lib/fbjson/TST/main.fb.schema.json: missing or SHA-256 is not " + "0" * 64, err)
        self.assertEqual(support.tree(self.gt), before)


if __name__ == "__main__":
    unittest.main()
