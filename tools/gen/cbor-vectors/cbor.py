"""Standalone CBOR codec written from RFC 8949 for deriving vectors.
Standard library only. No import from the repository.

Python values used to build items:
  int -> major 0/1; str -> major 3; bytes -> major 2; float -> major 7 float;
  True/False -> f5/f4; None -> f6 (null); UNDEF -> f7;
  list -> array; dict or M([(k,v),...]) -> map; Tag(n, item);
  Raw(hexstr) -> those bytes verbatim (input only, for non-canonical forms).
"""
import struct, math

class _Undef:
    def __repr__(self): return "UNDEF"
UNDEF = _Undef()

class Tag:
    def __init__(self, n, item): self.n, self.item = n, item
    def __repr__(self): return "Tag(%d,%r)" % (self.n, self.item)

class M:
    def __init__(self, pairs): self.pairs = list(pairs)
    def __repr__(self): return "M(%r)" % self.pairs

class Raw:
    def __init__(self, hx): self.b = bytes.fromhex(hx.replace(" ", ""))

def head(major, n):
    """Shortest head (RFC 8949 4.2.1 'preferred serialization' of arguments)."""
    if n < 24: return bytes([major << 5 | n])
    if n < 0x100: return bytes([major << 5 | 24, n])
    if n < 0x10000: return bytes([major << 5 | 25]) + n.to_bytes(2, "big")
    if n < 0x100000000: return bytes([major << 5 | 26]) + n.to_bytes(4, "big")
    if n < 1 << 64: return bytes([major << 5 | 27]) + n.to_bytes(8, "big")
    raise ValueError("argument too large")

def _same(a, b):
    return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)

def enc_float(x):
    """Shortest of half, single, double holding x exactly (4.2.2), -0.0 as f98000."""
    if math.isnan(x): return bytes.fromhex("f97e00")
    try:
        h = struct.pack(">e", x)
        if _same(struct.unpack(">e", h)[0], x): return b"\xf9" + h
    except OverflowError:
        pass
    try:
        s = struct.pack(">f", x)
        if _same(struct.unpack(">f", s)[0], x): return b"\xfa" + s
    except OverflowError:
        pass
    return b"\xfb" + struct.pack(">d", x)

def enc(item, canonical=True):
    if isinstance(item, Raw): return item.b
    if item is True: return b"\xf5"
    if item is False: return b"\xf4"
    if item is None: return b"\xf6"
    if item is UNDEF: return b"\xf7"
    if isinstance(item, int):
        return head(0, item) if item >= 0 else head(1, -1 - item)
    if isinstance(item, float): return enc_float(item)
    if isinstance(item, bytes): return head(2, len(item)) + item
    if isinstance(item, str):
        b = item.encode("utf-8"); return head(3, len(b)) + b
    if isinstance(item, Tag): return head(6, item.n) + enc(item.item, canonical)
    if isinstance(item, list):
        return head(4, len(item)) + b"".join(enc(i, canonical) for i in item)
    if isinstance(item, (dict, M)):
        pairs = list(item.items()) if isinstance(item, dict) else item.pairs
        ep = [(enc(k, canonical), enc(v, canonical)) for k, v in pairs]
        if canonical:
            ep.sort(key=lambda kv: kv[0])   # bytewise lexicographic on encoded keys
            for a, b in zip(ep, ep[1:]):
                assert a[0] != b[0], "duplicate key in built map"
        return head(5, len(ep)) + b"".join(k + v for k, v in ep)
    raise TypeError(repr(item))

def H(item, canonical=True): return enc(item, canonical).hex()

def positional(present, walks=None):
    """An array addressed by positions, as Writing step 3 and ruling 23 of
    0.28 write it: up to the highest present position; a position below it
    with nothing to write is an empty map when the pack's lines walk into it
    as a map, an empty array when they walk into it as an array, else null.
    present: {position: item to write}; walks: {position: "map" | "array" |
    "group"}, stated by hand from the pack's lines. A position that is a
    group's own path is not walked into (ruling 23): an absent list there is
    null; a present list, even empty, is an item of `present` (step 4)."""
    walks = walks or {}
    if not present: return []
    out = []
    for i in range(max(present) + 1):
        if i in present: out.append(present[i])
        elif walks.get(i) == "map": out.append({})
        elif walks.get(i) == "array": out.append([])
        else: out.append(None)          # a scalar line, a group's own path, or no line
    return out

# ---------------------------------------------------------------- decoding
class Malformed(Exception): pass

class Node:
    """A decoded item: kind in uint,nint,bytes,text,array,map,float,simple;
    value; tags (outermost first); raw (bytes as they stood, tags included)."""
    def __init__(self, kind, value, tags, raw):
        self.kind, self.value, self.tags, self.raw = kind, value, tags, raw
    def __repr__(self): return "Node(%s,%r,tags=%r)" % (self.kind, self.value, self.tags)

