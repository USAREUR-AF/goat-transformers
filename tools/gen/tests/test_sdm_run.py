"""Tests of tools/gen/sdm-run.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_sdm_run*.py'

fixtures/sdm-run/input/sources holds one synthetic subject repository
(`dataModel.Test`, one model `Thing`) written for these tests; the test makes it
a git checkout with a fixed author, committer and date, so its commit is the
same on every run. fixtures/sdm-run/input/checkout is the part of a
goat-transformers checkout the run reads (a model directory and the notes
file). The run table of sdm-run.py is replaced by one row for that model.
fixtures/sdm-run/expected is the tree the run writes into the checkout.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

import support

S = support.load_script("sdm-run.py")
FIXTURE = os.path.join(support.FIXTURES, "sdm-run")
INPUTS = ("model/core.def", "model/track.def", "tools/gen/notes/sdm.md")
GIT_ENV = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture", "GIT_COMMITTER_NAME": "fixture",
           "GIT_COMMITTER_EMAIL": "fixture", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
           "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1"}


def git(repo, *args):
    done = subprocess.run(["git", "-C", repo] + list(args), env=dict(os.environ, **GIT_ENV),
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


class Workspace(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="sdm-run-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = support.copy_tree(os.path.join(FIXTURE, "input", "sources"), os.path.join(self.work, "sources"))
        self.gt = support.copy_tree(os.path.join(FIXTURE, "input", "checkout"), os.path.join(self.work, "checkout"))
        repo = os.path.join(self.src, "dataModel.Test")
        git(repo, "init", "-q", "-b", "master")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "fixture")
        self.commit = git(repo, "rev-parse", "HEAD")
        saved = (S.COMMITS, S.MODELS, S.TIME_OBSERVED, S.EXTRA_MAPS, S.CROSS)
        self.addCleanup(self.restore, saved)
        S.COMMITS = {"dataModel.Test": self.commit}
        S.MODELS = [("dataModel.Test", "Thing", "model")]
        S.TIME_OBSERVED = {"Thing"}
        S.EXTRA_MAPS = {}
        S.CROSS = set()

    @staticmethod
    def restore(saved):
        S.COMMITS, S.MODELS, S.TIME_OBSERVED, S.EXTRA_MAPS, S.CROSS = saved

    def run_sdm(self, *extra):
        return support.run_main(S.main, list(extra) + [self.src, self.gt])


class SdmRunTest(Workspace):
    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_sdm()
        self.assertEqual((status, err), (0, ""))
        self.assertEqual(out, "sdm-test-thing\n")
        # the commit is fixed by the fixture's git settings; the expected tree names it
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.gt, ignore=INPUTS)

    def test_check_after_a_run_is_ok_and_writes_nothing(self):
        self.assertEqual(self.run_sdm()[0], 0)
        before = support.tree(self.work)
        status, out, err = self.run_sdm("--check")
        self.assertEqual(status, 0, err)
        self.assertEqual(out, "")
        self.assertIn("jsonschema2pack: --check: ok", err)
        self.assertIn("sdm-run (PROVENANCE.md): --check: ok, 1 file(s)", err)
        self.assertEqual(support.tree(self.work), before)

    def test_check_names_a_changed_provenance_and_a_changed_pack(self):
        self.assertEqual(self.run_sdm()[0], 0)
        for rel in ("packs/sdm-test-thing/PROVENANCE.md", "packs/sdm-test-thing/pack.def"):
            with open(os.path.join(self.gt, rel), "a", encoding="utf-8") as fh:
                fh.write("# changed\n")
        before = support.tree(self.work)
        status, _, err = self.run_sdm("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/sdm-test-thing/PROVENANCE.md differs", err)
        self.assertIn("packs/sdm-test-thing/pack.def differs", err)
        self.assertEqual(support.tree(self.work), before)

    def test_check_on_a_checkout_without_output_creates_nothing(self):
        before = support.tree(self.work)
        status, _, err = self.run_sdm("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/sdm-test-thing/pack.def is missing", err)
        self.assertIn("packs/sdm-test-thing/PROVENANCE.md is missing", err)
        self.assertEqual(support.tree(self.work), before)

    def test_a_source_at_another_commit_is_refused(self):
        S.COMMITS = {"dataModel.Test": "0" * 40}
        status, _, err = self.run_sdm()
        self.assertEqual(status, 1)
        self.assertIn("dataModel.Test is at %s, not %s" % (self.commit, "0" * 40), err)


if __name__ == "__main__":
    unittest.main()
