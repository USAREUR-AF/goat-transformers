"""Tests for tools/boundary-gate (docs/boundary.md). Standard library only:

    python3 -I -m unittest discover -s tools/tests

Every test builds a tree in a temporary directory and runs the gate on it. A
tree is a plain directory, where the gate reads every file, or a git checkout,
where it reads the files git would commit; the two ways of finding files are
tested on their own, and one test fires every check on a checkout.

This file is read by the gate when the gate checks the repository, so nothing
here is written as the text the gate refuses. Every marking, path and address
is put together from pieces by `j`, and every needle is an invented word.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import unittest
from unittest import mock

from support import REPO, TempTree, have_git, load_tool, run_main

gate = load_tool("boundary-gate")

FINDING = re.compile(r"^boundary-gate: (?P<check>[a-z]+) +(?P<where>.+?): (?P<message>.+)$")
WAIVED_SUMMARY = re.compile(r"^boundary-gate: \d+ needle hits waived ")

MODULE = 'module core\ndistribution public\nsource "an invented public document"\nkey uid string - "identifier"\n'
PACK = 'format sample\ndistribution public\nsource "an invented public document"\nwire json\nfield uid id string\n'


def j(*pieces):
    """One string from pieces, so that the whole never stands in this file."""
    return "".join(pieces)


# (what the gate calls it, a text that carries it, a near miss that does not)
MARKINGS = [
    ("restricted distribution statement", j("Distri", "bution State", "ment D"), j("Distri", "bution State", "ment A")),
    ("restricted distribution statement", j("distri", "bution state", "ment: c"), j("distri", "bution state", "ment described")),
    ("controlled-unclassified banner", j("marked C", "UI here"), j("a cir", "cuit, and the name C", "UI_Banner")),
    ("arms-regulation marking", j("under IT", "AR rules"), "military guitar"),
    ("export-control marking", j("Export", "-", "Controlled"), "the export of controlled goods"),
    ("export-control warning", j("Arms Export", " Control", " Act"), j("an arms export", " control", " list")),
    ("release marking", j("(NO", "FORN)"), j("no", "fornication")),
    ("handling marking", j("FO", "UO"), j("fo", "uoz")),
    ("proprietary banner", j("Proprietary", " ", "Information"), "proprietary formats and public information"),
    ("proprietary banner", j("Company", " ", "Confidential"), "the company keeps it confidential"),
]

# The same, for the hygiene check.
HYGIENE = [
    ("local absolute path", j("/Us", "ers/", "someone/file"), "the Users/ directory"),
    ("local absolute path", j("/ho", "me/", "someone/file"), j("under /ho", "me/ there is one directory per person")),
    ("private organization name", j("Desert", "GOAT"), "a desert goat"),
    ("email address", j("a.person", "@", "example.org"), "@decorator and user@host"),
]


class GateCase(unittest.TestCase):
    """A valid tree of one module and one pack, and the gate run on it."""

    git = False

    def setUp(self):
        if self.git and not have_git():
            self.skipTest("git is not installed")
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        env = mock.patch.dict(os.environ, self.tree.env, clear=True)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(gate.GEN_SOURCES_ENV, None)  # the waiver's source directories, if the caller has any
        if self.git:
            self.tree.git("init", "-q")
        self.tree.write("model/core.def", MODULE)
        self.tree.write("packs/sample/pack.def", PACK)

    def needles(self, *lines):
        """A needle file beside the tree. -> the arguments that name it"""
        return ["--needles", self.tree.write_beside("needles.txt", "".join(line + "\n" for line in lines))]

    def run_gate(self, *args):
        """-> (exit status, [(check, where, message)], every line printed).
        The waived hits are left in `self.waived` as (where, message), and the
        summary line of the waiver in `self.waived_summary`."""
        code, out, _ = run_main(gate.main, "--root", self.tree.root, *args)
        lines = out.splitlines()
        body = [line for line in lines[:-1] if not WAIVED_SUMMARY.match(line)]
        self.waived_summary = [line for line in lines[:-1] if WAIVED_SUMMARY.match(line)]
        rows = [m.group("check", "where", "message") for m in map(FINDING.match, body)]
        self.waived = [(where, message) for check, where, message in rows if check == "waived"]
        found = [row for row in rows if row[0] != "waived"]
        return code, found, lines

    def assert_ok(self, *args):
        code, found, lines = self.run_gate(*args)
        self.assertEqual((code, found), (0, []), lines)
        self.assertTrue(lines[-1].startswith("boundary-gate: ok, "), lines)

    def assert_findings(self, expected, *args):
        """The gate fails with exactly `expected`: (check, where) pairs."""
        code, found, lines = self.run_gate(*args)
        self.assertEqual(sorted((check, where) for check, where, _ in found), sorted(expected), lines)
        self.assertEqual(code, 1)
        return found


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------

class Checks(GateCase):
    def test_valid_tree_passes_and_says_what_it_read(self):
        code, _, lines = self.run_gate()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["boundary-gate: ok, 2 files, 1 modules, needles: not supplied (structural checks only)"])

    # --- marking -----------------------------------------------------------

    def test_marking_module(self):
        cases = {
            "no distribution": MODULE.replace("distribution public\n", ""),
            "controlled": MODULE.replace("distribution public", "distribution controlled"),
            "stated twice": MODULE + "distribution public\n",
            "no source": MODULE.replace('source "an invented public document"\n', ""),
            "no module line": MODULE.replace("module core\n", ""),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.tree.write("model/core.def", text)
                found = self.run_gate()[1]
                self.assertIn(("marking", "model/core.def"), [(check, where) for check, where, _ in found])

    def test_marking_pack(self):
        cases = {
            "no distribution": PACK.replace("distribution public\n", ""),
            "controlled": PACK.replace("distribution public", "distribution controlled"),
            "no source": PACK.replace('source "an invented public document"\n', ""),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.tree.write("packs/sample/pack.def", text)
                self.assert_findings([("marking", "packs/sample/pack.def")])

    def test_marking_reads_a_def_file_as_the_engines_do(self):
        # A `#` inside double quotes is text; a `#` that starts a token is a comment.
        self.tree.write("packs/sample/pack.def", PACK.replace(
            'source "an invented public document"', 'source "document #7"  # distribution controlled'))
        self.assert_ok()

    def test_marking_does_not_apply_outside_model_and_packs(self):
        self.tree.write("docs/notes.def", "anything\n")
        self.tree.write("packs/sample/extra/pack.def", "format nested\n")
        self.assert_ok()

    # --- closure -----------------------------------------------------------

    def test_closure_uses_a_module_that_is_not_in_model(self):
        self.tree.write("packs/sample/pack.def", PACK + "uses extra\n")
        found = self.assert_findings([("closure", "packs/sample/pack.def")])
        self.assertIn("`extra`", found[0][2])

    def test_closure_maps_a_key_without_uses(self):
        self.tree.write("model/extra.def", MODULE.replace("module core", "module extra").replace("key uid", "key size"))
        self.tree.write("packs/sample/pack.def", PACK + "field extra.size n int\n")
        self.assert_findings([("closure", "packs/sample/pack.def:6")])

    def test_closure_maps_a_key_its_module_does_not_declare(self):
        self.tree.write("packs/sample/pack.def", PACK + "field callsign c string\n")
        found = self.assert_findings([("closure", "packs/sample/pack.def:6")])
        self.assertIn("`callsign`", found[0][2])

    def test_closure_holds_for_a_declared_key_of_a_used_module(self):
        self.tree.write("model/extra.def", MODULE.replace("module core", "module extra").replace("key uid", "key size"))
        self.tree.write("packs/sample/pack.def", PACK + "uses extra\nfield extra.size n int\n")
        self.assert_ok()

    # --- filetype ----------------------------------------------------------

    def test_filetype_refuses_what_is_not_on_the_allowlist(self):
        for name in ("docs/standard.pdf", "docs/table.xlsx", "docs/bundle.tar.gz", "bin/program", ".env", "a/.hidden.docx"):
            with self.subTest(name):
                self.tree.write(name, "text\n")
                self.assert_findings([("filetype", name)])
                self.tree.remove(name)

    def test_filetype_accepts_the_allowlist(self):
        for name in ("docs/notes.md", "docs/NOTES.MD", "LICENSE", ".gitignore", "engines/x/build.zig.zon", "a.b/Makefile"):
            self.tree.write(name, "text\n")
        self.assert_ok()

    def test_filetype_allows_schema_fixtures_under_the_generator_tests_only(self):
        for name in ("tools/gen/tests/fixtures/a/input.proto", "tools/gen/tests/fixtures/b.xsd",
                     "tools/gen/tests/fixtures/c/d.xml"):
            self.tree.write(name, "text\n")
        self.assert_ok()
        for name in ("docs/schema.proto", "packs/x/schema.xsd", "tools/gen/fixtures/e.xml"):
            with self.subTest(name):
                self.tree.write(name, "text\n")
                self.assert_findings([("filetype", name)])
                self.tree.remove(name)

    def test_filetype_allows_the_web_page_and_its_stylesheet_under_site_only(self):
        for name in ("site/index.html", "site/assets/site.css"):
            self.tree.write(name, "text\n")
        self.assert_ok()
        for name in ("docs/page.html", "bindings/wasm/style.css", "tools/site/index.html", "site/page.htm"):
            with self.subTest(name):
                self.tree.write(name, "text\n")
                self.assert_findings([("filetype", name)])
                self.tree.remove(name)

    def test_filetype_refuses_a_file_that_is_not_utf8(self):
        self.tree.write("docs/notes.md", b"caf\xe9\n")
        found = self.assert_findings([("filetype", "docs/notes.md")])
        self.assertIn("not readable as UTF-8 text", found[0][2])

    def test_filetype_refuses_a_nul_byte(self):
        self.tree.write("docs/notes.md", b"text\x00more\n")
        found = self.assert_findings([("filetype", "docs/notes.md")])
        self.assertEqual(found[0][2], "binary content")

    def test_filetype_refuses_a_file_name_that_is_not_utf8(self):
        name = os.path.join(os.fsencode(self.tree.root), b"docs", b"caf\xe9.md")
        os.makedirs(os.path.dirname(name))
        try:
            with open(name, "wb") as fh:
                fh.write(b"text\n")
        except OSError:
            self.skipTest("this file system refuses a file name that is not UTF-8")
        code, found, lines = self.run_gate()
        self.assertEqual(code, 1)
        self.assertEqual(found, [("filetype", "docs/caf\\udce9.md", "file name is not UTF-8")], lines)

    def test_an_empty_tree_fails(self):
        self.tree.remove("model/core.def")
        self.tree.remove("packs/sample/pack.def")
        found = self.assert_findings([("filetype", ".")])
        self.assertIn("empty tree", found[0][2])

    # --- phrase ------------------------------------------------------------

    def test_phrase_fires_on_each_marking(self):
        for what, text, _ in MARKINGS:
            with self.subTest(what=what, text=text):
                self.tree.write("docs/notes.md", "first line\n%s\n" % text)
                found = self.assert_findings([("phrase", "docs/notes.md:2")])
                self.assertEqual(found[0][2], what)

    def test_phrase_passes_each_near_miss(self):
        self.tree.write("docs/notes.md", "".join(miss + "\n" for _, _, miss in MARKINGS))
        self.assert_ok()

    def test_phrase_ignores_case(self):
        for _, text, _ in MARKINGS:
            self.tree.write("docs/notes.md", text.upper() + "\n" + text.lower() + "\n")
            self.assert_findings([("phrase", "docs/notes.md:1"), ("phrase", "docs/notes.md:2")])

    def test_phrase_wrapped_over_a_line_break(self):
        # The words of a marking, with what a wrapped line puts between them.
        breaks = ["\n", "\n    ", "  ", "\t", "\n# ", "\n    // ", "\n * ", "\n> ", "\n;; ", "\n%% ", "_", " - "]
        markings = [
            (j("export"), j("controlled")),
            (j("distri", "bution"), j("state", "ment e")),
            (j("proprietary"), j("information")),
            (j("company"), j("confidential")),
            (j("arms export control"), j("act")),
        ]
        for first, second in markings:
            for between in breaks:
                with self.subTest(first=first, between=between):
                    self.tree.write("docs/notes.md", "intro\nsome %s%s%s here\n" % (first, between, second))
                    self.assert_findings([("phrase", "docs/notes.md:2")])

    def test_phrase_does_not_join_words_across_other_text(self):
        self.tree.write("docs/notes.md", "what we export.\n\nControlled vocabularies are listed below.\n")
        self.assert_ok()

    def test_phrase_in_a_file_path(self):
        name = "docs/%s/notes.md" % j("export", "-", "controlled")
        self.tree.write(name, "text\n")
        self.assert_findings([("phrase", name)])

    # --- hygiene -----------------------------------------------------------

    def test_hygiene_fires_on_each_pattern(self):
        for what, text, _ in HYGIENE:
            with self.subTest(what=what, text=text):
                self.tree.write("docs/notes.md", "first line\nsee %s\n" % text)
                found = self.assert_findings([("hygiene", "docs/notes.md:2")])
                self.assertEqual(found[0][2], what)

    def test_hygiene_passes_each_near_miss(self):
        self.tree.write("docs/notes.md", "".join(miss + "\n" for _, _, miss in HYGIENE))
        self.assert_ok()

    def test_hygiene_reads_an_escaped_at_sign(self):
        self.tree.write("docs/data.json", '{"contact": "%s"}\n' % j("a.person", "\\u0040", "example.org"))
        self.assert_findings([("hygiene", "docs/data.json:1")])

    # --- boundary-allow ----------------------------------------------------

    def test_allow_exempts_phrase_and_hygiene_on_its_own_line_only(self):
        marking, address = MARKINGS[4][1], HYGIENE[3][1]
        self.tree.write("docs/notes.md", "\n".join([
            "the banner %s is quoted here  <!-- boundary-allow: names the banner -->" % marking,
            "write to %s  # boundary-allow: a public contact" % address,
            "the banner %s again" % marking,
            "write to %s again" % address,
        ]) + "\n")
        self.assert_findings([("phrase", "docs/notes.md:3"), ("hygiene", "docs/notes.md:4")])

    def test_allow_covers_a_wrapped_marking_only_when_on_every_line_of_it(self):
        first, second = j("export"), j("controlled")
        self.tree.write("docs/notes.md", "boundary-allow: first line only: %s\n%s\n" % (first, second))
        self.assert_findings([("phrase", "docs/notes.md:1")])
        self.tree.write("docs/notes.md", "the banner %s\n%s  boundary-allow: second line only\n" % (first, second))
        self.assert_findings([("phrase", "docs/notes.md:1")])
        self.tree.write("docs/notes.md", "boundary-allow: both: %s\n%s  boundary-allow: both\n" % (first, second))
        self.assert_ok()

    def test_allow_never_exempts_a_needle(self):
        self.tree.write("docs/notes.md", "the zorblat value  boundary-allow: no such exemption\n")
        self.assert_findings([("needle", "docs/notes.md:1")], *self.needles("zorblat"))

    def test_allow_does_not_exempt_marking_or_filetype(self):
        self.tree.write("packs/sample/pack.def", "# boundary-allow: no\n" + PACK.replace("distribution public\n", ""))
        self.tree.write("docs/boundary-allow:.pdf", "boundary-allow: no\n")
        self.assert_findings([("marking", "packs/sample/pack.def"), ("filetype", "docs/boundary-allow:.pdf")])

    # --- needle ------------------------------------------------------------

    def test_needle_fires_and_names_only_its_line_and_length(self):
        self.tree.write("docs/notes.md", "one\nthe Zorblat value\n")
        found = self.assert_findings([("needle", "docs/notes.md:2")], *self.needles("filler-word", "zorblat"))
        self.assertEqual(found[0][2], "text matches the needle on line 2 of the needle file (7 characters)")

    def test_needle_clean_tree_reports_how_many_needles_it_checked(self):
        self.tree.write("docs/notes.md", "nothing of interest\n")
        code, _, lines = self.run_gate(*self.needles("zorblat", "", "quuxfrob", "ZORBLAT"))
        self.assertEqual((code, lines), (0, ["boundary-gate: ok, 3 files, 1 modules, needles: 2"]))

    def test_needle_matches_whole_words_only(self):
        self.tree.write("docs/notes.md", "zorblatter prezorblat zorblat9 9zorblat\n")
        self.assert_ok(*self.needles("zorblat"))

    def test_needle_matches_inside_an_identifier_at_word_boundaries(self):
        spellings = [
            "zorblatCount", "theZorblat", "ZorblatKind", "getZorblatKind", "ZORBLATKind", "theZORBLAT",
            "zorblat_count", "the_zorblat", "ZORBLAT_COUNT", "zorblat-count", "the.zorblat", "zorblat/count",
            "zorblat2Count", '"zorblat"', "(zorblat)",
        ]
        self.tree.write("src/code.py", "".join("x = %s\n" % s for s in spellings))
        expected = [("needle", "src/code.py:%d" % n) for n in range(1, len(spellings) + 1) if spellings[n - 1] != "zorblat2Count"]
        self.assert_findings(expected, *self.needles("zorblat"))

    def test_needle_of_several_words_matches_across_spaces_line_breaks_and_comment_marks(self):
        texts = [
            "zorblat quux", "zorblat  quux", "zorblat\tquux", "zorblat\nquux", "zorblat\n    # quux",
            "zorblat\n// quux", "zorblat\n> quux", "Zorblat Quux", "ZORBLAT QUUX",
        ]
        for text in texts:
            with self.subTest(text=text):
                self.tree.write("docs/notes.md", "intro\nthe %s value\n" % text)
                self.assert_findings([("needle", "docs/notes.md:2")], *self.needles("zorblat quux"))

    def test_needle_of_several_words_does_not_yet_match_words_joined_by_other_marks(self):
        # Matching `_`, `-` and `.` joins as well (with an allowlist for the
        # public catalogs that use them) is an open decision; until it is made
        # these spellings do not match a needle written with a space.
        for text in ("zorblat_quux", "zorblat-quux", "zorblat.quux", "zorblatQuux", "ZorblatQuux",
                     "ZORBLAT_QUUX", "zorblat, quux", "<zorblat>quux</zorblat>", "zorblat\n\nquux"):
            with self.subTest(text=text):
                self.tree.write("docs/notes.md", "intro\nthe %s value\n" % text)
                self.assert_ok(*self.needles("zorblat quux"))

    def test_needle_of_several_words_needs_them_adjacent_and_in_order(self):
        self.tree.write("docs/notes.md", "quux zorblat\nzorblat of quux\nzorblatquux\nzorblat quuxes\n")
        self.assert_ok(*self.needles("zorblat quux"))

    def test_needle_written_as_an_identifier_matches_its_own_spelling_and_spaced_words(self):
        for needle in ("zorblatQuux", "ZorblatQuux", "zorblat_quux", "zorblat-quux", "ZORBLAT_QUUX", "Zorblat Quux"):
            for text in (needle, needle.swapcase(), "zorblat quux", "zorblat\nquux"):
                with self.subTest(needle=needle, text=text):
                    self.tree.write("docs/notes.md", "the %s value\n" % text)
                    self.assert_findings([("needle", "docs/notes.md:1")], *self.needles(needle))

    def test_needle_written_as_an_identifier_does_not_yet_match_another_join(self):
        for needle, text in (("zorblat_quux", "zorblat-quux"), ("zorblat-quux", "zorblat_quux"),
                             ("zorblatQuux", "zorblat_quux"), ("zorblat_quux", "zorblatQuux")):
            with self.subTest(needle=needle, text=text):
                self.tree.write("docs/notes.md", "the %s value\n" % text)
                self.assert_ok(*self.needles(needle))

    def test_needle_written_in_camel_case_still_matches_its_all_lower_spelling(self):
        self.tree.write("docs/notes.md", "the zorblatquux value\n")
        self.assert_findings([("needle", "docs/notes.md:1")], *self.needles("zorblatQuux"))
        self.tree.write("docs/notes.md", "the zorblatQuux value\n")
        self.assert_findings([("needle", "docs/notes.md:1")], *self.needles("zorblatquux"))

    def test_needle_with_punctuation_matches_its_words(self):
        self.tree.write("docs/notes.md", "see ZB 4.7a and ZB-4-7A\n")
        self.assert_findings([("needle", "docs/notes.md:1")], *self.needles("zb.4.7a"))

    def test_needle_in_a_file_path(self):
        for name in ("docs/zorblat/notes.md", "docs/zorblatNotes.md", "docs/the_zorblat.md", "ZORBLAT.md"):
            with self.subTest(name):
                self.tree.write(name, "text\n")
                found = self.assert_findings([("needle", name)], *self.needles("zorblat"))
                self.assertEqual(found[0][2], "file path matches the needle on line 1 of the needle file (7 characters)")
                self.tree.remove(name)

    def test_needle_written_as_json_escapes(self):
        escaped = "".join("\\u%04x" % ord(c) for c in "zorblat")
        self.tree.write("docs/data.json", '{"name": "%s"}\n{"name": "\\u007Aorblat"}\n' % escaped)
        self.assert_findings([("needle", "docs/data.json:1"), ("needle", "docs/data.json:2")], *self.needles("zorblat"))

    def test_json_escape_of_a_line_break_does_not_move_line_numbers(self):
        self.tree.write("docs/data.json", '{"a": "x\\u000ay\\u000dz"}\n{"b": "zorblat"}\n')
        self.assert_findings([("needle", "docs/data.json:2")], *self.needles("zorblat"))

    def test_needle_in_another_unicode_form(self):
        composed = unicodedata.normalize("NFC", "z\u00f6rbl\u00e5t")
        decomposed = unicodedata.normalize("NFD", composed)
        self.assertNotEqual(composed, decomposed)
        full_width = "".join(chr(ord(c) + 0xFEE0) for c in "zorblat")
        cases = [(composed, decomposed), (decomposed, composed), ("zorblat", full_width), ("stra\u00dfe", "STRASSE")]
        for needle, text in cases:
            with self.subTest(needle=needle, text=text):
                self.tree.write("docs/notes.md", "the %s value\n" % text)
                self.assert_findings([("needle", "docs/notes.md:1")], *self.needles(needle))

    def test_needle_with_no_ascii_letter(self):
        cyrillic = "\u0437\u043e\u0440\u0431\u043b\u0430\u0442"
        self.tree.write("docs/notes.md", "a %s b\nthe%sKind\n" % (cyrillic, cyrillic.capitalize()))
        self.assert_findings([("needle", "docs/notes.md:1"), ("needle", "docs/notes.md:2")], *self.needles(cyrillic))

    def test_needle_in_a_script_without_spaces_matches_inside_a_run(self):
        needle = "\u6771\u4eac\u30bf\u30ef\u30fc"
        self.tree.write("docs/notes.md", "\u3053\u308c\u306f%s\u3067\u3059\n\u6771\u4eac\u3067\u3059\n" % needle)
        self.assert_findings([("needle", "docs/notes.md:1")], *self.needles(needle))

    def test_several_needles_on_one_line_are_one_finding_that_counts_them(self):
        self.tree.write("docs/notes.md", "zorblat and quuxfrob and wibblezap\n")
        found = self.assert_findings([("needle", "docs/notes.md:1")], *self.needles("wibblezap", "zorblat", "quuxfrob"))
        self.assertEqual(
            found[0][2], "text matches the needle on line 1 of the needle file (9 characters); 2 more needles match here")

    def test_no_output_holds_the_text_of_a_needle(self):
        made_up_needle = "zorblat quuxfrob"
        self.tree.write("docs/notes.md", "the Zorblat_Quuxfrob value, twice: zorblat quuxfrob\n")
        _, _, lines = self.run_gate(*self.needles(made_up_needle, "zq", "zorblat quuxfrob extra"))
        # The temporary directory's random name may hold any short piece: it is
        # not output of the gate's own, so it is removed before the check.
        printed = "\n".join(lines).replace(self.tree.base, "<tmp>").lower()
        for piece in ("zorblat", "quuxfrob", "zor", "zq"):
            self.assertNotIn(piece, printed)

    # --- the needle file ---------------------------------------------------

    def test_a_needle_that_is_too_short_fails_and_names_its_line(self):
        args = self.needles("zorblat", "", "zq", "abc", "abcd")
        code, found, _ = self.run_gate(*args)
        self.assertEqual(code, 1)
        self.assertEqual(found, [
            ("needle", "%s:3" % args[1], "needle is shorter than 4 characters"),
            ("needle", "%s:4" % args[1], "needle is shorter than 4 characters"),
        ])

    def test_a_needle_with_no_letter_or_digit_fails_and_names_its_line(self):
        args = self.needles("zorblat", "----", "_ . _ .")
        code, found, _ = self.run_gate(*args)
        self.assertEqual(code, 1)
        self.assertEqual(found, [
            ("needle", "%s:2" % args[1], "needle holds no letter or digit"),
            ("needle", "%s:3" % args[1], "needle holds no letter or digit"),
        ])

    def test_an_empty_needle_file_fails(self):
        for content in ("", "\n\n   \n"):
            with self.subTest(content=content):
                args = ["--needles", self.tree.write_beside("needles.txt", content)]
                found = self.assert_findings([("needle", args[1])], *args)
                self.assertEqual(found[0][2], "needle file is empty: refusing to pass")

    def test_a_needle_file_that_cannot_be_read_fails(self):
        missing = os.path.join(self.tree.beside, "absent.txt")
        found = self.assert_findings([("needle", missing)], "--needles", missing)
        self.assertEqual(found[0][2], "cannot read needle file: FileNotFoundError")
        binary = self.tree.write_beside("needles.bin", b"\xff\xfezorblat\n")
        found = self.assert_findings([("needle", binary)], "--needles", binary)
        self.assertEqual(found[0][2], "cannot read needle file: UnicodeDecodeError")

    def test_require_needles_without_needles_fails(self):
        found = self.assert_findings([("needle", "-")], "--require-needles")
        self.assertEqual(found[0][2], "--require-needles set and no --needles given")

    def test_require_needles_with_needles_passes(self):
        self.assert_ok("--require-needles", *self.needles("zorblat"))

    # --- svg ---------------------------------------------------------------

    SVG = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">%s</svg>\n'

    def test_svg_of_shapes_text_and_inside_references_passes(self):
        self.tree.write("docs/figure.svg", self.SVG % (
            '<defs><linearGradient id="g"/><path id="p" d="M0 0"/></defs>\n'
            '<style>.a { fill: url(#g); }</style>\n'
            '<rect class="a" width="5" height="5" fill="url(#g)"/><use href="#p"/><use xlink:href="#p"/>\n'
            '<text>Data: 25 bytes, on one line; script and data are words here</text>'))
        self.assert_ok()

    def test_svg_refuses_code_embedded_data_and_outside_references(self):
        refused = {
            "<script>alert(1)</script>": "svg holds a script element",
            '<SCRIPT href="#x"/>': "svg holds a script element",
            "<foreignObject><p>html</p></foreignObject>": "svg holds a foreignObject element",
            '<image href="data:image/png;base64,AAAA"/>': "svg holds a data: URI",
            '<image xlink:href=" DATA:image/png;base64,AAAA"/>': "svg holds a data: URI",
            '<rect fill="url(data:image/png;base64,AAAA)"/>': "svg holds a data: URI",
            '<image href="https://example.org/a.png"/>': "svg holds a reference outside the file",
            "<use href='other.svg#p'/>": "svg holds a reference outside the file",
            '<a href="javascript:alert(1)">x</a>': "svg holds a reference outside the file",
            "<style>.a { fill: url('https://example.org/a.png'); }</style>": "svg holds a reference outside the file",
            '<set attributeName="href" to="data:image/svg+xml;base64,AAAA"/>': "svg holds a data: URI",
            '<rect onload="alert(1)"/>': "svg holds an event handler attribute",
            '<style>@import "a.css";</style>': "svg holds a style sheet import",
        }
        for content, message in refused.items():
            with self.subTest(content=content):
                self.tree.write("docs/figure.svg", self.SVG % ("<title>t</title>\n" + content))
                found = self.assert_findings([("filetype", "docs/figure.svg:2")])
                self.assertEqual(found[0][2], message)

    def test_svg_refuses_a_style_sheet_reference_and_an_entity(self):
        self.tree.write("docs/figure.svg", '<?xml-stylesheet href="#s"?>\n<!DOCTYPE svg [\n<!ENTITY e "x">\n]>\n' + self.SVG % "")
        found = self.assert_findings([("filetype", "docs/figure.svg:1"), ("filetype", "docs/figure.svg:3")])
        self.assertEqual(
            sorted(message for _, _, message in found),
            ["svg holds a style sheet reference", "svg holds an entity declaration"])

    def test_svg_rules_apply_to_svg_files_only(self):
        self.tree.write("docs/page.md", '<script>x</script> <img src="https://example.org/a.png">\n')
        self.assert_ok()


# --------------------------------------------------------------------------
# The waiver for generated packs
# --------------------------------------------------------------------------

GENERATED = "# Generated by tools/gen/inv2pack.py; edit the generator, not this file.\n"
INV_MODULE = 'module inv\ndistribution public\nsource "an invented public schema"\nkey zorblat_count int - "a count"\n'
INV_PACK = ('format inv\ndistribution public\nsource "an invented public schema"\nwire json\nuses inv\n'
            'field inv.zorblat_count zorblatCount int\n')
SCHEMA = "message Inv {\n  int32 zorblat_count = 1;\n}\n"


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Waiver(GateCase):
    """A generated pack `inv` and its generated module, whose names restate an
    invented upstream schema; the schema file sits beside the tree."""

    def setUp(self):
        super().setUp()
        self.sources = os.path.join(self.tree.beside, "sources")
        os.environ[gate.GEN_SOURCES_ENV] = self.sources
        self.tree.write("tools/gen/inv2pack.py", "# an invented generator\n")
        self.tree.write("model/inv.def", GENERATED + INV_MODULE)
        self.tree.write("packs/inv/pack.def", GENERATED + INV_PACK)
        self.provenance(sha256(SCHEMA))
        self.source("schema/inv.proto", SCHEMA)

    def provenance(self, digest, path="schema/inv.proto"):
        self.tree.write("packs/inv/PROVENANCE.md", "# Provenance\n\n| File | SHA-256 |\n|---|---|\n| `%s` | `%s` |\n"
                        % (path, digest))

    def source(self, rel, text):
        full = os.path.join(self.sources, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)

    def assert_waived(self, expected, *args):
        """The gate passes, and waives exactly `expected`: where."""
        code, found, lines = self.run_gate(*args)
        self.assertEqual((code, found), (0, []), lines)
        self.assertEqual(sorted(where for where, _ in self.waived), sorted(expected), lines)
        self.assertTrue(lines[-1].startswith("boundary-gate: ok, "), lines)

    def test_a_hit_in_a_generated_pack_and_its_module_is_waived(self):
        self.assert_waived(["packs/inv/pack.def:7", "model/inv.def:5"], *self.needles("filler-word", "zorblat"))
        self.assertEqual(self.waived_summary, [
            "boundary-gate: 2 needle hits waived in 2 files of 1 generated packs (each needle also appears in a "
            "cited upstream source whose SHA-256 matches)"])
        self.assertEqual(sorted(self.waived), [
            ("model/inv.def:5", "text matches the needle on line 2 of the needle file (7 characters)"),
            ("packs/inv/pack.def:7", "text matches the needle on line 2 of the needle file (7 characters)"),
        ])

    def test_the_summary_comes_after_the_findings_and_the_verdict_is_last(self):
        self.tree.write("docs/notes.md", "the zorblat value\n")
        code, _, lines = self.run_gate(*self.needles("zorblat"))
        self.assertEqual(code, 1)
        self.assertEqual([line.split(":")[1].split()[0] for line in lines], ["needle", "2", "waived", "waived", "FAIL,"])

    def test_every_file_of_the_pack_directory_is_covered(self):
        self.tree.write("packs/inv/pack.md", "Maps zorblat_count.\n")
        self.tree.write("packs/inv/vectors/round-trip.json", '{"input": {"zorblatCount": 1}}\n')
        self.assert_waived(["packs/inv/pack.def:7", "model/inv.def:5", "packs/inv/pack.md:1",
                            "packs/inv/vectors/round-trip.json:1"], *self.needles("zorblat"))

    def test_a_wrong_hash_is_a_finding(self):
        self.provenance(sha256(SCHEMA + "changed"))
        found = self.assert_findings([("needle", "packs/inv/pack.def:7"), ("needle", "model/inv.def:5")],
                                     *self.needles("zorblat"))
        for _, _, message in found:
            self.assertIn("packs/inv/PROVENANCE.md under GOAT_GEN_SOURCES (0 of 1 present", message)

    def test_an_absent_source_is_a_finding_that_names_the_provenance_file(self):
        os.environ[gate.GEN_SOURCES_ENV] = os.path.join(self.tree.beside, "nowhere")
        found = self.assert_findings([("needle", "packs/inv/pack.def:7"), ("needle", "model/inv.def:5")],
                                     *self.needles("zorblat"))
        self.assertEqual(found[0][2], (
            "text matches the needle on line 1 of the needle file (7 characters); the waiver for this generated "
            "pack needs the source files cited in packs/inv/PROVENANCE.md under GOAT_GEN_SOURCES "
            "(0 of 1 present with the recorded SHA-256)"))
        self.assertEqual(self.waived_summary, [])

    def test_a_source_at_a_path_the_record_does_not_name_does_not_count(self):
        self.source("elsewhere/inv.proto", SCHEMA)
        self.provenance(sha256(SCHEMA), path="schema/other.proto")
        self.assert_findings([("needle", "packs/inv/pack.def:7"), ("needle", "model/inv.def:5")], *self.needles("zorblat"))

    def test_a_source_under_a_directory_named_for_the_pack_counts(self):
        shutil.rmtree(self.sources)
        self.source("inv/schema/inv.proto", SCHEMA)
        self.assert_waived(["packs/inv/pack.def:7", "model/inv.def:5"], *self.needles("zorblat"))

    def test_several_source_directories(self):
        shutil.rmtree(self.sources)
        other = os.path.join(self.tree.beside, "other")
        os.environ[gate.GEN_SOURCES_ENV] = os.pathsep.join([os.path.join(self.tree.beside, "nowhere"), other])
        os.makedirs(os.path.join(other, "schema"))
        with open(os.path.join(other, "schema", "inv.proto"), "w", encoding="utf-8") as fh:
            fh.write(SCHEMA)
        self.assert_waived(["packs/inv/pack.def:7", "model/inv.def:5"], *self.needles("zorblat"))

    def test_a_sha256sum_record_in_a_family_file_the_generator_names(self):
        self.tree.write("packs/inv/PROVENANCE.md", "# Provenance\n\nNo source is copied here.\n")
        self.tree.write("tools/gen/inv2pack.py", "# checks tools/gen/sources/inv-PROVENANCE.md\n")
        self.tree.write("tools/gen/sources/inv-PROVENANCE.md", "```\n%s  schema/inv.proto\n```\n" % sha256(SCHEMA))
        self.assert_waived(["packs/inv/pack.def:7", "model/inv.def:5"], *self.needles("zorblat"))

    def test_a_family_file_nothing_names_is_not_cited(self):
        self.tree.write("packs/inv/PROVENANCE.md", "# Provenance\n\nNo source is copied here.\n")
        self.tree.write("tools/gen/sources/inv-PROVENANCE.md", "%s  schema/inv.proto\n" % sha256(SCHEMA))
        found = self.assert_findings([("needle", "packs/inv/pack.def:7"), ("needle", "model/inv.def:5")],
                                     *self.needles("zorblat"))
        self.assertIn("; no hit in this generated pack is waived: packs/inv/PROVENANCE.md records no SHA-256",
                      found[0][2])

    def test_a_hand_written_pack_is_not_waived(self):
        self.tree.write("packs/inv/pack.def", "# Written by hand from an invented schema.\n" + INV_PACK)
        self.assert_findings([("needle", "packs/inv/pack.def:7"), ("needle", "model/inv.def:5")], *self.needles("zorblat"))

    def test_a_module_used_only_by_a_pack_of_another_generator_is_not_waived(self):
        self.tree.write("tools/gen/other2pack.py", "# another invented generator\n")
        self.tree.write("model/inv.def", GENERATED.replace("inv2pack", "other2pack") + INV_MODULE)
        found = self.assert_findings([("needle", "model/inv.def:5")], *self.needles("zorblat"))
        self.assertEqual(found[0][2], "text matches the needle on line 1 of the needle file (7 characters)")
        self.assertEqual([where for where, _ in self.waived], ["packs/inv/pack.def:7"])

    def test_a_generator_that_is_not_in_the_tree_makes_no_generated_pack(self):
        self.tree.remove("tools/gen/inv2pack.py")
        self.assert_findings([("needle", "packs/inv/pack.def:7"), ("needle", "model/inv.def:5")], *self.needles("zorblat"))

    def test_a_synthetic_pack_is_not_waived(self):
        self.tree.write("packs/conformance-inv/pack.def", GENERATED + INV_PACK.replace("format inv", "format conformance-inv"))
        self.tree.write("packs/conformance-inv/PROVENANCE.md", "| `schema/inv.proto` | `%s` |\n" % sha256(SCHEMA))
        code, found, _ = self.run_gate(*self.needles("zorblat"))
        self.assertEqual(found, [("needle", "packs/conformance-inv/pack.def:7",
                                  "text matches the needle on line 1 of the needle file (7 characters)")])

    def test_a_hit_outside_packs_and_model_is_not_waived(self):
        for name in ("docs/notes.md", "tools/gen/names/inv.json", "packs/notes.md"):
            with self.subTest(name):
                self.tree.write(name, "the zorblat_count key\n")
                self.assert_findings([("needle", name + ":1")], *self.needles("zorblat"))
                self.assertEqual(len(self.waived), 2)
                self.tree.remove(name)

    def test_a_file_path_is_not_waived(self):
        self.tree.write("packs/inv/vectors/zorblat.json", "{}\n")
        found = self.assert_findings([("needle", "packs/inv/vectors/zorblat.json")], *self.needles("zorblat"))
        self.assertTrue(found[0][2].startswith("file path matches"))

    def test_a_needle_only_partly_in_the_source_is_not_waived(self):
        self.tree.write("packs/inv/pack.md", "The zorblat quux of the message.\n")
        for schema in (SCHEMA, "the zorblat_quux field\n", "zorblat\n\nquux\n"):
            with self.subTest(schema=schema):
                self.source("schema/inv.proto", schema)
                self.provenance(sha256(schema))
                self.assert_findings([("needle", "packs/inv/pack.md:1")], *self.needles("zorblat quux"))
                self.assertIn("none of the 1 cited sources present with the recorded SHA-256 holds it",
                              self.run_gate(*self.needles("zorblat quux"))[1][0][2])

    def test_only_the_needles_the_source_holds_are_waived_on_a_line(self):
        self.tree.write("packs/inv/pack.md", "zorblat and wibblezap\n")
        found = self.assert_findings([("needle", "packs/inv/pack.md:1")], *self.needles("zorblat", "wibblezap"))
        self.assertTrue(found[0][2].startswith("text matches the needle on line 2 of the needle file (9 characters);"),
                        found)
        self.assertIn(("packs/inv/pack.md:1", "text matches the needle on line 1 of the needle file (7 characters)"),
                      self.waived)

    def test_the_default_source_directory_is_ignored_by_git(self):
        if not have_git():
            self.skipTest("git is not installed")
        self.tree.git("init", "-q")
        with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as fh:
            self.tree.write(".gitignore", fh.read())
        del os.environ[gate.GEN_SOURCES_ENV]
        self.tree.write("tools/gen/sources/schema/inv.proto", SCHEMA)
        self.assert_waived(["packs/inv/pack.def:7", "model/inv.def:5"], *self.needles("zorblat"))

    def test_no_output_holds_the_text_of_a_needle(self):
        self.tree.write("docs/notes.md", "zorblat quuxfrob\n")
        self.tree.write("packs/inv/pack.md", "zorblat quuxfrob and zorblat\n")
        for sources in (self.sources, os.path.join(self.tree.beside, "nowhere")):
            os.environ[gate.GEN_SOURCES_ENV] = sources
            _, _, lines = self.run_gate(*self.needles("zorblat", "zorblat quuxfrob"))
            printed = "\n".join(lines).replace(self.tree.base, "<tmp>").lower()
            for piece in ("zorblat", "quuxfrob", "zor"):
                self.assertNotIn(piece, printed)


class ProvenanceRecords(unittest.TestCase):
    H1, H2 = "ab" * 32, "cd" * 32

    def test_sha256sum_lines(self):
        text = "```\n%s  a/b.proto\n%s *c.xml\n```\n" % (self.H1, self.H2.upper())
        self.assertEqual(gate.sha256_records(text), [(self.H1, ["a/b.proto"]), (self.H2, ["c.xml"])])

    def test_a_table_with_a_sha256_column(self):
        text = "| Local | Path | SHA-256 |\n|---|---|---|\n| `common.xml` | `defs/common.xml` | `%s` |\n" % self.H1
        self.assertEqual(gate.sha256_records(text), [(self.H1, ["common.xml", "defs/common.xml"])])

    def test_a_hash_alone_on_its_row_takes_the_paths_of_its_table(self):
        text = "| Fact | Value |\n|---|---|\n| definition | `specs/def.json` of https://example.org/x |\n" \
               "| SHA-256 | `%s` |\n" % self.H1
        (digest, names), = gate.sha256_records(text)
        self.assertEqual((digest, set(names)), (self.H1, {"SHA-256", "Fact", "Value", "definition", "specs/def.json", "x"}))

    def test_a_hash_in_prose(self):
        text = "The file `LICENSE` (SHA-256 `%s`) holds it.\n" % self.H1
        self.assertEqual(gate.sha256_records(text), [(self.H1, ["LICENSE"])])
        text = "As served at https://example.org/api/openapi.json, sha256\n`%s`.\n" % self.H1
        self.assertEqual(gate.sha256_records(text), [(self.H1, ["openapi.json"])])

    def test_paths_that_leave_the_source_directory_are_dropped(self):
        text = "| `../x` | `/etc/x` | `a/./b` | `c:\\\\x` | `ok/x` | `%s` |\n" % self.H1
        self.assertEqual(gate.sha256_records(text), [(self.H1, ["ok/x"])])
        self.assertEqual(gate.sha256_records("%s  ../x\n" % self.H1), [])

    def test_a_header_names_its_generator(self):
        cases = {
            "# Generated by tools/gen/a2pack.py; do not edit.\nformat a\n": "tools/gen/a2pack.py",
            "# A pack. Public. Generated by\n# tools/gen/a2pack.py from x.\nformat a\n": "tools/gen/a2pack.py",
            "# GENERATED by `tools/gen/a2pack.py`.\n": "tools/gen/a2pack.py",
            "# The module. Last extended for the b format by\n# tools/gen/b2pack.py from the sources.\nmodule b\n":
                "tools/gen/b2pack.py",
            "# Written by hand.\nformat a\n# Generated by tools/gen/a2pack.py\n": None,
        }
        tree = TempTree()
        self.addCleanup(tree.cleanup)
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(gate.header_generator(tree.write("x.def", text)), expected)


# --------------------------------------------------------------------------
# Which files are read
# --------------------------------------------------------------------------

class DiscoveryInAGitCheckout(GateCase):
    git = True
    marked = MARKINGS[4][1] + "\n"

    def test_every_check_fires_on_a_checkout(self):
        self.tree.write("model/core.def", MODULE.replace("distribution public\n", ""))
        self.tree.write("packs/sample/pack.def", PACK + "field callsign c string\n")
        self.tree.write("docs/standard.pdf", "text\n")
        self.tree.write("docs/notes.md", "%s\n%s\nthe zorblat value\n" % (MARKINGS[4][1], HYGIENE[3][1]))
        self.tree.git("add", "--all")
        self.tree.git("-c", "user.name=t", "-c", "user.email=t", "commit", "-q", "--no-gpg-sign", "-m", "all")
        self.assert_findings([
            ("marking", "model/core.def"), ("closure", "packs/sample/pack.def:6"), ("filetype", "docs/standard.pdf"),
            ("phrase", "docs/notes.md:1"), ("hygiene", "docs/notes.md:2"), ("needle", "docs/notes.md:3"),
        ], *self.needles("zorblat"))

    def test_an_empty_checkout_fails(self):
        self.tree.remove("model/core.def")
        self.tree.remove("packs/sample/pack.def")
        self.assert_findings([("filetype", ".")])

    def test_untracked_and_staged_files_are_read(self):
        self.tree.write("docs/untracked.md", self.marked)
        self.tree.write("docs/staged.md", self.marked)
        self.tree.git("add", "docs/staged.md")
        self.assert_findings([("phrase", "docs/staged.md:1"), ("phrase", "docs/untracked.md:1")])

    def test_ignored_files_are_not_read(self):
        self.tree.write(".gitignore", "scratch/\n")
        self.tree.write("scratch/notes.pdf", self.marked)
        self.assert_ok()

    def test_an_ignored_file_that_was_added_is_read(self):
        self.tree.write(".gitignore", "scratch/\n")
        self.tree.write("scratch/notes.md", self.marked)
        self.tree.git("add", "--force", "scratch/notes.md")
        self.assert_findings([("phrase", "scratch/notes.md:1")])

    def test_a_tracked_file_deleted_from_the_working_tree_is_not_read(self):
        self.tree.write("docs/gone.md", self.marked)
        self.tree.git("add", "docs/gone.md")
        self.tree.remove("docs/gone.md")
        self.assert_ok()

    def test_build_directories_are_read_when_git_would_commit_them(self):
        self.tree.write("build/notes.md", self.marked)
        self.assert_findings([("phrase", "build/notes.md:1")])


class DiscoveryInAPlainDirectory(GateCase):
    marked = MARKINGS[4][1] + "\n"

    def test_every_file_outside_the_build_directories_is_read(self):
        self.tree.write("docs/deep/er/notes.md", self.marked)
        for skipped in gate.BUILD_DIRS:
            self.tree.write("%s/notes.pdf" % skipped, self.marked)
            self.tree.write("engines/x/%s/notes.pdf" % skipped, self.marked)
        self.assert_findings([("phrase", "docs/deep/er/notes.md:1")])

    @unittest.skipUnless(have_git(), "git is not installed")
    def test_a_checkout_is_read_as_a_plain_directory_when_git_cannot_run(self):
        self.tree.git("init", "-q")
        self.tree.write(".gitignore", "scratch/\n")
        self.tree.write("scratch/notes.md", self.marked)
        self.assert_ok()
        with mock.patch.dict(os.environ, {"PATH": self.tree.beside}):
            self.assert_findings([("phrase", "scratch/notes.md:1")])


# --------------------------------------------------------------------------
# The parts
# --------------------------------------------------------------------------

class Words(unittest.TestCase):
    def parts(self, text):
        whole, parts = gate.tokenizers(text)
        return gate.fold_words(whole.findall(text)), gate.fold_words(parts.findall(text))

    def test_an_identifier_is_read_whole_and_as_its_parts(self):
        cases = {
            "trackNumber": ["track", "number"],
            "TrackNumber": ["track", "number"],
            "XMLParser": ["xml", "parser"],
            "parseXML": ["parse", "xml"],
            "HTTPServer2Go": ["http", "server2", "go"],
            "ab12CD": ["ab12", "cd"],
            "ABC123def": ["abc123def"],
            "A1B2": ["a1", "b2"],
            "x": ["x"],
            "lowercase": ["lowercase"],
            "UPPERCASE": ["uppercase"],
        }
        for text, expected in cases.items():
            with self.subTest(text):
                whole, parts = self.parts(text)
                self.assertEqual(whole, [text.lower()])
                self.assertEqual(parts, expected)

    def test_capitals_of_other_scripts_break_an_identifier_too(self):
        whole, parts = self.parts("\u0442\u0440\u0435\u043a\u041d\u043e\u043c\u0435\u0440 \u00e9t\u00e9\u00c9t\u00e9")
        self.assertEqual(whole, ["\u0442\u0440\u0435\u043a\u043d\u043e\u043c\u0435\u0440", "\u00e9t\u00e9\u00e9t\u00e9"])
        self.assertEqual(parts, ["\u0442\u0440\u0435\u043a", "\u043d\u043e\u043c\u0435\u0440", "\u00e9t\u00e9", "\u00e9t\u00e9"])

    def test_words_are_runs_of_letters_and_digits(self):
        whole, parts = self.parts("a_b-c.d e\tf\ng:h/i\\j'k\"l(m)n")
        self.assertEqual(whole, list("abcdefghijklmn"))
        self.assertEqual(parts, whole)

    def test_plain_decodes_escapes_and_keeps_every_line_break(self):
        self.assertEqual(gate.plain("\\u0041\\u00e9"), "A\u00e9")
        self.assertEqual(gate.plain("\\ud83d\\ude00"), "\U0001F600")
        self.assertEqual(gate.plain("a\\ud83db"), "a b")
        self.assertEqual(gate.plain("a\\u000ab\\u0000c\nd"), "a b c\nd")
        self.assertEqual(gate.plain("\\u12"), "\\u12")

    def test_def_tokenizer(self):
        self.assertEqual(gate.tokens('field uid "a # b" x#y  # tail'), ["field", "uid", "a # b", "x#y"])
        self.assertEqual(gate.tokens("key a b\t#c d"), ["key", "a", "b"])
        self.assertEqual(gate.tokens("   # only a comment"), [])
        self.assertEqual(gate.tokens('source ""'), ["source", ""])


class Extension(unittest.TestCase):
    def test_extension(self):
        cases = {
            "a/b.MD": "md", "a/b.tar.gz": "gz", ".gitignore": "gitignore", "a/.hidden.txt": "txt",
            "Makefile": "", "a.b/c": "", "a/.x.": "",
        }
        for path, expected in cases.items():
            with self.subTest(path):
                self.assertEqual(gate.extension(path), expected)


# --------------------------------------------------------------------------
# The command, its output and its exit status
# --------------------------------------------------------------------------

class Command(GateCase):
    def test_finding_lines_and_the_verdict(self):
        self.tree.write("docs/notes.md", "one\n%s\n" % MARKINGS[4][1])
        self.tree.write("docs/standard.pdf", "x\n")
        code, _, lines = self.run_gate()
        self.assertEqual(code, 1)
        self.assertEqual(lines, [
            "boundary-gate: filetype docs/standard.pdf: file type not on the allowlist (pdf)",
            "boundary-gate: phrase   docs/notes.md:2: export-control marking",
            "boundary-gate: FAIL, 2 finding(s) in 4 files",
        ])

    def test_a_wrong_command_line_is_status_2(self):
        code, out, err = run_main(gate.main, "--no-such-option")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--no-such-option", err)

    def test_run_as_a_program(self):
        """The exit status and the output reach the caller of the script."""
        command = [sys.executable, "-I", os.path.join(REPO, "tools", "boundary-gate"), "--root", self.tree.root]
        done = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertTrue(done.stdout.startswith("boundary-gate: ok, 2 files"))
        self.tree.write("docs/standard.pdf", "x\n")
        done = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertTrue(done.stdout.endswith("boundary-gate: FAIL, 1 finding(s) in 3 files\n"))


class ThisRepository(unittest.TestCase):
    def test_the_repository_passes_its_own_gate(self):
        """With no needle list, as in CI. This file and the gate are in the
        tree that is read, so neither may hold what the gate refuses."""
        code, out, _ = run_main(gate.main, "--root", REPO)
        self.assertEqual(code, 0, "\n".join(out.splitlines()[:20]))


if __name__ == "__main__":
    unittest.main()
