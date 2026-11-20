#!/bin/sh
# The Erlang engine's command-line tool (engine-spec Version 0.23).
# Build first with ./build.sh; then, from anywhere:
#   engines/erlang/goat-xf.sh <subcommand> [<option> <value>]...
# Every argument after -extra reaches gt_cli unread by erl.
dir=$(dirname "$0")
exec erl -noshell -pa "$dir/ebin" -s gt_cli main -extra "$@"
