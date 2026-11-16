package goatxf

import (
	"strings"
	"testing"
)

func mustPack(t *testing.T, def string) *Pack {
	t.Helper()
	p, err := ParsePack([]byte(def), "test.def")
	if err != nil {
		t.Fatalf("ParsePack: %v", err)
	}
	return p
}

// testCore declares the keys the unit-test packs map.
const testCore = `module core
version 0.1.0
distribution public
source "unit tests"
key uid string -
key type string -
key lat float deg
key lon float deg
key remarks string -
`

func mustEngine(t *testing.T, defs ...string) *Engine {
	t.Helper()
	eng := New()
	if err := eng.LoadModel([]byte(testCore), "core.def"); err != nil {
		t.Fatalf("LoadModel: %v", err)
	}
	for _, def := range defs {
		if err := eng.AddPack(mustPack(t, def)); err != nil {
			t.Fatalf("AddPack: %v", err)
		}
	}
	return eng
}

func TestPackErrorsAreNamed(t *testing.T) {
	cases := []struct {
		name, def string
		kind      ErrorKind
	}{
		{"unknown directive", "format a\nwire xml\nroot r\nbogus x\n", ErrUnknownDirective},
		{"unknown transform", "format a\nwire xml\nroot r\nfield uid @uid rot13\n", ErrUnknownTransform},
		{"unknown wire", "format a\nwire yaml\n", ErrUnknownWire},
		{"xml without root", "format a\nwire xml\nfield uid @uid string\n", ErrMissingRoot},
		{"bad xml locator", "format a\nwire xml\nroot r\nfield uid point string\n", ErrBadLocator},
		{"bad geojson locator", "format a\nwire geojson\nfield lat geometry.z float\n", ErrBadLocator},
		{"wrong arity", "format a\nwire geojson\nfield lat geometry.lat\n", ErrBadDirective},
		{"missing format", "wire geojson\n", ErrBadDirective},
	}
	for _, c := range cases {
		_, err := ParsePack([]byte("distribution public\nsource s\n"+c.def), "test.def")
		if err == nil || !IsKind(err, c.kind) {
			t.Errorf("%s: got %v, want kind %s", c.name, err, c.kind)
		}
	}
}

func TestTokenizerCommentsAndQuotes(t *testing.T) {
	toks, err := tokenize(`field callsign "detail/a b/#text" string  # trailing comment`)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"field", "callsign", "detail/a b/#text", "string"}
	if strings.Join(toks, "|") != strings.Join(want, "|") {
		t.Fatalf("got %q, want %q", toks, want)
	}
	toks, _ = tokenize("field remarks remarks/#text string")
	if len(toks) != 4 || toks[2] != "remarks/#text" {
		t.Fatalf("#text locator split as comment: %q", toks)
	}
	// 0.5 rulings 6 and 17: no escape inside quotes, and `#` there is literal.
	toks, err = tokenize(`when note "a\ #b" # comment`)
	if err != nil || len(toks) != 3 || toks[2] != `a\ #b` {
		t.Fatalf("quoted value: %q, %v", toks, err)
	}
}

func TestFloatFormatting(t *testing.T) {
	for in, want := range map[float64]string{30.0: "30", -42.6: "-42.6", 0.1: "0.1", 1e-7: "0.0000001", 30.0090027: "30.0090027"} {
		got, err := formatFloat(in)
		if err != nil || got != want {
			t.Errorf("formatFloat(%v) = %q, %v; want %q", in, got, err, want)
		}
	}
}

