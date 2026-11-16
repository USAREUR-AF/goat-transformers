#!/usr/bin/env bash
# Compile the Java engine with javac (JDK 17, standard library only) and run every pack vector plus unit checks.
# Usage: ./build.sh [PACKS_DIR]   (default ../../packs)
set -euo pipefail
cd "$(dirname "$0")"
packs="${1:-../../packs}"
rm -rf build
mkdir -p build/main build/test
find src/main/java -name '*.java' > build/main-sources.txt
find src/test/java -name '*.java' > build/test-sources.txt
javac --release 17 -Xlint:all -Werror -d build/main @build/main-sources.txt
javac --release 17 -Xlint:all -Werror -cp build/main -d build/test @build/test-sources.txt
java -cp build/main:build/test goat.transformers.TestRunner "$packs"
