"""Tests for tools/time-quality-guard.py: a pack never invents time quality
(spec 0.32). Standard library only."""
import importlib.machinery
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def load():
    path = os.path.join(REPO, "tools", "time-quality-guard.py")
    loader = importlib.machinery.SourceFileLoader("time_quality_guard", path)
    spec = importlib.util.spec_from_loader("time_quality_guard", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


G = load()
HEAD = 'format t\nversion 0.1.0\ndistribution public\nsource "s"\n'


class Guard(unittest.TestCase):
    def test_a_default_is_refused_bare_and_prefixed(self):
        for key in ("time_utc_state", "core.time_anchor", "time_state"):
            out = G.check_pack(HEAD + "wire json\nfield %s a string\ndefault %s x\n" % (key, key), "p")
            self.assertEqual(len(out), 1, out)
            self.assertIn("default on " + key, out[0])

    def test_an_absent_option_is_refused(self):
        out = G.check_pack(HEAD + "wire json\nfield time_attested a int absent 0\n", "p")
        self.assertEqual(len(out), 1, out)

    def test_an_unconditional_bits_field_is_refused_and_optional_or_gated_is_not(self):
        bits = HEAD + "wire bits\n"
        self.assertEqual(len(G.check_pack(bits + "field time_attested 0:0:1 uint\n", "p")), 1)
        self.assertEqual(G.check_pack(bits + "field time_attested 0:0:1 uint optional\n", "p"), [])
        gated = bits + "layout sequential\nif 0:0:1 1\n  field time_anchor_age_ms 8 uint\nend\n"
        self.assertEqual(G.check_pack(gated, "p"), [])

    def test_a_derive_of_a_time_key_is_refused_in_any_module(self):
        module = 'module m\nversion 0.1.0\ndistribution public\nsource "s"\nderive time_attested present m.x\n'
        self.assertEqual(len(G.check_module(module, "m")), 1)
        self.assertEqual(G.check_module(module.replace("time_attested", "m.y"), "m"), [])

    def test_other_keys_and_plain_mappings_pass(self):
        self.assertEqual(G.check_pack(HEAD + "wire json\nfield time_utc_state a string\ndefault lat 0\n", "p"), [])

    def test_the_repository_passes(self):
        self.assertEqual(G.run(REPO), [])


if __name__ == "__main__":
    unittest.main()
