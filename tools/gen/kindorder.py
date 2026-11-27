"""kindorder: make every top-level kind of a pack reachable on encode.

engine-spec, Message kinds, Encode step 2: with no recorded kind, encode takes the
first kind whose `requires` keys are all present, and a kind with no `requires`
always qualifies. A requires-less kind before another kind therefore hides every
kind after it from a library caller or a cross-format conversion.

`order(text)` returns the pack text unchanged unless such a kind hides a later
kind that maps a key of its own. Then:

- Trailing kinds with no `when` (decode fallbacks) stay last, as they are, and are
  the encode fallback too.
- If the other kinds' `when`s are pairwise disjoint (each pair tests one locator with
  different values) and no `map` or `typemap` line sits among the kinds, the
  kinds are reordered, which cannot change decode: first the kinds that have a
  `requires` line or a key no other kind maps (they gain `requires <that key>`),
  in their order; then the kinds whose keys are all shared, most keys first,
  each requiring the keys that not every kind maps (or its first key); then, when
  the pack has no such trailing fallback, the first requires-less kind of the
  pack, without `requires`: it is the one every kind-less entity took, and stays
  the fallback for an entity that fits no other kind; last any other kind that
  maps no key.
- Otherwise nothing moves: each requires-less kind that maps a key gains
  `requires` on a key of its own, or else on its keys that not every kind maps,
  or else on its first key. A kind that maps no key keeps no `requires` and
  still hides the kinds after it; the pack's pack.md states it.

Kinds that `requires` cannot tell apart (the same keys, or no keys) are left to
the first of them; the pack's pack.md states them.
"""
import re

_KIND = re.compile(r"kind\s")
_FIELD = re.compile(r"\bfield\s+(\S+)")


def _parse(lines):
    starts = [i for i, l in enumerate(lines) if _KIND.match(l)]
    kinds = []
    for a, b in zip(starts, starts[1:] + [len(lines)]):
        body = lines[a:b]
        while body and body[-1].strip() == "":
            body = body[:-1]
        k = {"name": lines[a].split()[1], "lines": body, "when": {}, "req": False, "keys": [], "lists": set(),
             "last_when": 0}
        groups = []  # indents of the groups open at this line
        for j, l in enumerate(body[1:], 1):
            s = l.strip()
            if not s or s.startswith("#"):
                continue
            ind = len(l) - len(l.lstrip())
            while groups and ind <= groups[-1] and not (ind == groups[-1] and s == "end"):
                groups.pop()
            if groups and ind == groups[-1] and s == "end":
                groups.pop()
                continue
            if l.startswith("when"):
                parts = l.split(None, 2)
                if len(parts) == 3:
                    k["when"][parts[1]] = parts[2].split("#")[0].strip()
                k["last_when"] = j
                # a `when ... as <key>` that is not `optional` is an implicit requires term
                # (engine-spec 0.30 Encode, 0.94 ruling 1): the kind does not always qualify
                if re.search(r"\sas\s+\S+", l.split("#")[0]) and not re.search(r"\soptional\b", l.split("#")[0]):
                    k["req"] = True
            elif l.startswith("requires"):
                k["req"] = True
            # `requires` sees the entity's own keys and its lists (engine-spec: a list holds
            # when it has an item), not the keys inside a list's items
            g = re.match(r"group\s+(\S+)", s)
            if g:
                if not groups and g.group(1) not in k["keys"]:
                    k["keys"].append(g.group(1))
                    k["lists"].add(g.group(1))
                groups.append(ind)
                continue
            m = _FIELD.search(s)
            if m and not groups and m.group(1) not in k["keys"]:
                k["keys"].append(m.group(1))
        kinds.append(k)
    return starts, kinds


def _needs(kinds):
    for i, k in enumerate(kinds[:-1]):
        if not k["req"]:
            hidden = set(k["keys"])
            return any(set(o["keys"]) - hidden for o in kinds[i + 1:])
    return False


def _req_keys(k):
    return [w for l in k["lines"] if l.startswith("requires") for w in l.split()[1:]]


def _with_requires(k, keys):
    body = list(k["lines"])
    if keys:
        body.insert(k["last_when"] + 1, "requires  " + "  ".join(keys))
    return body


