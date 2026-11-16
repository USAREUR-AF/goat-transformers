#!/usr/bin/env bash
# Compile the Java engine with javac (JDK 17, standard library only), run every pack vector plus unit checks, and
# write build/goat-transformers-<version>.jar: the engine classes and nothing else, no dependencies.
# Usage: ./build.sh [PACKS_DIR]   (default ../../packs)
set -euo pipefail
cd "$(dirname "$0")"
packs="${1:-../../packs}"
version=0.8.0
rm -rf build
mkdir -p build/main build/test
find src/main/java -name '*.java' > build/main-sources.txt
find src/test/java -name '*.java' > build/test-sources.txt
javac --release 17 -Xlint:all -Werror -d build/main @build/main-sources.txt
javac --release 17 -Xlint:all -Werror -cp build/main -d build/test @build/test-sources.txt
java -cp build/main:build/test goat.transformers.TestRunner "$packs"
# The jar: `java -jar` runs the command-line tool (goat.transformers.Cli); on a class path it is the library.
printf '%s\n' \
  'Implementation-Title: goat-transformers' \
  "Implementation-Version: $version" \
  'Automatic-Module-Name: goat.transformers' \
  'Main-Class: goat.transformers.Cli' > build/manifest.txt
jar --create --file "build/goat-transformers-$version.jar" --manifest build/manifest.txt -C build/main .
echo "jar: build/goat-transformers-$version.jar"
