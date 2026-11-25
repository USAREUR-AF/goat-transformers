//go:build !goat_wires || goat_wire_bits

package goatxf

import "testing"

const innerBudgetModule = `module g
version 0.1.0
distribution public
source s
key n int -
key s string -
key v string -
list items
list subs
list more
`

const innerBudgetHead = "version 0.34.0\ndistribution public\nsource s\nuses g\nwire bits\nlayout sequential\nbit_order msb\n"

// innerBudgetKind decodes a message of the outer pack (one counted list, then
// the inner pack) under a limit and returns the kind of its error, "" for
// none.
func innerBudgetKind(t *testing.T, innerBody, message string, limit int64) ErrorKind {
	t.Helper()
	outer := "group g.items count 8\n  field g.n 8 uint\nend\ninner i\n"
	return innerBudgetKindOf(t, outer, innerBody, message, limit)
}

// innerBudgetKindOf is innerBudgetKind with the outer pack's lines given.
func innerBudgetKindOf(t *testing.T, outerBody, innerBody, message string, limit int64) ErrorKind {
	t.Helper()
	e := innerEngine(t, outerBody, innerBody)
	e.SetMaxItems(limit)
	_, err := e.Decode("o", []byte(message))
	if err == nil {
		return ""
	}
	if x, ok := err.(*Error); ok {
		return x.Kind
	}
	if _, ok := err.(*DecodeError); ok {
		return ErrTransformDecode
	}
	t.Fatalf("unexpected error %v", err)
	return ""
}

// innerEngine loads the outer pack o and the inner pack i with the lines given.
func innerEngine(t *testing.T, outerBody, innerBody string) *Engine {
	t.Helper()
	e := New()
	for _, text := range []string{testCore, innerBudgetModule} {
		m, err := ParseModule([]byte(text), "model")
		if err != nil {
			t.Fatal(err)
		}
		if err := e.AddModule(m); err != nil {
			t.Fatal(err)
		}
	}
	outer := "format o\n" + innerBudgetHead + outerBody
	for _, text := range []string{outer, "format i\n" + innerBudgetHead + innerBody} {
		p, err := ParsePack([]byte(text), "t")
		if err != nil {
			t.Fatal(err)
		}
		if err := e.AddPack(p); err != nil {
			t.Fatal(err)
		}
	}
	return e
}

// A count line's number of items (0.21, 0.31) is checked against the budget
// the outer lines left (7d of 0.11, spec 0.34 ruling 7).
func TestInnerCountRefBudget(t *testing.T) {
	for _, body := range []string{
		"count a 8\ncount b 8\ngroup g.subs count @a @b\n  field g.n 8 uint\nend\n",
		"count a 8\npad 8\ngroup g.subs count @a\n  field g.n 8 uint\nend\n",
	} {
		// One outer item, two inner items.
		const msg = "010702020809"
		if k := innerBudgetKind(t, body, msg, 3); k != "" {
			t.Errorf("limit 3: %s, want none", k)
		}
		if k := innerBudgetKind(t, body, msg, 2); k != ErrMalformedWire {
			t.Errorf("limit 2: %q, want malformed-wire", k)
		}
	}
}

// An inner group that replaces the list an earlier inner group gave releases
// the items it replaces (7g of 0.11); the budget is what the outer lines left.
func TestInnerReplaceReleasesBudget(t *testing.T) {
	body := `presence p 8
if p.1
  group g.subs count 8
    field g.n 8 uint
  end
end
if p.2
  group g.subs count 8
    field g.n 8 uint
  end
end
group g.more while
  pad 7
end
`
	// One outer item, one inner item and the one that replaces it, then two
	// of the other list: four items held.
	const msg = "0107c001080109" + "8080" + "00"
	if k := innerBudgetKind(t, body, msg, 4); k != "" {
		t.Errorf("limit 4: %s, want none", k)
	}
	if k := innerBudgetKind(t, body, msg, 3); k != ErrMalformedWire {
		t.Errorf("limit 3: %q, want malformed-wire", k)
	}
}

