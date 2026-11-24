package goatxf

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"
)

const packsDir = "../../packs"

type vector struct {
	Name        string            `json:"name"`
	From        string            `json:"from"`
	To          string            `json:"to"`
	Input       *string           `json:"input"`
	InputB64    *string           `json:"input_b64"`
	Expect      *string           `json:"expect"`
	ExpectB64   *string           `json:"expect_b64"`
	ExpectError *string           `json:"expect_error"`
	Model       map[string]any    `json:"model"`
	Context     map[string]string `json:"context"`
	MaxItems    *json.Number      `json:"max_items"` // Version 0.11: the limit on list items for this vector
	Source      string            `json:"source"`    // where the vector's bytes come from; not checked
	Reference   string            `json:"reference"` // not checked
}

func bytesOf(t *testing.T, text, b64 *string, what string) []byte {
	t.Helper()
	switch {
	case text != nil && b64 != nil:
		t.Fatalf("vector sets both %s and %s_b64", what, what)
	case text != nil:
		return []byte(*text)
	case b64 != nil:
		b, err := base64.StdEncoding.DecodeString(*b64)
		if err != nil {
			t.Fatalf("%s_b64: %v", what, err)
		}
		return b
	}
	t.Fatalf("vector has neither %s nor %s_b64", what, what)
	return nil
}

// kindKey is the `model` key that holds the kind name a decode must select;
// completeKey, set to true, moves the model checks to the completed entity.
const (
	kindKey      = "@kind"
	completeKey  = "@complete"
	absentKey    = "@absent"
	innerKindKey = "@inner_kind" // Version 0.34: the kind name Entity.inner_kind holds
)

// checkAbsent checks one entry of a vector's `"@absent"` list (spec 0.9,
// "Vector additions") and returns what is wrong, "" when the check passes. An
// entry `<list>[<i>].<key>` needs item i to exist and lack the key; any other
// entry is a model key or a list name, and the entity must have neither.
func checkAbsent(rec *Item, k string) string {
	if i := strings.IndexByte(k, '['); i >= 0 {
		list := k[:i]
		j := strings.IndexByte(k[i:], ']')
		if j < 0 || !strings.HasPrefix(k[i+j:], "].") {
			return "malformed list key"
		}
		idx, err := strconv.Atoi(k[i+1 : i+j])
		if err != nil || idx < 0 {
			return "malformed item index"
		}
		items, present := rec.Lists[list]
		if !present {
			return fmt.Sprintf("list %s is absent", list)
		}
		if idx >= len(items) {
			return fmt.Sprintf("list %s has %d item(s), no item %d", list, len(items), idx)
		}
		return checkAbsent(items[idx], k[i+j+2:])
	}
	if v, has := rec.Fields[k]; has {
		return fmt.Sprintf("present with %q, want absent", v.String())
	}
	if items, has := rec.Lists[k]; has {
		return fmt.Sprintf("list %s is present with %d item(s), want absent", k, len(items))
	}
	return ""
}

// floatsMatch compares a model float with its expected value: within 1e-9
// absolute on a decoded entity, within 1e-9 relative or 1e-7 absolute on a
// completed one (spec/vector-format.md step 3; the absolute bound is of
// Version 0.16).
func floatsMatch(got, want float64, relative bool) bool {
	if got == want {
		return true
	}
	if relative {
		return math.Abs(got-want) < 1e-9*math.Max(math.Abs(got), math.Abs(want)) ||
			math.Abs(got-want) < 1e-7
	}
	return math.Abs(got-want) <= 1e-9
}

