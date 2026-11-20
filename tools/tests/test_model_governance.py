"""Tests for tools/model-governance.py: a change to model/core.def or
model/track.def carries an ADR. Standard library only:

    python3 -I -m unittest discover -s tools/tests
"""
import os
import subprocess
import unittest
from unittest import mock

from support import REPO, TempTree, have_git, load_tool, run_main

gov = load_tool("model-governance.py")

INDEX = "# ADRs\n\n| ADR | Title |\n|---|---|\n| [0001](0001-first.md) | first |\n"
GOOD = """# ADR 0003: a new core key

Status: Proposed (2026-11-20)

## Changes

`model/core.def`: key `time_ns` added, int, ns.

## Context

x

## Consumers re-measured

| Project | Library commit | Result before | Result after | Differences |
|---|---|---|---|---|
| open-billie | abc1234 | 397 of 397 | 397 of 397 | none |

## Consequences

x
"""


@unittest.skipUnless(have_git(), "git is not installed")
class Change(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        env = mock.patch.dict(os.environ, self.tree.env, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.tree.write("model/core.def", "module core\n")
        self.tree.write("model/other.def", "module other\n")
        self.tree.write("docs/adr/INDEX.md", INDEX)
        self.tree.write("docs/adr/0001-first.md", "# ADR 0001\n\nStatus: Accepted\n")
        self.git("init", "-q", "-b", "main")
        self.commit("base")
        self.git("checkout", "-q", "-b", "change")

    def git(self, *args):
        subprocess.run(["git", "-C", self.tree.root, "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                       check=True, capture_output=True)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def run_check(self):
        return run_main(gov.main, "--base", "main", root=self.tree.root)

    def test_a_change_elsewhere_needs_nothing(self):
        self.tree.write("model/other.def", "module other\nkey x int - \"x\"\n")
        self.commit("other")
        self.assertEqual(self.run_check()[0], 0)

    def test_a_core_change_without_an_adr_fails(self):
        self.tree.write("model/core.def", "module core\nkey x int - \"x\"\n")
        self.commit("core")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("this change edits model/core.def, so it must add or change an ADR", err)

    def test_a_core_change_with_a_complete_adr_passes(self):
        self.tree.write("model/core.def", "module core\nkey x int - \"x\"\n")
        self.tree.write("docs/adr/0003-new-core-key.md", GOOD)
        self.tree.write("docs/adr/INDEX.md", INDEX + "| [0003](0003-new-core-key.md) | new |\n")
        self.commit("core and adr")
        self.assertEqual(self.run_check()[0], 0)

    def test_an_incomplete_adr_names_what_it_lacks(self):
        self.tree.write("model/core.def", "module core\nkey x int - \"x\"\n")
        self.tree.write("model/track.def", "module track\n")
        bad = GOOD.replace("| open-billie | abc1234 | 397 of 397 | 397 of 397 | none |\n",
                           "| <project> | <commit> | | | |\n")
        self.tree.write("docs/adr/0003-new-core-key.md", bad)
        self.commit("core, track and an incomplete adr")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("does not name model/track.def", err)
        self.assertIn("needs a table with a filled row", err)
        self.assertIn("0003-new-core-key.md is not listed in docs/adr/INDEX.md", err)


class Index(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        self.tree.write("docs/adr/INDEX.md", INDEX)
        self.tree.write("docs/adr/0001-first.md", "# ADR 0001\n\nStatus: Accepted\n")

    def test_index_rules(self):
        self.assertEqual(gov.check(self.tree.root), [])
        self.tree.write("docs/adr/0001-again.md", "# ADR\n")
        self.tree.write("docs/adr/Bad Name.md", "Status: x\n")
        problems = gov.check(self.tree.root)
        self.assertTrue(any("have the same number" in p for p in problems))
        self.assertTrue(any("0001-again.md has no 'Status:' line" in p for p in problems))
        self.assertTrue(any("0001-again.md is not listed" in p for p in problems))
        self.assertTrue(any("is not named NNNN-<name>.md" in p for p in problems))


class Repository(unittest.TestCase):
    def test_this_repository(self):
        self.assertEqual(gov.check(REPO), [])


if __name__ == "__main__":
    unittest.main()
