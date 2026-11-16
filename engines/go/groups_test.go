package goatxf

import (
	"strings"
	"testing"
)

// groupsModule declares the lists and item keys the group unit tests map.
const groupsModule = `module g
version 0.1.0
distribution public
source "unit tests"
key name string -
key n int -
key x float -
list items "items that hold name, n and the nested list subs"
list subs
list nums
`

const groupsHead = "version 0.7.0\ndistribution public\nsource s\nuses g\n"

const groupsJSON = "format gj\nwire json\n" + groupsHead + `field uid id string
group g.items items
  field g.name name string
  field g.n n int
  default g.n 1
  const k i
  group g.subs subs
    field g.n v int
  end
end
group g.nums nums
  field g.n . int
end
`

const groupsXML = "format gx\nwire xml\nroot m\n" + groupsHead + `field uid @id string
group g.items body/item
  field g.name @name string
  field g.n "#text" int
  group g.subs sub
    field g.n @v int
  end
end
group g.nums n
  field g.n "#text" int
end
`

const groupsPB = "format gp\nwire protobuf\n" + groupsHead + `field uid 1 pstring
group g.items 2
  field g.name 1 pstring
  field g.n 2 pvarint
  group g.subs 3
    field g.n 1 pvarint
  end
end
group g.nums 3
  field g.n . pvarint
end
`

const groupsBits = "format gb\nwire bits\nword_bytes 1\n" + groupsHead + `field g.n 0:0:8 uint
group g.items 0:8 item 16 count 0:0:8
  field g.n 0:0:8 uint
  group g.subs 0:16 item 8 count 0:8:8
    field g.n 0:0:8 uint
  end
end
`

func groupsEngine(t *testing.T) *Engine {
	t.Helper()
	eng := New()
	for _, m := range []string{testCore, groupsModule} {
		if err := eng.LoadModel([]byte(m), "model"); err != nil {
			t.Fatalf("LoadModel: %v", err)
		}
	}
	for _, def := range []string{groupsJSON, groupsXML, groupsPB, groupsBits} {
		if err := eng.LoadPack([]byte(def), "pack"); err != nil {
			t.Fatalf("LoadPack: %v", err)
		}
	}
	return eng
}

func TestGroupsDecodeAndLists(t *testing.T) {
	eng := groupsEngine(t)
	ent, err := eng.Decode("gj", []byte(`{"id":"u","items":[{"name":"a","n":2,"subs":[{"v":5},{"v":6}],"extra":1},{}],"nums":[]}`))
	if err != nil {
		t.Fatal(err)
	}
	items, ok := ent.List("g.items")
	if !ok || len(items) != 2 {
		t.Fatalf("g.items: %d item(s), present %v", len(items), ok)
	}
	if v := items[0].Fields["g.name"]; v.S != "a" {
		t.Errorf("items[0] name = %q", v.S)
	}
	if subs, ok := items[0].List("g.subs"); !ok || len(subs) != 2 || subs[1].Fields["g.n"].I != 6 {
		t.Errorf("items[0] subs = %v, present %v", subs, ok)
	}
	if _, ok := items[1].List("g.subs"); ok {
		t.Error("items[1] must have no list subs")
	}
	if len(items[1].Fields) != 0 {
		t.Errorf("an empty item holds no keys, got %v", items[1].Fields)
	}
	// Present and empty is distinct from absent.
	if nums, ok := ent.List("g.nums"); !ok || len(nums) != 0 {
		t.Errorf("g.nums: %d item(s), present %v; want present and empty", len(nums), ok)
	}
	if _, ok := ent.List("g.subs"); ok {
		t.Error("the entity itself has no list subs")
	}
	if len(ent.Residue) != 0 {
		t.Errorf("items carry no residue, got %v", ent.Residue)
	}
}

