#!/bin/bash
# Regenerate the OpenADR 3.1.0 packs, one per object the API exchanges: program, event,
# report, subscription, ven, resource, notification.
#
# Usage: tools/gen/openadr3-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/openadr3-specification is a git checkout of
# https://github.com/grid-coordination/openadr3-specification at commit
# 17b91725e0f07203574ddc946e28def31cb11e44 (the script checks). That repository is a public
# mirror: the OpenADR Alliance publishes the specification at no charge but behind an
# account registration, and its own repository (oadr3-org/specification) is not public.
# The mirror republishes 3.1.0 from upstream commit ddd2cc5. The script reads
# 3.1.0/openadr3-UPSTREAM.yaml, the mirror's byte-for-byte copy of the upstream file. The
# document's info.license names the Apache License 2.0; the packs are labelled Apache-2.0.
#
# Writes model/openadr3*.def, packs/openadr3-*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/openadr3-*.json. PROVENANCE.md is not generated. With --check nothing is
# written (jsonschema2pack --check per run); every run is made and the exit status is 1
# when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <sources> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=17b91725e0f07203574ddc946e28def31cb11e44
got="$(git -C "$SRC/openadr3-specification" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "openadr3-specification is at $got, not $COMMIT" >&2; exit 1; }
F="$SRC/openadr3-specification/3.1.0/openadr3-UPSTREAM.yaml"
STATUS=0
LICENSE="Apache-2.0, OpenADR Alliance (info.license of the OpenAPI document)"
SOURCE="https://github.com/grid-coordination/openadr3-specification at commit $COMMIT, 3.1.0/openadr3-UPSTREAM.yaml (mirror of oadr3-org/specification commit ddd2cc5)"
cd "$W"

# adr <format> <module> <schema> [options...]
adr() {
  local fmt="$1" mod="$2" schema="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$F" \
      --message "$schema=$F#/components/schemas/$schema" \
      --format "$fmt" --module "$mod" --title "OpenADR 3.1.0 OpenAPI document; schema $schema" \
      --license "$LICENSE" --source "$SOURCE" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/openadr3.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
ID="the identifier the server (VTN) assigns to the object when it is created"

adr openadr3-program openadr3program program --map program:id=uid --evidence "program:id=$ID"
adr openadr3-event openadr3event event --map event:id=uid --evidence "event:id=$ID"
adr openadr3-report openadr3report report --map report:id=uid --evidence "report:id=$ID"
adr openadr3-subscription openadr3sub subscription --map subscription:id=uid --evidence "subscription:id=$ID"
adr openadr3-ven openadr3ven ven --map ven:id=uid --evidence "ven:id=$ID"
adr openadr3-resource openadr3resource resource --map resource:id=uid --evidence "resource:id=$ID"
adr openadr3-notification openadr3notif notification

exit "$STATUS"
