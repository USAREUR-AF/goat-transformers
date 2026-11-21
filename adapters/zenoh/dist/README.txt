goat-xf-pipe-zenoh @VERSION@, Linux arm64 (aarch64-unknown-linux-gnu)
========================================================================

goat-xf-pipe with the zenoh: scheme: it subscribes to a Zenoh key
expression, converts each message from one format to another with the
goat-transformers engine, and publishes the result (or writes it to any
other output goat-xf-pipe knows). Built for NVIDIA Jetson Thor and Orin
(glibc 2.35 or later).

This directory holds:

  goat-xf-pipe-zenoh   the program
  packs/  model/       the formats and the shared model, from tag @TAG@
                       (without the conformance vectors)
  LICENSE  NOTICE      the licence and the third-party notices
  LICENSES/ licences.toml licences.json LICENSING.md REUSE.toml
                       the licence of every pack and model module

Run (from this directory):

  ./goat-xf-pipe-zenoh --packs packs --packs-only \
    --from-format cot-xml --in 'zenoh:capture/cot/**' \
    --to-format geojson --out zenoh:converted/geojson \
    --metrics :9464

  --packs-only loads only the formats named on the command line, which
  starts in well under a second. A Zenoh router or peer is reached with
  ?mode=client&connect=tcp/<host>:7447 on a zenoh: URI, or with
  ?config=<file>. Run ./goat-xf-pipe-zenoh --help for every option.

Prometheus (with --metrics <addr>; GET /metrics):

  goat_xf_pipe_messages_in_total{format}          messages received
  goat_xf_pipe_messages_out_total{format}         messages converted and sent
  goat_xf_pipe_errors_total{stage,format,kind}    stage decode, encode,
                                                  deliver or source
  goat_xf_pipe_uptime_seconds

Exit status: 0 every message converted and delivered; 1 stopped on a
failure; 2 the command line or the configuration is wrong; 3 the input ended
and some messages failed and were skipped.

Verify the download: sha256sum -c SHA256SUMS, and
gh attestation verify goat-xf-pipe-zenoh_@VERSION@_linux_arm64.tar.gz \
  --repo USAREUR-AF/goat-transformers
