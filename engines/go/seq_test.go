package goatxf

import (
	"os"
	"path/filepath"
	"testing"
)

// Unit tests of spec 0.8: sequential binary layouts, the rulings of 0.7 the
// vectors now pin, and the model additions.

const seqHead = "version 0.8.0\ndistribution public\nsource s\nuses g\nwire bits\nlayout sequential\nbit_order msb\n"

// seqPack: a byte n; two presence bits and six unused bits; name by p.1 and
// x by p.2 on the same byte as an `also`; an optional chain; a counted list
// whose items select a kind; the length of the whole message last.
const seqPack = "format sq\n" + seqHead + `field g.n 8 uint
presence p 2
pad 6
if p.1
  field g.name 16 ascii
end
if p.2
  length 8 bits
    field g.n2 4 uint
    also  g.n3 via t
  end
  align 8
end
opt
  pad 7
  chain
    field g.c1 7 uint
    fx
    field g.c2 7 uint
    fx
  end
end
align 8
group g.items count 8
  field g.n 4 uint
  kind small
  when 4 1
  requires g.n2
  field g.n2 8 uint
  kind none
  when 4 0
end
map t 1 100
`

const seqModule = `module g
version 0.1.0
distribution public
source "unit tests"
key name string -
key n int -
key n2 int -
key n3 int -
key c1 int -
key c2 int -
key x float -
list items
list subs
list nums
`

func seqEngine(t *testing.T) *Engine {
	t.Helper()
	eng := New()
	for _, m := range []string{testCore, seqModule} {
		if err := eng.LoadModel([]byte(m), "model"); err != nil {
			t.Fatalf("LoadModel: %v", err)
		}
	}
	if err := eng.LoadPack([]byte(seqPack), "pack"); err != nil {
		t.Fatalf("LoadPack: %v", err)
	}
	return eng
}

func TestSequentialRoundTripAndPresence(t *testing.T) {
	eng := seqEngine(t)
	// n=5; p.1 and p.2; name "ok"; block of 4 bits holding 1; opt with a
	// chain of two parts; two items, one of each kind.
	in := "05c06f6b0410" + "800b0c" + "02" + "3109" + "70"
	ent, err := eng.Decode("sq", []byte(in))
	if err != nil {
		t.Fatal(err)
	}
	for key, want := range map[string]string{"g.n": "5", "g.name": "ok", "g.n2": "1", "g.n3": "100", "g.c1": "5", "g.c2": "6"} {
		if got := ent.Fields[key].String(); got != want {
			t.Errorf("%s = %q, want %q", key, got, want)
		}
	}
	items, ok := ent.List("g.items")
	if !ok || len(items) != 2 {
		t.Fatalf("g.items: %d item(s), present %v", len(items), ok)
	}
	if items[0].Kind != (EntityKind{Format: "sq", Name: "small"}) || items[1].Kind.Name != "none" {
		t.Errorf("item kinds = %v, %v", items[0].Kind, items[1].Kind)
	}
	if items[0].Fields["g.n2"].I != 9 || items[1].Fields["g.n"].I != 7 {
		t.Errorf("items = %v, %v", items[0].Fields, items[1].Fields)
	}
	out, err := eng.Convert("sq", "sq", []byte(in))
	if err != nil || string(out) != in {
		t.Errorf("round trip = %s, %v; want %s", out, err, in)
	}

	// Encode from an entity: presence bits and the opt bit follow from what
	// the entity holds; an item with no recorded kind selects by `requires`.
	e := NewEntity()
	e.Fields["g.n"] = Value{Kind: KindInt, I: 1}
	e.Fields["g.n3"] = Value{Kind: KindInt, I: 100} // written through the `also` line and its table
	it := NewItem()
	it.Fields["g.n"] = Value{Kind: KindInt, I: 2}
	e.SetList("g.items", []*Item{it})
	out, err = eng.Encode("sq", e)
	if want := "0140" + "0410" + "00" + "01" + "20"; err != nil || string(out) != want {
		t.Errorf("encode = %s, %v; want %s", out, err, want)
	}
	// An item naming a kind the group does not have.
	it.Kind = EntityKind{Format: "sq", Name: "other"}
	if _, err := eng.Encode("sq", e); !IsKind(err, ErrNoKind) {
		t.Errorf("an item naming an unknown kind: got %v, want no-kind", err)
	}
}

