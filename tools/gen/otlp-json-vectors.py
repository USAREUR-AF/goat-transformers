#!/usr/bin/env python3
"""Vectors of the otlp-json-* packs from the OTLP JSON examples the specification publishes.

The inputs are the files examples/trace.json, metrics.json, logs.json and events.json of
github.com/open-telemetry/opentelemetry-proto at commit d31f7acf (Apache-2.0), read from
<sources>/examples/ and checked against their SHA-256. The expected text is the input in the
canonical form of the json wire (engine-spec 0.5 "Canonical output" and 0.7): members in the
order of the pack's lines, which is the declaration order of the fields in the .proto files; no
whitespace; inside arrays only what the pack maps, so the `values` of an ArrayValue and of a
KeyValueList (where AnyValue would stand inside itself) are dropped and the emptied object is not
written. The order is read from the .proto files with proto2pack's reader; no engine is run.

    python3 -I tools/gen/otlp-json-vectors.py --sources <checkout of opentelemetry-proto> [--check] [<checkout>]
"""
import argparse
import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import proto2pack  # noqa: E402

COMMIT = "d31f7acf9d461fd0601077de516ac1eb7051422f"
EXAMPLES = {
    "trace.json": ("f8f2870852b247f734a53ca7f022d4d942bd29732df54440494948af181bd373",
                   "otlp-json-export-trace-request", "collector.trace.v1.ExportTraceServiceRequest"),
    "metrics.json": ("b40977696f743f556b9556eb5e716425c4c1b4369f078a3504615e605cf21bff",
                     "otlp-json-export-metrics-request", "collector.metrics.v1.ExportMetricsServiceRequest"),
    "logs.json": ("5da7283e6772026408341cb45054c7c90cdc9674bd083bcfa6b586341dc3f7a4",
                  "otlp-json-export-logs-request", "collector.logs.v1.ExportLogsServiceRequest"),
    "events.json": ("76e398b8f285ae8349085c4535d94b14f0d1a4028f3c8712a59b10dd1bdb48ae",
                    "otlp-json-export-logs-request", "collector.logs.v1.ExportLogsServiceRequest"),
}
PROTO = ["collector/trace/v1/trace_service.proto", "collector/metrics/v1/metrics_service.proto",
         "collector/logs/v1/logs_service.proto", "common/v1/common.proto", "resource/v1/resource.proto",
         "trace/v1/trace.proto", "metrics/v1/metrics.proto", "logs/v1/logs.proto"]


def jname(name):
    parts = name.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def canon(msg, obj, chain):
    """The members of `obj` (a JSON object of message `msg`) in declaration order; members that the
    pack has no line for are dropped (every OTLP object here sits inside an array)."""
    out = {}
    for f in msg.fields:
        jn = jname(f.name)
        if jn not in obj or f.kind in ("map", "group"):
            continue
        v = obj[jn]
        if f.kind == "message":
            if f.ref in chain:
                continue
            if f.label == "repeated":
                out[jn] = [canon(f.ref, x, chain + [f.ref]) for x in v]
            else:
                sub = canon(f.ref, v, chain + [f.ref])
                if sub:
                    out[jn] = sub
        else:
            out[jn] = v
    return out


def build(out, sources):
    schema = proto2pack.load_schema([os.path.join(sources, "opentelemetry", "proto", p) for p in PROTO], comments=False)
    written = {}
    for n, (fname, (sha, fmt, env)) in enumerate(sorted(EXAMPLES.items()), 1):
        path = os.path.join(sources, "examples", fname)
        with open(path, "rb") as fh:
            data = fh.read()
        if hashlib.sha256(data).hexdigest() != sha:
            raise SystemExit("otlp-json-vectors: %s is not the file of commit %s" % (fname, COMMIT))
        text = data.decode("utf-8")
        msg = schema.messages["opentelemetry.proto." + env]
        expect = json.dumps(canon(msg, json.loads(text), [msg]), separators=(",", ":"), ensure_ascii=False)
        vec = {"name": "%s-example-%s" % (fmt, fname[:-5]), "from": fmt, "to": fmt, "input": text, "expect": expect,
               "source": "published: opentelemetry-proto %s examples/%s (Apache-2.0)" % (COMMIT[:8], fname),
               "reference": "expected text by tools/gen/otlp-json-vectors.py: the canonical member order of the json "
                            "wire; the values of ArrayValue and KeyValueList are not carried"}
        out.write("packs/%s/vectors/%02d-example-%s" % (fmt, n, fname), json.dumps(vec, indent=2, ensure_ascii=False) + "\n")
        written[fmt] = written.get(fmt, 0) + 1
    return written


def main(argv=None):
    p = argparse.ArgumentParser(prog="otlp-json-vectors", description=__doc__.split("\n")[0])
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    genio.add_arguments(p, default_out=here)
    p.add_argument("--sources", required=True, help="a checkout of opentelemetry-proto at the commit")
    p.add_argument("checkout", nargs="?")
    a = p.parse_args(argv)
    out = genio.Output(a.checkout or a.out, check=a.check)
    written = build(out, a.sources)
    if not a.check:
        for k, v in sorted(written.items()):
            print(k, v)
    return out.report("otlp-json-vectors")


if __name__ == "__main__":
    sys.exit(main())