func TestISO8601(t *testing.T) {
	v, err := decISO("2021-02-27T20:00:00Z")
	if err != nil || v.I != 1614456000000 {
		t.Fatalf("decISO: %v %v", v, err)
	}
	s, err := encISO(Value{Kind: KindInt, I: 1614456000123})
	if err != nil || s != "2021-02-27T20:00:00.123Z" {
		t.Fatalf("encISO: %q %v", s, err)
	}
	// 0.6: an offset, a lowercase designator and a lowercase `t` are read and
	// converted to UTC; encode still writes `Z` and `T`.
	for _, in := range []string{"2021-02-27T20:00:00z", "2021-02-27t20:00:00.000Z", "2021-02-27T20:00:00+00:00", "2021-02-27T21:30:00.0009+01:30", "2021-02-27T15:00:00-05:00"} {
		if v, err := decISO(in); err != nil || v.I != 1614456000000 {
			t.Errorf("decISO(%q): %v %v", in, v, err)
		}
	}
	for _, in := range []string{"27 Feb 2021", "2021-02-27T20:00:00", "2021-02-27T20:00:00+0100", "2021-02-27 20:00:00Z"} {
		if _, err := decISO(in); err == nil {
			t.Errorf("decISO accepted %q", in)
		}
	}
}

const xmlDef = `format x
version 0.1.0
distribution public
source "unit tests"
wire xml
root event
field uid @uid string
field type @type string
field lat point/@lat float
field remarks remarks/#text string
typemap NAT a-f-G
`

const geoDef = `format g
distribution public
source "unit tests"
wire geojson
field uid id string
field type properties.type string
field lat geometry.lat float
field lon geometry.lon float
`

func TestResidueAndTypemap(t *testing.T) {
	eng := mustEngine(t, xmlDef, geoDef)
	in := `<?xml version="1.0" encoding="UTF-8"?>
<event uid="U1" extra="e&amp;1" type="NAT">
  <point lat="30.0" hae="1"/>
  <remarks>hello &lt;world&gt;</remarks>
  <marker/>
</event>`
	ent, err := eng.Decode("x", []byte(in))
	if err != nil {
		t.Fatal(err)
	}
	if v, _ := ent.Get("type"); v.S != "a-f-G" {
		t.Errorf("typemap decode: type = %q", v.S)
	}
	out, err := eng.Encode("x", ent)
	if err != nil {
		t.Fatal(err)
	}
	// Residue is the unmapped attributes of the root element; unmapped child
	// elements and their attributes are not carried (0.1.1 ruling 6).
	want := `<event uid="U1" type="NAT" extra="e&amp;1"><point lat="30"/><remarks>hello &lt;world&gt;</remarks></event>`
	if string(out) != want {
		t.Errorf("xml round trip\n got: %s\nwant: %s", out, want)
	}
	// Residue does not cross formats; with lon absent the geometry is null
	// (0.1.1 ruling 5).
	if gj, err := eng.Encode("g", ent); err != nil || string(gj) != `{"type":"Feature","geometry":null,"properties":{"type":"a-f-G"},"id":"U1"}` {
		t.Errorf("geojson encode with lat only: %s, %v", gj, err)
	}
	ent.Fields["lon"] = Value{Kind: KindFloat, F: 1.5}
	gj, err := eng.Encode("g", ent)
	if err != nil {
		t.Fatal(err)
	}
	if string(gj) != `{"type":"Feature","geometry":{"type":"Point","coordinates":[1.5,30]},"properties":{"type":"a-f-G"},"id":"U1"}` {
		t.Errorf("geojson encode: %s", gj)
	}
}

// An unmapped native type code passes through its mapped locator and is not
// added to residue (0.1.1 ruling 2).
func TestUnknownNativeTypePassesThrough(t *testing.T) {
	eng := mustEngine(t, xmlDef)
	ent, err := eng.Decode("x", []byte(`<event uid="U" type="ZZZ"/>`))
	if err != nil {
		t.Fatal(err)
	}
	if v, _ := ent.Get("type"); v.S != "ZZZ" {
		t.Errorf("unmapped native code should pass through, got %q", v.S)
	}
	if len(ent.Residue) != 0 {
		t.Errorf("unmapped native code must not be residue: %+v", ent.Residue)
	}
	out, _ := eng.Encode("x", ent)
	if string(out) != `<event uid="U" type="ZZZ"/>` {
		t.Errorf("round trip: %s", out)
	}
}

