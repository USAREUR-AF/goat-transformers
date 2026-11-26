package goatxf

import (
	"errors"
	"testing"
)

// A carrier pack whose kind p holds an `inner` line and no `run` line, and
// whose kind r holds a `run` line of the same inner pack.
const runKeptProbe = `format     run-kept-probe
version    0.94.0
distribution public
source  "goat-transformers spec/engine-spec.md (synthetic probe format, no external standard)"
uses       probe
wire       bits
layout     sequential
bit_order  msb
kind p
when 8 1
length 8
inner conformance-run-in-ping
end
kind r
when 8 2
inner conformance-run-in-ping run
`

// TestRunKeptKind pins 0.94 ruling 7, carrier to carrier pack: to a kind
// without a run line the joined entity is checked as convert, ruling 4
// included, so the one message's inner kind is kept; to a kind with a
// run line it is not.
func TestRunKeptKind(t *testing.T) {
	e, err := LoadPacksOnly("../../model", "../../packs", DistControlled, []string{"conformance-run-c-ping", "conformance-run-in-ping", "conformance-run-only-ping"})
	if err != nil {
		t.Fatal(err)
	}
	if err := e.LoadPack([]byte(runKeptProbe), "run-kept-probe"); err != nil {
		t.Fatal(err)
	}
	// Kind without a run line: the same as convert from the inner pack.
	rs, err := e.ConvertRun("conformance-run-c-ping", "run-kept-probe", []byte("010109"), nil)
	if err != nil || len(rs) != 1 || rs[0].Err != nil || string(rs[0].Bytes) != "010101" {
		t.Fatalf("convert_run to a kind without a run line: %v %+v", err, rs)
	}
	out, err := e.Convert("conformance-run-in-ping", "run-kept-probe", []byte("01"))
	if err != nil || string(out) != "010101" {
		t.Fatalf("convert from the inner pack: %s %v", out, err)
	}
	// Kind with a run line: the first message's inner kind is not kept.
	_, err = e.ConvertRun("conformance-run-c-ping", "conformance-run-only-ping", []byte("010109"), nil)
	var ge *Error
	if !errors.As(err, &ge) || ge.Kind != ErrNoKind {
		t.Fatalf("convert_run to a kind with a run line: want no-kind, got %v", err)
	}
}
