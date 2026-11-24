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

// A count line's number of items (0.21, 0.31) is checked against the budget
// the outer lines left, though the list is discarded (7d of 0.11, spec 0.34
// ruling 7).
func TestInnerCountRefBudget(t *testing.T) {
	for _, body := range []string{
		"count a 8\ncount b 8\ngroup g.items count @a @b\n  field g.n 8 uint\nend\n",
		"count a 8\npad 8\ngroup g.items count @a\n  field g.n 8 uint\nend\n",
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

// Replacing a discarded list, or a list inside its items, releases nothing:
// those items were never held (7g of 0.11, spec 0.34 ruling 7).
func TestInnerDiscardedReplaceKeepsBudget(t *testing.T) {
	body := `presence p 8
if p.1
  group g.items count 8
    field g.n 8 uint
  end
end
if p.2
  group g.items count 8
    field g.n 8 uint
  end
end
group g.subs while
  pad 7
end
`
	// One outer item, one and one discarded inner items, then two subs:
	// three items held.
	const msg = "0107c001080109" + "8080" + "00"
	if k := innerBudgetKind(t, body, msg, 3); k != "" {
		t.Errorf("limit 3: %s, want none", k)
	}
	if k := innerBudgetKind(t, body, msg, 2); k != ErrMalformedWire {
		t.Errorf("limit 2: %q, want malformed-wire", k)
	}
}

// An outer list read after the inner list of its name is discarded; its items
// are read and never held (7g of 0.11, spec 0.34 Decode step 4).
func TestInnerListKeptOuterItemsNotCounted(t *testing.T) {
	outer := "length 8\n  inner i\nend\ngroup g.items while\n  pad 7\n  field g.n 8 uint\nend\n"
	inner := "group g.items count 8\n  field g.n 8 uint\nend\n"
	// Two inner items, then two outer items that are discarded.
	const msg = "03020708" + "8009" + "800a" + "00"
	if k := innerBudgetKindOf(t, outer, inner, msg, 2); k != "" {
		t.Errorf("limit 2: %s, want none", k)
	}
	if k := innerBudgetKindOf(t, outer, inner, msg, 1); k != ErrMalformedWire {
		t.Errorf("limit 1: %q, want malformed-wire", k)
	}
}

// A line whose transform succeeds and whose table has no entry, the types
// differing, is an error in a discarded list of either pack and when the
// other pack gave the key; a failed transform is not (0.34 rulings 21, 23).
func TestInnerMissingEntry(t *testing.T) {
	const table = "map t 1 one\n"
	const plainList = "group g.items count 8\n  field g.s 8 ascii\nend\n"
	const viaList = table + "group g.items count 8\n  field g.s 8 uint via t\nend\n"
	const plain = "field g.s 8 ascii\n"
	const via = table + "field g.s 8 uint via t\n"
	const innerFirst = "length 8\n  inner i\nend\n"
	for _, c := range []struct {
		name, outer, inner, msg string
		want                    ErrorKind
	}{
		{"inner list discarded, no entry", plainList + "inner i\n", viaList, "0141" + "0102", ErrTransformDecode},
		{"inner list discarded, entry", plainList + "inner i\n", viaList, "0141" + "0101", ""},
		{"inner list discarded, failed transform", plainList + "inner i\n", plainList, "0141" + "01ff", ""},
		{"outer list discarded, no entry", innerFirst + viaList, plainList, "02" + "0141" + "0102", ErrTransformDecode},
		{"outer list discarded, entry", innerFirst + viaList, plainList, "02" + "0141" + "0101", ""},
		{"outer list discarded, failed transform", innerFirst + plainList, plainList, "02" + "0141" + "01ff", ""},
		{"nested in a discarded list, no entry", plainList + "inner i\n", table + "group g.items count 8\n  group g.subs count 8\n    field g.v 8 uint via t\n  end\nend\n", "0141" + "010102", ErrTransformDecode},
		{"inner key after outer, no entry", plain + "inner i\n", via, "4102", ErrTransformDecode},
		{"inner key after outer, entry", plain + "inner i\n", via, "4101", ""},
		{"outer key after inner, no entry", innerFirst + via, plain, "01" + "41" + "02", ErrTransformDecode},
		{"outer key after inner, entry", innerFirst + via, plain, "01" + "41" + "01", ""},
		{"outer key after inner, failed transform", innerFirst + plain, plain, "01" + "41" + "ff", ""},
	} {
		if k := innerBudgetKindOf(t, c.outer, c.inner, c.msg, 100); k != c.want {
			t.Errorf("%s: %q, want %q", c.name, k, c.want)
		}
	}
}
