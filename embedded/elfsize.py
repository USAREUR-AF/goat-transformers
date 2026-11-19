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


def stack_bound(path, entry, depth):
    text = subprocess.run([objdump(), "-d", "--no-show-raw-insn", path], capture_output=True, text=True, check=True).stdout
    frames, calls, cur = {}, {}, None
    head = re.compile(r"^[0-9a-f]+ <(.+)>:$")
    for line in text.split("\n"):
        m = head.match(line.strip())
        if m:
            cur = m.group(1)
            frames[cur], calls[cur] = 0, set()
            continue
        if cur is None or "\t" not in line:
            continue
        ins = line.split("\t", 1)[1].strip() if ":" in line else ""
        parts = ins.split(None, 1)
        if not parts:
            continue
        op, args = parts[0], parts[1] if len(parts) > 1 else ""
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
