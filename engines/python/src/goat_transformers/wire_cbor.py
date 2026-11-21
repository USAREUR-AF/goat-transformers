"""The `cbor` wire (spec/engine-spec.md, Version 0.28): one CBOR data item
(RFC 8949), a map or an array at the top, addressed by paths of integer keys,
text keys and array positions. Input and output are hex text.

Decode reads the whole item strictly (`parse`: well-formedness, lengths
compared with the bytes left before anything is taken for them, UTF-8 of every
text chunk, equal map keys, a depth of at most 64, the `tag <n>` of the pack
and the type of the top item). Kinds are selected leniently (`when_holds`);
then `walk` checks every line of the selected scope (Reading step 8). Residue
is every member or element that no line maps or walks into, as the hex of the
item as it stood.

Encode builds a tree from the lines of the scope and the residue and writes it
with the core deterministic encoding of RFC 8949 4.2.1: shortest heads,
shortest exact floats, definite lengths, map members sorted by the bytes of
their encoded keys.

Every reader here is iterative over items and recursive only over nesting,
which the depth limit bounds."""

import math
import re
import struct

from .errors import MalformedWire
from .transforms import Transform
from .octets import hex_to_bytes as _hex_to_bytes  # shared with `bits`, `protobuf` and `tlv`

MAX_DEPTH = 64
MAX_POSITION = 65535
_I64_MIN, _I64_MAX = -(1 << 63), (1 << 63) - 1
_U64_MAX = (1 << 64) - 1

MAP, ARRAY, SCALAR = "map", "array", "scalar"

# major types of an Item; 8 is a float (major type 7 with ai 25, 26 or 27)
_UINT, _NINT, _BYTES, _TEXT, _ARR, _MAP, _SIMPLE, _FLOAT = 0, 1, 2, 3, 4, 5, 7, 8
_FALSE, _TRUE, _NULL, _UNDEF = 20, 21, 22, 23

TRANSFORM_NAMES = ("uint", "int", "float", "text", "bytes", "bool", "epoch_s")

# --- paths ----------------------------------------------------------------------
#
# A step is an int (an integer key), a str (a text key) or a one-tuple (i,)
# (an array position). A path is a tuple of steps; `.` is the empty path.

_INT_STEP = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_POS_STEP = re.compile(r"\[(0|[1-9][0-9]*)\]\Z")
_TEXT_STEP = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_INT_TEXT = re.compile(r"-?[0-9]+\Z")  # 2a of 0.11
_HEX_TEXT = re.compile(r"(?:[0-9a-fA-F]{2})*\Z")
_LOWER_HEX = re.compile(r"(?:[0-9a-f]{2})*\Z")


def parse_step(text):
    """One step of a path -> int | str | (i,). Raises ValueError."""
    if not text.isascii():
        raise ValueError("a step holds a character outside ASCII: %r" % text[:40])
    if _INT_STEP.match(text):
        if text == "-0":
            raise ValueError("'-0' is not an integer key")
        if len(text) > 21:
            raise ValueError("integer key %r out of range" % text[:40])
        n = int(text)
        if n < _I64_MIN or n > _U64_MAX:
            raise ValueError("integer key %s lies outside -2^63 to 2^64-1" % text)
        return n
    m = _POS_STEP.match(text)
    if m is not None:
        if len(m.group(1)) > 5 or int(m.group(1)) > MAX_POSITION:
            raise ValueError("position %s lies above 65535" % text)
        return (int(m.group(1)),)
    if _TEXT_STEP.match(text):
        return text
    raise ValueError("%r is not an integer key, an array position [i] or a text key" % text[:40])


def parse_path(locator):
    """A path of steps separated by `.` -> tuple of steps. `.` itself is not
    read here. Raises ValueError."""
    if locator == "":
        raise ValueError("an empty path")
    return tuple(parse_step(part) for part in locator.split("."))


def is_position(step):
    return type(step) is tuple


def step_text(step):
    return "[%d]" % step[0] if type(step) is tuple else str(step)


def path_text(path):
    return ".".join(step_text(s) for s in path)


def read_tag_value(text):
    """`tag <n>` on `cbor`: a decimal integer from 0 to 2^64-1 with no leading
    zero -> int, or None."""
    if not (text.isascii() and re.match(r"(?:0|[1-9][0-9]*)\Z", text)) or len(text) > 20:
        return None
    n = int(text)
    return n if n <= _U64_MAX else None


