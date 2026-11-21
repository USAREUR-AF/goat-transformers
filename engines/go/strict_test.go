package goatxf

import (
	"math"
	"testing"
)

// The grammars of ruling 2 of 0.11.
func TestNumberGrammars(t *testing.T) {
	for _, s := range []string{"0", "-0", "007", "-9223372036854775808", "9223372036854775807"} {
		if _, err := parseIntText(s); err != nil {
			t.Errorf("integer text %q refused: %v", s, err)
		}
	}
	for _, s := range []string{"", "+1", " 1", "1 ", "1.0", "1e3", "9223372036854775808", "-", "٣"} {
		if _, err := parseIntText(s); err == nil {
			t.Errorf("integer text %q accepted", s)
		}
	}
	for _, s := range []string{"+1", ".5", "5.", "0x10", "Infinity", "NaN", " 1", "1e400", "1.7976931348623159e308", "1e", "1_0"} {
		if _, err := parseNumberText(s); err == nil {
			t.Errorf("number text %q accepted", s)
		}
	}
	if f, err := parseNumberText("-1e-400"); err != nil || f != 0 || !math.Signbit(f) {
		t.Errorf("-1e-400 reads as %v (%v), want -0", f, err)
	}
	if f, err := parseNumberText("1e-400"); err != nil || f != 0 || math.Signbit(f) {
		t.Errorf("1e-400 reads as %v (%v), want 0", f, err)
	}
	for in, want := range map[string]int64{"1.0": 1, "1e3": 1000, "9.223372036854775807e18": math.MaxInt64, "-0.0e5": 0, "12300e-2": 123} {
		if got, err := exactInt(in); err != nil || got != want {
			t.Errorf("exactInt(%q) = %d (%v), want %d", in, got, err, want)
		}
	}
	for _, in := range []string{"1.5", "1e-1", "9.223372036854775808e18", "1e999999999999", "1e-999999999999"} {
		if _, err := exactInt(in); err == nil {
			t.Errorf("exactInt(%q) accepted", in)
		}
	}
	for in, want := range map[float64]string{1e21: "1000000000000000000000", 1e-7: "0.0000001", math.Copysign(0, -1): "0", 0.5: "0.5"} {
		if got, _ := formatFloat(in); got != want {
			t.Errorf("formatFloat(%v) = %s, want %s", in, got, want)
		}
	}
}

// The grammar and the range of iso8601_ms (ruling 3 of 0.11).
func TestISO8601Ruling(t *testing.T) {
	for in, want := range map[string]int64{
		"1970-01-01T00:00:00Z":           0,
		"1969-12-31T23:59:59.9999Z":      -1,
		"1970-01-01t00:00:00.5z":         500,
		"1970-01-01T01:00:00+01:00":      0,
		"1970-01-01T00:00:00-00:00":      0,
		"0001-01-01T00:00:00.000Z":       minISOms,
		"9999-12-31T23:59:59.999Z":       maxISOms,
		"2000-02-29T00:00:00Z":           951782400000,
		"2021-02-27T20:00:00.123456789Z": 1614456000123,
	} {
		if got, err := parseISO(in); err != nil || got != want {
			t.Errorf("parseISO(%q) = %d (%v), want %d", in, got, err, want)
		}
	}
	for _, in := range []string{
		"1970-01-01", "1970-01-01T00:00Z", "1970-01-01 00:00:00Z", "1970-01-01T00:00:00,5Z",
		"1970-01-01T00:00:00.Z", "1970-01-01T00:00:00+0100", "1970-01-01T00:00:00+01", "1970-01-01T00:00:00",
		"+1970-01-01T00:00:00Z", "19700101T000000Z", "1970-01-01T00:00:60Z", "1970-01-01T24:00:00Z",
		"1900-02-29T00:00:00Z", "0000-01-01T00:00:00Z", "0001-01-01T00:00:00+00:01", " 1970-01-01T00:00:00Z",
	} {
		if _, err := parseISO(in); err == nil {
			t.Errorf("parseISO(%q) accepted", in)
		}
	}
	if s, err := formatISO(-1); err != nil || s != "1969-12-31T23:59:59.999Z" {
		t.Errorf("formatISO(-1) = %s (%v)", s, err)
	}
	if _, err := formatISO(maxISOms + 1); err == nil {
		t.Error("formatISO above 9999 accepted")
	}
}

// Rounding and range of the scaled transforms (ruling 4 of 0.11).
func TestScaledRounding(t *testing.T) {
	for _, c := range []struct {
		q      float64
		length int
		signed bool
		want   uint64
		ok     bool
	}{
		{0.5, 8, false, 1, true},
		{2.5, 8, false, 3, true},
		{-0.5, 8, true, 0xff, true},
		{-2.5, 8, true, 0xfd, true},
		{math.Nextafter(0.5, 0), 8, false, 0, true},
		{-0.4, 8, false, 0, true},
		{255.4, 8, false, 255, true},
		{255.5, 8, false, 0, false},
		{127.5, 8, true, 0, false},
		{-128.5, 8, true, 0, false},
		{math.Inf(1), 8, true, 0, false},
		{math.NaN(), 8, true, 0, false},
	} {
		got, err := roundedFits(c.q, c.q, c.length, c.signed)
		if (err == nil) != c.ok || (c.ok && got != c.want) {
			t.Errorf("roundedFits(%v, %d, %v) = %#x (%v), want %#x ok=%v", c.q, c.length, c.signed, got, err, c.want, c.ok)
		}
	}
}

// Causes that are not line checks are reported after the file, in a
// sequential pack as in a fixed one (ruling 5b of 0.11).
func TestSequentialLateChecks(t *testing.T) {
	head := "format a\nversion 1\ndistribution public\nsource s\nwire bits\nlayout sequential\n"
	for _, body := range []string{
		"kind k\nfield uid 8 uint\nkind k\nbogus 1\n",
		"end\nbogus 1\n",
		"const 8 +1\nbogus 1\n",
		"kind k\nwhen 8 256\nbogus 1\n",
	} {
		if _, err := ParsePack([]byte(head+body), "test.def"); !IsKind(err, ErrUnknownDirective) {
			t.Errorf("%q: got %v, want unknown-directive", body, err)
		}
	}
	if _, err := ParsePack([]byte(head+"const 8 +1\n"), "test.def"); !IsKind(err, ErrBadDirective) {
		t.Errorf("const 8 +1: got %v, want bad-directive", err)
	}
}

// The encode of iso8601_s (0.26 ruling 3): the second that holds the
// instant, milliseconds dropped, and the range of iso8601_ms.
func TestISO8601SecondsEncode(t *testing.T) {
	for in, want := range map[int64]string{
		0:             "1970-01-01T00:00:00Z",
		999:           "1970-01-01T00:00:00Z",
		-1:            "1969-12-31T23:59:59Z",
		1709210096789: "2024-02-29T12:34:56Z",
		minISOms:      "0001-01-01T00:00:00Z",
		maxISOms:      "9999-12-31T23:59:59Z",
	} {
		if s, err := encISOSeconds(Value{Kind: KindInt, I: in}); err != nil || s != want {
			t.Errorf("encISOSeconds(%d) = %q (%v), want %q", in, s, err, want)
		}
	}
	for _, in := range []int64{minISOms - 1, maxISOms + 1} {
		if _, err := encISOSeconds(Value{Kind: KindInt, I: in}); err == nil {
			t.Errorf("encISOSeconds(%d) accepted", in)
		}
	}
}
