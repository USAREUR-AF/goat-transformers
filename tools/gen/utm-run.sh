#!/bin/bash
# Regenerate the UTM interoperability API packs: ASTM F3411 network Remote ID (v19, v22a) and
# ASTM F3548-21 strategic coordination, as InterUSS publishes their OpenAPI interfaces.
#
# Usage: tools/gen/utm-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/api-<std>-<ver>/api.py are interuss/uas_standards v4.4.0's
# src/uas_standards/astm/<std>/<ver>/api.py (the source of record). <sources> also holds the
# three OpenAPI files that interuss/uas_standards tag v4.4.0 (commit
# 15c05ba878efe76b7d47225fc7d673a9effb70f7) pins as git submodules, each checked by SHA-256:
#   f3411-v19/canonical.yaml   uastech/standards commit 228b301be1f4466df9b014f20b515665861a8e67, remoteid/canonical.yaml
#   f3411-v22a/canonical.yaml  uastech/standards commit dd4016b09fc8cb98f30c2a17b5a088fb2995ab54, remoteid/canonical.yaml
#   f3548-v21/utm.yaml         interuss/astm-utm-protocol commit 1d3d8fbe75414e23d7e19ce35955770bea5e413f, utm.yaml
# The source of record is InterUSS's Apache-2.0 restatement of the same interfaces,
# interuss/uas_standards v4.4.0 src/uas_standards/astm/{f3411/v19,f3411/v22a,f3548/v21}/api.py;
# the OpenAPI files (which state no licence) are read for convenience, and
# tools/gen/utm-crosscheck.py confirms they agree with api.py member for member. No
# description text of either is copied: every binding's evidence is given by --evidence.
# The ASTM standards themselves are not used.
#
# Writes model/<module>.def, packs/astm-f3411-*/ and packs/astm-f3548-v21-*/ (pack.def,
# pack.md, vectors/gen-*), packs/geojson/vectors/gen-geojson-to-*.json and the names files.
# PROVENANCE.md is not generated. With --check nothing is written; every run is made and the
# exit status is 1 when any file differs.
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
while read -r sha f; do
  got="$(sha256sum "$SRC/$f" | cut -d' ' -f1)"
  [ "$got" = "$sha" ] || { echo "$f: sha256 $got, expected $sha" >&2; exit 1; }
done <<'SUMS'
74f4107b93f77a805a59956e36778d68f6ab5a313a76289ff2b15c15cc8d5a2a f3411-v19/canonical.yaml
0d37e6911befa23e187f3a0a7b986509f38b0a01db7619f6c2631abd0da0df38 f3411-v22a/canonical.yaml
63482b2a665ecd836b269028a13b19adfde7a5c32b01301c168d87ca3313dd15 f3548-v21/utm.yaml
baa31e8758fd49e15c8c1f871fdbc5231abb126ba2780bb213923808d8357774 api-f3411-v19/api.py
138541ba2f797c78985bfa2136cdfa6cd511a6f071d9ecd8871636084e5805ed api-f3411-v22a/api.py
541efac9f3440434c51a9fbb9f1ac283d9ee9c72df838edd99ccff805ca354ac api-f3548-v21/api.py
SUMS
LICENSE="Apache-2.0: restated from InterUSS interuss/uas_standards api.py (Apache-2.0); the upstream OpenAPI file states no licence and is a cross-check (PROVENANCE.md)"
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
cd "$W"