func TestGeoJSONResidueRoundTrip(t *testing.T) {
	eng := mustEngine(t, geoDef)
	in := `{ "id": "A", "type": "Feature", "properties": {"type": "a-h", "n": 3, "tags": ["x", {"k": null}], "s": "v"},
	        "geometry": {"type": "Point", "coordinates": [10, 20.25]}, "bbox": [1,2,3,4] }`
	out, err := eng.Convert("g", "g", []byte(in))
	if err != nil {
		t.Fatal(err)
	}
	// A scalar residue member is written back as a string (0.5 ruling 28);
	// a member name that repeats is accepted on this wire.
	want := `{"type":"Feature","geometry":{"type":"Point","coordinates":[10,20.25]},"properties":{"type":"a-h","n":"3","tags":["x",{"k":null}],"s":"v"},"id":"A","bbox":[1,2,3,4]}`
	if string(out) != want {
		t.Errorf("got  %s\nwant %s", out, want)
	}
}

func TestWireErrors(t *testing.T) {
	eng := mustEngine(t, xmlDef, geoDef)
	cases := []struct {
		format, in string
		kind       ErrorKind
	}{
		{"x", `<event uid="a">`, ErrMalformedWire},
		{"x", `<other/>`, ErrMissingRoot},
		{"x", ``, ErrMalformedWire}, // an input with no element (0.8 ruling 37)
		{"x", `<event/><event/>`, ErrMalformedWire},
		{"g", `{"type":"Feature"} x`, ErrMalformedWire},
		{"g", `{"type":"FeatureCollection"}`, ErrMalformedWire},
		{"g", `{"type":"Feature","geometry":{"type":"LineString","coordinates":[]}}`, ErrMalformedWire},
		{"nope", `{}`, ErrUnknownFormat},
	}
	for _, c := range cases {
		if _, err := eng.Decode(c.format, []byte(c.in)); err == nil || !IsKind(err, c.kind) {
			t.Errorf("decode %s %q: got %v, want %s", c.format, c.in, err, c.kind)
		}
	}
	ent, err := eng.Decode("x", []byte(`<event uid="a" type="NAT"><point lat="north"/></event>`))
	if err == nil || !IsKind(err, ErrTransformDecode) || !strings.Contains(err.Error(), "point/@lat") {
		t.Fatalf("bad float: got %v", err)
	}
	if _, present := ent.Get("lat"); present {
		t.Error("failed field must be absent")
	}
	if _, err := eng.Convert("x", "g", []byte(`<event uid="a"><point lat="north"/></event>`)); err == nil {
		t.Error("convert must fail when a field could not be decoded")
	}
}

const kindsDef = `format k
distribution public
source "unit tests"
wire bits
word_bytes 1
bit_order msb
kind named
when 0:0:8 1
requires uid
field uid 0:8:16 ascii
kind pos
when 0:0:8 2
requires lat
field lat 0:8:8 uscale:1/2
field lon 0:16:8 sscale:0.5:10
kind empty
when 0:0:8 0
`

const jsonDef = `format j
distribution public
source "unit tests"
wire json
when v 1
field uid id string
kind full
requires lat
field lat pos.lat float
kind bare
`

