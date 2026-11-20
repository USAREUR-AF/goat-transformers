#!/usr/bin/env python3
"""catalog-figure: draw every public format family of packs/, by domain.

Writes docs/figures/catalog-light.svg and docs/figures/catalog-dark.svg: one
tile for each family of formats, with the number of packs it holds, grouped
in labelled bands by domain (air, land vehicles, sea, space, uncrewed systems,
C2 and tactical, sensors, transport, IoT, networks, maps). README.md and
docs/coverage-roadmap.md show the figure.

Usage:
  python3 -I tools/catalog-figure.py                   write both figures
  python3 -I tools/catalog-figure.py --check           write nothing; exit 1
                                                       when either figure
                                                       differs from what this
                                                       run would write
  python3 -I tools/catalog-figure.py --check-families  write nothing; exit 1
                                                       when a pack has no
                                                       family or a family has
                                                       no pack

The modes and who runs them:
  --check-families   CI runs it on every pull request (the `tools` job of
                     .github/workflows/conformance.yml). It fails only when the
                     family table is wrong: a new pack that no family holds, or
                     a family whose packs are gone. It does not compare counts.
  --check            the counts pull request runs it, with tools/repo-stats,
                     after it has written the figures again. The figures carry
                     pack counts, and counts are brought up to date only in the
                     counts pull request, so this mode is not a CI step.
  (no option)        writes the figures; the counts pull request runs it.

Where the families come from: tools/catalog-families/ holds one file per
family (a display name, a domain, and the pack names (`exact`) or name
beginnings (`prefixes`) that belong to it) and _domains.json (the domains and
the synthetic prefixes). A pack belongs to the family that names it in
`exact`, else to the family with the longest prefix that begins its name; two
families that hold a pack equally stop the tool. One file per family means a
pull request that adds a pack never edits a line another pull request edits.
A pack whose name starts with one of
`synthetic_prefixes` (`conformance`, `demo-`: the formats that exercise the
specification, as tools/repo-stats counts them) is not drawn. Every other
directory of packs/ that holds a pack.def must belong to a family, or this
tool stops and names the pack; so a new family cannot be left out silently.

What it guarantees: the output depends only on packs/ and the family table.
It is sorted, has no timestamp, uses \\n line ends and plain integer
coordinates, so it is the same bytes on every platform. Text is placed with a
width table that takes, for each character, the widest of the fonts the
figure's font stack can resolve to (-apple-system, Segoe UI, Helvetica,
Arial, Liberation Sans, DejaVu Sans), plus 6 per cent; a label that fits here
fits in each of them. Standard library only; it reads files and runs nothing.
"""
import argparse
import json
import os
import re
import sys
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FAMILIES = os.path.join(HERE, "catalog-families")
OUT_NAMES = ("catalog-light.svg", "catalog-dark.svg")

# Advance widths in 1/1000 em of the characters 32 to 126, the maximum over the
# fonts of the stack below (measured in Chrome; DejaVu Sans is the widest of
# most). Any other character counts as 1000.
_REGULAR = (
    "318 401 460 838 636 950 780 275 390 390 500 838 318 361 318 337 636 636 636 636 636 636 636 636 636 636 "
    "337 337 838 838 838 556 1015 684 686 722 770 667 611 778 752 295 500 667 557 863 748 787 667 787 722 667 "
    "611 732 684 989 685 667 685 390 337 390 838 556 500 613 635 550 635 615 352 635 634 278 278 579 278 974 "
    "634 612 635 635 411 521 392 634 592 818 592 592 525 636 337 636 838")
_BOLD = (
    "348 456 521 838 696 1002 872 306 457 457 523 838 380 415 380 365 696 696 696 696 696 696 696 696 696 696 "
    "400 400 838 838 838 611 1000 774 762 734 830 683 683 821 837 372 556 775 637 995 837 850 733 850 770 720 "
    "682 812 774 1103 771 724 725 457 365 457 838 556 500 675 716 593 716 678 435 716 712 343 343 665 343 1042 "
    "712 687 716 716 493 595 478 712 652 924 645 652 582 712 365 712 838")