func TestGroupsConvertAcrossWires(t *testing.T) {
	eng := groupsEngine(t)
	in := `{"id":"u","items":[{"name":"a","n":2,"subs":[{"v":5},{"v":6}]},{"name":"b"}],"nums":[3,270]}`
	cases := []struct{ from, to, in, want string }{
		// Same format: the per-item default and const are written.
		{"gj", "gj", in, `{"id":"u","items":[{"name":"a","n":2,"k":"i","subs":[{"v":5},{"v":6}]},{"name":"b","n":1,"k":"i"}],"nums":[3,270]}`},
		{"gj", "gx", in, `<m id="u"><body><item name="a">2<sub v="5"/><sub v="6"/></item><item name="b"/></body><n>3</n><n>270</n></m>`},
		// Occurrences of one field number stay together; scalars are packed.
		{"gj", "gp", in, "0a0175120d" + "0a01611002" + "1a020805" + "1a020806" + "12030a0162" + "1a03038e02"},
		// The count is written over the field on its bits; an item ends where
		// its nested counted group ends.
		{"gj", "gb", in, "02" + "02020506" + "0000"},
		{"gb", "gj", "0202020506" + "0000", `{"items":[{"n":2,"k":"i","subs":[{"v":5},{"v":6}]},{"n":0,"k":"i","subs":[]}]}`},
		{"gx", "gj", `<m id="u"><n>1</n><x/><n>2</n><body><item name="a">7</item></body><body><item/></body></m>`, `{"id":"u","items":[{"name":"a","n":7,"k":"i"}],"nums":[1,2]}`},
		// Unpacked and packed occurrences of a repeated scalar both decode.
		{"gp", "gj", "1801" + "1a020203" + "1804", `{"nums":[1,2,3,4]}`},
		// An empty list writes `[]` on json and nothing on xml and protobuf.
		{"gj", "gj", `{"items":[],"nums":[]}`, `{"items":[],"nums":[]}`},
		{"gj", "gx", `{"items":[],"nums":[]}`, `<m/>`},
		{"gj", "gp", `{"items":[],"nums":[]}`, ``},
	}
	for _, c := range cases {
		out, err := eng.Convert(c.from, c.to, []byte(c.in))
		if err != nil || string(out) != c.want {
			t.Errorf("%s -> %s %s:\n got: %s (%v)\nwant: %s", c.from, c.to, c.in, out, err, c.want)
		}
	}
	errs := []struct {
		from, to, in string
		kind         ErrorKind
	}{
		{"gj", "gj", `{"items":{}}`, ErrMalformedWire},             // the member is not an array
		{"gj", "gj", `{"items":[{"n":"x"}]}`, ErrTransformDecode},  // an item field fails
		{"gj", "gj", `{"nums":[1,{}]}`, ErrTransformDecode},        // `.` on an object
		{"gp", "gp", "1a020180", ErrMalformedWire},                 // packed varints cut short
		{"gp", "gp", "1005", ErrMalformedWire},                     // an item that is not a submessage
		{"gb", "gb", "0101", ErrMalformedWire},                     // input ends inside the items
		{"gb", "gb", "01010201", ErrMalformedWire},                 // input ends inside the nested items
		{"gj", "gb", `{"items":[{"n":1,"subs":[{"v":300}]}]}`, ""}, // uint keeps the low bits
		{"gj", "gb", `{"nums":[1]}`, ""},                           // a list the target does not map
		{"gj", "gb", bigItems(256), ErrTransformEncode},            // the count does not fit
	}
	for _, c := range errs {
		_, err := eng.Convert(c.from, c.to, []byte(c.in))
		if c.kind == "" {
			if err != nil {
				t.Errorf("%s -> %s %.40s: %v", c.from, c.to, c.in, err)
			}
			continue
		}
		if err == nil || !IsKind(err, c.kind) || !strings.HasPrefix(err.Error(), string(c.kind)+":") {
			t.Errorf("%s -> %s %.40s: got %v, want %s", c.from, c.to, c.in, err, c.kind)
		}
	}
}

