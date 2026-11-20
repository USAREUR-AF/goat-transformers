#!/usr/bin/env python3
"""Check the Markdown tables of README.md and docs/: a table that a blank line
splits, or a row with another number of cells than its header, renders as
running text or loses cells on GitHub.

    python3 -I tools/markdown-tables.py [FILE...]   default: README.md and docs/**/*.md

A table is a header row, a delimiter row (`|---|---|`) and body rows, each
starting with `|`. It fails when:
  - a table ends at a blank line and the next text is a `|` row with no
    delimiter row under it (rows split off the table, which GitHub shows as
    a paragraph);
  - a body row has more or fewer cells than the header;
  - a `|` row has no table above it and no delimiter row below it.
Text inside fenced code blocks is not read. A `|` escaped as `\\|` is not a
cell boundary. Exit status 0 ok, 1 a problem (each as file:line: why).
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DELIMITER = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


def cells(row):
    """The number of cells of a table row (GitHub's rule: unescaped `|`)."""
    text = row.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    return len(re.split(r"(?<!\\)\|", text))


def is_row(line):
    return line.lstrip().startswith("|")


def problems_in(text, label):
    lines = text.split("\n")
    out = []
    fenced = False
    table_cells = None  # the header's number of cells while inside a table
    last_table_end = None  # line index of the blank line that ended the last table
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            table_cells = None
            i += 1
            continue
        if fenced:
            i += 1
            continue
        if table_cells is not None:
            if is_row(line):
                n = cells(line)
                if n != table_cells:
                    out.append("%s:%d: the row has %d cells; the table's header has %d" % (label, i + 1, n, table_cells))
                i += 1
                continue
            table_cells = None
            if not line.strip():
                last_table_end = i
            i += 1
            continue
        if is_row(line):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if DELIMITER.match(nxt) and "-" in nxt:
                table_cells = cells(line)
                if cells(nxt) != table_cells:
                    out.append("%s:%d: the delimiter row has %d cells; the header has %d"
                               % (label, i + 2, cells(nxt), table_cells))
                i += 2
                continue
            prev_blank_after_table = last_table_end is not None and all(
                not lines[k].strip() for k in range(last_table_end, i))
            if prev_blank_after_table:
                out.append("%s:%d: a blank line at line %d splits this row from the table above it"
                           % (label, i + 1, last_table_end + 1))
            else:
                out.append("%s:%d: a table row with no table: no header and delimiter row above it" % (label, i + 1))
            # skip the rest of this stray block
            while i < len(lines) and is_row(lines[i]):
                i += 1
            continue
        if line.strip():
            last_table_end = None
        i += 1
    return out


def default_files(root):
    files = [os.path.join(root, "README.md")]
    for folder, _, names in os.walk(os.path.join(root, "docs")):
        files += [os.path.join(folder, n) for n in sorted(names) if n.endswith(".md")]
    return sorted(f for f in files if os.path.isfile(f))


def main(argv, root=ROOT):
    files = [os.path.abspath(a) for a in argv] if argv else default_files(root)
    problems = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            problems += problems_in(fh.read(), os.path.relpath(path, root))
    for p in problems:
        print("markdown-tables:", p, file=sys.stderr)
    if problems:
        return 1
    print("markdown-tables: ok, %d files" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
