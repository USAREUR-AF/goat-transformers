#!/usr/bin/env python3
"""Meaning is tested, not only agreement: every decoded shared-model value is
plausible, and every pack that maps a height names its vertical datum.

Seven engines that produce the same bytes for a vector show that they agree,
not that the value is right. This tool decodes the `input` of every conversion
vector (packs/*/vectors/*.json) with the Python engine of this repository
(engines/python; no second parser here), and checks each value of the decoded
entity, items of lists included, against the rules of tools/model-ranges.json:

  - a range (`min`, `max`, inclusive; a value that is not finite fails it),
  - a set of values (`one_of`, or `one_of_meaning`: the words the key's
    meaning in model/*.def lists after its last colon),
  - every int key whose meaning begins with `flag:` is 0 or 1,
  - `order`: an entity's (or a list item's) stale_ms comes no sooner than
    its time_ms.

A wire value a pack declares as a sentinel (`absent`, spec 0.9) never reaches
the entity: the engine leaves the key absent, so it is not checked.

Vectors of the synthetic packs (tools/model-ranges.json, `synthetic`: the
names beginning `conformance` or `demo-`) are skipped, and so is every vector
whose source or target is one of them: those exercise the rules of the
specification with edge values on purpose. A vector whose input does not
decode (it has `expect_error`, as a rule) has no values to check and is
counted.

The datum check: a pack that maps a height key (a key of unit m whose name or
meaning is a height or an altitude, `datum` in tools/model-ranges.json) names
the vertical datum of that height in its pack.md. A pack that maps a key of
height above the WGS 84 ellipsoid (core `hae`) names the ellipsoid; one whose
pack.md names only mean sea level, a barometric altitude or a height above
ground maps a height from another datum to the ellipsoid unless it converts,
and its pack.md says so.

The failures of today are listed in tools/model-checks-allow.txt, one per
line: `<pack>/<vector> <key> <reason>` for a value (the key as the entity
holds it, `<list>[<i>].<key>` inside a list), `<pack>/pack.md datum <reason>`
for the datum. The list is for burning down: a new failure is not added
without a reason, and a line that no longer fails is removed.

  python3 -I tools/model-checks.py            every failure, allowed or not,
                                              and the summary
  python3 -I tools/model-checks.py --check    CI: only what fails the check;
                                              exit 1 on a failure the allow
                                              file does not list, or an allow
                                              line that no longer fails
  --shard I/N    check only the pack directories whose index in name order is
                 I modulo N (each shard still loads every pack); an allow line
                 is judged only by the shard that holds its pack
  --json         the failures and the counts as one JSON object
  --root DIR     the tree (default: the repository this tool is in)
  --rules FILE   default tools/model-ranges.json beside this tool
  --allow FILE   default <root>/tools/model-checks-allow.txt

Exit status: 0 ok, 1 a check fails (with --check), 2 a wrong command line or
a tree that does not load. Standard library only; run with -I.
"""
import argparse
import base64
import glob
import json
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE_SRC = os.path.join(ROOT, "engines", "python", "src")
ALLOW_LINE = re.compile(r"^(\S+/\S+)\s+(\S+)\s+(\S.*)$")


def engine_api():
    """The Python engine of this repository, imported on first use."""
    if ENGINE_SRC not in sys.path:
        sys.path.insert(0, ENGINE_SRC)
    import goat_transformers
    return goat_transformers


class Rules:
    """tools/model-ranges.json, with the model modules the engine loaded."""

    def __init__(self, data, models):
        self.data = data
        self.models = models
        self.synthetic = tuple(data.get("synthetic", {}).get("prefixes", ()))
        self.order = data.get("order", [])
        self.meanings = {}  # key as a pack writes it -> modeldef.Key
        for mod in models.values():
            for name, key in mod.keys.items():
                self.meanings[name if mod.name == "core" else "%s.%s" % (mod.name, name)] = key
        self.by_key = {}
        for name, rule in data.get("keys", {}).items():
            rule = dict(rule)
            if rule.get("one_of_meaning"):
                key = self.meanings.get(name)
                rule["one_of"] = meaning_values(key.meaning) if key is not None and key.meaning else []
            self.by_key[name] = rule
        for rule in data.get("meaning_rules", []):
            for name, key in self.meanings.items():
                if name in self.by_key or key.type != rule.get("type"):
                    continue
                if (key.meaning or "").startswith(rule["meaning_prefix"]):
                    self.by_key[name] = rule
        datum = data.get("datum", {})
        self.terms = [(label, re.compile(rx)) for label, rx in datum.get("terms", {}).items()]
        self.heights, self.ellipsoid_keys = height_keys(datum, self.meanings)

    def is_synthetic(self, name):
        return bool(name) and name.startswith(self.synthetic)


