#!/usr/bin/env python3
"""elfsize: print the allocated sections of a 32-bit little-endian ELF image
and the size of each function, largest first. Standard library only; used by
embedded/measure.sh where no binutils for the target are installed.

With --stack it also bounds the stack an entry function uses, from the
disassembly `objdump -d` prints. The disassembler must read the target's
images: $OBJDUMP when set, else LLVM's objdump (`llvm-objdump`, a versioned
`llvm-objdump-N`, or the one of `rustup component add llvm-tools`), else
`objdump`. The bytes
each function pushes and reserves, added along the deepest chain of calls. A
group of functions that call one another (the engine's walk over nested
blocks) is counted DEPTH times over; the engine stops at 12 nested blocks, and
a plan states its own nesting in the compiler's report.

Usage: elfsize.py IMAGE [--symbols N] [--stack ENTRY [--depth DEPTH]]
"""
import glob
import os
import re
import shutil
import struct
import subprocess
import sys


def objdump():
    """The disassembler: one that reads ARM images, where one is installed."""
    if os.environ.get("OBJDUMP"):
        return os.environ["OBJDUMP"]
    if shutil.which("llvm-objdump"):
        return "llvm-objdump"
    found = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        found += glob.glob(os.path.join(d, "llvm-objdump-[0-9]*"))
    try:
        sysroot = subprocess.run(["rustc", "--print", "sysroot"], capture_output=True, text=True, check=True).stdout.strip()
        found += glob.glob(os.path.join(sysroot, "lib", "rustlib", "*", "bin", "llvm-objdump"))
    except (OSError, subprocess.CalledProcessError):
        pass
    return sorted(found)[-1] if found else "objdump"


def bytes_at(image, addr, n):
    """`n` bytes at virtual address `addr` of an ELF image, from the allocated
    section that holds them; None when none does."""
    shoff, = struct.unpack_from("<I", image, 0x20)
    shentsize, shnum = struct.unpack_from("<HH", image, 0x2E)
    for i in range(shnum):
        _, kind, flags, vaddr, off, size = struct.unpack_from("<6I", image, shoff + i * shentsize)
        if flags & 2 and kind != 8 and vaddr <= addr and addr + n <= vaddr + size:
            return image[off + addr - vaddr:off + addr - vaddr + n]
    return None


def word_at(image, addr):
    """The 32-bit little-endian word at virtual address `addr`, or None."""
    b = bytes_at(image, addr, 4)
    return struct.unpack("<I", b)[0] if b is not None else None


def table_targets(image, at, half):
    """The targets of the `tbb` (bytes) or `tbh` (halfwords) at address `at`.
    The table starts after the instruction and ends where the first target
    begins: the code of the cases follows the table. None when it cannot be
    read."""
    base, size = at + 4, 2 if half else 1
    out, end, i = set(), None, 0
    while end is None or base + i * size < end:
        b = bytes_at(image, base + i * size, size)
        if b is None or i > 4096:
            return None
        t = base + 2 * (struct.unpack("<H", b)[0] if half else b[0])
        out.add(t)
        end = t if end is None else min(end, t)
        i += 1
    return out


REG = re.compile(r"^(r\d+|lr|ip|sb|sl|fp)\b")


