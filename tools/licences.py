#!/usr/bin/env python3
"""The licence of every pack and model module, its flags, and the build
profile it belongs to: one fact per pack, everything else derived.

  REUSE.toml     gives each file its SPDX licence (https://reuse.software). A
                 pack has exactly one: the licence of its directory.
  licences.toml  gives each licence id its flags: commercial, share_alike,
                 attribution, field_of_use, distribution.
  profiles       open           commercial "yes", no share-alike, no field of use
                 open+copyleft  open, and share-alike licences
                 everything     every public pack
                 A pack's profile is the narrowest that holds its own licence
                 and the licence of every model module it uses (transitively).

From these this tool writes, at the repository root:

  licences.json  for machines: the flags of each licence and every pack and
                 module whose licence is not Apache-2.0 or whose profile is
                 not `open`. A pack it does not list is Apache-2.0, profile open.
  LICENSING.md   the same for people.

Usage (run with -I; standard library only):

  python3 -I tools/licences.py              write licences.json and LICENSING.md
  python3 -I tools/licences.py --check      exit 1 when a label is missing or
                                            unknown, a pack has two licences, a
                                            licence text is missing from LICENSES/,
                                            or the two files are stale
  python3 -I tools/licences.py --list [--profile P]
                                            every pack (or every pack of profile
                                            P): directory, format, licence, profile
  python3 -I tools/licences.py --totals     the number of packs in each profile
"""
import json
import os
import re
import subprocess
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES = ["open", "open+copyleft", "everything"]
PROFILE_TEXT = {
    "open": "commercial use permitted, no share-alike, no field-of-use restriction (the default build)",
    "open+copyleft": "open, and packs whose licence is share-alike",
    "everything": "every public pack, also non-commercial, unknown and field-of-use licences",
}
DEFAULT = "Apache-2.0"
FLAGS = ("commercial", "share_alike", "attribution", "field_of_use", "distribution")


class LicenceError(Exception):
    pass


# --------------------------------------------------------------------------
# REUSE.toml
# --------------------------------------------------------------------------

