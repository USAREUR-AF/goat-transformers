#!/usr/bin/env python3
"""Write NOTICE from one file per source, so a pull request that adds a
source touches no line another pull request touches.

  tools/notice/header.txt         the first paragraphs of NOTICE: the
                                  project's own notice and what the entries
                                  below it are
  tools/notice/entries/<name>.txt one entry: the source of one pack, one
                                  family of packs or one module, as NOTICE
                                  shows it. <name> is the pack or family, in
                                  lower case: letters, digits, '.' and '-'

NOTICE is the header, then every entry in byte order of its file name, each
after one blank line. An entry's first line is not indented and names the
packs and modules ("Pack x; module y", "Packs x-*; modules x*"); its other
lines are indented by two spaces or more, or are blank lines between
indented paragraphs.

Usage (run with -I; standard library only):

  python3 -I tools/notice.py                  write NOTICE (the counts pull
                                              request runs it)
  python3 -I tools/notice.py --check          exit 1 when an entry file is
                                              malformed, or NOTICE holds an
                                              entry no file holds (an edit
                                              made to NOTICE itself, which the
                                              next write would lose) (CI); a
                                              NOTICE that lacks a newer entry
                                              is a note, as counts are
  python3 -I tools/notice.py --check-current  --check, and exit 1 when NOTICE
                                              is not what this tool writes
                                              (the counts PR)
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER = os.path.join("tools", "notice", "header.txt")
ENTRIES = os.path.join("tools", "notice", "entries")
NAME = re.compile(r"^[a-z0-9][a-z0-9.-]*\.txt$")


def _read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _text_problems(label, text):
    problems = []
    if not text.endswith("\n") or text.endswith("\n\n"):
        problems.append("%s must end with exactly one newline" % label)
    if "\r" in text or "\t" in text:
        problems.append("%s holds a carriage return or a tab" % label)
    for i, line in enumerate(text.split("\n"), 1):
        if line != line.rstrip(" "):
            problems.append("%s line %d ends with a space" % (label, i))
    return problems


def entry_problems(name, text):
    """The problems of one entry file; [] when it is well formed."""
    label = os.path.join(ENTRIES, name)
    problems = []
    if not NAME.match(name):
        problems.append("%s: the name is lower-case letters, digits, '.' and '-', then .txt" % label)
    problems += _text_problems(label, text)
    lines = text.rstrip("\n").split("\n")
    if not lines[0] or lines[0][0] == " ":
        problems.append("%s: the first line names the packs and is not indented" % label)
    # after the first paragraph (the heading may wrap onto unindented lines),
    # every paragraph is indented: an unindented paragraph would read as a
    # second entry
    paras = text.rstrip("\n").split("\n\n")
    for p in paras:
        if p == "":
            problems.append("%s holds two blank lines in a row" % label)
    for p in paras[1:]:
        if p and not p.startswith("  "):
            problems.append("%s: a paragraph after the first is not indented, so it reads as another entry: %r"
                            % (label, p.split("\n")[0][:60]))
    return problems


def gather(root):
    """(header text, [(file name, entry text)] in byte order of name, problems)."""
    problems = []
    try:
        header = _read(os.path.join(root, HEADER))
    except OSError as e:
        return None, [], ["%s cannot be read: %s" % (HEADER, e.strerror)]
    problems += _text_problems(HEADER, header)
    d = os.path.join(root, ENTRIES)
    try:
        names = sorted(os.listdir(d), key=lambda n: n.encode("utf-8"))
    except OSError as e:
        return header, [], problems + ["%s cannot be read: %s" % (ENTRIES, e.strerror)]
    entries = []
    for n in names:
        p = os.path.join(d, n)
        if not os.path.isfile(p):
            problems.append("%s is not a file" % os.path.join(ENTRIES, n))
            continue
        text = _read(p)
        problems += entry_problems(n, text)
        entries.append((n, text))
    seen = {}
    for n, text in entries:
        first = text.split("\n", 1)[0]
        if first in seen:
            problems.append("%s and %s begin with the same line: %r" % (seen[first], n, first))
        seen[first] = n
    return header, entries, problems


def render(header, entries):
    return header + "".join("\n" + text for _, text in entries)


def _entries_of_notice(text):
    """The entries of a NOTICE, as entry_problems reads them: each starts at an
    unindented paragraph and runs to the next."""
    out = []
    for p in text.rstrip("\n").split("\n\n"):
        if p and p[0] != " ":
            out.append(p)
        elif out:
            out[-1] += "\n\n" + p
    return out


def check(root, current=False):
    header, entries, problems = gather(root)
    notes = []
    if header is None:
        return problems, notes
    want = render(header, entries)
    try:
        have = _read(os.path.join(root, "NOTICE"))
    except OSError:
        have = ""
    if have != want:
        known = set(_entries_of_notice(want))
        lost = [e for e in _entries_of_notice(have) if e not in known]
        for e in lost:
            problems.append("NOTICE holds a paragraph no file under tools/notice/ holds; put it in an entry file "
                            "(tools/notice/entries/<name>.txt) or the header, then run python3 -I tools/notice.py: %r"
                            % e.split("\n")[0][:80])
        msg = "NOTICE is behind tools/notice/; the counts pull request writes it: python3 -I tools/notice.py"
        if not lost:
            (problems if current else notes).append(msg)
    return problems, notes


def main(argv, root=ROOT):
    if argv in (["--check"], ["--check-current"]):
        problems, notes = check(root, current=argv == ["--check-current"])
        for n in notes:
            print("notice: note:", n)
        for p in problems:
            print("notice:", p, file=sys.stderr)
        if problems:
            return 1
        _, entries, _ = gather(root)
        print("notice: %d entries, each in its own file" % len(entries))
        return 0
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    header, entries, problems = gather(root)
    if problems:
        for p in problems:
            print("notice:", p, file=sys.stderr)
        return 1
    with open(os.path.join(root, "NOTICE"), "w", encoding="utf-8", newline="") as fh:
        fh.write(render(header, entries))
    print("notice: wrote NOTICE, %d entries" % len(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