def stack_bound(path, entry, depth):
    text = subprocess.run([objdump(), "-d", "--no-show-raw-insn", path], capture_output=True, text=True, check=True).stdout
    with open(path, "rb") as fh:
        image = fh.read()
    frames, calls, cur = {}, {}, None
    head = re.compile(r"^([0-9a-f]+) <(.+)>:$")
    # the instructions of each function: (address, op, args)
    body, order = {}, []
    for line in text.split("\n"):
        m = head.match(line.strip())
        if m:
            cur = m.group(2)
            body[cur] = []
            order.append((int(m.group(1), 16), cur))
            continue
        if cur is None or "\t" not in line or ":" not in line:
            continue
        addr = line.split(":", 1)[0].strip()
        ins = line.split("\t", 1)[1].strip()
        parts = ins.split(None, 1)
        if not parts or not re.match(r"^[0-9a-f]+$", addr):
            continue
        body[cur].append((int(addr, 16), parts[0], parts[1] if len(parts) > 1 else ""))
    starts = {a: n for a, n in order}
    # Calls through a register: opt-level z calls one routine many times through
    # a register that an unconditional `ldr rN, [pc, #...]` loaded from the
    # literal pool. Such a call is followed when the register's value is known
    # on every path to it: a forward dataflow over the function's instructions,
    # where an instruction knows a register only when every instruction that
    # can come before it (the one above, unless that one always branches away
    # or writes pc, and every branch or table branch of the function to it)
    # leaves the same value there. A write to a register forgets it. A
    # function with a table branch whose table cannot be read knows nothing.
    # A call clobbers r0-r3, ip and lr and keeps r4-r11, as the procedure call
    # standard requires of every callee.
    branch = re.compile(r"^(b|b(eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al))(\.w|\.n)?$")
    clobbered = ("r0", "r1", "r2", "r3", "ip", "lr")

    def writes_pc(op, args):
        return op.startswith("bx") or re.match(r"pc\b", args) or (
            op.startswith(("pop", "ldm")) and re.search(r"\bpc\b", args))

    def after(held, op, args):
        """What is known of the registers after one instruction."""
        held = dict(held)
        lit = re.match(r"(r\d+),\s*\[pc,\s*#(?:0x[0-9a-f]+|\d+)\]\s*@\s*0x([0-9a-f]+)(\s*<[^>]*>)?$", args)
        mov = re.match(r"(r\d+),\s*(r\d+)$", args)
        if op in ("ldr", "ldr.w") and lit:
            w = word_at(image, int(lit.group(2), 16))
            fn = starts.get(w & ~1) if w is not None else None
            held.pop(lit.group(1), None)
            if fn is not None:
                held[lit.group(1)] = fn
        elif op == "mov" and mov:
            if mov.group(2) in held:
                held[mov.group(1)] = held[mov.group(2)]
            else:
                held.pop(mov.group(1), None)
        elif branch.match(op) or op.startswith(("cbz", "cbnz", "tbb", "tbh")):
            pass
        elif op.startswith("bl"):
            for r in clobbered:
                held.pop(r, None)
        else:
            # any register an instruction names may be written by it
            for r in re.findall(r"\b(r\d+|lr|ip|sb|sl|fp)\b", args):
                held.pop(r, None)
        return held

    for _, cur in order:
        frames[cur], calls[cur] = 0, set()
        ins = body[cur]
        index_of = {addr: i for i, (addr, _, _) in enumerate(ins)}
        succ, tables = [], False
        for i, (addr, op, args) in enumerate(ins):
            s = []
            if branch.match(op) or op.startswith(("cbz", "cbnz")):
                t = re.search(r"(?:^|,\s*)(?:0x)?([0-9a-f]+)\s*<", args)
                if t and int(t.group(1), 16) in index_of:
                    s.append(index_of[int(t.group(1), 16)])
                if op not in ("b", "b.w", "b.n"):
                    s.append(i + 1)
            elif op.startswith(("tbb", "tbh")):
                # a table branch goes to every address its table holds
                t = table_targets(image, addr, op.startswith("tbh"))
                if t is None:
                    tables = True
                else:
                    s.extend(index_of[x] for x in t if x in index_of)
            elif not (writes_pc(op, args) and op in ("bx", "pop", "pop.w", "ldm", "ldm.w", "mov")):
                # a write to pc that is conditional (inside an IT block) may fall through
                s.append(i + 1)
            succ.append([j for j in s if j < len(ins)])
        known = [None] * len(ins)
        if ins and not tables:
            known[0], work = {}, [0]
            while work:
                i = work.pop()
                out = after(known[i], ins[i][1], ins[i][2])
                for j in succ[i]:
                    new = out if known[j] is None else {r: f for r, f in known[j].items() if out.get(r) == f}
                    if new != known[j]:
                        known[j] = new
                        work.append(j)
        for i, (addr, op, args) in enumerate(ins):
            held = known[i] or {}
            if op in ("blx", "blx.w") and "<" not in args and args.strip() in held:
                calls[cur].add(held[args.strip()])
                continue
            if op.startswith("push") or (op.startswith("stmdb") and args.startswith("sp!")):
                frames[cur] += 4 * len(re.findall(r"\b(r\d+|lr|pc|sb|sl|fp|ip)\b", args[args.find("{"):]))
            elif op.startswith("vpush"):
                frames[cur] += 8 * len(re.findall(r"\bd\d+\b", args)) + 4 * len(re.findall(r"\bs\d+\b", args))
            elif op.startswith("sub") and re.match(r"sp,\s*(sp,\s*)?#", args):
                frames[cur] += int(re.search(r"#(0x[0-9a-f]+|\d+)", args).group(1), 0)
            elif op.startswith("blx") and "<" not in args:
                sys.exit("elfsize: %s makes an indirect call; the stack cannot be bounded from the disassembly" % cur)
            elif op[0] == "b" or op.startswith("cb"):
                # a call or tail call goes to the start of a function. A branch into
                # the middle of another function is the linker's fill between two
                # functions (0xd4d4 on Thumb), which disassembles as `bmi`.
                t = re.search(r"<([^>+]+)(\+0x[0-9a-f]+)?>", args)
                if t and t.group(1) != cur and not t.group(2):
                    calls[cur].add(t.group(1))
    if entry not in frames:
        sys.exit("elfsize: no function `%s` in %s" % (entry, path))
    # strongly connected groups (Tarjan), then the deepest chain over the groups
    index, low, on, stack, group_of, groups = {}, {}, set(), [], {}, []

    def visit(v):
        index[v] = low[v] = len(index)
        stack.append(v)
        on.add(v)
        for w in calls.get(v, ()):
            if w not in frames:
                continue
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            members = []
            while True:
                w = stack.pop()
                on.discard(w)
                members.append(w)
                if w == v:
                    break
            for w in members:
                group_of[w] = len(groups)
            groups.append(members)

    sys.setrecursionlimit(10000)
    visit(entry)
    memo = {}

    def deepest(g):
        if g not in memo:
            members = groups[g]
            cyclic = len(members) > 1 or members[0] in calls[members[0]]
            own = sum(frames[m] for m in members) * (depth if cyclic else 1)
            below = [deepest(group_of[w]) for m in members for w in calls[m] if w in group_of and group_of[w] != g]
            memo[g] = own + max(below or [0])
        return memo[g]

    total = deepest(group_of[entry])
    print()
    print("stack bound from `%s`, nested blocks counted %d deep: %d bytes" % (entry, depth, total))
    cyc = [m for g in groups if len(g) > 1 for m in g]
    print("  functions reached: %d; in groups that call one another: %d (%d bytes a round)"
          % (len(index), len(cyc), sum(frames[m] for m in cyc)))


