"""Tests for tools/vector-members.py. Standard library only:

    python3 -I -m unittest discover -s tools/tests
"""
import json
import unittest

from support import REPO, TempTree, load_tool, run_main

vm = load_tool("vector-members.py")

SPEC = """# Vector format

## File

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | x |
| `from` | yes | x |
| `to` | yes | x |
| `input` | yes | x |
| `expect` | unless | x |
| `source` | optional | x |
| `reference` | optional | x |

## What the engine checks per vector

| `notamember` | x | a table of another section is not read |

## Load vectors

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | x |
| `models` | yes | x |
| `pack` | yes | x |

## Capability vectors

| `name` | yes | x |
| `grade` | yes | x |

## Tool vectors

| `name` | yes | x |
| `args` | yes | x |
| `exit` | yes | x |
"""

GOOD = {"name": "a", "from": "f", "to": "f", "input": "x", "expect": "x", "source": "synthetic"}


class VectorMembers(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        self.tree.write("spec/vector-format.md", SPEC)
        self.tree.write("packs/f/vectors/01.json", json.dumps(GOOD))
        self.tree.write("packs/conformance/load-vectors/01.json", json.dumps({"name": "l", "models": [], "pack": ""}))
        self.tree.write("packs/conformance/tool-vectors/001.json", json.dumps({"name": "t", "args": [], "exit": 0}))

    def run_tool(self):
        return run_main(vm.main, root=self.tree.root)

    def test_members_the_spec_lists_pass(self):
        code, out, err = self.run_tool()
        self.assertEqual(code, 0, err)
        self.assertIn("1 conversion, 1 load, 0 capability, 1 tool", out)

    def test_a_note_member_fails_with_the_hint(self):
        self.tree.write("packs/f/vectors/sub/02.json", json.dumps(dict(GOOD, note="why")))
        code, _, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("packs/f/vectors/sub/02.json: member `note`", err)
        self.assertIn("`source` or `reference`", err)

    def test_each_kind_has_its_own_table(self):
        # `expect` is a conversion member, not a load member; `notamember` is in no table
        self.tree.write("packs/conformance/load-vectors/02.json", json.dumps({"name": "l", "models": [], "pack": "", "expect": "x"}))
        self.tree.write("packs/f/vectors/03.json", json.dumps(dict(GOOD, notamember=1)))
        code, _, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("load-vectors/02.json: member `expect` is not one spec/vector-format.md defines for a load vector", err)
        self.assertIn("packs/f/vectors/03.json: member `notamember`", err)
        self.assertNotIn("(text for people", err.split("load-vectors/02.json")[1].split("\n")[0])

    def test_not_an_object_or_not_json(self):
        self.tree.write("packs/f/vectors/04.json", "[1, 2]")
        self.tree.write("packs/f/vectors/05.json", "{")
        code, _, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("04.json: a conversion vector is one JSON object", err)
        self.assertIn("05.json: not readable as JSON", err)

    def test_a_missing_section_stops_it(self):
        self.tree.write("spec/vector-format.md", SPEC.replace("## Tool vectors", "## Something else"))
        code, _, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("no section '## Tool vectors'", err)


class Repository(unittest.TestCase):
    def test_every_vector_of_the_repository(self):
        code, _, err = run_main(vm.main, root=REPO)
        self.assertEqual(code, 0, err)


if __name__ == "__main__":
    unittest.main()