// A key or a list that the outer pack's lines in reach and the inner pack
// both map is bad-directive where the inner line is reached, on decode and on
// encode, whatever the values and the tables are (0.52 rulings 20 and 20b).
func TestInnerClash(t *testing.T) {
	const table = "map t 1 one\n"
	const plainList = "group g.items count 8\n  field g.s 8 ascii\nend\n"
	const viaList = table + "group g.items count 8\n  field g.s 8 uint via t\nend\n"
	const plain = "field g.s 8 ascii\n"
	const via = table + "field g.s 8 uint via t\n"
	const blockFirst = "length 8\n  inner i\nend\n"
	for _, c := range []struct {
		name, outer, inner, msg string
		want                    ErrorKind
	}{
		{"list before, no entry", plainList + "inner i\n", viaList, "0141" + "0102", ErrBadDirective},
		{"list before, entry", plainList + "inner i\n", viaList, "0141" + "0101", ErrBadDirective},
		{"list before, failed transform", plainList + "inner i\n", plainList, "0141" + "01ff", ErrBadDirective},
		{"list after, no entry", blockFirst + viaList, plainList, "02" + "0141" + "0102", ErrBadDirective},
		{"list after, entry", blockFirst + viaList, plainList, "02" + "0141" + "0101", ErrBadDirective},
		{"list after, failed transform", blockFirst + plainList, plainList, "02" + "0141" + "01ff", ErrBadDirective},
		{"list with a nested list", plainList + "inner i\n", table + "group g.items count 8\n  group g.subs count 8\n    field g.v 8 uint via t\n  end\nend\n", "0141" + "010102", ErrBadDirective},
		{"key before, no entry", plain + "inner i\n", via, "4102", ErrBadDirective},
		{"key before, entry", plain + "inner i\n", via, "4101", ErrBadDirective},
		{"key after, no entry", blockFirst + via, plain, "01" + "41" + "02", ErrBadDirective},
		{"key after, entry", blockFirst + via, plain, "01" + "41" + "01", ErrBadDirective},
		{"key after, failed transform", blockFirst + plain, plain, "01" + "41" + "ff", ErrBadDirective},
		{"list replaced by an outer group after", blockFirst + "group g.items while\n  pad 7\n  field g.n 8 uint\nend\n", "group g.items count 8\n  field g.n 8 uint\nend\n", "03020708" + "8009" + "800a" + "00", ErrBadDirective},
		// An item key and an entity key of one name are two entries, and so
		// are a list and the list of its name in the items of another.
		{"item key and entity key", plainList + "inner i\n", plain, "0141" + "42", ""},
		{"nested list and list", "group g.items count 8\n  group g.subs count 8\n    field g.n 8 uint\n  end\nend\ninner i\n", "group g.subs count 8\n  field g.n 8 uint\nend\n", "010105" + "0106", ""},
	} {
		if k := innerBudgetKindOf(t, c.outer, c.inner, c.msg, 100); k != c.want {
			t.Errorf("decode, %s: %q, want %q", c.name, k, c.want)
		}
		_, err := innerEngine(t, c.outer, c.inner).Encode("o", NewEntity())
		if c.want == "" && err != nil || c.want != "" && !IsKind(err, c.want) {
			t.Errorf("encode, %s: %v, want %q", c.name, err, c.want)
		}
	}
}

// Only the lines of the inner line's own kind and the common lines are in
// reach of an inner line in a kind; of one in the common lines every kind's
// are (0.52 ruling 20).
func TestInnerClashReach(t *testing.T) {
	const inner = "field g.n 8 uint\n"
	const otherKind = "kind a\nwhen 8 1\ninner i\nkind b\nwhen 8 2\nfield g.n 8 uint\n"
	const common = "length 8\n  inner i\nend\nkind a\nwhen 8 1\nkind b\nwhen 8 2\nfield g.n 8 uint\n"
	if k := innerBudgetKindOf(t, otherKind, inner, "0105", 100); k != "" {
		t.Errorf("inner in a kind, key of another kind: %s, want none", k)
	}
	if k := innerBudgetKindOf(t, common, inner, "010501", 100); k != ErrBadDirective {
		t.Errorf("inner in the common lines, key of a kind: %q, want bad-directive", k)
	}
}

// A whole length read in a length block ends the input for every block around
// it and for the message after them: a line that needs bits past it is
// malformed-wire, a rest list at message level is empty, and an inner line
// there has an empty input (0.8 ruling 8, 0.83 ruling 16, 0.34 ruling 3).
func TestWholeInBlockEndsInput(t *testing.T) {
	const block = "length 8\n  length 8 whole\nend\n"
	const rest = "group g.items rest\n  field g.n 8 uint\nend\n"
	const field = "field g.n 8 uint\n"
	for _, c := range []struct {
		name, outer, inner, msg string
		want                    ErrorKind
	}{
		{"line within a whole beyond the block", block + field, rest, "01" + "03" + "07", ""},
		{"inner within a whole beyond the block", block + "inner i\n", field, "01" + "03" + "07", ""},
		{"line past the whole in the block", "length 8\n  length 8 whole\n  field g.n 8 uint\nend\n", rest, "02" + "02" + "07", ErrMalformedWire},
		{"inner in a block that ends beyond the whole", "length 8\n  length 8 whole\n  inner i\nend\n", rest, "02" + "02" + "07", ErrMalformedWire},
		{"line past the whole", block + field, rest, "01" + "02" + "07", ErrMalformedWire},
		{"line past a block that runs past the whole", block + field, rest, "02" + "02" + "00" + "07", ErrMalformedWire},
		{"inner past the whole", block + "inner i\n", field, "01" + "02" + "07", ErrMalformedWire},
		{"inner past the whole reads no bytes", block + "inner i\n", rest, "02" + "02" + "00" + "0708", ""},
		{"nothing after the block", block, rest, "02" + "02" + "00" + "07", ""},
		{"whole in a block of a block", "length 8\n  " + block + "end\n" + field, rest, "02" + "01" + "03" + "07", ErrMalformedWire},
	} {
		if k := innerBudgetKindOf(t, c.outer, c.inner, c.msg, 100); k != c.want {
			t.Errorf("%s: %q, want %q", c.name, k, c.want)
		}
	}
	for _, outer := range []string{block + rest, block + "inner i\n"} {
		e := innerEngine(t, outer, rest)
		ent, err := e.Decode("o", []byte("02"+"02"+"00"+"0708"))
		if err != nil {
			t.Errorf("%q: %v", outer, err)
		} else if items, ok := ent.Lists["g.items"]; !ok || len(items) != 0 {
			t.Errorf("%q: the list holds %d item(s), present %v; want present and empty", outer, len(items), ok)
		}
	}
}
