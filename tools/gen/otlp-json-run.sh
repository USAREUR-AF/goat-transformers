#!/bin/bash
# Regenerate the otlp-json-* packs: the OTLP/JSON form of the three export requests.
#
# Usage: tools/gen/otlp-json-run.sh [--check] <checkout> <sources>
#
# <sources>/opentelemetry/proto/...: github.com/open-telemetry/opentelemetry-proto commit
# d31f7acf9d461fd0601077de516ac1eb7051422f (the commit of the protobuf otlp-* packs, tag v1.11.1
# and 17 commits), the 8 .proto files listed below. Apache License 2.0. Not kept in this
# repository; each pack's PROVENANCE.md has their SHA-256.
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
OTLP=d31f7acf9d461fd0601077de516ac1eb7051422f
O="$SRC/opentelemetry/proto"
PROTO=("$O/collector/trace/v1/trace_service.proto" "$O/collector/metrics/v1/metrics_service.proto"
       "$O/collector/logs/v1/logs_service.proto" "$O/common/v1/common.proto" "$O/resource/v1/resource.proto"
       "$O/trace/v1/trace.proto" "$O/metrics/v1/metrics.proto" "$O/logs/v1/logs.proto")
STATUS=0
for spec in export-trace-request:collector.trace.v1.ExportTraceServiceRequest \
            export-metrics-request:collector.metrics.v1.ExportMetricsServiceRequest \
            export-logs-request:collector.logs.v1.ExportLogsServiceRequest; do
  name="${spec%%:*}"; env="opentelemetry.proto.${spec#*:}"
  python3 -I "$GEN/protojson2pack.py" --out "$ROOT" ${CHECK[@]+"${CHECK[@]}"} \
    --proto "${PROTO[@]}" --envelope "$env" --format "otlp-json-$name" --module "otlpjson${name//-/}" \
    --hex-bytes trace_id --hex-bytes span_id --hex-bytes parent_span_id \
    --source "OpenTelemetry protocol (OTLP) protobuf definitions: github.com/open-telemetry/opentelemetry-proto commit $OTLP, opentelemetry/proto (8 .proto files); envelope $env in the OTLP/JSON encoding (proto3 JSON mapping, hex trace and span ids, enums as numbers); field names, numbers and types only" \
    --source "LICENSE and the file headers at that commit: Copyright The OpenTelemetry Authors; Apache License, Version 2.0" \
    --notes-file "$GEN/notes/otlp-json.md" > /dev/null || STATUS=1
done
exit $STATUS