// checkModelKey checks one `model` key of a vector against an entity or an
// item, and returns what is wrong, "" when the check passes. `<list>.#` is
// the number of items of a list ("absent" for an absent list) and
// `<list>[<i>].<key>` a key of item i, read the same way inside the item
// (spec/vector-format.md, "Lists in model"). Any other key is a model key.
func checkModelKey(rec *Item, k, want string, relative bool) string {
	if i := strings.IndexByte(k, '['); i >= 0 {
		list := k[:i]
		j := strings.IndexByte(k[i:], ']')
		if j < 0 || !strings.HasPrefix(k[i+j:], "].") {
			return "malformed list key"
		}
		idx, err := strconv.Atoi(k[i+1 : i+j])
		if err != nil || idx < 0 {
			return "malformed item index"
		}
		items, present := rec.Lists[list]
		if !present {
			return fmt.Sprintf("list %s is absent", list)
		}
		if idx >= len(items) {
			return fmt.Sprintf("list %s has %d item(s), no item %d", list, len(items), idx)
		}
		return checkModelKey(items[idx], k[i+j+2:], want, relative)
	}
	if list, isCount := strings.CutSuffix(k, ".#"); isCount {
		items, present := rec.Lists[list]
		if want == "absent" {
			if present {
				return fmt.Sprintf("list %s is present with %d item(s), want absent", list, len(items))
			}
			return ""
		}
		u, err := parseUintText(want, 1<<31-1)
		if err != nil {
			return fmt.Sprintf("expected count %q is not an unsigned decimal integer or \"absent\"; the vector is invalid", want)
		}
		n := int(u)
		if !present {
			return fmt.Sprintf("list %s is absent, want %d item(s)", list, n)
		}
		if len(items) != n {
			return fmt.Sprintf("list %s has %d item(s), want %d", list, len(items), n)
		}
		return ""
	}
	// "<list>[<i>].@kind" is the kind an item recorded (spec 0.8).
	if k == kindKey {
		if rec.Kind.Name != want {
			return fmt.Sprintf("the item recorded kind %q, want %q", rec.Kind.Name, want)
		}
		return ""
	}
	val, present := rec.Fields[k]
	if !present {
		return fmt.Sprintf("absent, want %q", want)
	}
	if val.Kind == KindFloat {
		w, err := parseNumberText(want)
		if err != nil {
			return fmt.Sprintf("expected value %q is not number text; the vector is invalid", want)
		}
		if !floatsMatch(val.F, w, relative) {
			return fmt.Sprintf("got %v, want %v (tolerance 1e-9, or 1e-9 relative / 1e-7 absolute on a completed entity)", val.F, w)
		}
		return ""
	}
	if val.Kind == KindInt {
		w, err := parseIntText(want)
		if err != nil {
			return fmt.Sprintf("expected value %q is not integer text; the vector is invalid", want)
		}
		if val.I != w {
			return fmt.Sprintf("got %d, want %d", val.I, w)
		}
		return ""
	}
	if val.String() != want {
		return fmt.Sprintf("got %q, want %q", val.String(), want)
	}
	return ""
}

// checkModelGrammar reads one `model` value by the grammar of its member
// (spec/vector-format.md, Version 0.11; ruling 2c of 0.11): a model key or an
// item path `<list>[<i>].<key>` by the grammar of the key's declared type, a
// `<list>.#` value as an unsigned decimal integer or `absent`. It returns
// what makes the vector invalid, "" when the value reads.
func checkModelGrammar(eng *Engine, k, want string) string {
	key := k
	for {
		i := strings.IndexByte(key, '[')
		if i < 0 {
			break
		}
		j := strings.Index(key[i:], "].")
		if j < 0 {
			return ""
		}
		key = key[i+j+2:]
	}
	if key == kindKey || key == innerKindKey {
		return ""
	}
	if _, isCount := strings.CutSuffix(key, ".#"); isCount {
		if want == "absent" {
			return ""
		}
		if _, err := parseUintText(want, 1<<63-1); err != nil {
			return fmt.Sprintf("count %q is not an unsigned decimal integer or absent", want)
		}
		return ""
	}
	kt, err := eng.keyType(key)
	if err != nil {
		return ""
	}
	switch kt {
	case KindInt:
		if _, err := parseIntText(want); err != nil {
			return fmt.Sprintf("%q is not integer text and %s is int", want, key)
		}
	case KindFloat:
		if _, err := parseNumberText(want); err != nil {
			return fmt.Sprintf("%q is not number text and %s is float", want, key)
		}
	}
	return ""
}

// TestVectors runs every conversion vector of every pack. With `expect`,
// convert must equal it byte-for-byte; with `expect_error`, convert must fail
// with that named error and a message that begins with the kind and a colon.
// With `context` the call is convert(from, to, input, context). Each `model`
// key must match decode(from, input), and "@kind" the kind the decode
// selected; with "@complete": true the keys are checked on the entity as
// convert hands it to the encoder (decode, context fill, derivations). Every
// failing vector is reported, by pack and name, before the test fails.
func TestVectors(t *testing.T) {
	runConversionVectors(t, packsDir)
}