func TestSequentialDecodeErrors(t *testing.T) {
	eng := seqEngine(t)
	cases := []struct {
		name, in string
		want     ErrorKind
	}{
		{"input ends inside a field", "05806f", ErrMalformedWire},
		{"line runs past its length extent", "05400300" + "0000", ErrMalformedWire},
		{"last fx bit of a chain is 1", "0500" + "810b0d" + "00", ErrMalformedWire},
		{"count larger than the bits left", "0500" + "00" + "ff", ErrMalformedWire},
		{"item matches no kind", "0500" + "00" + "01" + "15", ErrNoKind},
	}
	for _, c := range cases {
		if _, err := eng.Decode("sq", []byte(c.in)); !IsKind(err, c.want) {
			t.Errorf("%s: got %v, want %s", c.name, err, c.want)
		}
	}
}

func TestSequentialLoadErrors(t *testing.T) {
	fixed := "format f\nversion 0.8.0\ndistribution public\nsource s\nuses g\nwire bits\nword_bytes 1\n"
	cases := []struct {
		name, def string
		want      ErrorKind
	}{
		{"positional locator", "format f\n" + seqHead + "field g.n 0:0:8 uint\n", ErrBadDirective},
		{"optional", "format f\n" + seqHead + "field g.n 8 uint optional\n", ErrBadDirective},
		{"word_bytes", "format f\n" + seqHead + "word_bytes 1\nfield g.n 8 uint\n", ErrBadDirective},
		{"block with no end", "format f\n" + seqHead + "opt\nfield g.n 8 uint\n", ErrBadDirective},
		{"if naming an unknown presence", "format f\n" + seqHead + "if p.1\nend\n", ErrBadDirective},
		{"if naming a bit beyond the presence", "format f\n" + seqHead + "presence p 2\nif !p.3\nend\n", ErrBadDirective},
		{"presence declared twice", "format f\n" + seqHead + "presence p 2\npresence p 2\n", ErrBadDirective},
		{"fx outside a chain", "format f\n" + seqHead + "opt\nfx\nend\n", ErrBadDirective},
		{"also after a const", "format f\n" + seqHead + "const 8 1\nalso g.n\n", ErrBadDirective},
		{"length bits whole", "format f\n" + seqHead + "length 8 bits whole\n", ErrBadDirective},
		{"when after a line of its kind", "format f\n" + seqHead + "kind a\nfield g.n 8 uint\nwhen 8 1\n", ErrBadDirective},
		{"kind twice in a group", "format f\n" + seqHead + "group g.items while\nkind a\nkind a\nend\n", ErrDuplicateKind},
		{"const of 65 bits", "format f\n" + seqHead + "const 65 1\n", ErrBadDirective},
		{"sequential line in a fixed pack", fixed + "field g.n 0:0:8 uint\npad 8\n", ErrBadDirective},
		{"bit length in a fixed pack", fixed + "field g.n 8 uint\n", ErrBadDirective},
		{"layout on json", "format f\nversion 0.8.0\ndistribution public\nsource s\nwire json\nlayout sequential\n", ErrBadDirective},
		// Rulings 13, 15, 16, 18 and 21 of 0.7.
		{"protobuf body mixing . and a path", "format f\nversion 0.7.0\ndistribution public\nsource s\nuses g\nwire protobuf\ngroup g.items 2\nfield g.name . pstring\nfield g.n 1 pvarint\nend\n", ErrBadDirective},
		{"const beyond item bits", fixed + "group g.items 0:8 item 8 count 0:0:8\nconst 0:4:8 1\nend\n", ErrBadDirective},
		{"fixed-count group reaching a counted group", fixed + "group g.subs 0:8 item 8 count 2\nfield g.n 0:0:8 uint\nend\ngroup g.items 0:16 item 8 count 0:0:8\nfield g.n 0:0:8 uint\nend\n", ErrBadDirective},
		{"const on the item itself", "format f\nversion 0.7.0\ndistribution public\nsource s\nuses g\nwire json\ngroup g.items items\nfield g.name . string\nconst . x\nend\n", ErrBadDirective},
		{"field through a group path", "format f\nversion 0.7.0\ndistribution public\nsource s\nuses g\nwire json\ngroup g.items items\nfield g.name name string\nend\nfield g.n items.first int\n", ErrBadDirective},
	}
	for _, c := range cases {
		eng := New()
		for _, m := range []string{testCore, seqModule} {
			if err := eng.LoadModel([]byte(m), "model"); err != nil {
				t.Fatalf("LoadModel: %v", err)
			}
		}
		if err := eng.LoadPack([]byte(c.def), "pack"); !IsKind(err, c.want) {
			t.Errorf("%s: got %v, want %s", c.name, err, c.want)
		}
	}
}