WIDTHS = {False: [int(v) for v in _REGULAR.split()], True: [int(v) for v in _BOLD.split()]}
MARGIN_OF_SAFETY = 1.06

FONT = '-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,"Liberation Sans","DejaVu Sans",sans-serif'

THEMES = {
    "light": {"bg": "#ffffff", "ink": "#1f2328", "quiet": "#59636e", "num": "#0969da",
              "tile": "#f6f8fa", "edge": "#d1d9e0", "rule": "#d1d9e0"},
    "dark": {"bg": "#0d1117", "ink": "#e6edf3", "quiet": "#9198a1", "num": "#4493f8",
             "tile": "#161b22", "edge": "#3d444d", "rule": "#3d444d"},
}

# Layout, in units of a 760-wide view box (one unit is one pixel at README width).
WIDTH = 760
SIDE = 20
COLUMNS = 4
GAP = 8
CELL = (WIDTH - 2 * SIDE - (COLUMNS - 1) * GAP) // COLUMNS   # 174
PAD = 12                 # text to the tile's side edges
NAME_SIZE, DETAIL_SIZE = 14, 13
TILE_H = 34              # one line: the name and the count
NAME_BASE = 22           # name baseline below the tile's top
DETAIL_STEP = 17         # each further line of detail
TITLE_SIZE, SUB_SIZE, HEAD_SIZE = 18, 13, 15


class CatalogError(Exception):
    """A pack with no family, a family with no pack, or a broken table."""


def text_width(text, size, bold=False):
    table = WIDTHS[bold]
    units = sum(table[ord(c) - 32] if 32 <= ord(c) <= 126 else 1000 for c in text)
    return units * size / 1000.0 * MARGIN_OF_SAFETY


def wrap(text, width, size, bold=False):
    """Greedy wrap at spaces into lines no wider than `width`; then move words
    down so the last line does not hold one word under a longer line."""
    words = text.split()
    lines = []
    for w in words:
        if lines and text_width(lines[-1] + " " + w, size, bold) <= width:
            lines[-1] += " " + w
        else:
            lines.append(w)
    if len(lines) > 1 and " " not in lines[-1]:
        prev = lines[-2].split()
        candidate = prev[-1] + " " + lines[-1]
        if len(prev) > 2 and text_width(candidate, size, bold) <= width:
            lines[-2], lines[-1] = " ".join(prev[:-1]), candidate
    return lines


def grouped(n):
    return "{:,}".format(n)


def is_synthetic(name, prefixes):
    return any(name.startswith(p) for p in prefixes)


def load_table(path=FAMILIES):
    """The table: _domains.json, and every other *.json of the directory as one
    family, in file-name order."""
    with open(os.path.join(path, "_domains.json"), encoding="utf-8") as fh:
        table = json.load(fh)
    table["families"] = []
    for name in sorted(os.listdir(path)):
        if name.endswith(".json") and name != "_domains.json":
            with open(os.path.join(path, name), encoding="utf-8") as fh:
                fam = json.load(fh)
            fam["file"] = name
            table["families"].append(fam)
    ids = [d["id"] for d in table["domains"]]
    for fam in table["families"]:
        if fam["domain"] not in ids:
            raise CatalogError("family %r names the domain %r, which the table does not list" % (fam["name"], fam["domain"]))
        if not fam.get("exact") and not fam.get("prefixes"):
            raise CatalogError("family %r has neither `exact` nor `prefixes`" % fam["name"])
    return table


def pack_names(packs_dir):
    if not os.path.isdir(packs_dir):
        raise CatalogError("no packs directory at %s" % packs_dir)
    return sorted(n for n in os.listdir(packs_dir) if os.path.isfile(os.path.join(packs_dir, n, "pack.def")))