def decode(data, max_depth=64):
    pos = [0]
    def need(n):
        if n > len(data) - pos[0]: raise Malformed("length past input")
    def rd(n):
        need(n); b = data[pos[0]:pos[0] + n]; pos[0] += n; return b
    def arg(ai):
        if ai < 24: return ai
        if ai == 24: return rd(1)[0]
        if ai == 25: return int.from_bytes(rd(2), "big")
        if ai == 26: return int.from_bytes(rd(4), "big")
        if ai == 27: return int.from_bytes(rd(8), "big")
        raise Malformed("reserved additional information %d" % ai)
    def item(depth, allow_break=False):
        start = pos[0]
        tags = []
        while True:
            ib = rd(1)[0]; mt, ai = ib >> 5, ib & 31
            if mt == 6:
                if ai == 31: raise Malformed("indefinite tag")
                tags.append(arg(ai)); depth += 1
                if depth > max_depth: raise Malformed("depth")
                continue
            break
        if ib == 0xff:
            if allow_break and not tags: return "BREAK"
            raise Malformed("break outside indefinite item")
        def fin(kind, val): return Node(kind, val, tags, data[start:pos[0]])
        if mt in (0, 1):
            n = arg(ai); return fin("uint" if mt == 0 else "nint", n if mt == 0 else -1 - n)
        if mt in (2, 3):
            if ai == 31:
                chunks = []
                while True:
                    cs = pos[0]; cb = rd(1)[0]
                    if cb == 0xff: break
                    if cb >> 5 != mt or (cb & 31) == 31: raise Malformed("bad chunk")
                    n = arg(cb & 31); c = rd(n)
                    if mt == 3:
                        try: c.decode("utf-8")
                        except UnicodeDecodeError: raise Malformed("invalid UTF-8 in a chunk")
                    chunks.append(c)
                b = b"".join(chunks)
            else:
                n = arg(ai); b = rd(n)
                if mt == 3:
                    try: b.decode("utf-8")
                    except UnicodeDecodeError: raise Malformed("invalid UTF-8")
            return fin("bytes" if mt == 2 else "text", b if mt == 2 else b.decode("utf-8"))
        if mt in (4, 5):
            d = depth + 1
            if d > max_depth: raise Malformed("depth")
            out = []
            if ai == 31:
                while True:
                    k = item(d, allow_break=True)
                    if k == "BREAK": break
                    if mt == 5:
                        v = item(d)
                        out.append((k, v))
                    else: out.append(k)
            else:
                n = arg(ai)
                need(n * (2 if mt == 5 else 1))   # each item takes at least one byte
                for _ in range(n):
                    k = item(d)
                    if mt == 5: out.append((k, item(d)))
                    else: out.append(k)
            if mt == 5:
                seen = set()
                for k, _ in out:
                    ck = canon(k)
                    if ck in seen: raise Malformed("duplicate key %s" % ck.hex())
                    seen.add(ck)
            return fin("array" if mt == 4 else "map", out)
        # major 7
        if ai < 20: return fin("simple", ai)
        if ai in (20, 21): return fin("simple", ai)
        if ai in (22, 23): return fin("simple", ai)
        if ai == 24:
            v = rd(1)[0]
            if v < 32: raise Malformed("two-byte simple below 32")
            return fin("simple", v)
        if ai == 25: return fin("float", struct.unpack(">e", rd(2))[0])
        if ai == 26: return fin("float", struct.unpack(">f", rd(4))[0])
        if ai == 27: return fin("float", struct.unpack(">d", rd(8))[0])
        raise Malformed("reserved major 7 additional information %d" % ai)
    top = item(0)
    if top == "BREAK": raise Malformed("break")
    if pos[0] != len(data): raise Malformed("bytes after the item")
    return top

def canon(node):
    """Core deterministic encoding (RFC 8949 4.2.1) of a decoded node, tags kept."""
    k, v = node.kind, node.value
    if k in ("uint", "nint"): b = enc(v)
    elif k == "bytes": b = enc(bytes(v))
    elif k == "text": b = enc(v)
    elif k == "float": b = enc_float(v)
    elif k == "simple": b = head(7, v) if v < 24 else bytes([0xf8, v])
    elif k == "array": b = head(4, len(v)) + b"".join(canon(i) for i in v)
    elif k == "map":
        ep = sorted((canon(a), canon(c)) for a, c in v)
        b = head(5, len(ep)) + b"".join(a + c for a, c in ep)
    pre = b"".join(head(6, t) for t in node.tags)
    return pre + b

def dhex(hx, **kw): return decode(bytes.fromhex(hx), **kw)
