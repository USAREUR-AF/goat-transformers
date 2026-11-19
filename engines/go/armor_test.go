package goatxf

import (
	"strings"
	"testing"
)

// Unit tests of spec 0.14 (six-bit armor) for the rulings no vector pins:
// what counts toward L (ruling 7), byte padding inside the message (ruling
// 8), nothing to write (ruling 9), and `sixbit` with `lsb` and `trim`.

// armorHead and armorSeqHead put every line that needs the wire after the
// `wire` line, and `layout sequential` before `bit_order` (ruling 5b of 0.11).
const armorHead = "version 0.14.0\ndistribution public\nsource s\nuses g\nwire bits\nword_bytes 1\nbit_order msb\narmor sixbit\n"
const armorSeqHead = "version 0.14.0\ndistribution public\nsource s\nuses g\nwire bits\nlayout sequential\nbit_order msb\narmor sixbit\n"

var armorPacks = []string{
	// An optional field with a default counts toward L.
	"format a-def\n" + armorHead + "field g.n 0:0:6 uint\nfield g.n2 0:6:6 uint optional\ndefault g.n2 5\n",
	// The same without the default: an absent optional field does not count.
	"format a-nodef\n" + armorHead + "field g.n 0:0:6 uint\nfield g.n2 0:6:6 uint optional\n",
	// A scope whose only line is an optional field.
	"format a-empty\n" + armorHead + "field g.n 0:0:6 uint optional\n",
	// A count locator counts toward L whether the list is present or not.
	"format a-count\n" + armorHead + "field g.n 0:0:6 uint\ngroup g.items 0:10 item 6 count 0:6:4\n  field g.n2 0:0:6 uint\nend\n",
	// A `length … bytes` block is still padded to a whole byte.
	"format a-seq\n" + armorSeqHead + "field g.n 6 uint\nlength 4 bytes\n  field g.n2 3 uint\nend\n",
	// sixbit with lsb and trim on hex.
	// `absent` on armored bits, a sixbit field included (0.14 ruling 12).
	"format a-abs-fix\n" + armorHead + "field g.n 0:0:6 uint\nfield g.name 0:6:12 sixbit absent 0\nfield g.n2 0:18:6 uint optional absent 63\n",
	"format a-abs-seq\n" + armorSeqHead + "field g.n 6 uint absent 63\nfield g.name 12 sixbit absent 0\n",
	"format a-lsb\nversion 0.14.0\ndistribution public\nsource s\nuses g\nwire bits\nword_bytes 3\nbit_order lsb\nfield g.name 0:0:18 sixbit trim\n",
}

func armorEngine(t *testing.T) *Engine {
	t.Helper()
	eng := New()
	for _, m := range []string{testCore, seqModule} {
		if err := eng.LoadModel([]byte(m), "model"); err != nil {
			t.Fatalf("LoadModel: %v", err)
		}
	}
	for _, p := range armorPacks {
		if err := eng.LoadPack([]byte(p), "pack"); err != nil {
			t.Fatalf("LoadPack: %v\n%s", err, p)
		}
	}
	return eng
}

func TestArmorRulings(t *testing.T) {
	eng := armorEngine(t)
	encode := func(format string, ent *Entity, want string) {
		t.Helper()
		out, err := eng.Encode(format, ent)
		if err != nil || string(out) != want {
			t.Errorf("%s: encode = %q, %v; want %q", format, out, err, want)
		}
	}
	// Ruling 7: n absent writes zeros; n2 is written from its default.
	encode("a-def", NewEntity(), "05")
	encode("a-nodef", NewEntity(), "0")
	// Ruling 9: nothing to write is the empty text, and it decodes.
	encode("a-empty", NewEntity(), "")
	if ent, err := eng.Decode("a-empty", []byte("")); err != nil || len(ent.Fields) != 0 {
		t.Errorf("a-empty: decode of empty text = %v, %v", ent, err)
	}
	// Ruling 7: the count at bits 6..9 counts with the list absent: L = 10.
	e := NewEntity()
	e.Fields["g.n"] = Value{Kind: KindInt, I: 1}
	encode("a-count", e, "10")
	// Ruling 8: 6 + 4 + 3 bits, the block padded to a byte: 18 bits,
	// 000001 000110 100000.
	e = NewEntity()
	e.Fields["g.n"] = Value{Kind: KindInt, I: 1}
	e.Fields["g.n2"] = Value{Kind: KindInt, I: 5}
	encode("a-seq", e, "16P")
	if out, err := eng.Convert("a-seq", "a-seq", []byte("16P")); err != nil || string(out) != "16P" {
		t.Errorf("a-seq: round trip = %q, %v", out, err)
	}
	// lsb: A (1), space (32), @ (0): 1 + 32*64 = 0x801, bytes 01 08 00. With
	// trim the trailing run of space and @ is removed.
	ent, err := eng.Decode("a-lsb", []byte("010800"))
	if err != nil || ent.Fields["g.name"].S != "A" {
		t.Errorf("a-lsb: decode = %v, %v; want A", ent, err)
	}
	if out, err := eng.Convert("a-lsb", "a-lsb", []byte("010800")); err != nil || string(out) != "010000" {
		t.Errorf("a-lsb: round trip = %q, %v; want 010000", out, err)
	}
	// Errors: a character outside the map, short input.
	for _, c := range []struct{ format, in, kind string }{
		{"a-def", "0 ", "malformed-wire"},
		{"a-def", "0X", "malformed-wire"},
		{"a-count", "1", "malformed-wire"},
		{"a-seq", "16", "malformed-wire"},
	} {
		if _, err := eng.Decode(c.format, []byte(c.in)); err == nil || !strings.HasPrefix(err.Error(), c.kind) {
			t.Errorf("%s: decode %q = %v, want %s", c.format, c.in, err, c.kind)
		}
	}
}

