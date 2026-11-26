#!/bin/sh
# The single-wire check of the Java engine (spec 0.24, rulings 1a-1d; ruling 1 of 0.34). From the repository root:
#
#   sh engines/java/single-wire-check.sh                 (all eight wires)
#   GOAT_WIRES="json bits" sh engines/java/single-wire-check.sh
#
# For each wire it builds the jar with that wire alone and the jar with every wire but it (build.sh --wires, javac
# with -Xlint:all -Werror), then runs goat.transformers.ReducedCheck on the jar with the wire alone: every pack on
# another wire is unknown-wire with the wire named, and every conversion vector whose from and to packs both loaded,
# neither an outer pack, passes. It prints "<wire> alone: N conversion vectors run, N passed, 0 failed" per wire and
# stops, non-zero, at the first failure, with the failing step's output. It writes only under
# engines/java/build/single-wire/.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
packs="$root/packs"
all="xml geojson json bits protobuf text tlv cbor"
wires="${GOAT_WIRES:-$all}"
out="$here/build/single-wire"
version=$(sed -n 's/^version=//p' "$here/build.sh")
jar="goat-transformers-$version.jar"

for w in $wires; do
  case " $all " in
    *" $w "*) ;;
    *) echo "single-wire-check: \"$w\" is not a wire ($all)" >&2; exit 2 ;;
  esac
done

mkdir -p "$out"

# run LOG CMD...: run CMD with its output in LOG; on failure show LOG and stop with CMD's exit status.
run() {
  log="$1"
  shift
  status=0
  "$@" > "$log" 2>&1 || status=$?
  if [ "$status" != 0 ]; then
    cat "$log" >&2
    echo "FAIL (exit $status): $*" >&2
    exit "$status"
  fi
}

for w in $wires; do
  others=""
  for o in $all; do
    [ "$o" = "$w" ] && continue
    others="${others:+$others,}$o"
  done
  alone="$out/$w"
  without="$out/no-$w"
  logs="$out/logs-$w"
  rm -rf "$logs"
  mkdir -p "$logs"

  run "$logs/build-alone.log" bash "$here/build.sh" --wires "$w" --no-test --out "$alone"
  run "$logs/build-without.log" bash "$here/build.sh" --wires "$others" --no-test --out "$without"

  # The check compiles against the build with the wire alone, then runs on its jar.
  rm -rf "$alone-check"
  mkdir -p "$alone-check"
  run "$logs/check-javac.log" javac --release 17 -Xlint:all -Werror -cp "$alone/main" -d "$alone-check" \
    "$here/src/test/java/goat/transformers/Vectors.java" "$here/src/reduced/java/goat/transformers/ReducedCheck.java"
  run "$logs/check.log" java -Xmx6g -cp "$alone/$jar:$alone-check" goat.transformers.ReducedCheck "$packs"

  line=$(grep "^$w alone: " "$logs/check.log" || true)
  if [ -z "$line" ]; then
    cat "$logs/check.log" >&2
    echo "FAIL: the check of $w printed no \"$w alone:\" line" >&2
    exit 1
  fi
  grep "^packs on other wires refused" "$logs/check.log" | sed "s/^/  $w alone: /"
  echo "$line"
done
