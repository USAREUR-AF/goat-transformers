package goatxf

import (
	"strings"
	"testing"
)

// TestUperLoadRulings checks load points of spec 0.19 that no vector pins:
// the numbers of choice, alt and group … size lines (ruling 15), and lists
// in different alts and presence lines nested in an ext block (ruling 20).
func TestUperLoadRulings(t *testing.T) {
	head := "format p\nversion 1\ndistribution public\nsource \"s\"\nwire bits\nlayout sequential\nbit_order msb\nencoding uper\n"
	cases := []struct {
		name, body string
		bad        bool
	}{
		{"list in two alts", "choice 2\n  alt 0\n    group items size 0 3\n      field r int:0:3 uint\n    end\n  alt 1\n    group items size\n      field r int:0:3 uint\n    end\nend\n", false},
		{"list twice in one alt", "choice 2\n  alt 0\n    group items size 0 3\n      field r int:0:3 uint\n    end\n    group items size\n      field r int:0:3 uint\n    end\n  alt 1\nend\n", true},
		{"list in an alt and outside the choice", "group items size\n  field r int:0:3 uint\nend\nchoice 1\n  alt 0\n    group items size\n      field r int:0:3 uint\n    end\nend\n", true},
		{"presence nested in an ext block", "ext\n  field a int:0:3 uint\n  opt\n    presence q 1\n    if q.1\n      field b int:0:3 uint\n    end\n  end\nend\n", false},
		{"alt with a leading zero", "choice 2\n  alt 01\nend\n", true},
		{"choice with a leading zero", "choice 02\n  alt 0\nend\n", true},
		{"choice with a sign", "choice -1\n  alt 0\nend\n", true},
		{"group size with a sign", "group items size -0 3\n  field r int:0:3 uint\nend\n", true},
		{"group size with a leading zero", "group items size 0 03\n  field r int:0:3 uint\nend\n", true},
	}
	for _, c := range cases {
		_, err := ParsePack([]byte(head+c.body), c.name)
		switch {
		case c.bad && (err == nil || !strings.HasPrefix(err.Error(), "bad-directive:")):
			t.Errorf("%s: got %v, want bad-directive", c.name, err)
		case !c.bad && err != nil:
			t.Errorf("%s: %v", c.name, err)
		}
	}
}

