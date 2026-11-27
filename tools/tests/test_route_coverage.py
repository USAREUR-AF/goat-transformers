"""tools/route-coverage.py: a route drops no key without a written reason."""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("route_coverage", os.path.join(HERE, "..", "route-coverage.py"))
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)


def report(src, dst):
    """A source that maps a, b, m.x and m.y; a target that maps a and c."""
    if src == dst:
        return ["a", "c"], []
    return ["a"], ["b", "m.x", "m.y"]


def check(*lines):
    return rc.check("\n".join("\t".join(l) for l in lines), report)[0]


class RouteCoverage(unittest.TestCase):
    def test_every_dropped_key_listed_passes(self):
        self.assertEqual(check(("s", "t", "b", "derived:c", ""), ("s", "t", "m.*", "not-carried", "the target has no place for it")), [])

    def test_a_dropped_key_not_listed_fails(self):
        (problem,) = check(("s", "t", "m.*", "not-carried", "the target has no place for it"))
        self.assertIn("drops b", problem)

    def test_a_listed_key_the_route_does_not_drop_fails(self):
        got = check(("s", "t", "b", "derived:c", ""), ("s", "t", "m.*", "not-carried", "the target has no place for it"),
                    ("s", "t", "a", "not-carried", "the target has no place for it"))
        self.assertEqual(len(got), 1)
        self.assertIn("does not drop", got[0])

    def test_derived_names_a_key_the_target_maps(self):
        got = check(("s", "t", "b", "derived:z", ""), ("s", "t", "m.*", "not-carried", "the target has no place for it"))
        self.assertEqual(len(got), 1)
        self.assertIn("z is not a key", got[0])

    def test_not_carried_needs_a_reason_and_states_are_closed(self):
        got = check(("s", "t", "b", "not-carried", ""), ("s", "t", "m.*", "later", "x"))
        self.assertEqual(len(got), 2)

    def test_the_repository_table_passes(self):
        with open(rc.TABLE, encoding="utf-8") as handle:
            problems, count = rc.check(handle.read())
        self.assertEqual(problems, [])
        self.assertGreaterEqual(count, 6)


if __name__ == "__main__":
    unittest.main()
