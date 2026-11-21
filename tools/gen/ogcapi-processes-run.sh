#!/bin/bash
# Regenerate the OGC API - Processes - Part 1: Core 1.0 packs.
# Usage: tools/gen/ogcapi-processes-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/processes-1.0 is a checkout of https://github.com/opengeospatial/ogcapi-processes
# at branch 1.0.0-maintenance, commit 52a53a466c2cc9feca7f1c5dee463345fbf569d6 (the script
# checks it): the schemas of edition 1.0 (the default branch holds the next edition, a
# draft). License: the repository's LICENSE, the OGC Software License (SHA-256
# b3b9a76d230f057844d004c374406453d92f863caecaa42ccd9c7863e143fed1), quoted in each
# pack's PROVENANCE.md. The SHA-256 of every schema file read is in each pack.md.
#
# Not generated: the execute request (execute.yaml) and the results document
# (results.yaml): their inputs and outputs are objects whose member names are the
# process's own input and output identifiers, which no locator addresses.
#
# Writes model/ogcproc*.def, packs/ogcapi-process*/ and packs/ogcapi-job*/ (pack.def,
# pack.md, vectors/gen-*) and tools/gen/names/ogcapi-{process,job}*.json. PROVENANCE.md is
# not generated. With --check nothing is written; every run is made and the exit status is
# 1 when any file differs.
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
STATUS=0
got="$(git -C "$SRC/processes-1.0" rev-parse HEAD)"
[ "$got" = 52a53a466c2cc9feca7f1c5dee463345fbf569d6 ] || { echo "processes-1.0 is at $got" >&2; exit 1; }
LICENSE="OGC Software License (Open Geospatial Consortium, opengeospatial/ogcapi-processes LICENSE); this pack is a modification that OGC has not approved or adopted"
SP="https://github.com/opengeospatial/ogcapi-processes at branch 1.0.0-maintenance, commit 52a53a466c2cc9feca7f1c5dee463345fbf569d6, core/openapi/schemas"
P="$SRC/processes-1.0/core/openapi/schemas"
cd "$W"

gen() {
  local fmt="$1" mod="$2" title="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$LICENSE" --source "$SP" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
DESC=("$P/descriptionType.yaml" "$P/metadata.yaml" "$P/additionalParameter.yaml" "$P/jobControlOptions.yaml"
  "$P/transmissionMode.yaml" "$P/link.yaml" "$P/processSummary.yaml")
STATUSF=("$P/statusInfo.yaml" "$P/statusCode.yaml" "$P/link.yaml")

# A process description (process.yaml)
gen ogcapi-process ogcproc "OGC API - Processes - Part 1: Core 1.0, process description (process.yaml)" \
  --schema "$P/process.yaml" "${DESC[@]}" "$P/inputDescription.yaml" "$P/outputDescription.yaml" \
    "$P/schema.yaml" "$P/reference.yaml" \
  --message Process="$P/process.yaml"

# The process list (processList.yaml)
gen ogcapi-process-list ogcproclist "OGC API - Processes - Part 1: Core 1.0, process list (processList.yaml)" \
  --schema "$P/processList.yaml" "${DESC[@]}" \
  --message ProcessList="$P/processList.yaml"

# The status of a job (statusInfo.yaml)
gen ogcapi-job-status ogcjob "OGC API - Processes - Part 1: Core 1.0, job status (statusInfo.yaml)" \
  --schema "${STATUSF[@]}" \
  --message StatusInfo="$P/statusInfo.yaml" \
  --map StatusInfo:jobID=uid --map StatusInfo:updated=time_ms

# The job list (jobList.yaml)
gen ogcapi-job-list ogcjoblist "OGC API - Processes - Part 1: Core 1.0, job list (jobList.yaml)" \
  --schema "$P/jobList.yaml" "${STATUSF[@]}" \
  --message JobList="$P/jobList.yaml"

exit "$STATUS"
