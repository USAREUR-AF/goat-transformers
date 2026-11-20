#!/bin/bash
# Regenerate the prometheus-remote-write packs: remote write 1.0 (prometheus.WriteRequest) and
# 2.0 (io.prometheus.write.v2.Request), in their protobuf form.
#
# Usage: tools/gen/prometheus-run.sh [--check] <checkout> <sources>
#
# <sources> holds:
#   prometheus/prompb/types.proto, prometheus/prompb/remote.proto,
#   prometheus/prompb/io/prometheus/write/v2/types.proto
#     github.com/prometheus/prometheus tag v3.16.0 (commit e2e28adeee2c5883d000fc82aca6008cfbf7e96d),
#     each https://raw.githubusercontent.com/prometheus/prometheus/<commit>/prompb/<path>;
#     Apache License 2.0 (each file's header, LICENSE)
#   gogo/gogoproto/gogo.proto
#     github.com/gogo/protobuf tag v1.3.2 (commit b03c65ea87cdc3521ede29f62fe3ce239267c1bc),
#     BSD-3-Clause; imported for the Go options only
# The files are not kept in this repository; each pack's PROVENANCE.md has their SHA-256. With
# --check nothing is written: each run compares what it would write with <checkout>.
set -euo pipefail
CHECK=()
if [ "${1:-}" = "--check" ]; then
  CHECK=(--check)
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <checkout> <sources>" >&2
  exit 2
fi
ROOT="$(cd "$1" && pwd)"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
TAG=v3.16.0
COMMIT=e2e28adeee2c5883d000fc82aca6008cfbf7e96d
P="$SRC/prometheus/prompb"
GOGO="$SRC/gogo/gogoproto/gogo.proto"
STATUS=0
python3 -I "$GEN/proto2pack.py" --out "$ROOT" ${CHECK[@]+"${CHECK[@]}"} --no-comments --pack-version 0.1.0 \
  --proto "$P/types.proto" "$P/remote.proto" "$GOGO" \
  --envelope prometheus.WriteRequest --format prometheus-remote-write --module prometheusremotewrite \
  --source "Prometheus remote write 1.0 protobuf definitions: github.com/prometheus/prometheus tag $TAG (commit $COMMIT), prompb/types.proto and prompb/remote.proto; envelope prometheus.WriteRequest; field numbers, names and types only" \
  --source "Their headers and LICENSE: Apache License, Version 2.0, Copyright Prometheus Team; gogoproto/gogo.proto (gogo/protobuf v1.3.2, BSD-3-Clause) is read for its options only" \
  --names-file "$GEN/names/prometheus-remote-write.json" \
  --notes-file "$GEN/notes/prometheus.md" > /dev/null || STATUS=1
python3 -I "$GEN/proto2pack.py" --out "$ROOT" ${CHECK[@]+"${CHECK[@]}"} --no-comments --pack-version 0.1.0 \
  --proto "$P/io/prometheus/write/v2/types.proto" "$GOGO" \
  --envelope io.prometheus.write.v2.Request --format prometheus-remote-write-v2 --module prometheusremotewritev2 \
  --source "Prometheus remote write 2.0 (release candidate 5) protobuf definitions: github.com/prometheus/prometheus tag $TAG (commit $COMMIT), prompb/io/prometheus/write/v2/types.proto; envelope io.prometheus.write.v2.Request; field numbers, names and types only" \
  --source "Its header and LICENSE: Apache License, Version 2.0, Copyright Prometheus Team; gogoproto/gogo.proto (gogo/protobuf v1.3.2, BSD-3-Clause) is read for its options only" \
  --names-file "$GEN/names/prometheus-remote-write-v2.json" \
  --notes-file "$GEN/notes/prometheus.md" > /dev/null || STATUS=1
exit $STATUS