func TestModuleUsesAndDeriveFunctionsOf08(t *testing.T) {
	const other = `module o
version 0.1.0
distribution public
source s
uses g
key secs float s
key flag int -
key num int -
key text string -
derive o.secs day_seconds time_ms
derive o.flag any g.n g.n2
derive o.num parse_int g.name
derive o.text text_of g.n
`
	const core = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey time_ms int ms\n"
	eng := New()
	if err := eng.LoadModel([]byte(core), "core"); err != nil {
		t.Fatal(err)
	}
	if err := eng.LoadModel([]byte(other), "o"); !IsKind(err, ErrUnknownModule) {
		t.Errorf("a module whose used module is not loaded: got %v, want unknown-module", err)
	}
	if err := eng.LoadModel([]byte(seqModule), "g"); err != nil {
		t.Fatal(err)
	}
	if err := eng.LoadModel([]byte(other), "o"); err != nil {
		t.Fatal(err)
	}
	ent := NewEntity()
	ent.Fields["time_ms"] = Value{Kind: KindInt, I: -1}
	ent.Fields["g.n2"] = Value{Kind: KindInt, I: 3}
	ent.Fields["g.name"] = Value{Kind: KindString, S: "-17"}
	eng.Complete(ent)
	if got := ent.Fields["o.secs"].F; got != 86399.999 {
		t.Errorf("day_seconds = %v", got)
	}
	// `any` is set when only some of its arguments are present.
	if v, ok := ent.Fields["o.flag"]; !ok || v.I != 1 {
		t.Errorf("any = %v, present %v", v, ok)
	}
	if v := ent.Fields["o.num"]; v.I != -17 {
		t.Errorf("parse_int = %v", v)
	}
	if _, ok := ent.Fields["o.text"]; ok {
		t.Error("text_of of an absent key must leave the target absent")
	}
	ent.Fields["g.name"] = Value{Kind: KindString, S: "x1"}
	delete(ent.Fields, "o.num")
	eng.Complete(ent)
	if _, ok := ent.Fields["o.num"]; ok {
		t.Error("parse_int of text that is not a decimal integer must leave the target absent")
	}
	// A derive target of a used module, and an argument of a module not used.
	for name, text := range map[string]string{
		"target of a used module":        "module p\nversion 1\ndistribution public\nsource s\nuses g\nkey a int -\nderive g.n copy p.a\n",
		"argument of a module not used":  "module p\nversion 1\ndistribution public\nsource s\nkey a int -\nderive p.a copy g.n\n",
		"day_seconds with an int target": "module p\nversion 1\ndistribution public\nsource s\nkey a int -\nderive p.a day_seconds time_ms\n",
		"not with two arguments":         "module p\nversion 1\ndistribution public\nsource s\nuses g\nkey a int -\nderive p.a not g.n g.n2\n",
	} {
		if err := eng.LoadModel([]byte(text), "p"); !IsKind(err, ErrBadDirective) {
			t.Errorf("%s: got %v, want bad-directive", name, err)
		}
	}
}

func TestModuleFilesLoadAfterTheModulesTheyUse(t *testing.T) {
	dir := t.TempDir()
	write := func(name, text string) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(dir, name), []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	head := "version 1\ndistribution public\nsource s\n"
	write("core.def", "module core\n"+head)
	write("a.def", "module a\n"+head+"uses z\n")
	write("m.def", "module m\n"+head)
	write("z.def", "module z\n"+head+"uses m\n")
	files, err := moduleFiles(dir)
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, f := range files {
		got = append(got, filepath.Base(f))
	}
	want := []string{"core.def", "m.def", "z.def", "a.def"}
	if len(got) != len(want) {
		t.Fatalf("order = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("order = %v, want %v", got, want)
		}
	}
	write("m.def", "module m\n"+head+"uses a\n")
	if _, err := moduleFiles(dir); !IsKind(err, ErrBadDirective) {
		t.Errorf("a cycle of uses lines: got %v, want bad-directive", err)
	}
}

func TestRulings11To21Of07(t *testing.T) {
	eng := groupsEngine(t)
	// Ruling 11: a scalar item with no value is `null` on json, and is left
	// out of a packed protobuf field; a list whose items all lack it writes
	// nothing.
	out, err := eng.Convert("gj", "gj", []byte(`{"id":"u","nums":[1,null]}`))
	if want := `{"id":"u","nums":[1,null]}`; err != nil || string(out) != want {
		t.Errorf("json null item = %s, %v; want %s", out, err, want)
	}
	out, err = eng.Convert("gj", "gp", []byte(`{"id":"u","nums":[null]}`))
	if want := "0a0175"; err != nil || string(out) != want {
		t.Errorf("packed list of no values = %s, %v; want %s", out, err, want)
	}
}