// TestKinds covers kind selection on decode and encode, the entity's kind,
// and convert clearing it between two formats.
func TestKinds(t *testing.T) {
	eng := mustEngine(t, kindsDef, jsonDef)
	ent, err := eng.Decode("k", []byte("014142ff"))
	if err != nil {
		t.Fatal(err)
	}
	if ent.Kind != (EntityKind{"k", "named"}) {
		t.Errorf("kind = %+v", ent.Kind)
	}
	if v, _ := ent.Get("uid"); v.S != "AB" {
		t.Errorf("uid = %q", v.S)
	}
	// Encode to another format with the source kind still set picks by requires.
	if out, err := eng.Encode("j", ent); err != nil || string(out) != `{"v":1,"id":"AB"}` {
		t.Errorf("encode j: %s, %v", out, err)
	}
	// Same format: the kind is kept even though `pos` would not qualify.
	if out, err := eng.Convert("k", "k", []byte("020304")); err != nil || string(out) != "020304" {
		t.Errorf("k -> k: %s, %v", out, err)
	}
	// Cross format: the target kind is chosen by requires (lat present).
	if out, err := eng.Convert("k", "j", []byte("020304")); err != nil || string(out) != `{"v":1,"pos":{"lat":1.5}}` {
		t.Errorf("k -> j: %s, %v", out, err)
	}
	if out, err := eng.Convert("j", "k", []byte(`{"v":1,"id":"Z"}`)); err != nil || string(out) != "015a00" {
		t.Errorf("j -> k: %s, %v", out, err)
	}
	if out, err := eng.Convert("j", "k", []byte(`{"v":1}`)); err != nil || string(out) != "00" {
		t.Errorf("j -> k default kind: %s, %v", out, err)
	}
	keys, _ := eng.ModelKeys("k")
	if strings.Join(keys, ",") != "uid,lat,lon" {
		t.Errorf("model keys: %v", keys)
	}
	cases := []struct {
		from, to, in string
		kind         ErrorKind
	}{
		{"k", "k", "09", ErrNoKind},                              // no kind matches
		{"k", "k", "", ErrNoKind},                                // a when beyond the input does not hold
		{"k", "k", "0141", ErrMalformedWire},                     // shorter than the selected kind
		{"k", "k", "01410a", ErrTransformDecode},                 // ascii byte below 0x20
		{"k", "k", "0141ff", ErrTransformDecode},                 // ascii byte above 0x7E
		{"j", "j", `{"v":2,"id":"a"}`, ErrNoKind},                // common when fails
		{"j", "j", `{"v":1,"id":7}`, ErrTransformDecode},         // wrong JSON type
		{"j", "j", `[1]`, ErrMalformedWire},                      // not an object
		{"j", "k", `{"v":1,"id":"TOOLONG"}`, ErrTransformEncode}, // ascii longer than the field
		{"j", "k", `{"v":1,"pos":{"lat":200}}`, ErrTransformEncode},
		{"j", "k", `{"v":1,"pos":{"lat":-1}}`, ErrTransformEncode},
	}
	for _, c := range cases {
		_, err := eng.Convert(c.from, c.to, []byte(c.in))
		if err == nil || !IsKind(err, c.kind) || !strings.HasPrefix(err.Error(), string(c.kind)+":") {
			t.Errorf("convert %s -> %s %q: got %v, want %s", c.from, c.to, c.in, err, c.kind)
		}
	}
}

func TestKindLoadErrors(t *testing.T) {
	head := "format a\ndistribution public\nsource s\n"
	cases := []struct {
		name, def string
		kind      ErrorKind
	}{
		{"duplicate kind", "wire json\nkind a\nkind a\n", ErrDuplicateKind},
		{"requires before kind", "wire json\nrequires uid\nkind a\n", ErrBadDirective},
		{"when without kind", "wire json\nwhen a 1\n", ErrBadDirective},
		{"bit_order on json", "wire json\nbit_order msb\n", ErrBadDirective},
		{"bad bit_order", "wire bits\nword_bytes 1\nbit_order middle\n", ErrBadDirective},
		{"f32 length", "wire bits\nword_bytes 1\nfield lat 0:0:31 f32\n", ErrBadDirective},
		{"ascii length", "wire bits\nword_bytes 1\nfield uid 0:0:2048 ascii\n", ErrBadLocator},
		{"uint over 64 bits", "wire bits\nword_bytes 1\nfield uid 0:0:72 uint\n", ErrBadDirective},
		{"bits when not a number", "wire bits\nword_bytes 1\nkind a\nwhen 0:0:8 x\n", ErrBadDirective},
		{"bits when does not fit", "wire bits\nword_bytes 1\nkind a\nwhen 0:0:8 256\n", ErrBadDirective},
		{"bool on xml", "wire xml\nroot r\nfield uid @a bool\n", ErrUnknownTransform},
		// 0.6
		{"via with no map line", "wire json\nfield uid a string via t\n", ErrBadDirective},
		{"via with no table name", "wire json\nfield uid a string via\n", ErrBadDirective},
		{"unknown option", "wire json\nfield uid a string loud\n", ErrBadDirective},
		{"option twice", "wire bits\nword_bytes 1\nfield uid 0:0:16 ascii trim trim\n", ErrBadDirective},
		{"swap on json", "wire json\nfield uid a string swap\n", ErrBadDirective},
		{"swap on 12 bits", "wire bits\nword_bytes 1\nfield uid 0:0:12 uint swap\n", ErrBadDirective},
		{"trim without ascii", "wire bits\nword_bytes 1\nfield uid 0:0:16 uint trim\n", ErrBadDirective},
		{"optional on protobuf", "wire protobuf\nfield uid 1 pstring optional\n", ErrBadDirective},
		{"root in a kind on json", "wire json\nkind a\nroot r\n", ErrBadDirective},
		{"root twice in a kind", "wire xml\nkind a\nroot r\nroot s\n", ErrBadDirective},
		{"xml kind without any root", "wire xml\nkind a\nroot r\nkind b\n", ErrMissingRoot},
		{"bits const does not fit", "wire bits\nword_bytes 1\nconst 0:0:4 16\n", ErrBadDirective},
	}
	for _, c := range cases {
		_, err := ParsePack([]byte(head+c.def), "test.def")
		if err == nil || !IsKind(err, c.kind) || !strings.HasPrefix(err.Error(), string(c.kind)+":") {
			t.Errorf("%s: got %v, want kind %s", c.name, err, c.kind)
		}
	}
}