func bigItems(n int) string {
	return `{"items":[` + strings.TrimSuffix(strings.Repeat("{},", n), ",") + `]}`
}

func TestGroupsEncodeFromEntity(t *testing.T) {
	eng := groupsEngine(t)
	ent := NewEntity()
	ent.Fields["uid"] = Value{Kind: KindString, S: "u"}
	it := NewItem()
	it.Fields["g.name"] = Value{Kind: KindString, S: "a"}
	it.SetList("g.subs", nil)
	ent.SetList("g.items", []*Item{it})
	out, err := eng.Encode("gj", ent)
	if err != nil || string(out) != `{"id":"u","items":[{"name":"a","n":1,"k":"i","subs":[]}]}` {
		t.Errorf("encode: %s, %v", out, err)
	}
}

func TestGroupsModelKeysAndRequires(t *testing.T) {
	eng := groupsEngine(t)
	keys, _ := eng.ModelKeys("gj")
	want := "uid,g.items[],g.items[].g.name,g.items[].g.n,g.items[].g.subs[],g.items[].g.subs[].g.n,g.nums[],g.nums[].g.n"
	if strings.Join(keys, ",") != want {
		t.Errorf("model keys:\n got %s\nwant %s", strings.Join(keys, ","), want)
	}
	def := "format gk\nwire json\n" + groupsHead + "field uid id string\nkind listed\nwhen s 1\nrequires g.items\ngroup g.items items\n  field g.name name string\nend\nkind bare\nwhen s 2\n"
	if err := eng.LoadPack([]byte(def), "pack"); err != nil {
		t.Fatal(err)
	}
	for in, want := range map[string]string{
		`{"items":[{"name":"a"}]}`: `{"s":1,"items":[{"name":"a"}]}`,
		`{"items":[]}`:             `{"s":2}`, // present and empty does not satisfy requires
		`{}`:                       `{"s":2}`,
	} {
		if out, err := eng.Convert("gj", "gk", []byte(in)); err != nil || string(out) != want {
			t.Errorf("gj -> gk %s: %s, %v; want %s", in, out, err, want)
		}
	}
}

func TestGroupLoadErrors(t *testing.T) {
	bits := "format a\nwire bits\nword_bytes 1\n" + groupsHead
	json := "format a\nwire json\n" + groupsHead
	cases := []struct {
		name, def string
		kind      ErrorKind
	}{
		{"no end", json + "group g.items items\n  field g.n n int\n", ErrBadDirective},
		{"end with no group", json + "end\n", ErrBadDirective},
		{"when in a group", json + "kind k\ngroup g.items items\n  when n 1\nend\n", ErrBadDirective},
		{"map in a group", json + "group g.items items\n  map t 1 a\nend\n", ErrBadDirective},
		{"count on json", json + "group g.items items count 2\n  field g.n n int\nend\n", ErrBadDirective},
		{"dot outside a group", json + "field g.n . int\n", ErrBadDirective},
		{"list mapped twice", json + "group g.items a\nend\ngroup g.items b\nend\n", ErrBadDirective},
		{"undeclared list", json + "group g.things a\nend\n", ErrUndeclaredKey},
		{"group names a key", json + "group g.n a\nend\n", ErrKeyTypeMismatch},
		{"field names a list", json + "field g.items a string\n", ErrKeyTypeMismatch},
		{"default names a list", json + "field uid id string\ndefault g.items 1\n", ErrKeyTypeMismatch},
		{"bits group without count", bits + "group g.items 0:8 item 8\n  field g.n 0:0:8 uint\nend\n", ErrBadDirective},
		{"bits group without item", bits + "group g.items 0:8 count 2\n  field g.n 0:0:8 uint\nend\n", ErrBadDirective},
		{"field beyond a counted group", bits + "group g.items 0:8 item 8 count 0:0:8\n  field g.n 0:0:8 uint\nend\nfield g.n 0:8:8 uint\n", ErrBadDirective},
		{"count locator reaching the start", bits + "group g.items 0:4 item 8 count 0:0:8\n  field g.n 0:0:8 uint\nend\n", ErrBadDirective},
		{"item field beyond item bits", bits + "group g.items 0:8 item 8 count 2\n  field g.n 0:4:8 uint\nend\n", ErrBadDirective},
		{"const present", json + "field uid id string\nconst m present\n", ErrBadDirective},
	}
	for _, c := range cases {
		eng := New()
		for _, m := range []string{testCore, groupsModule} {
			if err := eng.LoadModel([]byte(m), "model"); err != nil {
				t.Fatal(err)
			}
		}
		err := eng.LoadPack([]byte(c.def), "pack")
		if err == nil || !IsKind(err, c.kind) {
			t.Errorf("%s: got %v, want %s", c.name, err, c.kind)
		}
	}
	// A list shares the key namespace of its module.
	for _, lines := range []string{"list n\n", "list items\n", "key items string -\n"} {
		if err := New().LoadModel([]byte(groupsModule+lines), "model"); !IsKind(err, ErrDuplicateKey) {
			t.Errorf("%q: got %v, want duplicate-key", lines, err)
		}
	}
}

