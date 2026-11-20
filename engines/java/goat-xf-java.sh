#!/usr/bin/env bash
# Start the Java engine's command-line tool (spec Version 0.23) from the jar that ./build.sh writes.
# Usage: engines/java/goat-xf-java.sh <subcommand> [<option> <value>]...
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
jars=("$here"/build/goat-transformers-*.jar)
if [ ! -f "${jars[0]}" ]; then
  echo "goat-xf-java: no jar under $here/build; run engines/java/build.sh first" >&2
  exit 1
fi
# The command line is UTF-8 (spec 0.23): the JVM decodes its arguments with the locale's character set.
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
  *UTF-8*|*utf8*|*UTF8*|*utf-8*) ;;
  *) export LC_ALL=C.UTF-8 ;;
esac
exec java -jar "${jars[0]}" "$@"
