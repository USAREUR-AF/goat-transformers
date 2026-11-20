#!/usr/bin/env bash
# The reduced-build check of spec 0.24 for the Java engine. From the repository root:
#
#   engines/java/reduced-check.sh [PACKS_DIR]      (default: the packs directory of this tree)
#
# It builds the jar with all eight wires and the jar with only xml, json and geojson (build.sh --wires), checks
# that the reduced jar holds no class of another wire's codec, runs goat.transformers.ReducedCheck on the reduced
# jar (conversion vectors on the three wires, one pack each on bits, protobuf, text, tlv and cbor refused as
# unknown-wire), and prints the size of both jars. Exits non-zero on any failure. It writes only under
# engines/java/build/reduced-check/.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
packs="${1:-$(cd "$here/../.." && pwd)/packs}"
wires=xml,json,geojson
out="$here/build/reduced-check"
version="$(sed -n 's/^version=//p' "$here/build.sh")"
jar="goat-transformers-$version.jar"

"$here/build.sh" --no-test --out "$out/full" > /dev/null
"$here/build.sh" --no-test --wires "$wires" --out "$out/reduced" > /dev/null

# The classes of every codec the three wires do not use must be absent from the reduced jar.
present="$(jar tf "$out/reduced/$jar" | grep -E '^goat/transformers/(BitsCodec|SeqCodec|BitsWire|ProtobufCodec|TextCodec|TlvCodec|CborCodec)[.$]' || true)"
if [ -n "$present" ]; then
  echo "FAIL the reduced jar holds classes of wires it was built without:" >&2
  echo "$present" >&2
  exit 1
fi
echo "reduced jar: no class of the bits, protobuf, text, tlv or cbor codecs"

# The check compiles against the reduced build only, then runs on the reduced jar.
rm -rf "$out/check"
mkdir -p "$out/check"
javac --release 17 -Xlint:all -Werror -cp "$out/reduced/main" -d "$out/check" \
  "$here/src/test/java/goat/transformers/Vectors.java" "$here/src/reduced/java/goat/transformers/ReducedCheck.java"
status=0
java -cp "$out/reduced/$jar:$out/check" goat.transformers.ReducedCheck "$packs" || status=$?

full_size=$(wc -c < "$out/full/$jar" | tr -d " ")
reduced_size=$(wc -c < "$out/reduced/$jar" | tr -d " ")
echo "jar size, all eight wires:       $full_size bytes ($out/full/$jar)"
echo "jar size, xml, json and geojson: $reduced_size bytes ($out/reduced/$jar), $(( 100 * reduced_size / full_size ))% of the full jar"
exit "$status"