// runConversionVectors runs every conversion vector under one packs
// directory, with the modules of the `model` directory beside it.
func runConversionVectors(t *testing.T, packsDir string) {
	eng, err := Load(packsDir)
	if err != nil {
		t.Fatalf("loading packs from %s: %v", packsDir, err)
	}
	files, err := filepath.Glob(filepath.Join(packsDir, "*", "vectors", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(files)
	if len(files) == 0 {
		t.Fatalf("no vectors under %s", packsDir)
	}
	run, passed := 0, 0
	var failed []string
	names := map[string]string{}
	for _, file := range files {
		pack := filepath.Base(filepath.Dir(filepath.Dir(file)))
		raw, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		var v vector
		dec := json.NewDecoder(bytes.NewReader(raw))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&v); err != nil {
			t.Fatalf("%s: %v", file, err)
		}
		if v.Name == "" || v.From == "" || v.To == "" {
			t.Fatalf("%s: name, from and to are required", file)
		}
		id := pack + "/" + v.Name
		if prev, dup := names[id]; dup {
			t.Fatalf("%s: vector name %q already used by %s", file, v.Name, prev)
		}
		names[id] = file
		run++
		ok := t.Run(id, func(t *testing.T) { checkVector(t, eng, pack, v) })
		if ok {
			passed++
		} else {
			failed = append(failed, id)
		}
	}
	summary := fmt.Sprintf("conversion vectors: %d run, %d passed, %d failed (%d packs loaded)", run, passed, run-passed, len(eng.Formats()))
	fmt.Println(summary)
	t.Log(summary)
	for _, id := range failed {
		t.Errorf("FAILED conversion vector: %s", id)
	}
}

// checkVector runs one conversion vector of the pack it lives in against an
// engine (spec/vector-format.md, "What the engine checks per vector").
func checkVector(t *testing.T, eng *Engine, pack string, v vector) {
	// A vector that pins unknown-format names a format no pack
	// directory holds (spec/vector-format.md, Version 0.11).
	if _, loaded := eng.packs[v.From]; v.From != pack && loaded {
		t.Errorf("vector lives in pack %q but from is %q", pack, v.From)
	}
	if v.MaxItems != nil {
		n, err := parseUintText(v.MaxItems.String(), 1<<62)
		if err != nil {
			t.Fatalf("max_items %q is not an integer of 0 or more; the vector is invalid", v.MaxItems.String())
		}
		eng.SetMaxItems(int64(n))
		defer eng.SetMaxItems(DefaultMaxItems)
	}
	in := bytesOf(t, v.Input, v.InputB64, "input")
	got, err := eng.ConvertWith(v.From, v.To, in, v.Context)
	if v.ExpectError != nil {
		if v.Expect != nil || v.ExpectB64 != nil {
			t.Fatalf("vector sets both expect and expect_error")
		}
		want := *v.ExpectError
		switch {
		case err == nil:
			t.Errorf("convert %s -> %s succeeded with %s, want error %s", v.From, v.To, got, want)
		case !IsKind(err, ErrorKind(want)):
			t.Errorf("convert %s -> %s: got %v, want error kind %s", v.From, v.To, err, want)
		case !strings.HasPrefix(err.Error(), want+":"):
			t.Errorf("message %q does not begin with %q", err.Error(), want+":")
		}
	} else {
		want := bytesOf(t, v.Expect, v.ExpectB64, "expect")
		if err != nil {
			t.Errorf("convert %s -> %s: %v", v.From, v.To, err)
		} else if !bytes.Equal(got, want) {
			t.Errorf("convert %s -> %s mismatch\n got: %s\nwant: %s", v.From, v.To, got, want)
		}
	}
	if len(v.Model) == 0 {
		return
	}
	ent, err := eng.Decode(v.From, in)
	if err != nil {
		t.Fatalf("decode %s: %v", v.From, err)
	}
	complete := false
	if c, has := v.Model[completeKey]; has {
		b, isBool := c.(bool)
		if !isBool {
			t.Fatalf("model[%s] must be true or false", completeKey)
		}
		complete = b
	}
	if complete {
		if err := eng.Fill(ent, v.Context); err != nil {
			t.Fatalf("complete: %v", err)
		}
		eng.Complete(ent)
	}
	keys := make([]string, 0, len(v.Model))
	for k := range v.Model {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if k == completeKey {
			continue
		}
		if k == absentKey {
			list, isList := v.Model[k].([]any)
			if !isList {
				t.Errorf("model[%s] must be an array of keys", absentKey)
				continue
			}
			for _, e := range list {
				key, isString := e.(string)
				if !isString {
					t.Errorf("model[%s]: an entry must be a string, got %v", absentKey, e)
					continue
				}
				// A listed key that is also a member of model makes
				// the vector invalid (0.9 ruling 21).
				if _, clash := v.Model[key]; clash {
					t.Errorf("model[%s]: %q is also a member of model; the vector is invalid", absentKey, key)
					continue
				}
				if key == innerKindKey {
					if ent.InnerKind != (EntityKind{}) {
						t.Errorf("model[%s] %s: present with (%q, %q), want absent", absentKey, key, ent.InnerKind.Format, ent.InnerKind.Name)
					}
					continue
				}
				if msg := checkAbsent(ent.item(), key); msg != "" {
					t.Errorf("model[%s] %s: %s", absentKey, key, msg)
				}
			}
			continue
		}
		wantS, isString := v.Model[k].(string)
		if !isString {
			t.Errorf("model[%s]: expected value must be in string form", k)
			continue
		}
		if msg := checkModelGrammar(eng, k, wantS); msg != "" {
			t.Errorf("model[%s]: %s; the vector is invalid", k, msg)
			continue
		}
		if k == kindKey {
			if ent.Kind.Format != v.From || ent.Kind.Name != wantS {
				t.Errorf("decode selected kind (%q, %q), want (%q, %q)", ent.Kind.Format, ent.Kind.Name, v.From, wantS)
			}
			continue
		}
		if k == innerKindKey {
			if ent.InnerKind.Format == "" || ent.InnerKind.Name != wantS {
				t.Errorf("decode recorded inner kind (%q, %q), want kind %q", ent.InnerKind.Format, ent.InnerKind.Name, wantS)
			}
			continue
		}
		if msg := checkModelKey(ent.item(), k, wantS, complete); msg != "" {
			t.Errorf("model[%s]: %s", k, msg)
		}
	}
}