# api <file> <format prefix> <module prefix> <title> <source>; then pairs of
# <format suffix> <module suffix> <schema> [options...] via one()
api_file="" api_fmt="" api_mod="" api_title="" api_src=""
one() {
  local sfx="$1" msfx="$2" schema="$3"
  shift 3
  local fmt="$api_fmt-$sfx"
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$api_file" \
      --message "$schema=$api_file#/components/schemas/$schema" \
      --format "$fmt" --module "$api_mod$msfx" --title "$api_title; schema $schema" \
      --license "$LICENSE" --source "$api_src" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

# --- ASTM F3411 network Remote ID: v19 and v22a share their schema names
rid() {
  local ver="$1" ts="$2"
  api_file="$SRC/f3411-$ver/canonical.yaml"; api_fmt="astm-f3411-$ver"; api_mod="rid${ver//[^0-9a-z]/}"
  local flight=(--map "RIDFlight:id=uid" --map "RIDFlight:current_state.position.lat=lat"
    --map "RIDFlight:current_state.position.lng=lon" --map "RIDFlight:current_state.position.alt=hae"
    --map "RIDFlight:current_state.$ts=time_ms" --map "RIDFlight:current_state.track=course"
    --map "RIDFlight:current_state.speed=speed_ms" --map "RIDFlight:current_state.vertical_speed=track.vel_up_ms"
    --map "RIDFlight:simulated=track.simulated"
    --evidence "RIDFlight:id=api.py RIDFlight.id: the flight's identifier"
    --evidence "RIDFlight:current_state.position.lat=api.py Latitude: degrees north on the WGS 84 ellipsoid"
    --evidence "RIDFlight:current_state.position.lng=api.py Longitude: degrees east on the WGS 84 ellipsoid"
    --evidence "RIDFlight:current_state.position.alt=api.py RIDAircraftPosition.alt: height above the WGS 84 ellipsoid, metres"
    --evidence "RIDFlight:current_state.$ts=api.py RIDAircraftState.timestamp: the time the state was valid, RFC 3339"
    --evidence "RIDFlight:current_state.track=api.py RIDAircraftState.track: ground track angle from true north, degrees clockwise"
    --evidence "RIDFlight:current_state.speed=api.py RIDAircraftState.speed: ground speed, metres per second"
    --evidence "RIDFlight:current_state.vertical_speed=api.py RIDAircraftState.vertical_speed: speed upward, metres per second"
    --evidence "RIDFlight:simulated=api.py RIDFlight.simulated: the flight is simulated")
  if [ "$ver" = v22a ]; then
    # canonical.yaml of v22a states the unknown values (alt -1000, track 361, speed 255); they are
    # absent on the shared lines and kept by the raw keys. lat/lon 0,0 is a pair: not stated here.
    flight+=(--absent "RIDFlight:current_state.position.alt=-1000" --absent "RIDFlight:current_state.track=361"
      --absent "RIDFlight:current_state.speed=255")
  fi
  one flight fl RIDFlight "${flight[@]}" --cross "$XG"
  one get-flights-response gfr GetFlightsResponse
  one flight-details fd RIDFlightDetails --map "RIDFlightDetails:id=uid" \
    --evidence "RIDFlightDetails:id=api.py RIDFlightDetails.id: the identifier of the flight the details belong to"
  one get-flight-details-response gfdr GetFlightDetailsResponse
  one isa isa IdentificationServiceArea
  one create-isa-parameters cisa CreateIdentificationServiceAreaParameters
  one put-isa-response pisa PutIdentificationServiceAreaResponse
  one isa-notification isan PutIdentificationServiceAreaNotificationParameters
  one subscription sub Subscription
  one create-subscription-parameters csub CreateSubscriptionParameters
  one put-subscription-response psub PutSubscriptionResponse
  one error-response err ErrorResponse
}
api_title="ASTM F3411-19 network Remote ID OpenAPI (uastech/standards remoteid/canonical.yaml, as pinned by interuss/uas_standards v4.4.0)"
api_src="https://github.com/uastech/standards at commit 228b301be1f4466df9b014f20b515665861a8e67, remoteid/canonical.yaml (submodule interfaces/astm/f3411/v19 of interuss/uas_standards v4.4.0)"
rid v19 timestamp
api_title="ASTM F3411-22a network Remote ID OpenAPI (uastech/standards remoteid/canonical.yaml, as pinned by interuss/uas_standards v4.4.0)"
api_src="https://github.com/uastech/standards at commit dd4016b09fc8cb98f30c2a17b5a088fb2995ab54, remoteid/canonical.yaml (submodule interfaces/astm/f3411/v22a of interuss/uas_standards v4.4.0)"
rid v22a timestamp.value

# --- ASTM F3548-21 strategic coordination
api_file="$SRC/f3548-v21/utm.yaml"; api_fmt="astm-f3548-v21"; api_mod="utm21"
api_title="ASTM F3548-21 UTM USS-DSS and USS-USS OpenAPI (interuss/astm-utm-protocol utm.yaml, as pinned by interuss/uas_standards v4.4.0)"
api_src="https://github.com/interuss/astm-utm-protocol at commit 1d3d8fbe75414e23d7e19ce35955770bea5e413f, utm.yaml (submodule interfaces/astm/f3548/v21 of interuss/uas_standards v4.4.0)"
# tel <kind> <prefix>: the telemetry bindings and their evidence, in the project's words
tel() {
  local k="$1" p="$2"
  TEL=(--map "$k:${p}time_measured.value=time_ms" --map "$k:${p}position.latitude=lat"
    --map "$k:${p}position.longitude=lon" --map "$k:${p}position.altitude.value=hae"
    --map "$k:${p}velocity.speed=speed_ms" --map "$k:${p}velocity.track=course"
    --evidence "$k:${p}time_measured.value=api.py VehicleTelemetry.time_measured: the time the telemetry was measured, RFC 3339"
    --evidence "$k:${p}position.latitude=api.py Latitude: degrees north on the WGS 84 ellipsoid"
    --evidence "$k:${p}position.longitude=api.py Longitude: degrees east on the WGS 84 ellipsoid"
    --evidence "$k:${p}position.altitude.value=api.py Altitude: reference W84 (WGS 84) only, units metres only"
    --evidence "$k:${p}velocity.speed=api.py Velocity.speed: ground speed, metres per second only"
    --evidence "$k:${p}velocity.track=api.py Velocity.track: ground track angle from true north, degrees east of north"
    --absent "$k:${p}velocity.track=360")      # utm.yaml Velocity.track: 360 is invalid, no value or unknown
}
one operational-intent-reference oir OperationalIntentReference --map "OperationalIntentReference:id=uid" \
  --evidence "OperationalIntentReference:id=api.py OperationalIntentReference.id: the identifier of the operational intent"
one put-operational-intent-reference-parameters poir PutOperationalIntentReferenceParameters
one change-operational-intent-reference-response coir ChangeOperationalIntentReferenceResponse
one query-operational-intent-reference-parameters qoir QueryOperationalIntentReferenceParameters
one query-operational-intent-reference-response qoirr QueryOperationalIntentReferenceResponse
one operational-intent oi OperationalIntent --map "OperationalIntent:reference.id=uid" \
  --evidence "OperationalIntent:reference.id=api.py OperationalIntentReference.id: the identifier of the operational intent"
one get-operational-intent-details-response goid GetOperationalIntentDetailsResponse
one put-operational-intent-details-parameters poid PutOperationalIntentDetailsParameters
one constraint-reference cr ConstraintReference --map "ConstraintReference:id=uid" \
  --evidence "ConstraintReference:id=api.py ConstraintReference.id: the identifier of the constraint"
one constraint con Constraint --map "Constraint:reference.id=uid" \
  --evidence "Constraint:reference.id=api.py ConstraintReference.id: the identifier of the constraint"
one get-constraint-details-response gcd GetConstraintDetailsResponse
tel VehicleTelemetry ""
one vehicle-telemetry vt VehicleTelemetry "${TEL[@]}" --cross "$XG"
tel GetOperationalIntentTelemetryResponse "telemetry."
one get-operational-intent-telemetry-response goit GetOperationalIntentTelemetryResponse "${TEL[@]}" \
  --map "GetOperationalIntentTelemetryResponse:operational_intent_id=uid" \
  --evidence "GetOperationalIntentTelemetryResponse:operational_intent_id=api.py: the identifier of the operational intent"
one uss-availability-status uas UssAvailabilityStatus
one set-uss-availability-parameters suas SetUssAvailabilityStatusParameters
one uss-availability-response uasr UssAvailabilityStatusResponse
one error-report erep ErrorReport
one uss-log-set ulog USSLogSet
one airspace-conflict-response acr AirspaceConflictResponse
one subscription sub Subscription
one put-subscription-parameters psub PutSubscriptionParameters
one error-response err ErrorResponse

exit "$STATUS"
