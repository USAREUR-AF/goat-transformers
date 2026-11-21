#!/usr/bin/env bash
# tls-smoke.sh: goat-xf-pipe-zenoh reaches a Zenoh peer over TLS, and only TLS.
#
#   adapters/zenoh/tests/tls-smoke.sh <goat-xf-pipe-zenoh> <packs dir>
#
# 1. The binary holds Zenoh's TLS link (a cheap first guard: without the
#    `transport_tls` feature the session fails at run time with
#    "Unable to connect to any of [tls/...]").
# 2. A self-signed CA and a server certificate for 127.0.0.1 and localhost
#    are made with openssl in a temporary directory.
# 3. One goat-xf-pipe-zenoh listens on tls/127.0.0.1:<port> (peer mode, no
#    other endpoint, multicast scouting off) and writes what it receives, as
#    GeoJSON, to a file.
# 4. A second one connects to that endpoint only, trusting only the CA, and
#    publishes Cursor on Target messages read from standard input.
# 5. At least one converted message must arrive within the time limit.
#
# Needs: openssl, python3. Exit 0 on success, 1 on failure.
set -euo pipefail

bin="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
packs="$(cd "$2" && pwd)"
port="${TLS_SMOKE_PORT:-17447}"
work="$(mktemp -d)"
listener_pid=""
cleanup() {
  if [ -n "$listener_pid" ]; then kill "$listener_pid" 2>/dev/null || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

fail() { echo "tls-smoke: FAIL: $*" >&2; for f in "$work"/*.err; do [ -f "$f" ] && { echo "--- $f" >&2; tail -20 "$f" >&2; }; done; exit 1; }

# 1. the TLS link is in the binary
if ! grep -a -q -E 'zenoh[-_]link[-_]tls' "$bin"; then
  fail "$bin holds no zenoh TLS link (built without the transport_tls feature?)"
fi
echo "tls-smoke: the binary holds the zenoh TLS link"

# 2. certificates
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=tls-smoke CA" \
  -keyout "$work/ca.key" -out "$work/ca.pem" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=localhost" \
  -keyout "$work/server.key" -out "$work/server.csr" 2>/dev/null
printf 'subjectAltName=IP:127.0.0.1,DNS:localhost\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' > "$work/ext.cnf"
openssl x509 -req -in "$work/server.csr" -CA "$work/ca.pem" -CAkey "$work/ca.key" -CAcreateserial \
  -days 2 -extfile "$work/ext.cnf" -out "$work/server.pem" 2>/dev/null

cat > "$work/listener.json5" <<EOF
{
  mode: "peer",
  listen: { endpoints: ["tls/127.0.0.1:$port"] },
  connect: { endpoints: [] },
  scouting: { multicast: { enabled: false }, gossip: { enabled: false } },
  transport: { link: { tls: {
    listen_private_key: "$work/server.key",
    listen_certificate: "$work/server.pem",
  } } },
}
EOF
cat > "$work/talker.json5" <<EOF
{
  mode: "peer",
  listen: { endpoints: [] },
  connect: { endpoints: ["tls/127.0.0.1:$port"] },
  scouting: { multicast: { enabled: false }, gossip: { enabled: false } },
  transport: { link: { tls: {
    root_ca_certificate: "$work/ca.pem",
    verify_name_on_connect: true,
  } } },
}
EOF

# 3. the listener
"$bin" --packs "$packs" --packs-only --from-format cot-xml \
  --in "zenoh:tls-smoke/cot?config=$work/listener.json5" \
  --to-format geojson --out-frame newline --out "file:$work/received.geojson" \
  --status-every 0 > "$work/listener.out" 2> "$work/listener.err" &
listener_pid=$!
for _ in $(seq 1 50); do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then break; fi
  kill -0 "$listener_pid" 2>/dev/null || fail "the listener exited"
  sleep 0.2
done
(exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null || fail "nothing listens on 127.0.0.1:$port"
echo "tls-smoke: a peer listens on tls/127.0.0.1:$port"

# 4. the talker: one message every 0.3 s, so the first arrives once the session is up
msg="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["input"])' "$packs/cot-xml/vectors/01-track-to-geojson.json")"
( for _ in $(seq 1 30); do echo "$msg"; sleep 0.3; done ) | \
  timeout 30 "$bin" --packs "$packs" --packs-only --from-format cot-xml \
    --in stdin: --in-frame newline \
    --to-format cot-xml --out "zenoh:tls-smoke/cot?config=$work/talker.json5" \
    --status-every 0 > "$work/talker.out" 2> "$work/talker.err" || fail "the talker failed (exit $?)"

# 5. something arrived, converted
sleep 1
if ! grep -q '"type":"Feature"' "$work/received.geojson" 2>/dev/null; then
  fail "no message arrived over tls/127.0.0.1:$port"
fi
echo "tls-smoke: $(grep -c '"type":"Feature"' "$work/received.geojson") message(s) arrived over TLS and were converted to GeoJSON"
echo "tls-smoke: ok"
