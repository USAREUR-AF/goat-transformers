#!/usr/bin/env python3
"""release-version: every package of this repository carries one version.

The library version is the version of the specification the engines implement
(0.8.0 for spec Version 0.8). Packs and model modules carry their own
`version` lines and are not checked here.

Usage:
  tools/release-version.py            # every file below states the same version
  tools/release-version.py 0.8.0      # ... and it is this one (the release workflow passes the tag)

Exits non-zero and names each file that differs. Run with -I.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# file -> the pattern whose first group is the version
PLACES = {
    "engines/rust/Cargo.toml": r'^version\s*=\s*"([^"]+)"',
    "bindings/c/Cargo.toml": r'^version\s*=\s*"([^"]+)"',
    "bindings/wasm/Cargo.toml": r'^version\s*=\s*"([^"]+)"',
    "bindings/wasm/package.json": r'^\s*"version"\s*:\s*"([^"]+)"',
    "bindings/c/install.sh": r"^version=(\S+)",
    "engines/python/pyproject.toml": r'^version\s*=\s*"([^"]+)"',
    "engines/python/src/goat_transformers/__init__.py": r'^__version__\s*=\s*"([^"]+)"',
    "engines/java/build.sh": r"^version=(\S+)",
    "engines/cpp/CMakeLists.txt": r"^project\(\S+ VERSION (\S+)",
    "engines/erlang/src/goat_transformers.app.src": r'\{vsn,\s*"([^"]+)"\}',
    "engines/zig/build.zig.zon": r'^\s*\.version\s*=\s*"([^"]+)"',
    "build.zig.zon": r'^\s*\.version\s*=\s*"([^"]+)"',
}


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else None
    found = {}
    bad = []
    for rel, pattern in PLACES.items():
        try:
            with open(os.path.join(REPO, *rel.split("/")), encoding="utf-8") as fh:
                m = re.search(pattern, fh.read(), re.M)
        except OSError as e:
            bad.append(f"{rel}: cannot read ({e.strerror})")
            continue
        if m is None:
            bad.append(f"{rel}: no version line")
        else:
            found[rel] = m.group(1)
    if want is None and found:
        want = found["engines/rust/Cargo.toml"] if "engines/rust/Cargo.toml" in found else next(iter(found.values()))
    for rel, version in found.items():
        if version != want:
            bad.append(f"{rel}: {version}, expected {want}")
    if bad:
        for line in bad:
            print("release-version:", line, file=sys.stderr)
        return 1
    print(f"release-version: {want} in {len(found)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
