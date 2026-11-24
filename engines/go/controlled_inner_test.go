//go:build !goat_wires || goat_wire_bits

package goatxf

import (
	"reflect"
	"testing"
)

// Spec 0.93 with 0.34: a controlled inner pack never loads. The outer pack
// is public; the pack its `inner` line names is either not shown public or
// public and using a controlled module. Under a profile it is skipped, and
// with no profile and a limit of public its load is refused.

const innerTestHead = "version 0.93.0\n" + ctlSource + "wire bits\nlayout sequential\nbit_order msb\n"

func innerTestModule(name, dist, key string) string {
	return ctlModule(name, dist) + "key " + key + " int - \"a test key\"\n"
}

// innerTestTree is a tree with the outer pack c-outer, whose inner line
// names c-in, whose pack.def is innerDef; each in the directory of its name.
func innerTestTree(t *testing.T, innerDef string) (models, packs string) {
	root := ctlTree(t, map[string]string{
		"model/core.def": ctlCore,
		"model/g.def":    innerTestModule("g", "public", "n"),
		"model/g2.def":   innerTestModule("g2", "public", "m"),
		"model/ctl.def":  innerTestModule("ctl", "controlled", "x"),
		"packs/c-outer/pack.def": "format c-outer\ndistribution public\nuses g\n" + innerTestHead +
			"field g.n 8 uint\ninner c-in\n",
		"packs/c-in/pack.def": innerDef,
	})
	return dirs(root)
}

// The inner packs: (a) not shown public, in two forms (one the parser reads
// as public); (b) public, using a controlled module.
var innerTestCases = []struct {
	name, def    string
	limitRefuses bool // with no profile and a limit of public
}{
	{"a-controlled", "format c-in\ndistribution controlled\nuses g2\n" + innerTestHead + "field g2.m 8 uint\n", true},
	{"a-quoted-public", "format c-in\n\"distribution\" public\nuses g2\n" + innerTestHead + "field g2.m 8 uint\n", false},
	{"b-uses-controlled", "format c-in\ndistribution public\nuses g2\nuses ctl\n" + innerTestHead + "field g2.m 8 uint\nfield ctl.x 8 uint\n", true},
}

func TestControlledInnerPackUnderAProfile(t *testing.T) {
	for _, c := range innerTestCases {
		models, packs := innerTestTree(t, c.def)
		names := WithInnerPacks(packs, []string{"c-outer"})
		if !reflect.DeepEqual(names, []string{"c-outer", "c-in"}) {
			t.Fatalf("%s: the packs to load %v, want [c-outer c-in]", c.name, names)
		}
		for _, profile := range []string{"open", "open+copyleft", "everything"} {
			for _, limit := range []string{DistControlled, DistPublic} {
				e, err := LoadToolProfile(models, packs, limit, names, profile)
				if err != nil {
					t.Errorf("%s %s %s: %v", c.name, profile, limit, err)
					continue
				}
				if got := formatNames(e); !reflect.DeepEqual(got, []string{"c-outer"}) {
					t.Errorf("%s %s %s: formats %v, want [c-outer]", c.name, profile, limit, got)
				}
				if got, err := e.ModelKeys("c-outer"); err != nil || !reflect.DeepEqual(got, []string{"g.n"}) {
					t.Errorf("%s %s %s: model_keys(c-outer) %v, %v; want [g.n] and no error", c.name, profile, limit, got, err)
				}
				for _, format := range []string{"c-outer", "c-in"} {
					if _, err := e.Decode(format, []byte("0507")); !IsKind(err, ErrUnknownFormat) {
						t.Errorf("%s %s %s: decode %s: %v, want unknown-format", c.name, profile, limit, format, err)
					}
					ent := NewEntity()
					ent.Fields["g.n"] = Value{Kind: KindInt, I: 5}
					ent.Fields["g2.m"] = Value{Kind: KindInt, I: 7}
					if _, err := e.Encode(format, ent); !IsKind(err, ErrUnknownFormat) {
						t.Errorf("%s %s %s: encode %s: %v, want unknown-format", c.name, profile, limit, format, err)
					}
				}
				if _, err := e.Capability("c-outer", "c-outer"); err != nil {
					t.Errorf("%s %s %s: capability: %v", c.name, profile, limit, err)
				}
			}
		}
	}
}

func TestControlledInnerPackUnderAPublicLimit(t *testing.T) {
	for _, c := range innerTestCases {
		models, packs := innerTestTree(t, c.def)
		names := WithInnerPacks(packs, []string{"c-outer"})
		e, err := LoadPacksOnly(models, packs, DistPublic, names)
		e2, err2 := LoadToolProfile(models, packs, DistPublic, names, "")
		if !c.limitRefuses {
			// The parser reads the quoted line as public: with no profile
			// nothing of 0.93 is read, and the pack loads. (LoadToolProfile
			// loads every module, and refuses ctl.)
			if err != nil || !reflect.DeepEqual(formatNames(e), []string{"c-in", "c-outer"}) {
				t.Errorf("%s: %v, want both packs loaded", c.name, err)
			} else {
				// The fixture works when the inner pack is loaded.
				if _, derr := e.Decode("c-outer", []byte("0507")); derr != nil {
					t.Errorf("%s: decode c-outer with the inner pack loaded: %v", c.name, derr)
				}
				if got, _ := e.ModelKeys("c-outer"); !reflect.DeepEqual(got, []string{"g.n", "g2.m"}) {
					t.Errorf("%s: model_keys(c-outer) %v with the inner pack loaded, want [g.n g2.m]", c.name, got)
				}
			}
			if !IsKind(err2, ErrDistributionRefused) {
				t.Errorf("%s: LoadToolProfile %v, want distribution-refused for module ctl", c.name, err2)
			}
			continue
		}
		if !IsKind(err, ErrDistributionRefused) || e != nil {
			t.Errorf("%s: LoadPacksOnly %v, want distribution-refused and nothing loaded", c.name, err)
		}
		if !IsKind(err2, ErrDistributionRefused) || e2 != nil {
			t.Errorf("%s: LoadToolProfile %v, want distribution-refused and nothing loaded", c.name, err2)
		}
	}
}
