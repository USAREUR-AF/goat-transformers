"""Tests of tools/gen/kindorder.py, which makes every top-level kind of a pack
reachable on encode (engine-spec, Message kinds, Encode step 2).

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_kindorder*.py'
"""
import support  # noqa: F401  (puts tools/gen on the path)

import unittest

import kindorder

HEAD = "format x\nversion 1\nwire bits\nlayout sequential\nbit_order msb\nuses p\n\n"


class KindOrder(unittest.TestCase):
    def test_a_requires_less_kind_that_hides_a_later_kind_is_fixed(self):
        """A kind with no requires before a kind with a key of its own: the
        later kind gains requires on that key, or the pair is reordered."""
        text = HEAD + ("kind a\nwhen 8 1\nfield p.n 8 uint\n\n"
                       "kind b\nwhen 8 2\nfield p.n 8 uint\nfield p.m 8 uint\n")
        out = kindorder.order(text)
        self.assertNotEqual(out, text)
        self.assertIn("requires  p.m", out)

    def test_kinds_chosen_by_when_as_are_left_as_they_are(self):
        """A `when ... as <key>` that is not optional is an implicit requires
        term (engine-spec 0.30 Encode, 0.94 ruling 1), so no kind of such a
        pack always qualifies and nothing is hidden: the pack is unchanged,
        with no requires added beside the `as`."""
        text = HEAD + ("kind a\nwhen 16 13 as p.type\nwhen 16 1 as p.subtype\nfield p.n 8 uint\n\n"
                       "kind b\nwhen 16 13 as p.type\nwhen 16 2 as p.subtype\nfield p.n 8 uint\nfield p.m 8 uint\n")
        self.assertEqual(kindorder.order(text), text)

    def test_an_optional_as_is_not_a_term(self):
        """`when ... as <key> optional` (0.52) qualifies when the key is not
        held, so such a kind still hides the kinds after it."""
        text = HEAD + ("kind a\nwhen 8 1 as p.code optional\nfield p.n 8 uint\n\n"
                       "kind b\nwhen 8 2\nfield p.n 8 uint\nfield p.m 8 uint\n")
        self.assertNotEqual(kindorder.order(text), text)

    def test_order_is_a_fixed_point(self):
        text = HEAD + ("kind a\nwhen 8 1\nfield p.n 8 uint\n\n"
                       "kind b\nwhen 8 2\nfield p.n 8 uint\nfield p.m 8 uint\n")
        once = kindorder.order(text)
        self.assertEqual(kindorder.order(once), once)


if __name__ == "__main__":
    unittest.main()
