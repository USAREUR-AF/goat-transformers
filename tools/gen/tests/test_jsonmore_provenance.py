"""Tests of tools/gen/jsonmore-provenance.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_jsonmore_provenance*.py'

The source checkout is written by the test (synthetic): a LICENSE and one GOFS-like schema,
made a git repository with a fixed author and date, so its commit is the same on every run.
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

import support

P = support.load_script("jsonmore-provenance.py")
GIT_ENV = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture", "GIT_COMMITTER_NAME": "fixture",
           "GIT_COMMITTER_EMAIL": "fixture", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
           "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1"}


class ProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="jsonmore-prov-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = os.path.join(self.work, "src")
        os.makedirs(os.path.join(self.src, "schema"))
        with open(os.path.join(self.src, "LICENSE"), "w") as fh:
            fh.write("Test license, line one\nline two\nline three\nline four\n")
        with open(os.path.join(self.src, "schema", "a_b.json"), "w") as fh:
            fh.write('{"type": "object"}\n')
        env = dict(os.environ, **GIT_ENV)
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "fixture"]):
            subprocess.run(["git", "-C", self.src] + args, env=env, check=True, capture_output=True)
        self.commit = subprocess.run(["git", "-C", self.src, "rev-parse", "HEAD"], capture_output=True,
                                     text=True, check=True).stdout.strip()
        self.gt = os.path.join(self.work, "gt")
        os.makedirs(self.gt)

    def test_writes_then_checks(self):
        status, _, err = support.run_main(P.main, ["gofs", self.src, self.gt])
        self.assertEqual(status, 0, err)
        with open(os.path.join(self.gt, "packs", "gofs-a-b", "PROVENANCE.md"), encoding="utf-8") as fh:
            text = fh.read()
        sha = hashlib.sha256(b'{"type": "object"}\n').hexdigest()
        self.assertIn("| `schema/a_b.json` | `%s` |" % sha, text)
        self.assertIn("at commit `%s`" % self.commit, text)
        self.assertIn("> Test license, line one\n> line two\n> line three\n\n", text)
        self.assertNotIn("line four", text)
        before = support.tree(self.gt)
        status, _, err = support.run_main(P.main, ["gofs", "--check", self.src, self.gt])
        self.assertEqual(status, 0, err)
        self.assertEqual(support.tree(self.gt), before)

    def test_check_names_a_missing_file(self):
        status, _, err = support.run_main(P.main, ["gofs", "--check", self.src, self.gt])
        self.assertEqual(status, 1)
        self.assertIn("packs/gofs-a-b/PROVENANCE.md is missing", err)


if __name__ == "__main__":
    unittest.main()