def read_value(text):
    """A `when` or `const` value on `cbor` (Kinds; rulings 8 and 19) ->
    ("i", int) | ("b", bool) | ("t", str)."""
    if text.isascii() and _INT_TEXT.match(text):
        digits = text.lstrip("-").lstrip("0")
        if len(digits) <= 20:
            n = int(text)
            if _I64_MIN <= n <= _U64_MAX:
                return ("i", n)
    if text == "true" or text == "false":
        return ("b", text == "true")
    if text.startswith("="):
        text = text[1:]
    return ("t", text)


# --- the core deterministic encoding ----------------------------------------------


def head(mt, n):
    """The shortest head of major type `mt` with argument `n`."""
    b = mt << 5
    if n < 24:
        return bytes((b | n,))
    if n < 0x100:
        return bytes((b | 24, n))
    if n < 0x10000:
        return bytes((b | 25,)) + n.to_bytes(2, "big")
    if n < 0x100000000:
        return bytes((b | 26,)) + n.to_bytes(4, "big")
    return bytes((b | 27,)) + n.to_bytes(8, "big")


def int_bytes(n):
    return head(0, n) if n >= 0 else head(1, -1 - n)


def text_bytes(s):
    raw = s.encode("utf-8")
    return head(3, len(raw)) + raw


def step_key(step):
    """The encoded key of a map step."""
    return int_bytes(step) if type(step) is int else text_bytes(step)


def float_bytes(x):
    """The shortest of half, single and double that holds the finite double
    `x` exactly, subnormal halves included (RFC 8949 4.2.2); -0.0 is f98000."""
    try:
        h = struct.pack(">e", x)
        if struct.unpack(">e", h)[0] == x:
            return b"\xf9" + h
    except (OverflowError, struct.error):
        pass
    try:
        s = struct.pack(">f", x)
        if struct.unpack(">f", s)[0] == x:
            return b"\xfa" + s
    except (OverflowError, struct.error):
        pass
    return b"\xfb" + struct.pack(">d", x)


def _float_canon(width, bits):
    """The deterministic encoding of a float item read at `width` bytes."""
    if width == 2:
        if (bits >> 10) & 0x1F == 0x1F:  # an infinity or a NaN: no shorter width
            return b"\xf9" + bits.to_bytes(2, "big")
        return float_bytes(struct.unpack(">e", bits.to_bytes(2, "big"))[0])
    if width == 4:
        exp, mant, sign = (bits >> 23) & 0xFF, bits & 0x7FFFFF, bits >> 31
        if exp == 0xFF:
            dbits = (sign << 63) | (0x7FF << 52) | (mant << 29)
            return _special_canon(dbits)
        return float_bytes(struct.unpack(">f", bits.to_bytes(4, "big"))[0])
    exp = (bits >> 52) & 0x7FF
    if exp == 0x7FF:
        return _special_canon(bits)
    return float_bytes(struct.unpack(">d", bits.to_bytes(8, "big"))[0])


def _special_canon(dbits):
    """An infinity or a NaN, as double bits: the shortest width that keeps
    every bit of its payload."""
    sign = dbits >> 63
    mant = dbits & ((1 << 52) - 1)
    if mant & ((1 << 42) - 1) == 0:
        return b"\xf9" + ((sign << 15) | (0x1F << 10) | (mant >> 42)).to_bytes(2, "big")
    if mant & ((1 << 29) - 1) == 0:
        return b"\xfa" + ((sign << 31) | (0xFF << 23) | (mant >> 29)).to_bytes(4, "big")
    return b"\xfb" + dbits.to_bytes(8, "big")


def canon(item):
    """The core deterministic encoding of a read item, its tags included."""
    out = bytearray()
    for t in item.tags or ():
        out += head(6, t)
    mt = item.mt
    v = item.val
    if mt == _UINT:
        out += head(0, v)
    elif mt == _NINT:
        out += head(1, -1 - v)
    elif mt == _BYTES:
        out += head(2, len(v)) + v
    elif mt == _TEXT:
        out += text_bytes(v)
    elif mt == _ARR:
        out += head(4, len(v))
        for el in v:
            out += canon(el)
    elif mt == _MAP:
        pairs = sorted((canon(k), canon(x)) for k, x in v)
        out += head(5, len(pairs))
        for k, x in pairs:
            out += k + x
    elif mt == _SIMPLE:
        out += bytes((0xE0 | v,)) if v < 24 else bytes((0xF8, v))
    else:
        out += _float_canon(*v)
    return bytes(out)


# --- reading ----------------------------------------------------------------------


class _Bad(Exception):
    pass


