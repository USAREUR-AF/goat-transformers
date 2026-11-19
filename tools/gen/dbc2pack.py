#!/usr/bin/env python3
"""Generate goat-transformers packs from CAN DBC files (github.com/commaai/opendbc).

Reads   <src>/opendbc/dbc/*.dbc, <src>/opendbc/dbc/generator/<brand>/*.dbc (the
        files opendbc assembles from parts with `CM_ "IMPORT <part>";`) and
        <src>/LICENSE; tools/gen/sources/dbc-PROVENANCE.md (the commit and the
        SHA-256 of every file; a file that differs is refused)
Writes  <out>/model/dbc<file>.def          one module per DBC file
        <out>/packs/dbc-<file>/pack.def    one pack per DBC file, one kind per CAN
        <out>/packs/dbc-<file>/pack.md     message (and per multiplexor value)
        <out>/packs/dbc-<file>/PROVENANCE.md
        <out>/packs/dbc-<file>/vectors/*.json
        tools/gen/sources/dbc-PROVENANCE.md (only with --commit)

The message is one Linux SocketCAN `struct can_frame`: 16 bytes. Bytes 0-3 hold
the CAN identifier as a little-endian 32-bit word whose top three bits are the
flags (bit 31 extended frame format, bit 30 remote transmission request, bit 29
error frame); byte 4 the data length; bytes 5-7 padding; bytes 8-15 the data.
A kind is selected by the whole identifier word and the data length.

Every vector's frame is written by a DBC serializer in this file, built from
the DBC rules (Intel signals from their least significant bit upward, Motorola
signals from their most significant bit through the DBC bit numbering); the
generator then loads the pack with gtcheck and decodes and encodes every vector
with its own codec of the bits wire.

Python 3 standard library only. Exit status 0 when every check passed, 1 for a
refused input or a failed check, 2 for a usage error.
"""
import argparse
import collections
import hashlib
import json
import math
import os
import re
import struct
import sys
from decimal import Decimal
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

NAME = "dbc2pack"
VERSION = "0.1.0"
REPO = "https://github.com/commaai/opendbc"
PROV = "tools/gen/sources/dbc-PROVENANCE.md"
DBC_DIR = "opendbc/dbc"
CAN_UAPI = "Linux UAPI header include/uapi/linux/can.h, struct can_frame (GPL-2.0 WITH Linux-syscall-note)"
DATA_BIT0 = 64                 # data[0] starts at byte 8
EFF, RTR, ERR = 1 << 31, 1 << 30, 1 << 29
PSEUDO_ID = 0xC0000000         # VECTOR__INDEPENDENT_SIG_MSG and the like: no frame
MAX_REQUIRES = 3
SKIPPED_SOURCES = []           # (generator file, reason), filled by load_sources


class GenError(Exception):
    pass


class CodecError(Exception):
    pass


def read_text(path):
    """A DBC file's text: UTF-8, or else Windows-1252, the code page many DBC
    editors write."""
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ------------------------------------------------------------------ parse ---

Signal = collections.namedtuple("Signal", "name start length motorola signed factor offset unit mux muxor line")
Message = collections.namedtuple("Message", "id name size sender signals line")

BO_RE = re.compile(r"^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\S+)")
SG_RE = re.compile(r"^\s*SG_\s+(\w+)\s*(M|m\d*M?)?\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*"
                   r"\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)\s*\[\s*([^|\]]*)\|([^\]]*)\]\s*\"([^\"]*)\"")
VAL_RE = re.compile(r"^VAL_\s+(\d+)\s+(\w+)\s+(.*);\s*$")
VALTYPE_RE = re.compile(r"^SIG_VALTYPE_\s+(\d+)\s+(\w+)\s*:?\s*(\d)\s*;")
IMPORT_RE = re.compile(r'CM_ "IMPORT (.*?)";\n')


class DbcFile:
    def __init__(self, name, path):
        self.name, self.path = name, path       # path: the source files it is made of
        self.messages = []
        self.values = {}                        # (id, signal) -> [(raw, label)]
        self.valtype = {}                       # (id, signal) -> 1 float, 2 double
        self.mul_val = {}                       # (id, signal) -> (multiplexor, {values}) from SG_MUL_VAL_
        self.extended_mux = set()               # ids whose SG_MUL_VAL_ the pack cannot state


def parse_dbc(text, name, path):
    d = DbcFile(name, path)
    cur = None
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        m = BO_RE.match(line.lstrip())             # a keyword may be indented
        if m:
            cur = Message(int(m.group(1)), m.group(2), int(m.group(3)), m.group(4), [], ln)
            d.messages.append(cur)
            continue
        if line.lstrip().startswith("SG_ "):
            m = SG_RE.match(line)
            if not m or cur is None:
                raise GenError("%s:%d: cannot read the signal line" % (name, ln))
            mux = m.group(2)
            muxor = mux is not None and mux.endswith("M")
            muxval = None
            if mux and mux.startswith("m"):
                digits = mux[1:].rstrip("M")
                muxval = int(digits) if digits else -1     # `m` with no value: not a usable signal
            cur.signals.append(Signal(m.group(1), int(m.group(3)), int(m.group(4)), m.group(5) == "0",
                                      m.group(6) == "-", m.group(7), m.group(8), m.group(11),
                                      muxval, muxor, ln))
            continue
        if not line or (line[0].isspace() and not re.match(r"^\s*(VAL_|SIG_VALTYPE_|SG_MUL_VAL_)\s", line)):
            continue
        line = line.lstrip()
        cur = None
        m = VAL_RE.match(line)
        if m:
            pairs = re.findall(r'(-?\d+)\s+"([^"]*)"', m.group(3))
            d.values[(int(m.group(1)), m.group(2))] = [(int(v), lab) for v, lab in pairs]
            continue
        m = VALTYPE_RE.match(line)
        if m:
            d.valtype[(int(m.group(1)), m.group(2))] = int(m.group(3))
            continue
        if line.startswith("SG_MUL_VAL_"):
            m = re.match(r"^SG_MUL_VAL_\s+(\d+)\s+(\w+)\s+(\w+)\s+(.*?)\s*;\s*$", line)
            if not m:
                parts = line.split()
                if len(parts) > 1 and parts[1].isdigit():
                    d.extended_mux.add(int(parts[1]))
                continue
            values = set()
            for lo, hi in re.findall(r"(\d+)\s*-\s*(\d+)", m.group(4)):
                if int(hi) - int(lo) > 255:
                    d.extended_mux.add(int(m.group(1)))
                values |= set(range(int(lo), int(hi) + 1))
            d.mul_val[(int(m.group(1)), m.group(2))] = (m.group(3), values)
    return d


