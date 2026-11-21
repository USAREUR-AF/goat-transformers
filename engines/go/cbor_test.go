//go:build !goat_wires || (goat_wire_cbor && goat_wire_tlv)

package goatxf

import (
	"math/rand"
	"strings"
	"testing"
	"time"
)

// TestCBORMalformed holds hostile inputs of the cbor wire (spec 0.28,
// "Reading a message") that no vector pins: nesting far past the depth limit
// through arrays, maps and tags, declared lengths near 2^64 in every head
// that states one, and indefinite items that never end. Each must fail with
// malformed-wire, at once, without a panic.
func TestCBORMalformed(t *testing.T) {
	eng, err := LoadPacksOnly(DefaultModelsDir(packsDir), packsDir, DistControlled, []string{"conformance-cbor", "conformance-cbor-array", "conformance-cbor-group"})
	if err != nil {
		t.Fatal(err)
	}
	const pack = "conformance-cbor"
	// at10 is a message of kind plain whose member 10, residue, is x.
	at10 := func(x string) string { return "a200010a" + x }
	deep := 200000
	cases := []struct {
		name, pack, input string
		ok                bool
	}{
		{"plain message", pack, at10("00"), true},
		{"deep arrays", pack, at10(strings.Repeat("81", deep) + "00"), false},
		{"deep maps", pack, at10(strings.Repeat("a100", deep) + "00"), false},
		{"deep tags", pack, at10(strings.Repeat("c1", deep) + "00"), false},
		{"deep indefinite arrays without a break", pack, at10(strings.Repeat("9f", deep)), false},
		{"deep indefinite maps without a break", pack, at10(strings.Repeat("bf00", deep)), false},
		{"deep tags on the top item", pack, strings.Repeat("d818", deep) + "a10001", false},
		{"64 levels of tags and arrays", pack, at10(strings.Repeat("c1", 31) + strings.Repeat("81", 32) + "00"), true},
		{"byte string of 2^64-1 bytes", pack, at10("5bffffffffffffffff00"), false},
		{"text string of 2^64-1 bytes", pack, at10("7bffffffffffffffff00"), false},
		{"array of 2^64-1 elements", pack, at10("9bffffffffffffffff00"), false},
		{"map of 2^64-1 members", pack, at10("bbffffffffffffffff0000"), false},
		{"map of 2^63 members", pack, at10("bb80000000000000000000"), false},
		{"top map of 2^32-1 members", pack, "baffffffff0001", false},
		{"chunk of 2^64-1 bytes", pack, at10("5f5bffffffffffffffff00ff"), false},
		{"array of 3 elements with 2 left", pack, at10("830102"), false},
		{"map of 2 members with 3 bytes left", pack, at10("a2010203"), false},
		{"tag head cut", pack, at10("db0000"), false},
		{"tag with additional information 31", pack, at10("df00"), false},
		{"integer with additional information 31", pack, at10("1f"), false},
		{"unending indefinite array", pack, at10("9f" + strings.Repeat("01", 10000)), false},
		{"unending indefinite map", pack, at10("bf" + strings.Repeat("0101", 10000)), false},
		{"unending indefinite byte string", pack, at10("5f" + strings.Repeat("4101", 10000)), false},
		{"unending indefinite text string", pack, at10("7f" + strings.Repeat("6161", 10000)), false},
		{"indefinite map with a key and no value", pack, at10("bf00ff"), false},
		{"indefinite chunk inside an indefinite string", pack, at10("5f5fffff"), false},
		{"text chunk inside a byte string", pack, at10("5f6161ff"), false},
		{"indefinite byte string read", pack, at10("5f4101ff"), true},
		{"break alone", pack, "ff", false},
		{"empty input", pack, "", false},
		{"two-byte simple 31", pack, at10("f81f"), false},
		{"two-byte simple 32", pack, at10("f820"), true},
		{"half NaN with a payload as residue", pack, at10("f97e01"), true},
		{"double NaN as residue", pack, at10("fb7ff8000000000001"), true},
		{"top array of 65537 null positions, the last past 65535", "conformance-cbor-array", "d2" + "9a00010001" + strings.Repeat("f6", 65537), true},
		{"group of 100001 items over the limit", "conformance-cbor-group", "82" + "9a000186a1" + strings.Repeat("00", 100001) + "40", false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			start := time.Now()
			_, err, panicked := convertGuarded(eng, c.pack, c.pack, []byte(c.input), nil)
			switch {
			case panicked != "":
				t.Fatalf("panic: %s", panicked)
			case c.ok && err != nil:
				t.Errorf("convert: %v, want it to convert", err)
			case !c.ok && !IsKind(err, ErrMalformedWire):
				t.Errorf("convert: got %v, want %s", err, ErrMalformedWire)
			}
			if d := time.Since(start); d > 5*time.Second {
				t.Errorf("took %v", d)
			}
		})
	}
}

// TestCBORRandomBytes feeds random bytes, and random bytes after a valid
// head, to every cbor pack: no input may panic, and every error names a
// kind.
func TestCBORRandomBytes(t *testing.T) {
	eng, err := LoadPacksOnly(DefaultModelsDir(packsDir), packsDir, DistControlled, []string{"conformance-cbor", "conformance-cbor-array", "conformance-cbor-kinds", "conformance-cbor-group", "cose-sign1", "dtn-bpv7"})
	if err != nil {
		t.Fatal(err)
	}
	rng := rand.New(rand.NewSource(0xcb0e))
	const hexDigits = "0123456789abcdef"
	heads := []string{"", "a2", "bf", "9f", "d2", "d284", "82", "a10001", "a3000109"}
	for _, p := range eng.Formats() {
		for k := 0; k < 3000; k++ {
			n := rng.Intn(40)
			var b strings.Builder
			b.WriteString(heads[rng.Intn(len(heads))])
			for i := 0; i < 2*n; i++ {
				b.WriteByte(hexDigits[rng.Intn(16)])
			}
			in := b.String()
			_, err, panicked := convertGuarded(eng, p.Format, p.Format, []byte(in), nil)
			if panicked != "" {
				t.Fatalf("%s: input %q: panic: %s", p.Format, in, panicked)
			}
			if err != nil && !namedKind.MatchString(err.Error()) {
				t.Fatalf("%s: input %q: error %q names no kind", p.Format, in, err)
			}
		}
	}
}