class Item:
    """One read data item: its major type (8 for a float), its value (an int;
    bytes; a str; a list of Items; a list of (key, value) Items; a simple
    value; (width, bits) for a float), the tags on it (outermost first, or
    None), and its span in the input, tags included."""

    __slots__ = ("mt", "val", "tags", "start", "end", "_index")

    def __init__(self, mt, val, tags, start, end):
        self.mt = mt
        self.val = val
        self.tags = tags
        self.start = start
        self.end = end
        self._index = None

    def member(self, step):
        """The value of the member of this map whose addressable key is
        `step` (an int or a str), or None."""
        index = self._index
        if index is None:
            index = self._index = {}
            for k, x in self.val:
                a = addressable(k)
                if a is not None:
                    index[a] = x
        return index.get(step)

    def is_nil(self):
        return self.mt == _SIMPLE and (self.val == _NULL or self.val == _UNDEF)


def addressable(key):
    """The step a map key is addressed by -> int | str, or None when the key
    is not addressable (Paths; ruling 17)."""
    if key.tags:
        return None
    mt = key.mt
    if mt == _UINT:
        return key.val
    if mt == _NINT:
        return key.val if key.val >= _I64_MIN else None
    if mt == _TEXT:
        s = key.val
        return s if s.isascii() and _TEXT_STEP.match(s) else None
    return None


def _key_identity(key):
    """Reading step 4: integer keys are equal when their values are, text
    keys when their bytes are, other keys when their deterministic encodings
    are; keys of different major types never."""
    if not key.tags:
        if key.mt == _UINT or key.mt == _NINT:
            return key.val
        if key.mt == _TEXT:
            return ("t", key.val)
    return ("d", canon(key))


def _arg(buf, pos, end):
    """The head at `pos` -> (major type, argument or None for indefinite,
    additional information, position after the head)."""
    ib = buf[pos]
    mt, ai = ib >> 5, ib & 0x1F
    pos += 1
    if ai < 24:
        return mt, ai, ai, pos
    if ai < 28:
        n = 1 << (ai - 24)
        if end - pos < n:
            raise _Bad("a head runs past the input")
        return mt, int.from_bytes(buf[pos:pos + n], "big"), ai, pos + n
    if ai == 31:
        return mt, None, ai, pos
    raise _Bad("additional information %d is reserved (RFC 8949 3.1)" % ai)


def _string(buf, pos, end, mt, n):
    """A string of major type 2 or 3 whose head is read: definite of `n`
    bytes, or indefinite (n is None) of definite chunks of its own type."""
    if n is not None:
        if n > end - pos:
            raise _Bad("a string declares %d byte(s) where %d remain" % (n, end - pos))
        raw = buf[pos:pos + n]
        if mt == _TEXT:
            try:
                return raw.decode("utf-8"), pos + n
            except UnicodeDecodeError:
                raise _Bad("a text string is not valid UTF-8")
        return raw, pos + n
    parts = []
    while True:
        if pos >= end:
            raise _Bad("an indefinite string is not closed by a break")
        if buf[pos] == 0xFF:
            pos += 1
            break
        cmt, cn, _, pos = _arg(buf, pos, end)
        if cmt != mt or cn is None:
            raise _Bad("a chunk of an indefinite string is not a definite string of its type")
        chunk, pos = _string(buf, pos, end, mt, cn)
        parts.append(chunk)
    if mt == _TEXT:
        return "".join(parts), pos
    return b"".join(parts), pos