def assemble(src_dir, file_name):
    """A generator DBC with its `CM_ "IMPORT <part>";` parts, in the order and the
    form opendbc's generator.py writes them."""
    text = read_text(os.path.join(src_dir, file_name))
    parts = ['CM_ "AUTOGENERATED FILE, DO NOT EDIT";\n']
    includes = IMPORT_RE.findall(text)
    for inc in includes:
        parts.append('\n\nCM_ "Imported file %s starts here";\n' % inc)
        parts.append(read_text(os.path.join(src_dir, inc)))
    parts.append('\nCM_ "%s starts here";\n' % file_name)
    parts.append(IMPORT_RE.sub("", text))
    return "".join(parts), includes


def load_sources(src):
    """[(pack file name, text, [source paths relative to src])] of every DBC."""
    base = os.path.join(src, DBC_DIR)
    out = []
    for f in sorted(os.listdir(base)):
        if f.endswith(".dbc"):
            out.append((f[:-4], read_text(os.path.join(base, f)), [DBC_DIR + "/" + f]))
    gen = os.path.join(base, "generator")
    if os.path.isdir(gen):
        for brand in sorted(os.listdir(gen)):
            bdir = os.path.join(gen, brand)
            if not os.path.isdir(bdir):
                continue
            for f in sorted(os.listdir(bdir)):
                if f.endswith(".dbc") and not f.startswith("_"):
                    missing = [i for i in IMPORT_RE.findall(read_text(os.path.join(bdir, f)))
                               if not os.path.isfile(os.path.join(bdir, i))]
                    if missing:
                        # a part opendbc writes with a Python script: not read here
                        SKIPPED_SOURCES.append((f, "imports %s, which opendbc writes with a Python script"
                                                % ", ".join(missing)))
                        continue
                    text, includes = assemble(bdir, f)
                    rel = "%s/generator/%s/" % (DBC_DIR, brand)
                    out.append((f[:-4] + "_generated", text, [rel + f] + [rel + i for i in includes]))
    names = [n for n, _, _ in out]
    if len(set(names)) != len(names):
        raise GenError("two DBC files give one pack name")
    return out


def source_files(src):
    files = []
    base = os.path.join(src, DBC_DIR)
    for directory, dirs, names in os.walk(base):
        dirs.sort()
        for n in sorted(names):
            if n.endswith(".dbc"):
                files.append(os.path.relpath(os.path.join(directory, n), src).replace(os.sep, "/"))
    return files


# ------------------------------------------------------------------- plan ---

def slug(text):
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s if s and not s[0].isdigit() else "x" + s


def factor_text(text):
    """A DBC factor as the pack writes it: an integer, or an exact fraction
    (engine-spec 0.5 ruling 1)."""
    d = Decimal(text.strip())
    f = Fraction(d)
    if f == 0:
        raise ValueError("zero factor")
    if f < 0 and f.denominator != 1:
        # a fraction is `<num>/<den>` of two decimal integers; whether the
        # numerator may carry a sign is not pinned, and the Rust reference
        # refuses it, so a negative factor is written as its decimal
        return format(d.normalize(), "f")
    return str(f.numerator) if f.denominator == 1 else "%d/%d" % (f.numerator, f.denominator)


def offset_text(text):
    d = Decimal(text.strip())
    if d == 0:
        return None
    s = format(d.normalize(), "f")
    return s


