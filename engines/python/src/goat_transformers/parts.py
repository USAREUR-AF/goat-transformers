"""One text token split into coded fields (spec/engine-spec.md, Version 0.64):
the checks of a pack's part groups made after the file is read, the `const`
parts on decode, and the token of a group on encode. A part group is the lines
of one locator (as text) in one scope that hold at least one part line."""

from .entity import NoEntry, _via_decode, _via_encode
from .errors import BadDirective, TransformEncodeFailure
from .transforms import StringT

WHOLE = StringT()  # how the token is read from its place


def is_part(ln):
    """Whether a line is a part line: a `field` with `part`, or a `const ... part`."""
    if ln.is_field:
        return getattr(ln.transform, "is_part", False)
    return getattr(ln, "is_part_const", False)


# --- load checks --------------------------------------------------------------


def _has_part(lines):
    return any(is_part(ln) or (ln.is_group and _has_part(ln.lines)) for ln in lines)


def check_parts(wire, common, kinds, deferred, source, name, delimiter=None, checksum="none"):
    """Each failure is `bad-directive`, appended to `deferred` as (lineno, error).
    A scope is the common lines with each kind (alone when there are no kinds,
    rulings 6 and 19), or one group body."""

    def bad(ln, msg):
        deferred.append((ln.lineno, BadDirective("%s, at %s:%d" % (msg, source, ln.lineno), format=name,
                                                 locator=ln.locator)))

    def line(ln):
        sep = ln.transform.sep
        if not ln.is_field and (not ln.value or sep in ln.value):
            bad(ln, "the text %r of a 'const' part is empty or holds its separator" % ln.value)
        if wire == "text":
            if sep == delimiter:
                bad(ln, "the separator of a part is the delimiter")
            elif sep == "*" and checksum == "nmea":
                bad(ln, "the separator of a part is '*' under 'checksum nmea'")

    def group(lines):
        first = next(ln for ln in lines if is_part(ln))
        sep = first.transform.sep
        numbers = set()
        keys = set()
        whole = None
        fields = 0
        for ln in lines:
            if is_part(ln):
                if ln.transform.sep != sep:
                    bad(ln, "two separators in one part group")
                if ln.transform.n in numbers:
                    bad(ln, "part %d is named twice in one part group" % ln.transform.n)
                numbers.add(ln.transform.n)
                if ln.is_field:
                    fields += 1
                    keys.add(ln.key)
            elif not (ln.is_field and ln.transform.name == "string" and ln.via is None and ln.absent is None
                      and ln.with_key is None):
                bad(ln, "another line on the locator of a part group")
            elif whole is not None:
                bad(ln, "a second whole line in one part group")
            else:
                whole = ln
        if whole is not None and whole.key in keys:
            bad(whole, "a whole line and a part line of one key %s" % whole.key)
        if not fields:
            bad(first, "a part group with no part 'field'")
        if len(numbers) != max(numbers) + 1:
            bad(first, "part group %s does not name every part from 0 to %d" % (first.locator, max(numbers)))

    def scope(lines):
        places = {}
        for ln in lines:
            if not getattr(ln, "is_element", False):
                places.setdefault(ln.locator, []).append(ln)
        for got in places.values():
            if any(is_part(ln) for ln in got):
                group(got)

    def body(lines):
        for ln in lines:
            if ln.is_group:
                scope(ln.lines)
                body(ln.lines)
            elif is_part(ln):
                line(ln)

    if not _has_part(common) and not any(_has_part(k.lines) for k in kinds):
        return
    body(common)
    for k in kinds:
        body(k.lines)
        scope(common + k.lines)
    if not kinds:
        scope(common)


# --- one scope ----------------------------------------------------------------


class PartGroup:
    """`at`: the index, in the plan's lines, of the group's first `field`
    line, which carries its token; `parts`: the part lines by number;
    `fields`: the part fields; `checked`: those whose key no other `field`
    line of the scope maps (rulings 18 and 25); `whole`: the whole line or None."""

    __slots__ = ("at", "sep", "parts", "fields", "checked", "consts", "whole", "indexes")

    def __init__(self):
        self.at = None
        self.sep = None
        self.parts = {}
        self.fields = []
        self.checked = []
        self.consts = []
        self.whole = None
        self.indexes = []


