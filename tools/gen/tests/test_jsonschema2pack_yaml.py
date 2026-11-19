"""Tests of the YAML reader of tools/gen/jsonschema2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_jsonschema2pack*.py'

The documents are written for these tests in the style of the generated
`model.yaml` files of the Smart Data Models and of OpenAPI model files: block
mappings and sequences, plain, quoted and block scalars. Expected values follow
YAML 1.2 (core schema): only true/false are booleans.
"""
import support

import importlib.util
import os
import unittest

_spec = importlib.util.spec_from_file_location("jsonschema2pack", os.path.join(support.GEN, "jsonschema2pack.py"))
J = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(J)


class YamlReader(unittest.TestCase):
    def test_mapping_sequence_scalars(self):
        doc = J.yaml_load("a: 1\nb: x y\nc:\n  - p\n  - q: 2\n    r: 'it''s'\nd: [1, \"two\"]\ne: true\nf: no\n")
        self.assertEqual(doc, {"a": 1, "b": "x y", "c": ["p", {"q": 2, "r": "it's"}], "d": [1, "two"],
                               "e": True, "f": "no"})

    def test_quoted_scalar_over_several_lines(self):
        doc = J.yaml_load("m:\n  description: 'one line\n    and the next ''quoted''\n\n    after a blank'\n  type: string\n")
        self.assertEqual(doc, {"m": {"description": "one line and the next 'quoted'\nafter a blank",
                                     "type": "string"}})

    def test_double_quoted_over_two_lines(self):
        doc = J.yaml_load('k: "first\n  second"\nz: 1\n')
        self.assertEqual(doc, {"k": "first second", "z": 1})

    def test_plain_scalar_over_several_lines(self):
        doc = J.yaml_load("description:\n  The first part\n  and the second.\ntype: string\n")
        self.assertEqual(doc, {"description": "The first part and the second.", "type": "string"})

    def test_tab_inside_text_is_kept(self):
        doc = J.yaml_load("closes:\n  description: \" \\tThe closing hour\"\n")
        self.assertEqual(doc, {"closes": {"description": " \tThe closing hour"}})

    def test_block_scalars(self):
        doc = J.yaml_load("a: |-\n  line 1\n  line 2\nb: >\n  folded\n  text\n")
        self.assertEqual(doc, {"a": "line 1\nline 2", "b": "folded text\n"})


if __name__ == "__main__":
    unittest.main()