// TestRulingsOf06 covers the rulings of 0.6 that changed behaviour.
func TestRulingsOf06(t *testing.T) {
	head := "module core\nversion 0.1.0\ndistribution public\nsource s\nkey a string -\nkey b string -\nkey n int -\nkey m int -\n"
	eng := New()
	// Ruling 7: `join` takes one or more arguments. Ruling 8: an integer
	// offset that overflows leaves the target absent.
	if err := eng.LoadModel([]byte(head+"derive b join:- a\nderive m offset:9223372036854775807 n\n"), "core.def"); err != nil {
		t.Fatal(err)
	}
	ent := NewEntity()
	ent.Fields["a"] = Value{Kind: KindString, S: "x"}
	ent.Fields["n"] = Value{Kind: KindInt, I: 5}
	eng.Complete(ent)
	if v, ok := ent.Get("b"); !ok || v.S != "x" {
		t.Errorf("join of one argument: %q, present %v", v.S, ok)
	}
	if _, ok := ent.Get("m"); ok {
		t.Error("an integer offset that overflows must leave the target absent")
	}
	// Ruling 9: a derive line the file alone refuses comes before
	// missing-distribution; the checks of its keys come after (0.8 ruling 29).
	err := New().LoadModel([]byte("module core\nversion 0.1.0\nsource s\nkey a string -\nderive a nosuchfn a\n"), "core.def")
	if !IsKind(err, ErrBadDirective) {
		t.Errorf("derive line error before missing-distribution: got %v", err)
	}
	err = New().LoadModel([]byte("module core\nversion 0.1.0\nsource s\nkey a string -\nderive a copy zz\n"), "core.def")
	if !IsKind(err, ErrMissingDistribution) {
		t.Errorf("missing-distribution before the derive key checks: got %v", err)
	}
	// Ruling 4: a line whose transform succeeds and whose table has no entry
	// for a value of another type fails the decode, whatever a later line of
	// the key gives; ruling 5: a line whose transform fails is forgiven.
	def := "format r\nwire json\nversion 1.0.0\ndistribution public\nsource s\nfield n w string via t\nfield n w2 int\nmap t one 1\n"
	if err := eng.LoadPack([]byte(def), "pack"); err != nil {
		t.Fatal(err)
	}
	if _, err := eng.Decode("r", []byte(`{"w":"two","w2":2}`)); !IsKind(err, ErrTransformDecode) {
		t.Errorf("table miss of another type: got %v, want transform-decode", err)
	}
	if ent, err := eng.Decode("r", []byte(`{"w":5,"w2":2}`)); err != nil || ent.Fields["n"].I != 2 {
		t.Errorf("failed transform forgiven by a later line: %v, %v", ent, err)
	}
}