def groups_of(plan):
    """The part groups of a scope, worked out once and kept with its plan
    (built whole, then published: ruling 1c of 0.25)."""
    got = plan.cache.get("parts")
    if got is not None:
        return got
    locators = {ln.locator for ln in plan.lines if is_part(ln)}
    by_place = {}
    if locators:
        count = {}
        for f in plan.fields:
            count[f.key] = count.get(f.key, 0) + 1
        for i, ln in enumerate(plan.lines):
            if ln.locator not in locators:
                continue
            g = by_place.get(ln.locator)
            if g is None:
                g = by_place[ln.locator] = PartGroup()
            if ln.is_field:
                g.indexes.append(i)
                if g.at is None:
                    g.at = i
            if not is_part(ln):
                g.whole = ln
                continue
            g.sep = ln.transform.sep
            g.parts[ln.transform.n] = ln
            if not ln.is_field:
                g.consts.append(ln)
                continue
            g.fields.append(ln)
            if count[ln.key] == 1:
                g.checked.append(ln)
    got = plan.cache["parts"] = tuple(by_place.values())
    return got


def check_const(ln, token):
    """Raises ValueError when the token's part is missing or is not the text of the `const`."""
    if ln.transform.decode(token) != ln.value:
        raise ValueError("part %d of %r is not the constant %r" % (ln.transform.n, token, ln.value))


_ABSENT = object()


def _decoded(pack, f, token):
    """What decode gives the key of a part field, or _ABSENT (`unlisted`). Raises ValueError."""
    value = f.transform.decode(token)
    if f.via_dec is not None:
        try:
            value = _via_decode(f, value)
        except NoEntry:
            if f.unlisted:
                return _ABSENT
            raise
    if f.key == "type":
        value = pack.native_to_cot.get(value, value)
    return value


def _check_whole(pack, g, token, have):
    """Encode, step 1. Raises ValueError."""
    for ln in g.consts:
        check_const(ln, token)
    for f in g.checked:
        value = _decoded(pack, f, token)
        if value is _ABSENT:
            if f.key in have:
                raise ValueError("part %d of %r has no entry in table %s, and %s is held"
                                 % (f.transform.n, token, f.via, f.key))
        elif f.key in have and have[f.key] != value:  # compared as values (ruling 22)
            raise ValueError("part %d of %r decodes to %r, and %s holds %r"
                             % (f.transform.n, token, value, f.key, have[f.key]))


def _native(pack, f, value):
    if f.key == "type":
        value = pack.cot_to_native.get(value, value)
    if f.via_enc is not None:
        value = _via_encode(f, value)
    return f.transform.encode(value)  # a string


def token_of(pack, g, have, defaults):
    """-> the token the group writes, or None for nothing. Raises TransformEncodeFailure."""
    w = g.whole
    try:
        if w is None or w.key not in have:
            held = [f for f in g.fields if f.key in have]
            if held or all(f.key in defaults for f in g.fields):  # step 2
                return _joined(pack, g, have, defaults)
            if w is None or w.key not in defaults:
                return None
        value = have[w.key] if w.key in have else defaults[w.key]
        token = _native(pack, w, value)
        _check_whole(pack, g, token, have)
        return token
    except ValueError as e:
        raise TransformEncodeFailure(str(e), format=pack.name, locator=(w or g.fields[0]).locator)


def _joined(pack, g, have, defaults):
    out = []
    for n in range(len(g.parts)):
        ln = g.parts[n]
        if not ln.is_field:
            out.append(ln.value)
            continue
        if ln.key in have:
            value = have[ln.key]
        elif ln.key in defaults:
            value = defaults[ln.key]
        else:
            raise ValueError("part %d has no value: %s is not held" % (n, ln.key))
        text = _native(pack, ln, value)
        if g.sep in text:
            raise ValueError("the text %r of part %d holds the separator" % (text, n))
        out.append(text)
    return g.sep.join(out)