// Whole-file checks run before missing-distribution (0.5 ruling 25), and
// duplicate-field is withdrawn (0.6).
func TestWholeFileChecksAndWithdrawnDuplicateField(t *testing.T) {
	_, err := ParsePack([]byte("format a\nsource s\nwire bits\nword_bytes 4\nfield lat 0:0:16 f32\n"), "test.def")
	if !IsKind(err, ErrBadDirective) {
		t.Errorf("bad length with no distribution: got %v, want bad-directive", err)
	}
	_, err = ParsePack([]byte("format a\nsource s\nwire bits\nword_bytes 4\nfield lat 0:0:32 f32\n"), "test.def")
	if !IsKind(err, ErrMissingDistribution) {
		t.Errorf("no distribution: got %v, want missing-distribution", err)
	}
	head := "format a\ndistribution public\nsource s\n"
	for _, def := range []string{
		"wire json\nfield uid a string\nkind a\nfield uid b string\n",
		"wire json\nfield uid a string\nfield uid b string\n",
		"wire xml\nfield uid @id string\nkind a\nroot r\nkind b\nroot s\n",
		"wire xml\nroot r\nconst @v 1\nfield uid @id string\n",
	} {
		if _, err := ParsePack([]byte(head+def), "test.def"); err != nil {
			t.Errorf("%q must load: %v", def, err)
		}
	}
}

const rulesCore = `module core
version 0.1.0
distribution public
source "unit tests"
key uid string -
key type string -
key lat float deg
key lon float deg
key hae float m
key course float deg
key speed_ms float m/s
key time_ms int ms
key callsign string -
key vel_e float m/s
key vel_n float m/s
key next_ms int ms
key label string -
derive course bearing vel_e vel_n
derive speed_ms hypot vel_e vel_n
derive next_ms offset:1000 time_ms
derive label join:- uid callsign
`

const rulesJSONDef = `format rj
distribution public
source "unit tests"
wire json
const schema rules
field uid id string
field lat pos.lat float
field lat pos.y float
field callsign cls int via class
field course crs float
field speed_ms spd float
field vel_e ve float
field vel_n vn float
field time_ms t int
field next_ms t2 int
field label label string
const n =7
default callsign bird
map class 1 uas
map class 2 bird
map class 3 uas
`

const rulesBitsDef = `format rb
distribution public
source "unit tests"
wire bits
word_bytes 1
bit_order msb
const 0:0:8 90
field time_ms 0:8:16 uint swap
field callsign 0:24:32 ascii trim optional
field lat 0:56:32 f32 optional swap
`

const rulesXMLDef = `format rx
distribution public
source "unit tests"
wire xml
field uid @id string
kind a
root alpha
requires lat
field lat @lat float
kind b
root beta
when @mark present
`