func TestArmorAbsent(t *testing.T) {
	eng := armorEngine(t)
	// The sentinel is read before the sixbit transform: "00" is raw 0, the
	// sentinel of g.name, not the empty string.
	for _, c := range []struct{ format, in string }{{"a-abs-fix", "100w"}, {"a-abs-seq", "w00"}} {
		ent, err := eng.Decode(c.format, []byte(c.in))
		if err != nil {
			t.Fatalf("%s: decode %q: %v", c.format, c.in, err)
		}
		if _, has := ent.Fields["g.name"]; has {
			t.Errorf("%s: decode %q: g.name = %v, want absent", c.format, c.in, ent.Fields["g.name"])
		}
		if out, err := eng.Convert(c.format, c.format, []byte(c.in)); err != nil || string(out) != c.in {
			t.Errorf("%s: round trip %q = %q, %v", c.format, c.in, out, err)
		}
	}
	// Absent keys write their first sentinel, the optional one included and
	// counted toward L.
	e := NewEntity()
	e.Fields["g.n"] = Value{Kind: KindInt, I: 1}
	if out, err := eng.Encode("a-abs-fix", e); err != nil || string(out) != "100w" {
		t.Errorf("a-abs-fix: encode = %q, %v; want 100w", out, err)
	}
	if out, err := eng.Encode("a-abs-seq", NewEntity()); err != nil || string(out) != "w00" {
		t.Errorf("a-abs-seq: encode = %q, %v; want w00", out, err)
	}
	// A value that is not a sentinel: A is padded to A@, values 1, 0.
	e.Fields["g.name"] = Value{Kind: KindString, S: "A"}
	if out, err := eng.Encode("a-abs-fix", e); err != nil || string(out) != "110w" {
		t.Errorf("a-abs-fix: encode = %q, %v; want 110w", out, err)
	}
	if ent, err := eng.Decode("a-abs-fix", []byte("110w")); err != nil || ent.Fields["g.name"].S != "A" {
		t.Errorf("a-abs-fix: decode 110w = %v, %v; want A", ent, err)
	}
}

// TestArmorLineChecks: how the armor lines meet the line checks of ruling 5b
// of 0.11. `armor` takes exactly one argument, counted as the line is read
// (ruling 13 of 0.14); `sixbit` is a known transform name, so on another wire
// it is bad-directive after the file, as is its length (ruling 14).
func TestArmorLineChecks(t *testing.T) {
	head := "format p\nversion 0.14.0\ndistribution public\nsource s\nuses g\n"
	for _, c := range []struct{ name, pack, kind string }{
		{"armor-no-argument", head + "wire bits\nword_bytes 1\nbit_order msb\narmor\nfield g.n 0:0:6 uint\n", "bad-directive"},
		{"armor-two-arguments", head + "wire bits\nword_bytes 1\nbit_order msb\narmor sixbit hex\nfield g.n 0:0:6 uint\n", "bad-directive"},
		{"armor-no-argument-then-bogus", head + "wire bits\nword_bytes 1\nbit_order msb\narmor\nbogus\n", "bad-directive"},
		{"sixbit-len-8-then-bogus", head + "wire bits\nword_bytes 1\nbit_order msb\nfield g.n 0:0:8 sixbit\nbogus\n", "unknown-directive"},
		{"armor-before-wire", head + "armor sixbit\nwire bits\nword_bytes 1\nbit_order msb\nfield g.n 0:0:6 uint\n", ""},
		{"sixbit-on-json-then-bogus", head + "wire json\nfield g.n a sixbit\nbogus\n", "unknown-directive"},
		{"sixbit-on-json", head + "wire json\nfield g.n a sixbit\n", "bad-directive"},
		{"sixbit-param", head + "wire bits\nword_bytes 1\nfield g.n 0:0:6 sixbit:2\nbogus\n", "bad-directive"},
	} {
		eng := New()
		for _, m := range []string{testCore, seqModule} {
			if err := eng.LoadModel([]byte(m), "model"); err != nil {
				t.Fatalf("LoadModel: %v", err)
			}
		}
		err := eng.LoadPack([]byte(c.pack), "pack")
		switch {
		case c.kind == "" && err != nil:
			t.Errorf("%s: load = %v, want success", c.name, err)
		case c.kind != "" && (err == nil || !strings.HasPrefix(err.Error(), c.kind)):
			t.Errorf("%s: load = %v, want %s", c.name, err, c.kind)
		}
	}
}