def _item(buf, pos, end, level):
    """One data item at `pos` whose enclosing level is `level` -> (Item,
    position after it). Raises _Bad."""
    start = pos
    tags = None
    while True:
        if pos >= end:
            raise _Bad("the input ends where an item stands")
        if buf[pos] >> 5 != 6:
            break
        level += 1
        if level > MAX_DEPTH:
            raise _Bad("the item nests deeper than %d levels" % MAX_DEPTH)
        _, t, _, pos = _arg(buf, pos, end)
        if t is None:
            raise _Bad("a tag with indefinite length")
        if tags is None:
            tags = []
        tags.append(t)
    mt, n, ai, pos = _arg(buf, pos, end)
    if mt == _UINT or mt == _NINT:
        if n is None:
            raise _Bad("an integer with indefinite length")
        return Item(mt, n if mt == _UINT else -1 - n, tags, start, pos), pos
    if mt == _BYTES or mt == _TEXT:
        val, pos = _string(buf, pos, end, mt, n)
        return Item(mt, val, tags, start, pos), pos
    if mt == _ARR or mt == _MAP:
        level += 1
        if level > MAX_DEPTH:
            raise _Bad("the item nests deeper than %d levels" % MAX_DEPTH)
        out = []
        if n is not None:
            # each element takes at least one byte, each member two: compared
            # with the bytes left before anything is taken for them
            if n * (2 if mt == _MAP else 1) > end - pos:
                raise _Bad("a %s declares %d %s where %d byte(s) remain"
                           % ("map" if mt == _MAP else "array", n, "member(s)" if mt == _MAP else "element(s)",
                              end - pos))
        seen = set() if mt == _MAP else None
        count = 0
        while True:
            if n is None:
                if pos >= end:
                    raise _Bad("an indefinite %s is not closed by a break" % ("map" if mt == _MAP else "array"))
                if buf[pos] == 0xFF:
                    pos += 1
                    break
            elif count == n:
                break
            count += 1
            if mt == _ARR:
                el, pos = _item(buf, pos, end, level)
                out.append(el)
            else:
                k, pos = _item(buf, pos, end, level)
                ident = _key_identity(k)
                if ident in seen:
                    raise _Bad("a map holds two equal keys")
                seen.add(ident)
                x, pos = _item(buf, pos, end, level)
                out.append((k, x))
        return Item(mt, out, tags, start, pos), pos
    # major type 7
    if ai < 24:
        return Item(_SIMPLE, ai, tags, start, pos), pos
    if ai == 24:
        if n < 32:
            raise _Bad("a simple value below 32 in two bytes (RFC 8949 3.3)")
        return Item(_SIMPLE, n, tags, start, pos), pos
    if ai == 31:
        raise _Bad("a break where an item stands")
    return Item(_FLOAT, ({25: 2, 26: 4, 27: 8}[ai], n), tags, start, pos), pos


def read_item(buf):
    """Exactly one well-formed data item -> Item. Raises _Bad."""
    item, pos = _item(buf, 0, len(buf), 0)
    if pos != len(buf):
        raise _Bad("%d byte(s) after the data item" % (len(buf) - pos))
    return item


class Message:
    __slots__ = ("buf", "top")

    def __init__(self, buf, top):
        self.buf = buf
        self.top = top


class _Empty:
    """An element of the wrong type for a group body: an item with no keys."""


EMPTY = _Empty()


def parse(pack, data):
    """Reading steps 1 to 6: the item, the `tag <n>` of the pack, the type of
    the top item."""
    fmt = pack.name
    buf = _hex_to_bytes(data, fmt)
    try:
        top = read_item(buf)
    except _Bad as e:
        raise MalformedWire(str(e), format=fmt)
    want = pack.cbor_tag
    if want is not None and (not top.tags or top.tags[0] != want):
        raise MalformedWire("the outermost tag of the input is %s, not %d"
                            % ("absent" if not top.tags else top.tags[0], want), format=fmt)
    need = _ARR if pack.cbor_top == ARRAY else _MAP
    if top.mt != need:
        raise MalformedWire("the top item is not %s, as the paths of the pack decide"
                            % ("an array" if need == _ARR else "a map"), format=fmt)
    return Message(buf, top)


# --- walking paths --------------------------------------------------------------


class _Wrong(Exception):
    """An item on a path that is not the container its next step needs."""

    def __init__(self, depth):
        Exception.__init__(self)
        self.depth = depth


def _lookup(node, path):
    """The item at `path` under `node`, tags passed over -> Item, or None
    when it is not there or `null` or `undefined` stands on the way. Raises
    _Wrong for an item of the wrong type for its next step."""
    for d, step in enumerate(path):
        if node.mt == _SIMPLE and (node.val == _NULL or node.val == _UNDEF):
            return None  # ruling 12: the line's item is absent
        if type(step) is tuple:
            if node.mt != _ARR:
                raise _Wrong(d)
            arr = node.val
            i = step[0]
            if i >= len(arr):
                return None
            node = arr[i]
        else:
            if node.mt != _MAP:
                raise _Wrong(d)
            node = node.member(step)
            if node is None:
                return None
    return node


def _start(ctx):
    if ctx is EMPTY:
        return None
    return ctx.top if type(ctx) is Message else ctx


def _strict(pack, node, path, what):
    try:
        return _lookup(node, path)
    except _Wrong as w:
        raise MalformedWire(
            "%s: the item at %s is not the %s its next step needs"
            % (what, path_text(path[:w.depth]) or "the top", "array" if is_position(path[w.depth]) else "map"),
            format=pack.name, locator=path_text(path),
        )


def get(pack, ctx, f):
    """The item a field reads -> Item, or None when it is absent (not there,
    `null`, `undefined`, or `null` or `undefined` on the way)."""
    node = _start(ctx)
    if node is None:
        return None
    node = _strict(pack, node, f.loc, "field %s" % f.key)
    if node is None or node.is_nil():
        return None
    return node