def meaning_values(meaning):
    """The values a meaning lists after its last colon: `class: a, b or c` -> [a, b, c]."""
    tail = meaning.rsplit(":", 1)[-1].split(";")[0]
    return [w.strip() for w in re.split(r",|\bor\b", tail) if w.strip()]


def height_keys(datum, meanings):
    """-> (the height keys, the ones of them above the WGS 84 ellipsoid)."""
    if not datum:
        return set(), set()
    by_name = re.compile(datum["height_name"])
    by_meaning = re.compile(datum["height_meaning"], re.I)
    not_height = re.compile(datum["not_height"], re.I)
    ellipsoid = re.compile(datum["ellipsoid_meaning"], re.I)
    skip = datum.get("not_height_keys", {})
    units = set(datum.get("height_units", ["m"]))
    heights, ellipsoid_keys = set(), set()
    for name, key in meanings.items():
        if key.unit not in units or name in skip:
            continue
        bare = name.rsplit(".", 1)[-1]
        meaning = key.meaning or ""
        if not (by_name.search(bare) or by_meaning.search(meaning)):
            continue
        if not_height.search(meaning) or not_height.search(bare.replace("_", " ")):
            continue
        heights.add(name)
        if ellipsoid.search(meaning):
            ellipsoid_keys.add(name)
    return heights, ellipsoid_keys


def check_value(rule, value):
    """-> why the value breaks the rule, or None."""
    if "one_of" in rule:
        if value not in rule["one_of"]:
            return "not one of %s" % ", ".join(str(v) for v in rule["one_of"])
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "not a number"
    if isinstance(value, float) and not math.isfinite(value):
        return "not finite"
    if "min" in rule and value < rule["min"]:
        return "below %s" % rule["min"]
    if "max" in rule and value > rule["max"]:
        return "above %s" % rule["max"]
    return None


def check_scope(rules, scope, prefix, counts, out):
    """Check the fields of an entity or item, then its lists' items."""
    for key, value in scope.fields.items():
        rule = rules.by_key.get(key)
        if rule is None:
            continue
        counts[key] = counts.get(key, 0) + 1
        why = check_value(rule, value)
        if why:
            out.append((prefix + key, value, "%s: %s" % (why, rule.get("reason", ""))))
    for o in rules.order:
        a, b = scope.fields.get(o["earlier"]), scope.fields.get(o["later"])
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b < a:
            out.append((prefix + o["later"], b, "earlier than %s %s: %s" % (o["earlier"], a, o.get("reason", ""))))
    for name, items in scope.lists.items():
        for i, item in enumerate(items):
            check_scope(rules, item, "%s%s[%d]." % (prefix, name, i), counts, out)


def vector_input(vec):
    if "input" in vec:
        return vec["input"].encode("utf-8")
    return base64.b64decode(vec["input_b64"])


def check_vectors(api, eng, rules, root, dirs, stats):
    """-> [(location, key, value, why)] for the vectors of the pack directories `dirs`."""
    failures = []
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(root, "packs", d, "vectors", "*.json"))):
            stats["vectors"] += 1
            with open(path, encoding="utf-8") as fh:
                vec = json.load(fh)
            if rules.is_synthetic(vec.get("from")) or rules.is_synthetic(vec.get("to")):
                stats["skipped_synthetic"] += 1
                continue
            try:
                ent = eng.decode(vec["from"], vector_input(vec))
            except (api.GTError, KeyError, ValueError):
                stats["not_decoded"] += 1
                continue
            stats["decoded"] += 1
            where = "%s/%s" % (d, os.path.splitext(os.path.basename(path))[0])
            found = []
            check_scope(rules, ent, "", stats["checked"], found)
            failures += [(where, key, value, why) for key, value, why in found]
    return failures


