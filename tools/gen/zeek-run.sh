#!/bin/bash
# Regenerate the zeek-<log>-scope-underscore packs: Zeek JSON log records written with
# Log::default_scope_sep = "_", one pack per log (conn, dns, http, ssl, files, notice,
# weird, x509, dhcp).
#
# Usage: tools/gen/zeek-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/zeek is a checkout of https://github.com/zeek/zeek at tag v8.0.11, commit
# b961108c32a10ce8d42dc470a2fa6dc513c4cf0b (BSD-3-Clause; the script checks the commit).
# The field lists are restated in tools/gen/zeek-logs.tsv.txt from the &log fields of the Info
# records in the scripts zeek-schemas.py names; the checkout is read only for the commit.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then CHECK="--check"; shift; fi
[ "$#" -eq 2 ] || { echo "usage: $0 [--check] <sources> <checkout>" >&2; exit 2; }
SRC="$(cd "$1" && pwd)/zeek"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=b961108c32a10ce8d42dc470a2fa6dc513c4cf0b
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "zeek is at $got, not $COMMIT" >&2; exit 1; }
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
python3 -I "$GEN/zeek-schemas.py" schemas "$GEN/zeek-logs.tsv.txt" "$TMP"
cd "$W"
for log in conn dns http ssl files notice weird x509 dhcp; do
  NOTES="$TMP/notes-$log.md"
  cp "$GEN/notes/zeek.md" "$NOTES"
  MAP=()
  case "$log" in
    conn)
      MAP=(--map "record:uid=uid" --evidence "record:uid=Zeek's unique identifier of the connection; a conn record is that connection's summary, so it identifies the entity")
      printf '\n- `uid` (`uid`): the unique identifier Zeek gives the connection; a conn record summarises that connection.\n- `ts` is not bound to `time_ms`: seconds with a fraction of microseconds become milliseconds only by rounding, which is not exact.\n' >> "$NOTES" ;;
    files)
      MAP=(--map "record:fuid=uid" --evidence "record:fuid=Zeek's unique identifier of the file; a files record describes that file")
      printf '\n- `uid` (`fuid`): the identifier Zeek gives the file; a files record describes that file. Zeek'"'"'s `uid` member here is the connection that carried it and stays raw.\n- `ts` is not bound to `time_ms` (as for conn).\n' >> "$NOTES" ;;
    *)
      printf '\nNone. `ts` is not bound to `time_ms`: seconds with a fraction of microseconds become milliseconds only by rounding, which is not exact. Where the record has a `uid` it names the connection the record belongs to, not the record, and stays raw.\n' >> "$NOTES" ;;
  esac
  python3 -I "$GEN/jsonschema2pack.py" --schema "$TMP/$log.json" --message "record=$TMP/$log.json" \
    --format "zeek-$log-scope-underscore" --module "zeek$log" \
    --title "Zeek $log log, JSON with the scope separator _ (restated in tools/gen/zeek-logs.tsv.txt)" \
    --license "BSD-3-Clause source (zeek/zeek); field lists restated, no code copied: Apache-2.0" \
    --source "https://github.com/zeek/zeek at tag v8.0.11, commit $COMMIT: the &log fields of the $log log's Info record" \
    --source "tools/gen/zeek-logs.tsv.txt of this repository: the restated field list" \
    --out "$W" --model-dir "$W/model" --names-file "$GEN/names/zeek-$log.json" --notes-file "$NOTES" \
    "${MAP[@]}" ${CHECK:+"$CHECK"} > /dev/null
done
python3 -I "$GEN/zeek-schemas.py" provenance "$W" "$COMMIT" ${CHECK:+"$CHECK"}
[ -n "$CHECK" ] || echo zeek
