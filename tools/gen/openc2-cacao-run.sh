#!/bin/bash
# Regenerate the OpenC2 and CACAO packs: openc2-lang and openc2-slpf (the Command and the
# Response of the OpenC2 Language Specification 1.1 and of the Stateless Packet Filtering
# actuator profile 1.1) and cacao-playbook (a CACAO Security Playbooks 2.0 playbook).
#
# Usage: tools/gen/openc2-cacao-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds two git checkouts, each at the commit below (the script checks):
#   openc2-custom-aps   https://github.com/oasis-open/openc2-custom-aps  (Apache-2.0, OASIS TC
#                       Open Repository), commit f6ef6b3747e6927e262a73f47edd6f8b72b71b83;
#                       files Schema-Template/v1.1/JSON-Schema/oc2ls-v1.1-lang.json, oc2slpf-v1.1.json
#   cacao-json-schemas  https://github.com/oasis-open/cacao-json-schemas  (Apache-2.0, OASIS TC
#                       Open Repository), commit 72853294a18b7d42af84fe1cc410ac70b1366c3b;
#                       schemas/playbook.json and the files its $ref reach
# The SHA-256 of every file read is in each pack's pack.md and PROVENANCE.md. The OASIS
# specifications these schemas follow are not read.
#
# Shared keys: tools/gen/notes/openc2.md and tools/gen/notes/cacao.md.
#
# Writes model/{oc2lang,oc2slpf,cacao}.def, packs/{openc2-lang,openc2-slpf,cacao-playbook}/
# (pack.def, pack.md, vectors/gen-*, PROVENANCE.md through tools/gen/jsonmore-provenance.py)
# and tools/gen/names/<format>.json. With --check nothing is written: every run compares
# what it would write with the checkout, all runs are made, and the exit status is 1 when
# any file differs.
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
OC2=f6ef6b3747e6927e262a73f47edd6f8b72b71b83
CACAO=72853294a18b7d42af84fe1cc410ac70b1366c3b
check() {
  local got
  got="$(git -C "$SRC/$1" rev-parse HEAD)"
  [ "$got" = "$2" ] || { echo "$1 is at $got, not $2" >&2; exit 1; }
}
check openc2-custom-aps "$OC2"
check cacao-json-schemas "$CACAO"
cd "$W"
STATUS=0
run() {
  if ! python3 -I "$GEN/jsonschema2pack.py" "$@" ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

EV_CMDID="the schema's Command-ID: the identifier of this Command, up to 36 characters with no space; a Response refers to the Command by it"
O="$SRC/openc2-custom-aps/Schema-Template/v1.1/JSON-Schema"
# openc2 <format> <module> <file> <title>
openc2() {
  local f="$O/$3"
  run --schema "$f" \
    --message "Command=$f#/definitions/OpenC2-Command" --message "Response=$f#/definitions/OpenC2-Response" \
    --kind-when Command:action=present --kind-when Response:status=present \
    --map Command:command_id=uid --evidence "Command:command_id=$EV_CMDID" \
    --format "$1" --module "$2" --title "$4" \
    --license "Apache-2.0, OASIS TC Open Repository oasis-open/openc2-custom-aps" \
    --source "https://github.com/oasis-open/openc2-custom-aps at commit $OC2, Schema-Template/v1.1/JSON-Schema/$3" \
    --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$1.json" --notes-file "$GEN/notes/openc2.md"
}
openc2 openc2-lang oc2lang oc2ls-v1.1-lang.json "OpenC2 Language Specification 1.1, JSON Schema of the Command and the Response (oasis-open/openc2-custom-aps)"
openc2 openc2-slpf oc2slpf oc2slpf-v1.1.json "OpenC2 Stateless Packet Filtering actuator profile 1.1, JSON Schema of the Command and the Response (oasis-open/openc2-custom-aps)"

# The schema files one playbook reads: the file and every file its $ref reach, sorted.
closure() {
  python3 -I - "$1" <<'PY'
import json, os, sys
todo, seen = [os.path.abspath(sys.argv[1])], set()
while todo:
    f = todo.pop()
    if f in seen:
        continue
    seen.add(f)
    stack = [json.load(open(f, encoding="utf-8"))]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            r = x.get("$ref")
            if isinstance(r, str) and not r.startswith("#"):
                todo.append(os.path.normpath(os.path.join(os.path.dirname(f), r.split("#")[0])))
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
print("\n".join(sorted(seen)))
PY
}
EV_ID="identifier.json: the object's type, two dashes and an RFC 4122 UUID; playbook.json: it identifies the playbook, and all its versions share it"
EV_MOD="playbook.json: the time this version of the playbook was last changed; timestamp.json: RFC 3339 with the Z designator, so UTC"
EV_UNTIL="playbook.json: the time after which the playbook is no longer to be taken as valid to run; timestamp.json: RFC 3339 with the Z designator, so UTC"
P="$SRC/cacao-json-schemas/schemas/playbook.json"
# shellcheck disable=SC2046
run --schema $(closure "$P") --message "playbook=$P" --when type=playbook \
  --date-time playbook:modified --date-time playbook:valid_until \
  --map playbook:id=uid --map playbook:modified=time_ms --map playbook:valid_until=stale_ms \
  --evidence "playbook:id=$EV_ID" --evidence "playbook:modified=$EV_MOD" --evidence "playbook:valid_until=$EV_UNTIL" \
  --format cacao-playbook --module cacao \
  --title "CACAO Security Playbooks 2.0 playbook JSON Schema (oasis-open/cacao-json-schemas)" \
  --license "Apache-2.0, OASIS TC Open Repository oasis-open/cacao-json-schemas" \
  --source "https://github.com/oasis-open/cacao-json-schemas at commit $CACAO, schemas/playbook.json" \
  --source "CACAO Security Playbooks Version 2.0, OASIS Committee Specification: https://docs.oasis-open.org/cacao/security-playbooks/v2.0/security-playbooks-v2.0.html" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/cacao-playbook.json" --notes-file "$GEN/notes/cacao.md"

python3 -I "$GEN/jsonmore-provenance.py" openc2 ${CHECK:+"$CHECK"} "$SRC/openc2-custom-aps" "$W" || STATUS=1
python3 -I "$GEN/jsonmore-provenance.py" cacao ${CHECK:+"$CHECK"} "$SRC/cacao-json-schemas" "$W" || STATUS=1

exit "$STATUS"