def check_datum(eng, rules, root, dirs, by_dir):
    """-> [(location, "datum", the height keys, why)] for the packs of `dirs`."""
    failures = []
    for d in dirs:
        fmt = by_dir.get(d)
        if fmt is None:
            continue
        mapped = sorted({k.rsplit("].", 1)[-1] for k in eng.model_keys(fmt)} & rules.heights)
        if not mapped:
            continue
        path = os.path.join(root, "packs", d, "pack.md")
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = ""
        named = datum_terms(rules, text, mapped)
        ellipsoid = [k for k in mapped if k in rules.ellipsoid_keys]
        keys = ",".join(mapped)
        why = None
        if not named:
            why = "maps %s; no passage of pack.md about a height names its vertical datum" % keys
        elif ellipsoid and (named == [UNSTATED] or assumed(rules, text, ellipsoid)):
            why = ("maps %s (height above the WGS 84 ellipsoid) and pack.md says the source does not state what"
                   " that height is measured from: the binding is an assumption" % ",".join(ellipsoid))
        elif ellipsoid and ELLIPSOID not in named:
            why = ("maps %s (height above the WGS 84 ellipsoid) and pack.md names only %s for a height: such a"
                   " height is not above the ellipsoid unless the pack converts it, and pack.md says so"
                   % (",".join(ellipsoid), " and ".join(named)))
        if why:
            failures.append(("%s/pack.md" % d, "datum", keys, why))
    return failures


ELLIPSOID = "ellipsoid"
UNSTATED = "not stated by the source"
HEIGHT_WORDS = r"height|heights|altitude|altitudes|elevation|alt|ele|hae"


def passages(text):
    """pack.md cut into passages: a paragraph, a row of a table, an item of a list."""
    out, cur = [], []
    for line in text.splitlines():
        s = line.strip()
        starts_item = s.startswith("|") or re.match(r"^([-*+]|\d+\.)\s", s)
        if not s or starts_item:
            if cur:
                out.append(" ".join(cur))
            cur = []
            if starts_item:
                if s.startswith("|"):
                    out.append(s)
                else:
                    cur = [s]
            continue
        cur.append(s)
    if cur:
        out.append(" ".join(cur))
    return out


def assumed(rules, text, keys):
    """True when a sentence of pack.md says the source does not state what a
    height is measured from, is about a height (a height word or one of
    `keys`), and does not go on to say the value is therefore not that key."""
    unstated = dict(rules.terms).get(UNSTATED)
    if unstated is None:
        return False
    bare = "|".join(re.escape(k.rsplit(".", 1)[-1]) for k in keys)
    about = re.compile(r"(?i)(?<![A-Za-z0-9_])(%s|%s)(?![A-Za-z0-9_])" % (HEIGHT_WORDS, bare))
    refused = re.compile(r"(?i)\bnot\s+(mapped\s+to\s+|bound\s+to\s+)?`?(%s)\b" % bare)
    for p in passages(text):
        for sentence in re.split(r"(?<=[.;])\s+", p):
            if unstated.search(sentence) and about.search(sentence) and not refused.search(sentence):
                return True
    return False


def datum_terms(rules, text, mapped):
    """The datum vocabulary (`datum.terms`) that pack.md uses in a passage
    about a height: one that has a height word or the name of a mapped height key."""
    names = sorted({k.rsplit(".", 1)[-1] for k in mapped}, key=len, reverse=True)
    about = re.compile(r"(?i)(?<![A-Za-z0-9_])(%s)(?![A-Za-z0-9_])" % "|".join([HEIGHT_WORDS] + [re.escape(n) for n in names]))
    found = []
    for p in passages(text):
        if not about.search(p):
            continue
        for label, rx in rules.terms:
            if label not in found and rx.search(p):
                found.append(label)
    return [label for label, _ in rules.terms if label in found]


def read_allow(path):
    """-> ({(location, key): reason}, [malformed lines])."""
    allowed, bad = {}, []
    if not os.path.isfile(path):
        return allowed, bad
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = ALLOW_LINE.match(line)
            if not m:
                bad.append("%s:%d: not `<pack>/<vector> <key> <reason>`: %s" % (path, n, line))
                continue
            if (m.group(1), m.group(2)) in allowed:
                bad.append("%s:%d: listed twice: %s %s" % (path, n, m.group(1), m.group(2)))
            allowed[(m.group(1), m.group(2))] = m.group(3)
    return allowed, bad


