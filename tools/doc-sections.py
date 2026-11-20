#!/usr/bin/env python3
"""Write sections that appear both in README.md and on the site
(site/index.html) from one Markdown source, so the two cannot drift.

Each section is a file docs/<name>-section.md. README.md holds it, as
Markdown, between the lines

    <!-- section <name>: generated from docs/<name>-section.md by tools/doc-sections.py; edit that file -->
    <!-- /section <name> -->

and site/index.html holds it, as HTML, between the same two comments. Paths
in the source are relative to the repository root: README.md uses them as
they are; the site turns a link into its address on GitHub and an image under
site/ into its path from the page.

The Markdown the source may use: one `## ` heading first, `### ` headings,
paragraphs, `- ` lists, tables, an image alone on a line, and inside text
`code`, **bold** and [links](path). Anything else is an error.

    python3 -I tools/doc-sections.py            rewrite both files
    python3 -I tools/doc-sections.py --check    exit 1 when either is stale
"""
import html
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS = ["shared-model"]
GITHUB = "https://github.com/USAREUR-AF/goat-transformers/blob/main/"


class SectionError(Exception):
    pass


def markers(name):
    return ("<!-- section %s: generated from docs/%s-section.md by tools/doc-sections.py; edit that file -->"
            % (name, name), "<!-- /section %s -->" % name)


def blocks(text):
    """The source as [(kind, lines)]: heading2, heading3, para, list, table, image."""
    out, cur = [], []

    def flush():
        if cur:
            first = cur[0]
            if first.startswith("## "):
                kind = "heading2"
            elif first.startswith("### "):
                kind = "heading3"
            elif first.startswith("|"):
                kind = "table"
            elif first.startswith("- "):
                kind = "list"
            elif re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", first) and len(cur) == 1:
                kind = "image"
            elif first.startswith(("#", ">", "```", "* ", "1. ", "<")):
                raise SectionError("unsupported Markdown: %r" % first[:40])
            else:
                kind = "para"
            out.append((kind, list(cur)))
            cur.clear()

    for line in text.splitlines():
        if not line.strip():
            flush()
        else:
            cur.append(line.rstrip())
    flush()
    if not out or out[0][0] != "heading2" or any(k == "heading2" for k, _ in out[1:]):
        raise SectionError("a section has one '## ' heading, first")
    return out


def site_href(path):
    if re.match(r"^[a-z]+:", path) or path.startswith("#"):
        return path
    if path.startswith("site/"):
        return path[len("site/"):]
    return GITHUB + path


def inline(text):
    """Inline Markdown as HTML: `code`, **bold**, [text](path)."""
    out, i = [], 0
    pattern = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)]+)\)")
    for m in pattern.finditer(text):
        out.append(html.escape(text[i:m.start()], quote=False))
        if m.group(1) is not None:
            out.append("<code>%s</code>" % html.escape(m.group(1), quote=False))
        elif m.group(2) is not None:
            out.append("<b>%s</b>" % inline(m.group(2)))
        else:
            out.append('<a href="%s">%s</a>' % (html.escape(site_href(m.group(4))), inline(m.group(3))))
        i = m.end()
    out.append(html.escape(text[i:], quote=False))
    return "".join(out)


def cells(row):
    row = row.strip()
    if not (row.startswith("|") and row.endswith("|")):
        raise SectionError("a table row starts and ends with |: %r" % row[:40])
    return [c.strip() for c in row[1:-1].split("|")]


def to_html(name, text):
    parts = blocks(text)
    title = parts[0][1][0][3:]
    hid = "h-" + name
    out = ['<section id="%s" aria-labelledby="%s">' % (name, hid), '  <div class="wrap">',
           '    <p class="tag">Under the hood</p>', '    <h2 id="%s">%s</h2>' % (hid, inline(title))]
    for kind, lines in parts[1:]:
        if kind == "heading3":
            out.append("    <h3>%s</h3>" % inline(lines[0][4:]))
        elif kind == "para":
            out.append("    <p>%s</p>" % inline(" ".join(lines)))
        elif kind == "list":
            items, cur = [], None
            for line in lines:
                if line.startswith("- "):
                    if cur is not None:
                        items.append(cur)
                    cur = line[2:]
                else:
                    cur += " " + line.strip()
            items.append(cur)
            out.append("    <ul>" + "".join("<li>%s</li>" % inline(x) for x in items) + "</ul>")
        elif kind == "image":
            m = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", lines[0])
            out.append('    <figure><div class="scroll"><img src="%s" alt="%s"></div></figure>'
                       % (html.escape(site_href(m.group(2))), html.escape(m.group(1))))
        elif kind == "table":
            head = cells(lines[0])
            if len(lines) < 2 or not all(set(c) <= set("-: ") for c in cells(lines[1])):
                raise SectionError("a table has a header row and a --- row")
            rows = [cells(r) for r in lines[2:]]
            if any(len(r) != len(head) for r in rows):
                raise SectionError("a table row has another number of cells than its header")
            out.append('    <div class="table-scroll"><table>')
            out.append("      <thead><tr>%s</tr></thead>" % "".join("<th>%s</th>" % inline(c) for c in head))
            out.append("      <tbody>")
            for r in rows:
                out.append("        <tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in r))
            out.append("      </tbody>")
            out.append("    </table></div>")
    out += ["  </div>", "</section>"]
    return "\n".join(out)


def splice(text, label, name, body, where):
    """`text` with the section's body between its markers. Text without the
    markers gets them before the first line `where`."""
    start, end = markers(name)
    block = start + "\n" + body.rstrip("\n") + "\n" + end
    if start in text and end in text:
        return text[:text.index(start)] + block + text[text.index(end) + len(end):]
    if where not in text:
        raise SectionError("%s: no markers and no %r to place them before" % (label, where))
    i = text.index(where)
    return text[:i] + block + "\n\n" + text[i:]


def outputs(root=ROOT):
    """{path: text} of README.md and site/index.html with every section written."""
    targets = [(os.path.join(root, "README.md"), "## Contributing, security, license", False),
               (os.path.join(root, "site", "index.html"), "</main>", True)]
    files = {}
    for path, _, _ in targets:
        with open(path, encoding="utf-8") as fh:
            files[path] = fh.read()
    for name in SECTIONS:
        with open(os.path.join(root, "docs", "%s-section.md" % name), encoding="utf-8") as fh:
            source = fh.read()
        rendered = to_html(name, source)  # refuses what the site cannot render
        for path, where, is_html in targets:
            files[path] = splice(files[path], os.path.relpath(path, root), name,
                                 rendered if is_html else source, where)
    return files


def main(argv, root=ROOT):
    try:
        files = outputs(root)
    except (SectionError, OSError) as e:
        print("doc-sections: %s" % e, file=sys.stderr)
        return 1
    stale = []
    for path, text in files.items():
        with open(path, encoding="utf-8") as fh:
            if fh.read() != text:
                stale.append(path)
    if argv == ["--check"]:
        for path in stale:
            print("doc-sections: %s is stale: run python3 -I tools/doc-sections.py"
                  % os.path.relpath(path, root), file=sys.stderr)
        return 1 if stale else 0
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    for path in stale:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(files[path])
    print("doc-sections: %d file(s) written" % len(stale))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
