#!/usr/bin/env python3
"""Build the Python engine with a set of wires (spec/engine-spec.md, Version
0.24, ruling 1).

    python3 -I engines/python/build.py                          # all eight wires
    python3 -I engines/python/build.py --wires xml,json,geojson  # three

The build copies the package `src/goat_transformers` and leaves out the codec
modules of every wire not in the set, so the reduced package does not carry
that code; `_build.py` in the copy names the set it kept. It writes

    <out>/src/goat_transformers/               the package, importable as is
    <out>/dist/goat_transformers-<v>-py3-none-any.whl   the wheel, for pip

`<out>` defaults to `engines/python/build/wires-<set>` (`wires-all` for all
eight). Standard library only; the wheel is written byte for byte the same
for the same sources (fixed timestamps, sorted entries)."""

import argparse
import base64
import hashlib
import os
import re
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.join(HERE, "src", "goat_transformers")

# The wires of the specification, in its order (ruling 1a).
WIRES = ("xml", "geojson", "json", "bits", "protobuf", "text", "tlv", "cbor")

# The modules that are the codec of one wire. Ruling 1d: the sequential
# layout (`seqdef`, `wire_seq`), six-bit armor (in `wire_bits`) and
# `encoding uper` (`uper`) belong to `bits`.
WIRE_MODULES = {
    "xml": ("wire_xml",),
    "geojson": ("wire_geojson",),
    "json": ("wire_json",),
    "bits": ("wire_bits", "wire_seq", "seqdef", "uper"),
    "protobuf": ("wire_protobuf",),
    "text": ("wire_text",),
    "tlv": ("wire_tlv",),
    "cbor": ("wire_cbor",),
}

# Modules shared by some wires: carried when the build has any of them.
# `jsonio` is the JSON reader and writer of `json` and `geojson` (ruling 1d:
# `geojson` needs nothing of `json`); `octets` is hex input (also of `cbor`) and the `utf8`
# and `hex` octet transforms of `bits` (UPER `octets:`), `protobuf` and `tlv`.
SHARED_MODULES = {
    "jsonio": ("json", "geojson"),
    "octets": ("bits", "protobuf", "tlv", "cbor"),
}


def parse_wires(text):
    """`xml,json,geojson` -> the set in the specification's order. Raises ValueError."""
    names = [w.strip() for w in text.split(",") if w.strip()]
    for w in names:
        if w not in WIRES:
            raise ValueError("%r is not a wire of the specification (wires: %s)" % (w, ", ".join(WIRES)))
    return tuple(w for w in WIRES if w in names)


def left_out(wires):
    """-> the module names a build with `wires` does not carry."""
    out = set()
    for w, mods in WIRE_MODULES.items():
        if w not in wires:
            out.update(mods)
    for mod, users in SHARED_MODULES.items():
        if not any(w in wires for w in users):
            out.add(mod)
    return out


def version():
    with open(os.path.join(HERE, "pyproject.toml"), "r", encoding="utf-8") as fh:
        m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
    if m is None:
        raise SystemExit("build.py: no version in pyproject.toml")
    return m.group(1)


def build_text(wires):
    return (
        '"""The wires of this build (spec/engine-spec.md, Version 0.24, ruling 1),\n'
        'written by engines/python/build.py."""\n\n'
        "WIRES = (%s)\n" % "".join('"%s", ' % w for w in wires).rstrip(" ")
    )


def write_package(wires, dest):
    """Copy the package to `dest`, without the modules `wires` does not need.
    -> the sorted list of (name in the package, bytes)."""
    skip = left_out(wires)
    files = []
    for name in sorted(os.listdir(PACKAGE)):
        if not name.endswith(".py"):
            continue
        mod = name[:-3]
        if mod in skip:
            continue
        if mod == "_build":
            data = build_text(wires).encode("utf-8")
        else:
            with open(os.path.join(PACKAGE, name), "rb") as fh:
                data = fh.read()
        files.append((name, data))
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for name, data in files:
        with open(os.path.join(dest, name), "wb") as fh:
            fh.write(data)
    return files


def _record_hash(data):
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def write_wheel(files, wires, dist):
    """A pure-Python wheel of the package files (PEP 427). -> its path."""
    v = version()
    info = "goat_transformers-%s.dist-info" % v
    note = "all eight wires" if wires == WIRES else "wires: " + (", ".join(wires) or "none")
    entries = [("goat_transformers/" + name, data) for name, data in files]
    entries.append((info + "/METADATA", (
        "Metadata-Version: 2.1\nName: goat-transformers\nVersion: %s\n"
        "Summary: Convert messages between formats described by packs (Python engine; %s)\n"
        "License: Apache-2.0\nRequires-Python: >=3.9\n" % (v, note)
    ).encode("utf-8")))
    entries.append((info + "/WHEEL", (
        "Wheel-Version: 1.0\nGenerator: goat-transformers build.py\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    ).encode("utf-8")))
    entries.append((info + "/entry_points.txt", b"[console_scripts]\ngoat-xf-py = goat_transformers.cli:main\n"))
    record = "".join("%s,%s,%d\n" % (n, _record_hash(d), len(d)) for n, d in entries) + info + "/RECORD,,\n"
    entries.append((info + "/RECORD", record.encode("utf-8")))
    os.makedirs(dist, exist_ok=True)
    path = os.path.join(dist, "goat_transformers-%s-py3-none-any.whl" % v)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in entries:
            zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data)
    return path


def build(wires, out):
    """Build the package and the wheel for `wires` under `out`. -> a dict:
    `src` (the directory to put on sys.path), `wheel`, `wheel_bytes`,
    `package_bytes`, `modules`, `left_out`."""
    files = write_package(wires, os.path.join(out, "src", "goat_transformers"))
    wheel = write_wheel(files, wires, os.path.join(out, "dist"))
    return {
        "src": os.path.join(out, "src"),
        "wheel": wheel,
        "wheel_bytes": os.path.getsize(wheel),
        "package_bytes": sum(len(d) for _, d in files),
        "modules": [n[:-3] for n, _ in files],
        "left_out": sorted(left_out(wires)),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the Python engine with a set of wires (spec 0.24).")
    ap.add_argument("--wires", default=None,
                    help="the wires to build, comma-separated, from: %s (default: all eight)" % ",".join(WIRES))
    ap.add_argument("--out", default=None, help="the output directory (default: engines/python/build/wires-<set>)")
    args = ap.parse_args(argv)
    try:
        wires = WIRES if args.wires is None else parse_wires(args.wires)
    except ValueError as e:
        ap.error(str(e))
    out = args.out or os.path.join(HERE, "build", "wires-" + ("all" if wires == WIRES else "-".join(wires) or "none"))
    r = build(wires, out)
    print("wires:     %s" % (", ".join(wires) or "(none)"))
    print("left out:  %s" % (", ".join(r["left_out"]) or "(nothing)"))
    print("package:   %s (%d bytes of source, %d modules)" % (r["src"], r["package_bytes"], len(r["modules"])))
    print("wheel:     %s (%d bytes)" % (r["wheel"], r["wheel_bytes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