def parse_shard(text):
    m = re.fullmatch(r"(\d+)/(\d+)", text or "")
    if not m or int(m.group(2)) < 1 or int(m.group(1)) >= int(m.group(2)):
        raise argparse.ArgumentTypeError("--shard is I/N with 0 <= I < N")
    return int(m.group(1)), int(m.group(2))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check that decoded model values are plausible and heights name a datum.")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--rules", default=os.path.join(HERE, "model-ranges.json"))
    ap.add_argument("--allow")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--shard", type=parse_shard, default=(0, 1))
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    allow_path = args.allow or os.path.join(root, "tools", "model-checks-allow.txt")
    started = time.monotonic()

    api = engine_api()
    with open(args.rules, encoding="utf-8") as fh:
        rule_data = json.load(fh)
    try:
        eng = api.Engine.from_dir(os.path.join(root, "packs"), os.path.join(root, "model"))
    except (api.GTError, OSError) as e:
        print("model-checks: the tree does not load: %s" % e, file=sys.stderr)
        return 2
    rules = Rules(rule_data, eng.models)
    by_dir = {os.path.basename(eng.pack(f).path): f for f in eng.formats()}

    shard, shards = args.shard
    every = sorted(d for d in os.listdir(os.path.join(root, "packs"))
                   if os.path.isdir(os.path.join(root, "packs", d)))
    dirs = [d for i, d in enumerate(every) if i % shards == shard]
    real = [d for d in dirs if not rules.is_synthetic(d)]

    stats = {"vectors": 0, "skipped_synthetic": 0, "not_decoded": 0, "decoded": 0, "checked": {}}
    stats["vectors"] = sum(len(glob.glob(os.path.join(root, "packs", d, "vectors", "*.json")))
                           for d in dirs if rules.is_synthetic(d))
    stats["skipped_synthetic"] = stats["vectors"]
    failures = check_vectors(api, eng, rules, root, real, stats)
    failures += check_datum(eng, rules, root, real, by_dir)

    allowed, bad_lines = read_allow(allow_path)
    in_shard = set(dirs)
    allowed = {k: v for k, v in allowed.items() if k[0].split("/", 1)[0] in in_shard}
    failing = {(loc, key) for loc, key, _, _ in failures}
    new = [f for f in failures if (f[0], f[1]) not in allowed]
    stale = sorted(k for k in allowed if k not in failing)
    elapsed = time.monotonic() - started

    if args.json:
        print(json.dumps({
            "failures": [{"location": loc, "key": key, "value": value, "why": why, "allowed": (loc, key) in allowed}
                         for loc, key, value, why in failures],
            "stale_allow": ["%s %s" % k for k in stale], "bad_allow_lines": bad_lines,
            "stats": stats, "seconds": round(elapsed, 1),
        }, indent=1, default=str))
    else:
        for loc, key, value, why in failures:
            if args.check and (loc, key) in allowed:
                continue
            mark = "allowed " if (loc, key) in allowed else ""
            print("%s%s %s = %r: %s" % (mark, loc, key, value, why))
        for loc, key in stale:
            print("allow line no longer fails, remove it: %s %s" % (loc, key))
        for line in bad_lines:
            print(line)
        datum_n = sum(1 for f in failures if f[1] == "datum")
        print("model-checks: %d vectors; %d decoded and checked, %d skipped as synthetic, %d did not decode"
              % (stats["vectors"], stats["decoded"], stats["skipped_synthetic"], stats["not_decoded"]))
        print("model-checks: values checked: %s" % (
            ", ".join("%s %d" % (k, n) for k, n in sorted(stats["checked"].items())) or "none"))
        print("model-checks: %d failures (%d values, %d datum), %d allowed, %d new, %d allow lines stale; %.0f s"
              % (len(failures), len(failures) - datum_n, datum_n, len(failures) - len(new), len(new), len(stale),
                 elapsed))
    if args.check and (new or stale or bad_lines):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