func rulesEngine(t *testing.T) *Engine {
	t.Helper()
	eng := New()
	if err := eng.LoadModel([]byte(rulesCore), "core.def"); err != nil {
		t.Fatalf("LoadModel: %v", err)
	}
	for _, def := range []string{rulesJSONDef, rulesBitsDef, rulesXMLDef} {
		if err := eng.LoadPack([]byte(def), "test.def"); err != nil {
			t.Fatalf("LoadPack: %v", err)
		}
	}
	return eng
}

// TestMappingRules covers const, default, value tables, one key at several
// locators, the bits field options and a root per kind (spec 0.6).
func TestMappingRules(t *testing.T) {
	eng := rulesEngine(t)
	cases := []struct{ from, to, in, want string }{
		// const written and not checked; default through the table; one key at two locators
		{"rj", "rj", `{"schema":"x","id":"a","pos":{"y":2},"n":1}`, `{"schema":"rules","id":"a","pos":{"lat":2,"y":2},"cls":2,"n":"7"}`},
		// the earliest line fails, a later one succeeds; the first of two entries sharing a model value
		{"rj", "rj", `{"id":"a","pos":{"lat":"n","y":2},"cls":3}`, `{"schema":"rules","id":"a","pos":{"lat":2,"y":2},"cls":1,"n":"7"}`},
		// swap, trim, const; optional fields beyond the input are absent and encode writes the whole message
		{"rb", "rb", "0034124120422000002040", "5a34124120420000002040"},
		{"rb", "rb", "003412", "5a3412" + "0000000000000000"},
		{"rb", "rb", "00341241204220", "5a34124120420000000000"},
		{"rb", "rj", "003412", `{"schema":"rules","cls":2,"t":4660,"t2":5660,"n":"7"}`},
		// a root per kind; when-present does not map the attribute, so it is residue
		{"rx", "rx", `<alpha id="u" lat="1.50"/>`, `<alpha id="u" lat="1.5"/>`},
		{"rx", "rx", `<beta mark="m" id="u"/>`, `<beta id="u" mark="m"/>`},
		{"rj", "rx", `{"id":"u","pos":{"lat":1}}`, `<alpha id="u" lat="1"/>`},
	}
	for _, c := range cases {
		out, err := eng.Convert(c.from, c.to, []byte(c.in))
		if err != nil || string(out) != c.want {
			t.Errorf("convert %s -> %s %s\n got: %s, %v\nwant: %s", c.from, c.to, c.in, out, err, c.want)
		}
	}
	errs := []struct {
		from, to, in string
		kind         ErrorKind
	}{
		{"rj", "rj", `{"id":"a","cls":9}`, ErrTransformDecode},                   // no table entry, types differ
		{"rj", "rj", `{"id":"a","pos":{"lat":"n","y":"s"}}`, ErrTransformDecode}, // every line of the key fails
		{"rb", "rb", "0034", ErrMalformedWire},                                   // a field that is not optional
		{"rb", "rb", "003412414200000000c07f", ErrTransformDecode},               // f32 not-a-number, swapped
		{"rb", "rj", "0034124142000000002040", ErrTransformEncode},               // no table entry for the model value, types differ
		{"rx", "rx", `<gamma id="u"/>`, ErrNoKind},                               // the root of no kind
		{"rx", "rx", `<beta id="u"/>`, ErrNoKind},                                // the root matches, the when does not
		{"rj", "rb", `{"id":"a","pos":{"lat":1e39}}`, ErrTransformEncode},        // outside single range
	}
	for _, c := range errs {
		_, err := eng.Convert(c.from, c.to, []byte(c.in))
		if err == nil || !IsKind(err, c.kind) || !strings.HasPrefix(err.Error(), string(c.kind)+":") {
			t.Errorf("convert %s -> %s %q: got %v, want %s", c.from, c.to, c.in, err, c.kind)
		}
	}
	// An entity naming this format and a kind the pack does not have (0.5 ruling 24).
	ent := NewEntity()
	ent.Kind = EntityKind{"rx", "nosuch"}
	if _, err := eng.Encode("rx", ent); !IsKind(err, ErrNoKind) {
		t.Errorf("unknown kind: got %v, want no-kind", err)
	}
	// ascii text outside 0x20-0x7E is an encode error (0.5 ruling 19).
	ent = NewEntity()
	ent.Fields["callsign"] = Value{Kind: KindString, S: "A\tB"}
	if _, err := eng.Encode("rb", ent); !IsKind(err, ErrTransformEncode) {
		t.Errorf("ascii control character: got %v, want transform-encode", err)
	}
}

