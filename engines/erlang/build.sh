#!/bin/sh
# Compile the Erlang engine (OTP stdlib only, plain erlc).
set -eu
cd "$(dirname "$0")"
mkdir -p ebin
rm -f ebin/*.beam
erlc -Wall -o ebin src/*.erl
echo "built: $(ls ebin/*.beam | wc -l) modules"