def walk(pack, msg, plan):
    """Reading step 8 for the lines of the selected scope (outside group
    bodies, which are read per item): an item on a path that exists and is
    not the container its next step needs is `malformed-wire`."""
    top = msg.top
    for ln in plan.lines:
        if getattr(ln, "is_element", False):
            continue
        _strict(pack, top, ln.loc, "the line at %s" % ln.locator)


def when_holds(pack, msg, when):
    try:
        node = _lookup(msg.top, when.loc)
    except _Wrong:
        return False  # Reading step 7
    if node is None or node.is_nil():
        return False
    if when.present:
        return True
    kind, v = when.value
    if kind == "i":
        return (node.mt == _UINT or node.mt == _NINT) and node.val == v
    if kind == "b":
        return node.mt == _SIMPLE and node.val == (_TRUE if v else _FALSE)
    return node.mt == _TEXT and node.val == v


def body_kind(group):
    """The type of the elements a group body reads: SCALAR for a body of `.`
    only, ARRAY when its paths begin with positions, else MAP."""
    cache = group.plan.cache
    kind = cache.get("cbor-body")
    if kind is None:
        kind = MAP
        for ln in group.lines:
            if getattr(ln, "is_element", False):
                continue
            if ln.loc == ():
                kind = SCALAR
                break
            kind = ARRAY if is_position(ln.loc[0]) else MAP
            break
        cache["cbor-body"] = kind
    return kind


def items(pack, ctx, group):
    """The elements of the array at a group's path, or None for an absent
    list (not there, `null` or `undefined`). Another item is
    `malformed-wire`. An element of the wrong type for the body is an item
    with no keys (ruling 12 of 0.7)."""
    node = _start(ctx)
    if node is None:
        return None
    node = _strict(pack, node, group.loc, "group %s" % group.list)
    if node is None or node.is_nil():
        return None
    if node.mt != _ARR:
        raise MalformedWire("the item at the path of group %s is not an array" % group.list,
                            format=pack.name, locator=group.locator)
    kind = body_kind(group)
    if kind == SCALAR:
        return list(node.val)
    want = _ARR if kind == ARRAY else _MAP
    return [el if el.mt == want else EMPTY for el in node.val]


# --- residue --------------------------------------------------------------------


def _scope_paths(plan):
    """-> (the path of each line, {walked prefix: MAP | ARRAY}). Every proper
    prefix of a line's path is walked into, a `when ... present` and a group
    included; a line's own item is not."""
    info = plan.cache.get("cbor")
    if info is None:
        walked = {}
        for ln in plan.lines:
            if getattr(ln, "is_element", False):
                continue
            path = ln.loc
            for d in range(len(path)):
                walked.setdefault(path[:d], ARRAY if is_position(path[d]) else MAP)
        info = plan.cache["cbor"] = walked
    return info


def residue(pack, msg, plan, mapped_locators):
    """-> {path: hex of the item as it stood} of every member or element that
    no line of the scope maps and none walks into (Residue)."""
    walked = _scope_paths(plan)
    mapped = set()
    for ln in plan.lines:
        if ln.locator in mapped_locators and not getattr(ln, "is_element", False):
            mapped.add(ln.loc)
    buf = msg.buf
    out = {}

    def visit(node, path):
        prefix = path_text(path)
        dot = prefix + "." if prefix else ""
        if node.mt == _MAP:
            for k, x in node.val:
                step = addressable(k)
                if step is None:
                    out[dot + "#" + buf[k.start:k.end].hex()] = buf[x.start:x.end].hex()
                    continue
                here(x, path + (step,), dot + step_text(step))
        else:
            for i, x in enumerate(node.val):
                if i > MAX_POSITION:
                    break  # ruling 18: no key a path can write
                here(x, path + ((i,),), dot + "[%d]" % i)

    def here(x, p, text):
        if p in mapped:
            return
        kind = walked.get(p)
        if kind is not None:
            if (kind == MAP and x.mt == _MAP) or (kind == ARRAY and x.mt == _ARR):
                visit(x, p)
                return
            if x.is_nil():
                return  # ruling 12: walked into, not written back
        out[text] = buf[x.start:x.end].hex()

    visit(msg.top, ())
    return out


# --- transforms -----------------------------------------------------------------


class CborTransform(Transform):
    kind = "cbor"