def main(argv):
    path = argv[0]
    top = int(argv[argv.index("--symbols") + 1]) if "--symbols" in argv else 12
    with open(path, "rb") as fh:
        b = fh.read()
    if b[:4] != b"\x7fELF" or b[4] != 1 or b[5] != 1:
        sys.exit("elfsize: %s is not a 32-bit little-endian ELF image" % path)
    shoff, = struct.unpack_from("<I", b, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", b, 0x2E)
    sections = []
    for i in range(shnum):
        name, kind, flags, addr, off, size, link, info, align, entsize = struct.unpack_from("<10I", b, shoff + i * shentsize)
        sections.append({"name": name, "type": kind, "flags": flags, "addr": addr, "off": off, "size": size,
                         "link": link, "entsize": entsize})
    strtab = sections[shstrndx]

    def text(table, at):
        start = table["off"] + at
        return b[start:b.index(b"\0", start)].decode("ascii", "replace")

    print("%-18s %8s" % ("section", "bytes"))
    code = data = 0
    for s in sections:
        if not s["flags"] & 2 or s["size"] == 0:      # SHF_ALLOC
            continue
        name = text(strtab, s["name"])
        print("%-18s %8d" % (name, s["size"]))
        if s["type"] == 8:                             # SHT_NOBITS: RAM only
            continue
        if s["flags"] & 4:                             # SHF_EXECINSTR
            code += s["size"]
        else:
            data += s["size"]
    print("%-18s %8d" % ("code (flash)", code))
    print("%-18s %8d" % ("constants (flash)", data))
    symbols = []
    for s in sections:
        if s["type"] != 2 or not s["entsize"]:         # SHT_SYMTAB
            continue
        names = sections[s["link"]]
        for i in range(s["size"] // s["entsize"]):
            name, value, size, info, other, shndx = struct.unpack_from("<IIIBBH", b, s["off"] + i * s["entsize"])
            if size and info & 0xF in (1, 2):          # objects and functions
                symbols.append((size, "func" if info & 0xF == 2 else "data", text(names, name)))
    if symbols:
        print()
        print("largest symbols:")
        for size, kind, name in sorted(symbols, reverse=True)[:top]:
            print("  %6d  %s  %s" % (size, kind, name[:90]))
    if "--stack" in argv:
        depth = int(argv[argv.index("--depth") + 1]) if "--depth" in argv else 12
        stack_bound(path, argv[argv.index("--stack") + 1], depth)


if __name__ == "__main__":
    main(sys.argv[1:])