def msb_index(dbc_bit):
    """The DBC bit number (bit b of byte b//8, b%8 from the least significant)
    as a position in most-significant-bit-first order."""
    return (dbc_bit // 8) * 8 + 7 - dbc_bit % 8


def place(sig, order):
    """(first bit, swap) of a signal's `field` locator relative to data[0] in a
    pack of bit order `order`, or (None, reason)."""
    s, n = sig.start, sig.length
    if not sig.motorola:                       # Intel: bits s..s+n-1, least significant first
        if order == "lsb":
            return s, False
        if s // 8 == (s + n - 1) // 8:
            return msb_index(s + n - 1), False
        if s % 8 == 0 and n % 8 == 0:
            return s, True
        return None, "Intel signal over byte boundaries in a Motorola (msb) pack"
    m = msb_index(s)                           # Motorola: most significant bit at s
    if order == "msb":
        return m, False
    if m // 8 == (m + n - 1) // 8:
        return msb_index(m + n - 1), False     # one byte: the same bits, low first
    if m % 8 == 0 and n % 8 == 0:
        return m, True
    return None, "Motorola signal over byte boundaries in an Intel (lsb) pack"


def span(sig):
    """The set of DBC bit numbers a signal occupies (for overlap and length)."""
    if not sig.motorola:
        return set(range(sig.start, sig.start + sig.length))
    out, pos = set(), sig.start
    for _ in range(sig.length):
        out.add(pos)
        pos = pos + 15 if pos % 8 == 0 else pos - 1
    return out


Line = collections.namedtuple("Line", "key pos bits tr swap via")


class KindPlan:
    def __init__(self, name, msg, muxval):
        self.name, self.msg, self.muxval = name, msg, muxval
        self.lines, self.signals = [], []      # lines and the signals they map
        self.mux_line = None
        self.requires = []


def core_of(sig, msg):
    """`lat` / `lon` for a signal a DBC states as a latitude or longitude in
    degrees: a name ending in latitude or longitude, a unit of deg or degrees."""
    n = sig.name.lower()
    if sig.unit.strip().lower() not in ("deg", "degree", "degrees"):
        return None
    if n.endswith("latitude"):
        return "lat"
    if n.endswith("longitude"):
        return "lon"
    return None


class FilePlan:
    def __init__(self, dbc, sources):
        self.dbc, self.sources = dbc, sources
        self.format = "dbc-" + dbc.name.lower().replace("_", "-")
        self.module = "dbc" + re.sub(r"[^a-z0-9]", "", dbc.name.lower())
        motorola = sum(s.motorola for m in dbc.messages for s in m.signals)
        intel = sum(not s.motorola for m in dbc.messages for s in m.signals)
        self.order = "msb" if motorola > intel else "lsb"
        self.counts = (intel, motorola)
        self.kinds, self.keys, self.tables = [], collections.OrderedDict(), collections.OrderedDict()
        self.skipped_messages = []             # (message, reason)
        self.unmapped = []                     # (message, signal, reason)
        self.core = []                         # (kind, signal, core key)
        self.plan()

    def key_of(self, msg, sig):
        """`<message>_<signal>` in lower case; signal names of one message that
        differ only in case take `_2`, `_3`… in the order of the file."""
        cache = self.__dict__.setdefault("_keys", {})
        if (msg.id, msg.name, sig.name) not in cache:
            base = "%s_%s" % (slug(msg.name), slug(sig.name))
            taken = self.__dict__.setdefault("_taken", set())
            key, n = base, 1
            while key in taken:
                n += 1
                key = "%s_%d" % (base, n)
            taken.add(key)
            cache[(msg.id, msg.name, sig.name)] = key
        return cache[(msg.id, msg.name, sig.name)]

    def signal_line(self, msg, sig, used_bits):
        """The Line of one signal, or a reason it has none."""
        if sig.length < 1 or sig.length > 64:
            return None, "length %d bits" % sig.length
        bits = span(sig)
        if max(bits) >= 8 * msg.size or min(bits) < 0:
            return None, "outside the %d data bytes" % msg.size
        if bits & used_bits:
            return None, "overlaps another signal of the message"
        pos, swap = place(sig, self.order)
        if pos is None:
            return None, swap
        vt = self.dbc.valtype.get((msg.id, sig.name), 0)
        if vt:
            if (vt, sig.length) not in ((1, 32), (2, 64)):
                return None, "float signal of %d bits" % sig.length
            if Fraction(Decimal(sig.factor)) != 1 or Decimal(sig.offset) != 0:
                return None, "float signal with a factor or an offset"
            tr, typ = ("f32" if vt == 1 else "f64"), "float"
        else:
            try:
                fac, off = factor_text(sig.factor), offset_text(sig.offset)
            except (ValueError, ArithmeticError):
                return None, "factor %s" % sig.factor
            if fac == "1" and off is None:
                tr, typ = ("twos" if sig.signed else "uint"), "int"
            else:
                tr = ("sscale:" if sig.signed else "uscale:") + fac + (":" + off if off else "")
                typ = "float"
        core = core_of(sig, msg) if typ == "float" else None
        key = core if core else "%s.%s" % (self.module, self.key_of(msg, sig))
        via = None
        table = self.dbc.values.get((msg.id, sig.name))
        if table and typ == "int" and not core and self.complete(table, sig):
            via = "t_" + self.key_of(msg, sig)
            self.tables[via] = table
            typ = "string"
        return (Line(key, DATA_BIT0 + pos, sig.length, tr, swap, via), typ, bits), None

    @staticmethod
    def complete(table, sig):
        """A value table is applied when it names every raw value of the signal
        once, with labels that are text a pack line can hold."""
        if sig.length > 8:
            return False
        lo, hi = (-(1 << (sig.length - 1)), (1 << (sig.length - 1)) - 1) if sig.signed else (0, (1 << sig.length) - 1)
        raws = [r for r, _ in table]
        labels = [lab for _, lab in table]
        if sorted(raws) != list(range(lo, hi + 1)):
            return False
        if any('"' in lab or not lab.strip() or lab != lab.strip() for lab in labels):
            return False
        if all(re.match(r"^-?\d+(\.\d+)?$", lab) for lab in labels):
            return False                        # a table of numbers would type the key as int
        return len(set(labels)) == len(labels)

    def plan(self):
        dbc = self.dbc
        names = collections.Counter()
        for msg in dbc.messages:
            if msg.id >= PSEUDO_ID or (msg.id & 0x60000000):
                self.skipped_messages.append((msg, "not a frame (identifier %#x)" % msg.id))
                continue
            if msg.size > 8:
                self.skipped_messages.append((msg, "CAN FD: %d data bytes (struct canfd_frame)" % msg.size))
                continue
            muxors = [s for s in msg.signals if s.muxor]
            if len(muxors) > 1 or any(s.muxor and s.mux is not None for s in msg.signals):
                self.skipped_messages.append((msg, "extended multiplexing: more than one multiplexor"))
                continue
            # SG_MUL_VAL_ names, for a multiplexed signal, the values of the
            # multiplexor it appears under; with the message's one multiplexor
            # that is still one kind per value
            mul = {sig: v for (mid, sig), v in dbc.mul_val.items() if mid == msg.id}
            if msg.id in dbc.extended_mux or any(muxor_name != muxors[0].name if muxors else True
                                                 for muxor_name, _ in mul.values()):
                self.skipped_messages.append((msg, "extended multiplexing (SG_MUL_VAL_)"))
                continue

            def values_of(s):
                if s.mux is None:
                    return set()
                if s.name in mul:
                    return mul[s.name][1]
                return {s.mux} if s.mux >= 0 else set()
            plain = [s for s in msg.signals if s.mux is None and not s.muxor]
            if not muxors:
                for s in msg.signals:
                    if s.mux is not None:
                        self.unmapped.append((msg, s, "multiplexed and the message has no multiplexor"))
            if muxors:
                muxor = muxors[0]
                for s in msg.signals:
                    if s.mux is not None and not values_of(s):
                        self.unmapped.append((msg, s, "multiplexed (`m`) with no multiplexor value"))
                mux_values = sorted(set().union(*[values_of(s) for s in msg.signals]))
                mline, why = self.signal_line(msg, muxor._replace(factor="1", offset="0"), set())
                if mline is None or dbc.valtype.get((msg.id, muxor.name)):
                    self.skipped_messages.append((msg, "multiplexor %s: %s" % (muxor.name, why or "a float")))
                    continue
                if not mux_values:
                    self.skipped_messages.append((msg, "a multiplexor and no multiplexed signal"))
                    continue
                for v in mux_values:
                    if v >= 1 << muxor.length:
                        continue
                    k = KindPlan("%s_m%d" % (slug(msg.name), v), msg, v)
                    k.mux_line = mline[0]
                    self.fill(k, msg, plain + [s for s in msg.signals if v in values_of(s)], mline[2])
                    self.add_kind(k, names)
            else:
                k = KindPlan(slug(msg.name), msg, None)
                self.fill(k, msg, plain, set())
                self.add_kind(k, names)
        self.choose_requires()

    def fill(self, k, msg, signals, used):
        used = set(used)
        for sig in signals:
            res, why = self.signal_line(msg, sig, used)
            if res is None:
                if (msg, sig, why) not in self.unmapped:
                    self.unmapped.append((msg, sig, why))
                continue
            line, typ, bits = res
            used |= bits
            k.lines.append(line)
            k.signals.append(sig)
            if "." in line.key:
                old = self.keys.get(line.key.split(".", 1)[1])
                if old and old[0] != typ:
                    raise GenError("%s: key %s with two types" % (self.dbc.name, line.key))
                self.keys[line.key.split(".", 1)[1]] = (typ, sig.unit, msg.name, sig.name)
            else:
                self.core.append((k, sig, line.key))

    def add_kind(self, k, names):
        if not any("." in line.key for line in k.lines):
            why = "the message defines no signal" if not k.msg.signals else "no signal the pack can state"
            self.skipped_messages.append((k.msg, why + (
                " for multiplexor value %d" % k.muxval if k.muxval is not None else "")))
            return
        names[k.name] += 1
        if names[k.name] > 1:
            k.name = "%s_%d" % (k.name, names[k.name])
        cores = [line.key for line in k.lines if "." not in line.key]
        if sorted(cores) not in ([], ["lat", "lon"]):
            # a lone latitude or longitude is not a position: keep it raw
            for i, line in enumerate(k.lines):
                if "." not in line.key:
                    sig = k.signals[i]
                    key = "%s.%s" % (self.module, self.key_of(k.msg, sig))
                    k.lines[i] = line._replace(key=key)
                    self.keys[key.split(".", 1)[1]] = ("float", sig.unit, k.msg.name, sig.name)
            self.core = [c for c in self.core if c[0] is not k]
        self.kinds.append(k)

    def choose_requires(self):
        usage = collections.Counter()
        for k in self.kinds:
            usage.update({line.key for line in k.lines if "." in line.key})
        for k in self.kinds:
            raw = [line.key for line in k.lines if "." in line.key]
            ranked = sorted(range(len(raw)), key=lambda i: (usage[raw[i]], i))
            k.requires = [raw[i] for i in sorted(ranked[:MAX_REQUIRES])]

    def id_when(self, msg):
        """The `when` value on the identifier word: the word as the pack's bit
        order reads bytes 0-3, which hold it little-endian."""
        if self.order == "lsb":
            return can_id(msg)
        return int.from_bytes(can_id(msg).to_bytes(4, "little"), "big")


# ------------------------------------------------------------------- emit ---

def loc(pos, n):
    return "0:%d:%d" % (pos, n)


def pack_text(fp, sha):
    o = ["# CAN frames of the DBC file %s, one kind per message." % fp.dbc.name,
         "# Generated by tools/gen/dbc2pack.py; do not edit by hand.",
         "# The message is one SocketCAN struct can_frame of 16 bytes: identifier word",
         "# (little-endian, flags in the top three bits), data length, three padding",
         "# bytes, eight data bytes. Data bit 0 is bit %d of the frame." % DATA_BIT0,
         "format        %s" % fp.format,
         "version       %s" % VERSION,
         "distribution  public"]
    for p in fp.sources:
        o.append('source        "%s %s at commit %s"' % (REPO, p, sha))
    o.append('source        "%s"' % CAN_UAPI)
    o += ["uses          %s" % fp.module,
          "wire          bits",
          "bit_order     %s" % fp.order,
          "word_bytes    1"]
    for name, table in fp.tables.items():
        for raw, label in table:
            o.append('map   %s  %d  "%s"' % (name, raw, label))
    for k in fp.kinds:
        o.append("")
        o.append("kind      %s" % k.name)
        o.append("when      %s %d" % (loc(0, 32), fp.id_when(k.msg)))
        o.append("when      %s %d" % (loc(32, 8), k.msg.size))
        if k.mux_line is not None:
            ml = k.mux_line
            raw = k.muxval
            if ml.swap:
                raw = int.from_bytes(raw.to_bytes(ml.bits // 8, "big"), "little")
            o.append("when      %s %d" % (loc(ml.pos, ml.bits), raw))
        if k.requires:
            o.append("requires  %s" % " ".join(k.requires))
        covered = set()
        for line in k.lines:
            o.append("field     %s %s %s%s%s" % (line.key, loc(line.pos, line.bits), line.tr,
                                                " via " + line.via if line.via else "",
                                                " swap" if line.swap else ""))
            covered |= set(range(line.pos, line.pos + line.bits))
        if k.mux_line is not None:
            covered |= set(range(k.mux_line.pos, k.mux_line.pos + k.mux_line.bits))
        if not covered & set(range(120, 128)):
            o.append("const     %s 0" % loc(120, 8))
    return "\n".join(o) + "\n"


def module_text(fp, sha):
    o = ["# The %s module: the signals of the DBC file %s, in the units it states." % (fp.module, fp.dbc.name),
         "# Generated by tools/gen/dbc2pack.py; do not edit by hand. A key is",
         "# <message>_<signal>, both in lower case.",
         "module        %s" % fp.module,
         "version       %s" % VERSION,
         "distribution  public"]
    for p in fp.sources:
        o.append('source        "%s %s at commit %s"' % (REPO, p, sha))
    for key, (typ, unit, mname, sname) in fp.keys.items():
        u = re.sub(r"\s+", "_", unit.strip()) if unit.strip() else "-"
        if '"' in u or "#" in u or not u:
            u = "-"
        o.append('key  %s  %s  %s  "signal %s of message %s"' % (key, typ, u, sname, mname))
    return "\n".join(o) + "\n"


# --------------------------------------------- DBC serializer (vectors) ---

def put_signal(data, sig, raw):
    """Write the raw value of a signal into the data bytes by the DBC rules."""
    n = sig.length
    raw &= (1 << n) - 1
    if not sig.motorola:
        for i in range(n):
            b = sig.start + i
            if (raw >> i) & 1:
                data[b // 8] |= 1 << (b % 8)
        return
    pos = sig.start
    for i in range(n):
        if (raw >> (n - 1 - i)) & 1:
            data[pos // 8] |= 1 << (pos % 8)
        pos = pos + 15 if pos % 8 == 0 else pos - 1


def can_id(msg):
    """The SocketCAN identifier word of a message: a DBC identifier with bit 31
    set is extended; one above 0x7FF without it is a 29-bit identifier too (the
    form opendbc writes), and gains the extended flag."""
    if msg.id & EFF or msg.id <= 0x7FF:
        return msg.id
    return msg.id | EFF


def frame_bytes(msg, data):
    return can_id(msg).to_bytes(4, "little") + bytes([msg.size, 0, 0, 0]) + bytes(data)


def sample_raw(sig, salt, fp, msg):
    """A raw value inside the signal's range."""
    vt = fp.dbc.valtype.get((msg.id, sig.name), 0)
    if vt:
        x = ((salt % 41) - 20) * 0.25
        return int.from_bytes(struct.pack("<f" if vt == 1 else "<d", x), "little")
    n = sig.length
    if n == 1:
        return salt % 2
    v = (salt * 2654435761 + 12345) % (1 << min(n, 31))
    if n == 64 and salt % 2:
        v |= 1 << 63
    return v


def cross_case(fp):
    """For a pack that binds core lat/lon: the kind, raw values that give
    47.397742, 8.545594 degrees, and the expected GeoJSON (written by hand)."""
    for k in fp.kinds:
        keys = {line.key for line in k.lines}
        if {"lat", "lon"} <= keys:
            return k
    return None


CROSS_POSITION = (Decimal("47.397742"), Decimal("8.545594"))
CROSS_EXPECT = '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.545594,47.397742]},"properties":{}}'


def vector_files(fp):
    files = []
    for i, k in enumerate(fp.kinds):
        data = bytearray(8)
        if k.muxval is not None:
            muxor = next(s for s in k.msg.signals if s.muxor)
            put_signal(data, muxor, k.muxval)
        for j, sig in enumerate(k.signals):
            put_signal(data, sig, sample_raw(sig, k.msg.id * 31 + j * 7 + i, fp, k.msg))
        hexs = frame_bytes(k.msg, data).hex()
        files.append(("rt-%04d-%s.json" % (i, k.name), vector_text([
            ("name", "%s-roundtrip-%s" % (fp.format, k.name)), ("from", fp.format), ("to", fp.format),
            ("input", hexs), ("expect", hexs), ("model", {"@kind": k.name})])))
    k = cross_case(fp)
    if k is not None:
        data = bytearray(8)
        model = collections.OrderedDict([("@kind", k.name)])
        for j, sig in enumerate(k.signals):
            line = k.lines[j]
            if line.key in ("lat", "lon"):
                deg = CROSS_POSITION[0] if line.key == "lat" else CROSS_POSITION[1]
                f = Fraction(Decimal(sig.factor))
                raw = (Fraction(deg) - Fraction(Decimal(sig.offset))) / f
                if raw.denominator != 1:
                    raise GenError("%s: %s does not hold the cross position exactly" % (fp.format, sig.name))
                put_signal(data, sig, int(raw))
                model[line.key] = str(deg)
            else:
                put_signal(data, sig, sample_raw(sig, j, fp, k.msg))
        files.append(("x-01-%s-to-geojson.json" % k.name, vector_text([
            ("name", "%s-%s-to-geojson" % (fp.format, k.name)), ("from", fp.format), ("to", "geojson"),
            ("input", frame_bytes(k.msg, data).hex()), ("expect", CROSS_EXPECT), ("model", model)])))
    return files


def vector_text(pairs):
    return json.dumps(collections.OrderedDict(pairs), indent=2) + "\n"


# -------------------------------------------- codec, from the specification ---

def get_bits(data, pos, n, order):
    if order == "lsb":
        return (int.from_bytes(data, "little") >> pos) & ((1 << n) - 1)
    total = 8 * len(data)
    return (int.from_bytes(data, "big") >> (total - pos - n)) & ((1 << n) - 1)


def put_bits(acc, total, pos, n, v, order):
    if order == "lsb":
        return acc | (v << pos)
    return acc | (v << (total - pos - n))


def swap_bytes(v, n):
    return int.from_bytes(v.to_bytes(n // 8, "big"), "little")


def round_away(x):
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def canonical(v):
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e17:
            return str(int(v))
        return repr(v)
    return str(v)


def decode_value(node, raw, tables):
    tr, n = node.tr, node.bits
    if tr == "uint":
        v = raw - (1 << 64) if n == 64 and raw >> 63 else raw
    elif tr == "twos":
        v = raw - (1 << n) if raw >> (n - 1) else raw
    elif tr in ("uscale", "sscale"):
        if tr == "sscale" and raw >> (n - 1):
            raw -= 1 << n
        f = gtcheck.parse_factor(node.targs[0])
        off = float(node.targs[1]) if len(node.targs) > 1 else 0.0
        v = (raw * float(f[0]) / float(f[1]) if isinstance(f, tuple) else raw * f) + off
    elif tr == "f32":
        v = struct.unpack("<f", raw.to_bytes(4, "little"))[0]
        if not math.isfinite(v):
            raise CodecError("transform-decode")
    elif tr == "f64":
        v = struct.unpack("<d", raw.to_bytes(8, "little"))[0]
        if not math.isfinite(v):
            raise CodecError("transform-decode")
    else:
        raise CodecError("transform-decode")
    if node.via:
        t = dict(tables[node.via])
        if canonical(v) not in t:
            raise CodecError("transform-decode")
        return t[canonical(v)]
    return v


def encode_value(node, x, tables):
    tr, n = node.tr, node.bits
    if node.via:
        back = {}
        for native, model in tables[node.via]:
            back.setdefault(model, native)
        x = int(back[x])
    mask = (1 << n) - 1
    if tr in ("uint", "twos"):
        return x & mask
    if tr in ("uscale", "sscale"):
        f = gtcheck.parse_factor(node.targs[0])
        off = float(node.targs[1]) if len(node.targs) > 1 else 0.0
        r = round_away((x - off) * float(f[1]) / float(f[0]) if isinstance(f, tuple) else (x - off) / f)
        lo, hi = (0, mask) if tr == "uscale" else (-(1 << (n - 1)), (1 << (n - 1)) - 1)
        if not lo <= r <= hi:
            raise CodecError("transform-encode")
        return r & mask
    if tr == "f32":
        return int.from_bytes(struct.pack("<f", x), "little")
    return int.from_bytes(struct.pack("<d", x), "little")


def decode(pack, data):
    order = pack.bit_order
    total = 8 * len(data)

    def holds(lines):
        return all(n.start + n.bits <= total and get_bits(data, n.start, n.bits, order) == int(n.value)
                   for n in lines if n.d == "when")
    kind = next((k for k in pack.kinds if holds(k.lines)), None) if holds(pack.common) else None
    if kind is None:
        raise CodecError("no-kind")
    lines = pack.common + kind.lines
    if total < max(n.start + n.bits for n in lines if n.d in ("when", "field", "const")):
        raise CodecError("malformed-wire")
    ent = collections.OrderedDict()
    for n in lines:
        if n.d == "field":
            raw = get_bits(data, n.start, n.bits, order)
            if "swap" in n.opts:
                raw = swap_bytes(raw, n.bits)
            ent[n.key] = decode_value(n, raw, pack.tables)
    return kind.name, ent


def encode(pack, name, ent):
    order = pack.bit_order
    kind = next(k for k in pack.kinds if k.name == name)
    lines = pack.common + kind.lines
    nbytes = (max(n.start + n.bits for n in lines if n.d in ("when", "field", "const")) + 7) // 8
    total = 8 * nbytes
    acc = 0
    for n in lines:
        if n.d == "field" and n.key in ent:
            v = encode_value(n, ent[n.key], pack.tables)
            if "swap" in n.opts:
                v = swap_bytes(v, n.bits)
            acc = put_bits(acc, total, n.start, n.bits, v, order)
    for n in lines:                        # const, then when, over any field (0.5 ruling 5)
        if n.d in ("const", "when"):
            acc &= ~put_bits(0, total, n.start, n.bits, (1 << n.bits) - 1, order)
            acc = put_bits(acc, total, n.start, n.bits, int(n.value), order)
    return acc.to_bytes(nbytes, "little" if order == "lsb" else "big")


def geojson(ent):
    if "lat" in ent and "lon" in ent:
        return ('{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{}}'
                % (canonical(ent["lon"]), canonical(ent["lat"])))
    return '{"type":"Feature","geometry":null,"properties":{}}'


def check_vectors(pack, vectors, fmt):
    n, seen = 0, set()
    for fn, text in vectors:
        vec = json.loads(text)
        try:
            kname, ent = decode(pack, bytes.fromhex(vec["input"]))
            for key, want in vec.get("model", {}).items():
                got = kname if key == "@kind" else ent.get(key)
                if got is None:
                    raise GenError("%s/%s: model %s not decoded" % (fmt, fn, key))
                if key != "@kind" and isinstance(got, float):
                    if abs(got - float(want)) > 1e-9:
                        raise GenError("%s/%s: model %s = %r, vector says %s" % (fmt, fn, key, got, want))
                elif str(got) != want:
                    raise GenError("%s/%s: model %s = %s, vector says %s" % (fmt, fn, key, got, want))
            got = encode(pack, kname, ent).hex() if vec["to"] == fmt else geojson(ent)
            seen.add(kname)
        except CodecError as e:
            raise GenError("%s/%s: %s" % (fmt, fn, e))
        if got != vec["expect"]:
            raise GenError("%s/%s: convert gives %s, vector expects %s" % (fmt, fn, got, vec["expect"]))
        n += 1
    missing = {k.name for k in pack.kinds} - seen
    if missing:
        raise GenError("%s: kinds with no vector: %s" % (fmt, sorted(missing)[:5]))
    return n


# ---------------------------------------------------------------- pack.md ---

def pack_md(fp, sha, nvec):
    d = fp.dbc
    o = []
    a = o.append
    a("# Pack: %s" % fp.format)
    a("")
    a("CAN frames described by the DBC file `%s` of `%s` at commit `%s`." % (d.name, REPO, sha))
    if len(fp.sources) > 1:
        a("opendbc assembles this file from parts with `CM_ \"IMPORT …\";` lines; the generator")
        a("assembles it the same way from: %s." % ", ".join("`%s`" % p for p in fp.sources))
    else:
        a("Source: `%s`." % fp.sources[0])
    a("Public. Generated by `tools/gen/dbc2pack.py`; do not edit `pack.def`, this file,")
    a("`PROVENANCE.md`, `model/%s.def` or the vectors by hand." % fp.module)
    a("")
    a("Status: Built. Generated and checked by the generator's own serializer and codec.")
    a("")
    a("## The message")
    a("")
    a("One Linux SocketCAN `struct can_frame` (%s)," % CAN_UAPI)
    a("as 16 bytes in hex text:")
    a("")
    a("| Bytes | Content | In the pack |")
    a("|---|---|---|")
    a("| 0-3 | CAN identifier, little-endian; bit 31 extended frame, bit 30 remote request, bit 29 error frame | per-kind `when` on the whole word |")
    a("| 4 | data length in bytes | per-kind `when` = the DBC message size |")
    a("| 5-7 | padding | not mapped |")
    a("| 8-15 | data | the kind's `field` lines; a byte no signal uses in the last place is a `const 0` |")
    a("")
    a("The frame carries its identifier, so a kind is chosen by `when` on it. A DBC")
    a("writes an extended identifier with bit 31 set, as SocketCAN does; an identifier")
    a("above 0x7FF without it is taken as a 29-bit identifier (opendbc writes some that")
    a("way) and the `when` holds it with bit 31 set. A data frame has bits 30 and 29")
    a("clear, so a remote or error frame matches no kind.")
    if fp.order == "msb":
        a("The pack's bit order is `msb`, so the identifier word is read big-endian: each")
        a("kind's `when` value on bytes 0-3 is its identifier with the four bytes reversed.")
    a("")
    a("## Signals")
    a("")
    a("The file has %d Intel and %d Motorola signals; the pack's bit order is `%s`." % (
        fp.counts[0], fp.counts[1], fp.order))
    a("A signal's DBC start bit numbers bit `b` as bit `b mod 8` of data byte `b div 8`.")
    if fp.order == "lsb":
        a("An Intel signal from start bit `s` is the field `0:%d+s:<length>`. A Motorola" % DATA_BIT0)
        a("signal is a field when it lies in one byte, or covers whole bytes from a byte")
        a("boundary (`swap`); otherwise it is not mapped.")
    else:
        a("A Motorola signal whose most significant bit is DBC bit `s` is the field that")
        a("starts at msb position %d + 8 (s div 8) + 7 - (s mod 8). An Intel signal is a" % DATA_BIT0)
        a("field when it lies in one byte, or covers whole bytes from a byte boundary")
        a("(`swap`); otherwise it is not mapped.")
    a("")
    a("| DBC | Pack line | Model type |")
    a("|---|---|---|")
    a("| unsigned, factor 1, offset 0 | `uint` | int |")
    a("| signed, factor 1, offset 0 | `twos` | int |")
    a("| other factor or offset | `uscale` / `sscale` with the factor as an exact fraction | float |")
    a("| `SIG_VALTYPE_` 1 / 2 (IEEE float / double) | `f32` / `f64` | float |")
    a("| a `VAL_` table that names every raw value of an unscaled signal of up to 8 bits | the integer transform with `via` | string |")
    a("| a multiplexor (`M`) and its multiplexed signals (`m<n>`, or the values `SG_MUL_VAL_` lists for them) | one kind per value, a `when` on the multiplexor | - |")
    a("")
    a("Keys are `%s.<message>_<signal>` in lower case, in the unit the DBC states." % fp.module)
    n_fields = sum(len(k.lines) for k in fp.kinds)
    a("")
    a("| | Count |")
    a("|---|---|")
    a("| messages in the file | %d |" % len(d.messages))
    a("| kinds | %d |" % len(fp.kinds))
    a("| `field` lines | %d |" % n_fields)
    a("| value tables applied | %d |" % len(fp.tables))
    a("| messages with no kind | %d |" % len(fp.skipped_messages))
    a("| signals not mapped | %d |" % len(fp.unmapped))
    a("| vectors | %d |" % nvec)
    a("")
    if fp.core:
        a("### Core keys")
        a("")
        a("A signal is bound to core `lat` / `lon` when its name ends in latitude or")
        a("longitude and the DBC states its unit as degrees, and its message has both:")
        a("")
        for k, sig, ck in fp.core:
            a("- `%s.%s` (%s|%s@%s, factor %s, unit `%s`) to `%s`" % (
                k.msg.name, sig.name, sig.start, sig.length, "0" if sig.motorola else "1",
                sig.factor, sig.unit, ck))
        a("")
    else:
        a("No key is bound to a `core` or `track` key: the file states no latitude and")
        a("longitude in degrees.")
        a("")
    a("### `requires`")
    a("")
    a("Each kind requires up to %d of its own keys, those the fewest kinds map, so an" % MAX_REQUIRES)
    a("entity from another format selects a kind only when it holds them.")
    a("")
    a("## What is not mapped")
    a("")
    if fp.skipped_messages:
        a("Messages with no kind:")
        a("")
        a("| Message | Identifier | Reason |")
        a("|---|---|---|")
        for msg, why in fp.skipped_messages:
            a("| %s | %d | %s |" % (msg.name, msg.id, why))
        a("")
    if fp.unmapped:
        a("Signals not mapped:")
        a("")
        a("| Message | Signal | Reason |")
        a("|---|---|---|")
        for msg, sig, why in fp.unmapped:
            a("| %s | %s | %s |" % (msg.name, sig.name, why))
        a("")
    partial = [key for key in d.values if key not in {(k.msg.id, s.name) for k in fp.kinds
                                                      for s, line in zip(k.signals, k.lines) if line.via}]
    if partial:
        a("%d `VAL_` tables are not applied (they do not name every raw value, or the" % len(partial))
        a("signal is scaled or wider than 8 bits): those signals carry the number.")
        a("")
    a("- Remote and error frames, and CAN FD frames (`struct canfd_frame`, up to 64 data bytes).")
    a("- Comments, attributes (`BA_`), node lists, signal value ranges and receivers.")
    a("- Extended multiplexing: more than one multiplexor in a message, or a multiplexor")
    a("  that is itself multiplexed.")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-NNNN-<kind>.json`: one same-format round trip per kind. The frame is")
    a("written by a DBC serializer in the generator from sample raw values (Intel")
    a("signals from the start bit upward; Motorola signals from the start bit as the")
    a("most significant bit, through the DBC bit numbering); expect equals input.")
    if fp.core:
        a("")
        a("`vectors/x-01-…-to-geojson.json`: a frame whose latitude and longitude give")
        a("47.397742 and 8.545594 degrees, converted to GeoJSON; the expected text is")
        a("written by hand.")
    return "\n".join(o) + "\n"


def provenance_md(fp, sha, table, lic_sha):
    rows = "\n".join("| `%s` | `%s` |" % (p, table[p]) for p in fp.sources)
    return "\n".join([
        "# Provenance: %s" % fp.format,
        "",
        "| Fact | Value |",
        "|---|---|",
        "| repository | %s |" % REPO,
        "| commit | `%s` |" % sha,
        "| license of the repository | MIT, copyright (c) 2020 Comma.ai, Inc.: `LICENSE` at the root of the commit (SHA-256 `%s`), verbatim in `tools/gen/sources/dbc-PROVENANCE.md` |" % lic_sha,
        "| frame layout | %s; stated in this project's words, nothing copied |" % CAN_UAPI,
        "| date read | 2026-11-19 |",
        "| what the pack takes | message names, identifiers and sizes; signal names, start bits, lengths, byte orders, signs, factors, offsets and units; complete value tables; no comment text |",
        "| generator | `tools/gen/dbc2pack.py` |",
        "",
        "| File read | SHA-256 |",
        "|---|---|",
        rows,
        ""])


def write_sources_provenance(out, src, sha, files):
    lic = read_text(os.path.join(src, "LICENSE"))
    o = ["# Provenance of the DBC inputs",
         "",
         "| Fact | Value |",
         "|---|---|",
         "| repository | %s |" % REPO,
         "| commit | `%s` (head of `master`, read 2026-11-19) |" % sha,
         "| archive | `https://codeload.github.com/commaai/opendbc/tar.gz/%s` |" % sha,
         "| license | MIT, the file `LICENSE` at the root of the commit, verbatim below |",
         "",
         "## Files",
         "",
         "| Path | SHA-256 |",
         "|---|---|",
         "| `LICENSE` | `%s` |" % sha256(os.path.join(src, "LICENSE"))]
    for f in files:
        o.append("| `%s` | `%s` |" % (f, sha256(os.path.join(src, f))))
    o += ["", "## LICENSE", "", "```"] + lic.rstrip("\n").splitlines() + ["```", ""]
    out.write(PROV, "\n".join(o))


def read_sources_provenance(text, src, files):
    m = re.search(r"\| commit \| `([0-9a-f]{40})`", text)
    if not m:
        raise GenError("%s states no commit" % PROV)
    table = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    for rel in ["LICENSE"] + files:
        if rel not in table:
            raise GenError("%s has no SHA-256 for %s" % (PROV, rel))
        if sha256(os.path.join(src, rel)) != table[rel]:
            raise GenError("%s does not match the SHA-256 in %s" % (rel, PROV))
    return m.group(1), table


# ------------------------------------------------------------------- main ---

def run(args, out):
    del SKIPPED_SOURCES[:]
    src = args.src
    files = source_files(src)
    if args.commit:
        write_sources_provenance(out, src, args.commit, files)
    sha, table = read_sources_provenance(out.read(PROV), src, files)
    plans = []
    for name, text, sources in load_sources(src):
        if args.files and name not in args.files.split(","):
            continue
        plans.append(FilePlan(parse_dbc(text, name, sources), sources))
    core_text = read_text(args.core_def) if args.core_def else out.read("model/core.def")
    total = 0
    for fp in plans:
        if not fp.kinds:
            continue
        pdir = "packs/" + fp.format
        out.write("model/%s.def" % fp.module, module_text(fp, sha))
        out.write(pdir + "/pack.def", pack_text(fp, sha))
        vecs = vector_files(fp)
        keep = {n for n, _ in vecs}
        for old in out.listdir(pdir + "/vectors"):
            if old.endswith(".json") and old not in keep:
                out.remove("%s/vectors/%s" % (pdir, old))
        for n, t in vecs:
            out.write("%s/vectors/%s" % (pdir, n), t)
        model = gtcheck.Model()
        model.add(core_text, "model/core.def")
        model.add(out.read("model/%s.def" % fp.module), "model/%s.def" % fp.module)
        pack = gtcheck.load_pack(out.read(pdir + "/pack.def"), model, pdir + "/pack.def")
        total += check_vectors(pack, [(n, out.read("%s/vectors/%s" % (pdir, n))) for n, _ in vecs], fp.format)
        out.write(pdir + "/pack.md", pack_md(fp, sha, len(vecs)))
        out.write(pdir + "/PROVENANCE.md", provenance_md(fp, sha, table, table["LICENSE"]))
    made = [fp for fp in plans if fp.kinds]
    reasons = collections.Counter(why.split(":")[0] for fp in plans for _, _, why in fp.unmapped)
    skipped = collections.Counter(why.split(":")[0].split(" (")[0] for fp in plans for _, why in fp.skipped_messages)
    return ["commit          %s" % sha,
            "DBC files       %d, packs %d%s" % (len(plans), len(made), "".join(
                "\nno pack         %s: no message the pack can state" % fp.dbc.name for fp in plans if not fp.kinds)),
            "not assembled   %s" % "; ".join("%s (%s)" % x for x in SKIPPED_SOURCES),
            "kinds           %d (multiplexed %d)" % (sum(len(fp.kinds) for fp in made),
                                                     sum(k.muxval is not None for fp in made for k in fp.kinds)),
            "field lines     %d" % sum(len(k.lines) for fp in made for k in fp.kinds),
            "value tables    %d applied" % sum(len(fp.tables) for fp in made),
            "core bindings   %d" % sum(len(fp.core) for fp in made),
            "messages left   %d %s" % (sum(skipped.values()), dict(skipped)),
            "signals left    %d %s" % (sum(reasons.values()), dict(reasons)),
            "vectors         %d checked" % total,
            "self-check      ok"]


def build_parser():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(prog=NAME, description=__doc__.split("\n")[0] + " One pack per DBC file, "
                                 "one kind per CAN message, the frame a SocketCAN struct can_frame.")
    genio.add_arguments(ap, default_out=os.path.normpath(os.path.join(here, "..", "..")))
    ap.add_argument("--src", required=True, metavar="DIR", help="a checkout of github.com/commaai/opendbc")
    ap.add_argument("--commit", help="write %s for this commit" % PROV)
    ap.add_argument("--files", help="only these DBC files (names without .dbc), comma-separated")
    ap.add_argument("--core-def", help="model/core.def (default <out>/model/core.def)")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = genio.Output(args.out, check=args.check)
    try:
        lines = run(args, out)
    except (GenError, gtcheck.CheckError) as e:
        print("%s: %s" % (NAME, e), file=sys.stderr)
        return 1
    except OSError as e:
        print("%s: %s: %s" % (NAME, e.filename, e.strerror), file=sys.stderr)
        return 1
    print("\n".join(lines))
    return out.report(NAME)


if __name__ == "__main__":
    sys.exit(main())