// TestDeriveAndContext covers derived keys, complete(entity), caller-supplied
// keys and the order inside convert (spec 0.6).
func TestDeriveAndContext(t *testing.T) {
	eng := rulesEngine(t)
	in := `{"id":"a","ve":3,"vn":4,"t":5}`
	// Same format, no context: nothing is filled or derived.
	if out, err := eng.Convert("rj", "rj", []byte(in)); err != nil || string(out) != `{"schema":"rules","id":"a","cls":2,"ve":3,"vn":4,"t":5,"n":"7"}` {
		t.Errorf("no context: %s, %v", out, err)
	}
	// With a context the key the entity lacks is filled, then keys derive; a
	// context key the entity has does not replace it.
	out, err := eng.ConvertWith("rj", "rj", []byte(in), map[string]string{"callsign": "uas", "uid": "zzz"})
	if err != nil || string(out) != `{"schema":"rules","id":"a","cls":1,"crs":36.86989764584402,"spd":5,"ve":3,"vn":4,"t":5,"t2":1005,"label":"a-uas","n":"7"}` {
		t.Errorf("context: %s, %v", out, err)
	}
	ent, err := eng.Decode("rj", []byte(in))
	if err != nil {
		t.Fatal(err)
	}
	if _, has := ent.Get("speed_ms"); has {
		t.Error("decode alone must not derive")
	}
	eng.Complete(ent)
	if v, _ := ent.Get("speed_ms"); v.F != 5 {
		t.Errorf("speed_ms = %v, want 5", v.F)
	}
	if v, _ := ent.Get("course"); v.F < 36.8698976 || v.F > 36.8698977 {
		t.Errorf("course = %v", v.F)
	}
	// A zero vector gives speed 0 and no course.
	ent, _ = eng.Decode("rj", []byte(`{"ve":0,"vn":0}`))
	eng.Complete(ent)
	if _, has := ent.Get("course"); has {
		t.Error("bearing of a zero vector must stay absent")
	}
	if v, has := ent.Get("speed_ms"); !has || v.F != 0 {
		t.Errorf("speed_ms of a zero vector = %v, %v", v, has)
	}
	if _, err := eng.ConvertWith("rj", "rj", []byte(in), map[string]string{"nosuch": "1"}); !IsKind(err, ErrUndeclaredKey) {
		t.Errorf("undeclared context key: got %v", err)
	}
	if _, err := eng.ConvertWith("rj", "rj", []byte(in), map[string]string{"time_ms": "soon"}); !IsKind(err, ErrKeyTypeMismatch) {
		t.Errorf("context value of the wrong type: got %v", err)
	}
}

func TestDeriveLoadErrors(t *testing.T) {
	head := "module core\nversion 0.1.0\ndistribution public\nsource s\nkey a float -\nkey b float -\nkey n int -\nkey s string -\n"
	for name, line := range map[string]string{
		"unknown function":      "derive b cube a",
		"argument count":        "derive b hypot a",
		"undeclared key":        "derive b neg zz",
		"key of another module": "derive b neg other.z",
		"type does not fit":     "derive n hypot a b",
		"copy types differ":     "derive n copy a",
		"offset int by float":   "derive n offset:0.5 n",
		"join on floats":        "derive s join:- a b",
		"scale without factor":  "derive b scale a",
	} {
		err := New().LoadModel([]byte(head+line+"\n"), "core.def")
		if !IsKind(err, ErrBadDirective) {
			t.Errorf("%s: got %v, want bad-directive", name, err)
		}
	}
	ok := "derive b scale:1/3 a\nderive n offset:-2 n\nderive s join:/ s s\nderive b copy a\n"
	if err := New().LoadModel([]byte(head+ok), "core.def"); err != nil {
		t.Errorf("valid derive lines must load: %v", err)
	}
}