def classify(table, names):
    """-> (domains, synthetic count). Each domain: {name, families: [{name,
    packs, detail}]}, families by pack count, largest first. Raises
    CatalogError naming every pack that no family holds, and every family
    that holds no pack."""
    held = {i: [] for i in range(len(table["families"]))}
    unplaced, ambiguous, synthetic = [], [], 0
    for name in names:
        if is_synthetic(name, table["synthetic_prefixes"]):
            synthetic += 1
            continue
        exact = [i for i, fam in enumerate(table["families"]) if name in fam.get("exact", ())]
        if exact:
            best = exact
        else:
            longest = 0
            best = []
            for i, fam in enumerate(table["families"]):
                for p in fam.get("prefixes", ()):
                    if name.startswith(p):
                        if len(p) > longest:
                            longest, best = len(p), [i]
                        elif len(p) == longest and i not in best:
                            best.append(i)
        if len(best) == 1:
            held[best[0]].append(name)
        elif best:
            ambiguous.append("%s (%s)" % (name, ", ".join(table["families"][i]["file"] for i in best)))
        else:
            unplaced.append(name)
    empty = [fam["name"] for i, fam in enumerate(table["families"]) if not held[i]]
    problems = []
    if unplaced:
        problems.append(
            "no family in tools/catalog-families/ holds the pack%s %s. In the same pull request, add %s to "
            "the \"exact\" list of its family's file in tools/catalog-families/ (or add a file for a new family "
            "with a name, a domain and an \"exact\" list), then run "
            "`python3 -I tools/catalog-figure.py --check-families`"
            % ("s" if len(unplaced) > 1 else "", ", ".join(unplaced), "each" if len(unplaced) > 1 else "it"))
    if ambiguous:
        problems.append("two families hold the pack%s %s equally: name it in the \"exact\" list of one"
                        % ("s" if len(ambiguous) > 1 else "", "; ".join(ambiguous)))
    if empty:
        problems.append("no pack belongs to the famil%s %s" % ("ies" if len(empty) > 1 else "y", ", ".join(empty)))
    if problems:
        raise CatalogError("; ".join(problems))
    domains = []
    for dom in table["domains"]:
        fams = []
        for i, fam in enumerate(table["families"]):
            if fam["domain"] != dom["id"]:
                continue
            fams.append({"name": fam["name"], "packs": len(held[i]), "detail": detail_of(fam, held[i])})
        fams.sort(key=lambda f: (-f["packs"], f["name"].lower()))
        if fams:
            domains.append({"name": dom["name"], "families": fams})
    return domains, synthetic


def detail_of(fam, packs):
    if "detail" in fam:
        return fam["detail"]
    m = fam.get("members")
    if not m:
        return ""
    pat = re.compile(m["pattern"])
    values = sorted({mt.group(1) for mt in (pat.match(p) for p in packs) if mt})
    if m.get("upper"):
        values = [m.get("rename", {}).get(v, v.upper()) for v in values]
    label = m.get("label", "").format(n=len(values))
    if m.get("list", True) is False:
        return label
    listed = ", ".join(values)
    return label + ": " + listed if label else listed


# ---- layout ----------------------------------------------------------------

INNER = WIDTH - 2 * SIDE
MIN_TILE = 96


def size_tile(fam):
    """-> (width, detail lines): the narrowest tile that holds the name and
    the count on one line and the detail on one line, or, when the detail is
    longer than a line of the figure, the full width with the detail wrapped."""
    count = grouped(fam["packs"])
    head = PAD + text_width(fam["name"], NAME_SIZE) + PAD + text_width(count, NAME_SIZE, True) + PAD
    if head > INNER:
        raise CatalogError("the family name %r is too long for a tile" % fam["name"])
    need = max(head, MIN_TILE)
    if not fam["detail"]:
        return need, []
    one = PAD + text_width(fam["detail"], DETAIL_SIZE) + PAD
    if one <= INNER:
        return max(need, one), [fam["detail"]]
    return INNER, wrap(fam["detail"], INNER - 2 * PAD, DETAIL_SIZE)


def _fill(tiles, nrows):
    """Each tile, widest first, into the row with the most room that holds
    it; None when one does not fit."""
    rows = [{"used": -GAP, "tiles": []} for _ in range(nrows)]
    for t in sorted(tiles, key=lambda t: (-t["w"], t["order"])):
        room = [r for r in rows if r["used"] + GAP + t["w"] <= INNER]
        if not room:
            return None
        row = min(room, key=lambda r: (r["used"], rows.index(r)))
        row["tiles"].append(t)
        row["used"] += GAP + t["w"]
    return rows