def order(text):
    lines = text.split("\n")
    starts, kinds = _parse(lines)
    if len(kinds) < 2 or not _needs(kinds):
        return text
    count = {}
    for k in kinds:
        for key in k["keys"]:
            count[key] = count.get(key, 0) + 1
    # a kind's own field comes before its own list: a list may be empty, and then requires on it fails
    own = {k["name"]: sorted((key for key in k["keys"] if count[key] == 1), key=lambda key: key in k["lists"])
           for k in kinds}
    # trailing kinds with no `when` are fallbacks for decode: they stay last, as they are
    tail = []
    while kinds and not kinds[-1]["when"]:
        tail.insert(0, kinds.pop())
    disjoint = all(any(loc in b["when"] and b["when"][loc] != v for loc, v in a["when"].items())
                   for i, a in enumerate(kinds) for b in kinds[i + 1:])
    stray = any(l.startswith(("map ", "map\t", "typemap")) for k in kinds for l in k["lines"])
    head = lines[:starts[0]]
    out = list(head)
    if disjoint and not stray:
        # the first requires-less kind was the one every kind-less entity took: it stays the
        # fallback, moved last and without requires, so an entity that fits no other kind still
        # encodes as it did
        # with a decode fallback at the end (no `when`), that fallback is the encode fallback too
        default = None if tail else next(k for k in kinds if not k["req"])
        first, shared, nokeys = [], [], []
        for k in kinds:
            if k is default:
                continue
            if k["req"]:
                first.append((k, None))
            elif own[k["name"]]:
                first.append((k, own[k["name"]][:1]))
            elif k["keys"]:
                part = [key for key in k["keys"] if count[key] < len(kinds) + len(tail)]
                shared.append((k, part or k["keys"][:1]))
            else:
                nokeys.append((k, None))
        shared.sort(key=lambda kr: -len(kr[0]["keys"]))
        seq = first + shared
        # a kind whose requires include all of an earlier kind's requires would never be reached:
        # move it in front of that kind
        reqs = [set(_req_keys(k) + (keys or [])) for k, keys in seq]
        moved = True
        while moved:
            moved = False
            for i in range(len(seq)):
                for j in range(i):
                    if reqs[j] and reqs[j] < reqs[i]:
                        seq.insert(j, seq.pop(i)); reqs.insert(j, reqs.pop(i)); moved = True
                        break
                if moved:
                    break
        for k, keys in seq + ([(default, None)] if default else []) + nokeys:
            out += _with_requires(k, keys) + [""]
    else:
        for k in kinds:
            keys = None
            if not k["req"]:
                part = [key for key in k["keys"] if count[key] < len(kinds) + len(tail)]
                keys = own[k["name"]][:1] or part or k["keys"][:1]
            out += _with_requires(k, keys) + [""]
    for k in tail:
        out += _with_requires(k, None) + [""]
    return "\n".join(out).rstrip("\n") + "\n"


def encode_note(text):
    """A pack.md paragraph for the kinds `requires` cannot tell apart in `text` (a pack after
    `order`): kinds with the same `requires`, and kinds with neither `requires` nor a key past the
    first such kind. Empty when every kind is reached by its keys."""
    _, kinds = _parse(text.split("\n"))
    if len(kinds) < 2:
        return ""
    groups = {}
    for k in kinds:
        r = tuple(sorted(_req_keys(k)))
        if r:
            groups.setdefault(r, []).append(k["name"])
    ties = [g for g in groups.values() if len(g) > 1]
    loose = [k["name"] for k in kinds if not _req_keys(k)]
    if not ties and len(loose) < 2:
        return ""
    s = ["On encode with no recorded kind (engine-spec Encode step 2), each kind is chosen by the keys",
         "it requires."]
    for g in ties:
        s.append("%s require the same keys, so an entity with them is written as `%s`." % (
            ", ".join("`%s`" % n for n in g), g[0]))
    if len(loose) > 1:
        s.append("%s have no `requires`, so an entity that fits no other kind is written as `%s`." % (
            ", ".join("`%s`" % n for n in loose), loose[0]))
    s.append("Choosing between them needs `requires` on a value or on an absent key, a language addition.")
    return "\n".join(s) + "\n"