def _model_int(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s transform needs an integer, got %s" % (name, type(value).__name__))
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError("%s transform got non-integral %r" % (name, value))
        value = int(value)
    return value


def _need(name, item, *mts):
    if type(item) is not Item or item.mt not in mts:
        raise ValueError("%s transform: the item is of another type" % name)


class UintT(CborTransform):
    name = "uint"
    yields = "int"

    def decode(self, item):
        _need(self.name, item, _UINT)
        if item.val > _I64_MAX:
            raise ValueError("uint: %d lies above 2^63-1" % item.val)
        return item.val

    def encode(self, value):
        v = _model_int(self.name, value)
        if v < 0 or v > _U64_MAX:
            raise ValueError("uint: %d is not a value of major type 0" % v)
        return head(0, v)


class IntT(CborTransform):
    name = "int"
    yields = "int"

    def decode(self, item):
        _need(self.name, item, _UINT, _NINT)
        if not _I64_MIN <= item.val <= _I64_MAX:
            raise ValueError("int: %d lies outside -2^63 to 2^63-1" % item.val)
        return item.val

    def encode(self, value):
        v = _model_int(self.name, value)
        if v < -(1 << 64) or v > _U64_MAX:
            raise ValueError("int: %d does not fit a CBOR integer" % v)
        return int_bytes(v)


class FloatT(CborTransform):
    name = "float"
    yields = "float"

    def decode(self, item):
        _need(self.name, item, _FLOAT, _UINT, _NINT)
        if item.mt != _FLOAT:
            return float(item.val)  # the nearest double, ties to even
        width, bits = item.val
        x = struct.unpack({2: ">e", 4: ">f", 8: ">d"}[width], bits.to_bytes(width, "big"))[0]
        if not math.isfinite(x):
            raise ValueError("float: a NaN or an infinity")
        return x

    def encode(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("float transform needs a number, got %s" % type(value).__name__)
        try:
            x = float(value)
        except OverflowError:
            raise ValueError("float: %r does not fit a double" % (value,))
        if not math.isfinite(x):
            raise ValueError("float: %r is not finite" % (value,))  # ruling 20
        return float_bytes(x)


class TextT(CborTransform):
    name = "text"
    yields = "string"

    def decode(self, item):
        _need(self.name, item, _TEXT)
        return item.val

    def encode(self, value):
        if not isinstance(value, str):
            raise ValueError("text transform needs a str, got %s" % type(value).__name__)
        return text_bytes(value)


class BytesT(CborTransform):
    name = "bytes"
    yields = "string"

    def decode(self, item):
        _need(self.name, item, _BYTES)
        return item.val.hex()

    def encode(self, value):
        if not isinstance(value, str) or not value.isascii() or _LOWER_HEX.match(value) is None:
            raise ValueError("bytes: %r is not an even number of lowercase hex digits" % (value[:40],))
        raw = bytes.fromhex(value)
        return head(2, len(raw)) + raw


class BoolT(CborTransform):
    name = "bool"
    yields = "int"

    def decode(self, item):
        _need(self.name, item, _SIMPLE)
        if item.val == _TRUE:
            return 1
        if item.val == _FALSE:
            return 0
        raise ValueError("bool: simple value %d" % item.val)

    def encode(self, value):
        if not isinstance(value, bool):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            if isinstance(value, int) and value in (0, 1):
                return b"\xf5" if value == 1 else b"\xf4"
        raise ValueError("bool transform encodes 1 or 0, got %r" % (value,))


class EpochST(CborTransform):
    name = "epoch_s"
    yields = "int"

    def decode(self, item):
        _need(self.name, item, _UINT, _NINT)
        ms = item.val * 1000
        if not _I64_MIN <= ms <= _I64_MAX:  # ruling 7: the range applies to the product
            raise ValueError("epoch_s: %d s gives a time_ms outside -2^63 to 2^63-1" % item.val)
        return ms

    def encode(self, value):
        v = _model_int(self.name, value)
        q, r = divmod(abs(v), 1000)
        if r >= 500:  # half away from zero
            q += 1
        s = -q if v < 0 else q
        if s < -(1 << 64) or s > _U64_MAX:
            raise ValueError("epoch_s: %d s does not fit a CBOR integer" % s)
        return int_bytes(s)


TRANSFORMS = {t.name: t for t in (UintT(), IntT(), FloatT(), TextT(), BytesT(), BoolT(), EpochST())}


def value_bytes(value):
    """A `when` or `const` value, written with its type."""
    kind, v = value
    if kind == "i":
        return int_bytes(v)
    if kind == "b":
        return b"\xf5" if v else b"\xf4"
    return text_bytes(v)


# --- load checks ----------------------------------------------------------------


def check_pack(common, kinds, deferred, source, name):
    """The checks of 0.28 "Types" and rulings 13 and 22 that need the whole
    file, each `bad-directive` appended to `deferred`: two top-level paths
    that decide the top item's type differently, anywhere in the pack; within
    one scope (common with one kind, or one group body) an item used both as
    a map and as an array, a line at a path under another line's path (a
    `when ... present` excepted as the shorter path), a line at or under a
    group's path, a group at or under another line's path. -> the type of the
    top item, MAP or ARRAY."""
    from .errors import BadDirective

    def bad(lineno, msg, locator):
        deferred.append((lineno, BadDirective("%s, at %s:%d" % (msg, source, lineno), format=name, locator=locator)))

    def lines_of(seq):
        return [ln for ln in seq if not getattr(ln, "is_element", False)]

    top = None
    for ln in lines_of(common) + [ln for k in kinds for ln in lines_of(k.lines)]:
        path = ln.loc
        if path == ():
            t = ARRAY  # `group <list> .`
        else:
            t = ARRAY if is_position(path[0]) else MAP
        if top is None:
            top = (t, ln.lineno)
        elif top[0] != t:
            bad(ln.lineno, "the path decides the top item is %s; an earlier line decides %s" % (
                "an array" if t == ARRAY else "a map", "an array" if top[0] == ARRAY else "a map"), ln.locator)

    def kind_of(ln):
        if ln.is_group:
            return "group"
        if ln.is_field:
            return "field"
        if ln.is_const:
            return "const"
        return "whenp" if ln.present else "when"

    def scope(lines):
        by_path = {}
        for ln in lines:
            by_path.setdefault(ln.loc, []).append(kind_of(ln))
        types = {}
        for ln in lines:
            path = ln.loc
            for d in range(len(path)):
                t = ARRAY if is_position(path[d]) else MAP
                prev = types.setdefault(path[:d], t)
                if prev != t:
                    bad(ln.lineno, "the item at %s is used both as a map and as an array"
                        % (path_text(path[:d]) or "the top"), ln.locator)
                    break
            for d in range(len(path)):
                if any(k != "whenp" for k in by_path.get(path[:d], ())):
                    bad(ln.lineno, "a line at a path under the path of another line of its scope (ruling 13)",
                        ln.locator)
                    break
            same = by_path[path]
            if len(same) > 1 and "group" in same:
                bad(ln.lineno, "a line at the path of a group of its scope", ln.locator)

    def bodies(groups):
        for g in groups:
            body = lines_of(g.lines)
            scope(body)
            bodies([ln for ln in body if ln.is_group])

    base = lines_of(common)
    if kinds:
        for k in kinds:
            scope(base + lines_of(k.lines))
    else:
        scope(base)
    bodies([ln for ln in base if ln.is_group])
    for k in kinds:
        bodies([ln for ln in lines_of(k.lines) if ln.is_group])
    return top[0] if top is not None else MAP


def overridden(plan):
    """-> the indexes of the `field` lines at a path a `when` with a value or
    a `const` of the scope names: the item holds that value (Writing step 1),
    so the field is not encoded."""
    skip = plan.cache.get("cbor-skip")
    if skip is None:
        fixed = {ln.loc for ln in plan.lines
                 if not ln.is_field and not ln.is_group and not ln.present and not getattr(ln, "is_element", False)}
        skip = plan.cache["cbor-skip"] = {i for i, f in plan.ifields if f.loc in fixed}
    return skip


# --- writing --------------------------------------------------------------------


class _Node:
    """A map or an array being written. `kids` maps an encoded key (a map)
    or a position (an array) to a _Node or to the bytes of an item. `walked`:
    the lines walk into it (ruling 23). `fallback`: a residue item whole at
    this place, written when nothing else is."""

    __slots__ = ("kind", "kids", "walked", "fallback")

    def __init__(self, kind, walked):
        self.kind = kind
        self.kids = {}
        self.walked = walked
        self.fallback = None


def _kid(step):
    return step[0] if type(step) is tuple else step_key(step)


def _build(pack, enc, kind):
    """The tree of one encoded scope whose top item is of `kind` -> _Node,
    or the bytes of the item when a line writes the scope's item itself
    (`.`)."""
    plan = enc.plan
    chosen = {}
    lines = [ln for ln in plan.lines if not getattr(ln, "is_element", False)]
    for ln in lines:  # a `when` or `const` value over a field's
        if not ln.is_field and not ln.is_group and not ln.present and ln.loc not in chosen:
            chosen[ln.loc] = value_bytes(ln.value)
    values = enc.values
    for i, f in plan.ifields:  # the earliest line whose key is present (ruling 16 of 0.5)
        if i in values and f.loc not in chosen:
            chosen[f.loc] = values[i]
    for i, g in plan.igroups:
        children = enc.groups.get(i)
        if children is not None and g.loc not in chosen:
            body = body_kind(g)
            parts = [head(4, len(children))]
            for c in children:
                if body == SCALAR:
                    b = _build(pack, c, MAP)
                    parts.append(b if isinstance(b, bytes) else b"\xf6")
                else:
                    parts.append(_serialize(_build(pack, c, body), True))
            chosen[g.loc] = b"".join(parts)
    if () in chosen:
        return chosen[()]
    root = _Node(kind, True)
    for ln in lines:
        path = ln.loc
        node = root
        for d in range(len(path) - 1):
            k = _kid(path[d])
            child = node.kids.get(k)
            if child is None:
                child = node.kids[k] = _Node(ARRAY if is_position(path[d + 1]) else MAP, True)
            node = child
    for path, b in chosen.items():
        node = root
        for step in path[:-1]:
            node = node.kids[_kid(step)]
        node.kids[_kid(path[-1])] = b
    return root


def _residue_path(text):
    """A residue key -> list of steps, the last possibly ("#", key bytes);
    or None."""
    if not isinstance(text, str) or not text:
        return None
    parts = text.split(".")
    steps = []
    for n, part in enumerate(parts):
        if part.startswith("#") and n == len(parts) - 1:
            hx = part[1:]
            if not hx.isascii() or _HEX_TEXT.match(hx) is None or not hx:
                return None
            try:
                steps.append(("#", canon(read_item(bytes.fromhex(hx)))))
            except (_Bad, RecursionError):
                return None
            continue
        try:
            steps.append(parse_step(part))
        except ValueError:
            return None
    return steps


def _place_residue(root, residue):
    """Put each residue entry back into its map or array, re-encoded with the
    deterministic encoding (Residue). An entry whose key or item does not
    parse, whose steps do not fit the containers on its way, or that stands
    where a line writes (ruling 21) is not written."""
    pairs = residue.items() if isinstance(residue, dict) else residue
    for entry in pairs or ():
        try:
            text, value = entry
        except (TypeError, ValueError):
            continue
        if not isinstance(value, str) or not value or not value.isascii() or _HEX_TEXT.match(value) is None:
            continue
        steps = _residue_path(text)
        if steps is None:
            continue
        try:
            item = canon(read_item(bytes.fromhex(value)))
        except (_Bad, RecursionError):
            continue
        node = root
        last = len(steps) - 1
        for d, step in enumerate(steps):
            hashed = type(step) is tuple and len(step) == 2
            if (node.kind == ARRAY) != (type(step) is tuple and len(step) == 1):
                break  # the step does not fit its container
            k = step[1] if hashed else _kid(step)
            child = node.kids.get(k)
            if d == last:
                if child is None:
                    node.kids[k] = item
                elif isinstance(child, _Node) and child.fallback is None:
                    child.fallback = item  # written only when nothing else is written there
                break  # else a line writes there, and wins (ruling 21)
            nxt = steps[d + 1]
            want = ARRAY if type(nxt) is tuple and len(nxt) == 1 else MAP
            if child is None:
                child = node.kids[k] = _Node(want, False)
            elif not isinstance(child, _Node) or child.kind != want:
                break  # a line writes a value or another container there
            node = child


def _serialize(node, top):
    """-> the bytes of a _Node, or None when it is not written (Writing steps
    2 and 3, ruling 23)."""
    if isinstance(node, bytes):
        return node
    written = {}
    for k, child in node.kids.items():
        b = _serialize(child, False)
        if b is not None:
            written[k] = b
    if not written:
        if node.fallback is not None:
            return node.fallback
        if top:
            return b"\xa0" if node.kind == MAP else b"\x80"
        return None
    if node.kind == MAP:
        out = [head(5, len(written))]
        for k in sorted(written):
            out.append(k)
            out.append(written[k])
        return b"".join(out)
    hi = max(written)
    out = [head(4, hi + 1)]
    for i in range(hi + 1):
        b = written.get(i)
        if b is None:
            c = node.kids.get(i)
            if isinstance(c, _Node) and c.walked:
                b = b"\xa0" if c.kind == MAP else b"\x80"
            else:
                b = b"\xf6"
        out.append(b)
    return b"".join(out)


def write(pack, enc, residue):
    """Writing steps 1 to 5 -> lowercase hex text."""
    tree = _build(pack, enc, pack.cbor_top)
    if isinstance(tree, bytes):
        body = tree
    else:
        if residue:
            _place_residue(tree, residue)
        body = _serialize(tree, True)
    if pack.cbor_tag is not None:
        body = head(6, pack.cbor_tag) + body
    return body.hex()