def glob_regex(pattern):
    """A REUSE.toml path glob as a regular expression: `*` matches within one
    path component, `**` across components, and a backslash escapes."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def annotations(root):
    """[(compiled globs, licence id)] of REUSE.toml, in order. A tree with no
    REUSE.toml (a test tree, an assembled overlay without one) is all Apache-2.0."""
    path = os.path.join(root, "REUSE.toml")
    if not os.path.isfile(path):
        return [([glob_regex("**")], DEFAULT)]
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    out = []
    for a in data.get("annotations", []):
        if a.get("precedence") != "override":
            raise LicenceError('REUSE.toml: every annotation takes precedence = "override" (%s)' % a.get("path"))
        paths = a.get("path")
        paths = [paths] if isinstance(paths, str) else list(paths or [])
        lic = a.get("SPDX-License-Identifier")
        if not paths or not isinstance(lic, str):
            raise LicenceError("REUSE.toml: an annotation without path or SPDX-License-Identifier")
        out.append(([glob_regex(p) for p in paths], lic.strip()))
    return out


def licence_of(rules, path):
    """The licence REUSE.toml gives `path` (the last matching annotation)."""
    found = None
    for globs, lic in rules:
        if any(g.match(path) for g in globs):
            found = lic
    return found


# --------------------------------------------------------------------------
# The tree
# --------------------------------------------------------------------------

def table(root):
    """{licence id: flags} of licences.toml; Apache-2.0 alone in a tree without one."""
    path = os.path.join(root, "licences.toml")
    if not os.path.isfile(path):
        return {DEFAULT: {"commercial": "yes", "share_alike": False, "attribution": True,
                          "field_of_use": [], "distribution": "public"}}
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    out = {}
    for lid, row in data.get("licences", {}).items():
        missing = [f for f in FLAGS if f not in row]
        if missing:
            raise LicenceError("licences.toml: %s has no %s" % (lid, ", ".join(missing)))
        if row["commercial"] not in ("yes", "no", "unknown"):
            raise LicenceError("licences.toml: %s: commercial is not yes, no or unknown" % lid)
        if row["distribution"] not in ("public", "controlled"):
            raise LicenceError("licences.toml: %s: distribution is not public or controlled" % lid)
        out[lid] = row
    return out


def licence_profile(flags):
    """The narrowest profile that holds a licence; None for `controlled`."""
    if flags["distribution"] != "public":
        return None
    if flags["commercial"] == "yes" and not flags["field_of_use"]:
        return "open" if not flags["share_alike"] else "open+copyleft"
    return "everything"


def _first_args(path, word):
    found = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^%s\s+(\S+)" % word, line)
            if m:
                found.append(m.group(1).strip('"'))
    return found


def tracked(root):
    """The files git tracks under packs/ and model/, or every file there when
    the tree is not a git checkout."""
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--", "packs", "model"],
                             capture_output=True, check=True).stdout
        files = [p for p in out.decode("utf-8").split("\0") if p]
        if files:
            return files
    except (OSError, subprocess.CalledProcessError):
        pass
    files = []
    for top in ("packs", "model"):
        for folder, _, names in os.walk(os.path.join(root, top)):
            files += [os.path.relpath(os.path.join(folder, n), root).replace(os.sep, "/") for n in names]
    return sorted(files)


def survey(root, every_file=True):
    """Every pack and module with its licence and profile. `every_file` also
    checks that each file of a pack carries the pack's licence (the check of
    --check; slower).
    -> {"licences": {id: flags}, "packs": {dir: row}, "modules": {file: row}, "problems": [..]}"""
    rules, flags = annotations(root), table(root)
    problems = []
    modules, by_name = {}, {}
    model_dir = os.path.join(root, "model")
    for fname in sorted(os.listdir(model_dir)) if os.path.isdir(model_dir) else []:
        if not fname.endswith(".def"):
            continue
        path = os.path.join(model_dir, fname)
        names = _first_args(path, "module")
        lid = licence_of(rules, "model/" + fname)
        modules[fname] = {"module": names[0] if names else None, "licence": lid,
                          "uses": _first_args(path, "uses")}
        if names:
            by_name[names[0]] = fname
    packs = {}
    packs_dir = os.path.join(root, "packs")
    for d in sorted(os.listdir(packs_dir)) if os.path.isdir(packs_dir) else []:
        path = os.path.join(packs_dir, d, "pack.def")
        if not os.path.isfile(path):
            continue
        fmt = _first_args(path, "format")
        packs[d] = {"format": fmt[0] if fmt else None, "licence": licence_of(rules, "packs/%s/pack.def" % d),
                    "uses": _first_args(path, "uses"), "sources": len(_first_args(path, "source"))}

    def own_profile(kind, key, lid):
        if lid is None:
            problems.append("%s %s has no licence in REUSE.toml" % (kind, key))
            return "everything"
        if lid not in flags:
            problems.append("%s %s: licence %s is not in licences.toml" % (kind, key, lid))
            return "everything"
        p = licence_profile(flags[lid])
        if p is None:
            problems.append("%s %s: licence %s is controlled; it cannot be in the public repository" % (kind, key, lid))
            return "everything"
        return p

    rank = PROFILES.index
    for fname, row in modules.items():
        row["profile"] = own_profile("model", fname, row["licence"])
        row["because"] = None
    changed = True
    while changed:  # a module is as narrow as the modules it uses
        changed = False
        for fname, row in modules.items():
            for u in row["uses"]:
                dep = modules.get(by_name.get(u))
                if dep and rank(dep["profile"]) > rank(row["profile"]):
                    row["profile"], row["because"] = dep["profile"], "uses module %s (%s)" % (u, dep["licence"])
                    changed = True
    for d, row in packs.items():
        row["profile"] = own_profile("pack", d, row["licence"])
        row["because"] = None
        for u in row["uses"]:
            dep = modules.get(by_name.get(u))
            if dep and rank(dep["profile"]) > rank(row["profile"]):
                row["profile"] = dep["profile"]
                row["because"] = "uses module %s (%s)" % (u, dep["licence"])
        if row["sources"] == 0:
            problems.append("pack %s has no source line" % d)
    # one licence per pack: every file of its directory carries the pack's licence
    for rel in tracked(root) if every_file else []:
        parts = rel.split("/")
        if parts[0] == "packs" and len(parts) > 2 and parts[1] in packs:
            lid = licence_of(rules, rel)
            if lid != packs[parts[1]]["licence"]:
                problems.append("%s is %s but its pack %s is %s; a pack has one licence"
                                % (rel, lid, parts[1], packs[parts[1]]["licence"]))
    return {"licences": flags, "packs": packs, "modules": modules, "problems": problems}


def in_profile(pack_profile, profile):
    """True when a pack of profile `pack_profile` is in a build of `profile`."""
    return PROFILES.index(pack_profile) <= PROFILES.index(profile)


def pack_profiles(root):
    """{pack directory: profile} of every pack; raises LicenceError on a
    problem that leaves a pack unclassified."""
    s = survey(root, every_file=False)
    return {d: row["profile"] for d, row in s["packs"].items()}


def excluded(root, profile):
    """What a build of `profile` leaves out.
    -> {"packs": {dir: why}, "modules": {file: why}, "formats": set of format names}"""
    if profile not in PROFILES:
        raise LicenceError("profile %s is not one of %s" % (profile, ", ".join(PROFILES)))
    flags = table(root)
    named = {lid for _, lid in annotations(root)}
    if all(lid in flags and in_profile(licence_profile(flags[lid]) or "everything", profile) for lid in named):
        return {"packs": {}, "modules": {}, "formats": set()}  # no file of the tree is outside the profile
    s = survey(root, every_file=False)
    packs, modules, formats = {}, {}, set()
    for d, row in s["packs"].items():
        if not in_profile(row["profile"], profile):
            packs[d] = row["because"] or "%s (profile %s)" % (row["licence"], row["profile"])
            if row["format"]:
                formats.add(row["format"])
    for f, row in s["modules"].items():
        if not in_profile(row["profile"], profile):
            modules[f] = row["because"] or "%s (profile %s)" % (row["licence"], row["profile"])
    return {"packs": packs, "modules": modules, "formats": formats}


# --------------------------------------------------------------------------
# The generated files
# --------------------------------------------------------------------------

def listed(row):
    return row["licence"] != DEFAULT or row["profile"] != "open"


def licences_json(s):
    used = sorted({r["licence"] for r in list(s["packs"].values()) + list(s["modules"].values()) if r["licence"]})
    doc = {
        "generated_by": "tools/licences.py from REUSE.toml and licences.toml; do not edit",
        "default": {"licence": DEFAULT, "profile": "open"},
        "profiles": {p: PROFILE_TEXT[p] for p in PROFILES},
        "licences": {lid: dict({k: s["licences"][lid][k] for k in ("name", "url") if k in s["licences"][lid]},
                               **{f: s["licences"][lid][f] for f in FLAGS},
                               profile=licence_profile(s["licences"][lid]))
                     for lid in sorted(s["licences"]) if lid in used},
        "packs": {d: {"format": r["format"], "licence": r["licence"], "profile": r["profile"],
                      **({"because": r["because"]} if r["because"] else {})}
                  for d, r in s["packs"].items() if listed(r)},
        "modules": {f: {"module": r["module"], "licence": r["licence"], "profile": r["profile"],
                        **({"because": r["because"]} if r["because"] else {})}
                    for f, r in s["modules"].items() if listed(r)},
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def yes_no(v):
    return {True: "yes", False: "no"}.get(v, v)


def licensing_md(s):
    used = sorted({r["licence"] for r in list(s["packs"].values()) + list(s["modules"].values()) if r["licence"]})
    out = ["<!-- Generated by tools/licences.py from REUSE.toml and licences.toml. Do not edit. -->",
           "# Licensing", "",
           "The library's code, and its restatements of message formats, are under the",
           "Apache License 2.0. A format whose source allows less is still included, with",
           "its real licence on the pack, so that a build can leave it out. Each pack has",
           "one SPDX licence, given in [REUSE.toml](REUSE.toml) (the",
           "[REUSE](https://reuse.software) specification, read by `reuse lint` and SBOM",
           "tools); [licences.toml](licences.toml) gives each licence its flags; the",
           "profile of a pack follows from those. [licences.json](licences.json) holds the",
           "same as this page, for machines.", "",
           "## Profiles", "",
           "| Profile | Holds |", "|---|---|"]
    out += ["| `%s` | %s |" % (p, PROFILE_TEXT[p]) for p in PROFILES]
    out += ["",
            "A pack's profile is the narrowest that holds its own licence and the licence of",
            "every model module it uses. Build with a profile to leave out what it does not",
            "hold: `tools/goat-pkg plan|bundle|archive --profile <profile>` (default `open`).",
            "A bundle or archive of `open` leaves out every pack below, every model module",
            "below, and every vector of another pack that converts from or to one of them.",
            "",
            "## Licences in use", "",
            "| Licence | Commercial use | Share-alike | Attribution | Field of use | Profile |",
            "|---|---|---|---|---|---|"]
    for lid in used:
        f = s["licences"].get(lid)
        if f is None:
            out.append("| %s | not in licences.toml | | | | |" % lid)
            continue
        name = "[%s](%s)" % (lid, f["url"]) if f.get("url") else lid
        out.append("| %s | %s | %s | %s | %s | `%s` |" % (
            name, yes_no(f["commercial"]), yes_no(f["share_alike"]), yes_no(f["attribution"]),
            ", ".join(f["field_of_use"]) or "none", licence_profile(f)))
    packs = [(d, r) for d, r in s["packs"].items() if listed(r)]
    mods = [(f, r) for f, r in s["modules"].items() if listed(r)]
    out += ["", "## Packs outside `open`, or not under Apache-2.0", ""]
    if packs:
        out += ["| Pack | Format | Licence | Profile | Why |", "|---|---|---|---|---|"]
        out += ["| `packs/%s` | `%s` | %s | `%s` | %s |" % (d, r["format"], r["licence"], r["profile"],
                                                          r["because"] or "its own licence") for d, r in packs]
    else:
        out.append("None: every pack is Apache-2.0, profile `open`.")
    out += ["", "## Model modules outside `open`, or not under Apache-2.0", ""]
    if mods:
        out += ["| Module | Licence | Profile | Why |", "|---|---|---|---|"]
        out += ["| `model/%s` | %s | `%s` | %s |" % (f, r["licence"], r["profile"], r["because"] or "its own licence")
                for f, r in mods]
    else:
        out.append("None.")
    out += ["", "Every pack and module not listed here is Apache-2.0, profile `open`.",
            "[NOTICE](NOTICE) carries the attribution each licence asks for.", ""]
    return "\n".join(out)


def outputs(root):
    s = survey(root)
    return s, {"licences.json": licences_json(s), "LICENSING.md": licensing_md(s)}


def check(root):
    s, files = outputs(root)
    problems = list(s["problems"])
    used = {r["licence"] for r in list(s["packs"].values()) + list(s["modules"].values()) if r["licence"]}
    for lid in sorted(used):
        if not os.path.isfile(os.path.join(root, "LICENSES", lid + ".txt")):
            problems.append("LICENSES/%s.txt is missing (reuse download %s)" % (lid, lid))
    for d, r in s["packs"].items():  # the open profile holds nothing restricted
        if r["profile"] == "open":
            f = s["licences"].get(r["licence"])
            if f and (f["commercial"] != "yes" or f["share_alike"] or f["field_of_use"]):
                problems.append("pack %s is in open but its licence %s is restricted" % (d, r["licence"]))
    for name, text in files.items():
        try:
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                current = fh.read() == text
        except OSError:
            current = False
        if not current:
            problems.append("%s is stale: run python3 -I tools/licences.py" % name)
    return problems


def main(argv, root=ROOT):
    try:
        if argv == ["--check"]:
            problems = check(root)
            for p in problems:
                print("licences:", p, file=sys.stderr)
            if problems:
                return 1
            print("licences: every pack has one known licence; licences.json and LICENSING.md are current")
            return 0
        if argv == ["--totals"]:
            s = survey(root)
            for p in PROFILES:
                print("%s\t%d" % (p, sum(1 for r in s["packs"].values() if in_profile(r["profile"], p))))
            return 0
        if argv[:1] == ["--list"]:
            profile = None
            if argv[1:2] == ["--profile"] and len(argv) == 3:
                profile = argv[2]
                if profile not in PROFILES:
                    print("licences: profile %s is not one of %s" % (profile, ", ".join(PROFILES)), file=sys.stderr)
                    return 2
            elif len(argv) != 1:
                print(__doc__, file=sys.stderr)
                return 2
            for d, r in survey(root)["packs"].items():
                if profile is None or in_profile(r["profile"], profile):
                    print("%s\t%s\t%s\t%s" % (d, r["format"], r["licence"], r["profile"]))
            return 0
        if argv:
            print(__doc__, file=sys.stderr)
            return 2
        s, files = outputs(root)
        for name, text in files.items():
            with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        for p in s["problems"]:
            print("licences:", p, file=sys.stderr)
        print("licences: wrote licences.json and LICENSING.md")
        return 1 if s["problems"] else 0
    except (LicenceError, OSError, tomllib.TOMLDecodeError) as e:
        print("licences: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