def pack_rows(fams):
    """The fewest rows that hold the tiles, with the width shared out evenly
    between the rows; within a row the families keep their order (the
    largest first), rows in the order of their largest family. Then each
    row's spare width is shared out among its tiles, so that every row ends
    at the figure's right margin."""
    tiles = []
    for i, fam in enumerate(fams):
        w, lines = size_tile(fam)
        tiles.append({"fam": fam, "w": w, "lines": lines, "order": i})
    nrows = max(1, -(-int(sum(t["w"] + GAP for t in tiles)) // (INNER + GAP)))
    rows = _fill(tiles, nrows)
    while rows is None:
        nrows += 1
        rows = _fill(tiles, nrows)
    rows = [r for r in rows if r["tiles"]]
    for row in rows:
        row["tiles"].sort(key=lambda t: t["order"])
    rows.sort(key=lambda r: r["tiles"][0]["order"])
    for row in rows:
        spare = INNER - row["used"]
        n = len(row["tiles"])
        x = 0.0
        for i, t in enumerate(row["tiles"]):
            t["x"] = round(x)
            x += t["w"] + spare / n + GAP
            t["w"] = (INNER if i == n - 1 else round(x - GAP)) - t["x"]
        row["height"] = max(TILE_H + DETAIL_STEP * len(t["lines"]) for t in row["tiles"])
    return rows


def build(domains, synthetic):
    """-> (title, desc, list of drawing items) with the view box height."""
    nfam = sum(len(d["families"]) for d in domains)
    npacks = sum(f["packs"] for d in domains for f in d["families"])
    title = "Every public format, by family: %s families, %s formats" % (grouped(nfam), grouped(npacks))
    if text_width(title, TITLE_SIZE, True) > WIDTH - 2 * SIDE:
        raise CatalogError("the title is wider than the figure")
    parts = []
    for d in domains:
        parts.append("%s: %s." % (d["name"], ", ".join("%s %s" % (f["name"], grouped(f["packs"])) for f in d["families"])))
    desc = ("%s families of public formats in %d domains, %s formats in all; each family is shown with its number "
            "of packs, counted from packs/. %s Not shown: the %s synthetic packs whose names start with "
            "conformance or demo-, which exercise the specification and stand for no real format."
            % (grouped(nfam), len(domains), grouped(npacks), " ".join(parts), grouped(synthetic)))
    items = []
    y = 20 + TITLE_SIZE
    items.append(("text", SIDE, y, title, TITLE_SIZE, True, "ink", "title"))
    sub = ("Each tile is one family and the number of its packs in packs/, in %d domains. "
           "The %s synthetic conformance and demo packs are not shown." % (len(domains), grouped(synthetic)))
    for line in wrap(sub, WIDTH - 2 * SIDE, SUB_SIZE):
        y += 20
        items.append(("text", SIDE, y, line, SUB_SIZE, False, "quiet", "note"))
    y += 14
    for d in domains:
        y += 12
        items.append(("rule", SIDE, y, WIDTH - 2 * SIDE))
        y += 12 + HEAD_SIZE
        items.append(("text", SIDE, y, d["name"], HEAD_SIZE, True, "ink", None))
        n = sum(f["packs"] for f in d["families"])
        summary = "%d famil%s, %s format%s" % (len(d["families"]), "y" if len(d["families"]) == 1 else "ies",
                                               grouped(n), "" if n == 1 else "s")
        items.append(("count", WIDTH - SIDE, y, summary, SUB_SIZE, "quiet"))
        y += 12
        for row in pack_rows(d["families"]):
            for t in row["tiles"]:
                x, w = SIDE + t["x"], t["w"]
                items.append(("tile", x, y, w, row["height"]))
                # a tile shorter than its row has its lines centred in the row's height
                top = y + (row["height"] - TILE_H - DETAIL_STEP * len(t["lines"])) // 2
                items.append(("text", x + PAD, top + NAME_BASE, t["fam"]["name"], NAME_SIZE, False, "ink", None))
                items.append(("count", x + w - PAD, top + NAME_BASE, grouped(t["fam"]["packs"]), NAME_SIZE, "num"))
                for k, line in enumerate(t["lines"]):
                    items.append(("text", x + PAD, top + NAME_BASE + DETAIL_STEP * (k + 1), line, DETAIL_SIZE, False, "quiet", None))
            y += row["height"] + GAP
        y -= GAP
    height = y + 20
    return title, desc, items, height


def render(theme, title, desc, items, height):
    c = THEMES[theme]
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="100%%" role="img" aria-labelledby="t d">' % (WIDTH, height),
           '<title id="t">%s</title>' % escape(title),
           '<desc id="d">%s</desc>' % escape(desc),
           "<style>",
           "  .cf-bg{fill:%s} .cf-ink{fill:%s} .cf-quiet{fill:%s} .cf-num{fill:%s}" % (c["bg"], c["ink"], c["quiet"], c["num"]),
           "  .cf-t{font-family:%s}" % FONT,
           "  .cf-tile{fill:%s;stroke:%s;stroke-width:1}" % (c["tile"], c["edge"]),
           "  .cf-rule{fill:%s}" % c["rule"],
           "</style>",
           '<rect x="0" y="0" width="%d" height="%d" class="cf-bg"/>' % (WIDTH, height)]
    for it in items:
        kind = it[0]
        if kind == "text":
            _, x, y, s, size, bold, cls, role = it
            out.append('<text x="%d" y="%d" class="cf-t cf-%s" font-size="%d"%s%s>%s</text>' % (
                x, y, cls, size, ' font-weight="700"' if bold else "",
                ' data-role="%s"' % role if role else "", escape(s)))
        elif kind == "count":
            _, x, y, s, size, cls = it
            out.append('<text x="%d" y="%d" class="cf-t cf-%s" font-size="%d"%s text-anchor="end">%s</text>' % (
                x, y, cls, size, ' font-weight="700"' if cls == "num" else "", escape(s)))
        elif kind == "tile":
            _, x, y, w, h = it
            out.append('<rect x="%d.5" y="%d.5" width="%d" height="%d" rx="6" class="cf-tile"/>' % (x, y, w - 1, h - 1))
        elif kind == "rule":
            _, x, y, w = it
            out.append('<rect x="%d" y="%d" width="%d" height="1" class="cf-rule"/>' % (x, y, w))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def figures(packs_dir, table):
    domains, synthetic = classify(table, pack_names(packs_dir))
    title, desc, items, height = build(domains, synthetic)
    return domains, {name: render(theme, title, desc, items, height)
                     for name, theme in zip(OUT_NAMES, ("light", "dark"))}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="catalog-figure", description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="write nothing; exit 1 when a figure differs")
    mode.add_argument("--check-families", action="store_true", help="write nothing; exit 1 when a pack has no family")
    ap.add_argument("--packs", default=os.path.join(REPO, "packs"), help=argparse.SUPPRESS)
    ap.add_argument("--families", default=FAMILIES, help=argparse.SUPPRESS)
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "figures"), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        table = load_table(args.families)
        domains, svgs = figures(args.packs, table)
    except CatalogError as e:
        print("catalog-figure: %s" % e, file=sys.stderr)
        return 1
    nfam = sum(len(d["families"]) for d in domains)
    if args.check_families:
        print("catalog-figure: every pack has a family (%d families in %d domains)" % (nfam, len(domains)))
        return 0
    if args.check:
        stale = []
        for name, svg in svgs.items():
            path = os.path.join(args.out, name)
            try:
                with open(path, "rb") as fh:
                    same = fh.read() == svg.encode("utf-8")
            except OSError:
                same = False
            if not same:
                stale.append(name)
        if stale:
            print("catalog-figure: %s differ%s from what it would write; run python3 -I tools/catalog-figure.py"
                  % (", ".join(stale), "s" if len(stale) == 1 else ""), file=sys.stderr)
            return 1
        print("catalog-figure: the figures are up to date")
        return 0
    os.makedirs(args.out, exist_ok=True)
    for name, svg in svgs.items():
        with open(os.path.join(args.out, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(svg)
    print("catalog-figure: wrote %s (%d families in %d domains)" % (", ".join(OUT_NAMES), nfam, len(domains)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