// TestUperLineOrder checks where the UPER lines meet the line checks of
// ruling 5b of 0.11: what 0.19 checks after the file is read stands behind a
// later line's error, and the argument counts and transform parameters are
// line checks.
func TestUperLineOrder(t *testing.T) {
	h := "format p\nversion 1\ndistribution public\nsource \"s\"\n"
	uper := h + "wire bits\nlayout sequential\nbit_order msb\nencoding uper\n"
	seq := h + "wire bits\nlayout sequential\nbit_order msb\n"
	fixed := h + "wire bits\nword_bytes 4\nbit_order msb\n"
	js := h + "wire json\n"
	cases := []struct{ name, text, kind string }{
		{"encoding on json", js + "encoding uper\nbogus\n", "unknown-directive"},
		{"encoding other value", seq + "encoding foo\nbogus\n", "unknown-directive"},
		{"encoding twice", uper + "encoding uper\nbogus\n", "unknown-directive"},
		{"encoding in a fixed pack", fixed + "encoding uper\nbogus\n", "unknown-directive"},
		{"encoding with no argument", seq + "encoding\n", "bad-directive"},
		{"encoding with two arguments", seq + "encoding uper none\n", "bad-directive"},
		{"int locator without encoding", seq + "field n int:0:255 uint\nbogus\n", "unknown-directive"},
		{"int locator in a fixed pack", fixed + "field n int:0:255 uint\nbogus\n", "unknown-directive"},
		{"int locator in a fixed pack alone", fixed + "field n int:0:255 uint\n", "bad-directive"},
		{"ext on json", js + "ext\nend\nbogus\n", "unknown-directive"},
		{"ext on json alone", js + "ext\nend\n", "bad-directive"},
		{"choice on json", js + "choice 2\nalt 0\nfield y y int\nend\nbogus\n", "unknown-directive"},
		{"choice with three arguments", js + "choice 2 ext x\n", "bad-directive"},
		{"ext with an argument", uper + "ext 1\nend\n", "bad-directive"},
		{"alt with no argument", uper + "choice 1\nalt\nend\n", "bad-directive"},
		{"another transform", uper + "field n int:0:255 f32\nbogus\n", "unknown-directive"},
		{"scale parameters", uper + "field n int:0:255 uscale:0\nbogus\n", "bad-directive"},
		{"unknown transform", uper + "field n int:0:255 nosuch\n", "unknown-transform"},
		{"locator numbers", uper + "field n int:5:3 uint\nbogus\n", "unknown-directive"},
		{"absent on a UPER locator", uper + "field n int:0:255 uint absent 0\nbogus\n", "unknown-directive"},
		{"alt repeated", uper + "choice 2\nalt 0\nalt 0\nend\nbogus\n", "unknown-directive"},
		{"alt outside a choice", uper + "alt 0\nbogus\n", "unknown-directive"},
		{"alt outside a choice alone", uper + "alt 0\n", "bad-directive"},
		{"choice with no alt", uper + "choice 2\nend\nbogus\n", "unknown-directive"},
		{"choice with no alt alone", uper + "choice 2\nend\n", "bad-directive"},
		{"line before the first alt", uper + "choice 2\nfield n int:0:7 uint\ngroup l size\nfield m 8 uint\nend\nalt 0\nend\nbogus\n", "unknown-directive"},
		{"line before the first alt alone", uper + "choice 2\nfield n int:0:7 uint\nalt 0\nend\n", "bad-directive"},
		{"swap on a UPER locator", uper + "field n int:0:255 uint swap\nbogus\n", "unknown-directive"},
		// The value transforms of 0.15 are known transforms a UPER locator
		// does not take: bad-directive after the file (0.19, Transforms on
		// UPER locators; ruling 19).
		{"0.15 smag on int", uper + "field n int:0:255 smag\n", "bad-directive"},
		{"0.15 smag on int then bogus", uper + "field n int:0:255 smag\nbogus\n", "unknown-directive"},
		{"0.15 uiscale on int", uper + "field n int:0:255 uiscale:10\n", "bad-directive"},
		{"0.15 chars set on chars", uper + "field s chars:0:8 chars:ascii7\n", "bad-directive"},
		{"0.15 octal on enum", uper + "field e enum:3 octal\n", "bad-directive"},
		{"0.15 iscale on octets", uper + "field o octets: iscale:10\n", "bad-directive"},
		{"0.15 unknown character set", uper + "field s chars:0:8 chars:nosuch\nbogus\n", "bad-directive"},
		// A fraction factor is unsigned on every wire (0.15 ruling 25).
		{"signed fraction on int", uper + "field n int:0:255 sscale:-1/10\nbogus\n", "bad-directive"},
		// The UPER lines are not lines of a 0.17 gate block: bad-directive
		// after the file, in a fixed-layout pack.
		{"ext in a gate block", fixed + "if 0:0:2 1\next\nend\nend\n", "bad-directive"},
		{"ext in a gate block then bogus", fixed + "if 0:0:2 1\next\nend\nend\nbogus\n", "unknown-directive"},
		{"choice in a gate block", fixed + "if 0:0:2 1\nchoice 1\nalt 0\nend\nend\n", "bad-directive"},
		{"int locator in a gate block", fixed + "if 0:0:2 1\nfield n int:0:7 uint\nend\n", "bad-directive"},
	}
	for _, c := range cases {
		_, err := ParsePack([]byte(c.text), c.name)
		if err == nil || !strings.HasPrefix(err.Error(), c.kind+":") {
			t.Errorf("%s: got %v, want %s", c.name, err, c.kind)
		}
	}
}

// TestUperSequentialIf checks that in a UPER pack, a sequential pack, `if`
// is the presence block of 0.8, not a gate of 0.17, and that a bit-length
// field there takes the value transforms of 0.15 (ruling 3 of 0.15).
func TestUperSequentialIf(t *testing.T) {
	text := "format p\nversion 1\ndistribution public\nsource \"s\"\nwire bits\nlayout sequential\nbit_order msb\nencoding uper\n" +
		"kind k\nfield t 8 uint\npresence p 1\nif p.1\n  field a int:0:7 uint\nend\nfield s 7 smag\nfield c 12 chars:icao6\n"
	if _, err := ParsePack([]byte(text), "seq-if"); err != nil {
		t.Fatalf("UPER pack with a 0.8 if and 0.15 transforms: %v", err)
	}
}
