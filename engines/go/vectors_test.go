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
	kindKey     = "@kind"
	completeKey = "@complete"
)

// floatsMatch compares a model float with its expected value: within 1e-9
// absolute on a decoded entity, within 1e-9 relative on a completed one.
func floatsMatch(got, want float64, relative bool) bool {
	if got == want {
		return true
	}
	if relative {
		return math.Abs(got-want) < 1e-9*math.Max(math.Abs(got), math.Abs(want))
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
		n, err := strconv.Atoi(want)
		if err != nil {
			return fmt.Sprintf("expected count %q is not a number or \"absent\"", want)
		}
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
		w, err := strconv.ParseFloat(want, 64)
		if err != nil {
			return fmt.Sprintf("expected value %q is not a float", want)
		}
		if !floatsMatch(val.F, w, relative) {
			return fmt.Sprintf("got %v, want %v (tolerance 1e-9)", val.F, w)
		}
		return ""
	}
	if val.String() != want {
		return fmt.Sprintf("got %q, want %q", val.String(), want)
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
		ok := t.Run(id, func(t *testing.T) {
			if v.From != pack {
				t.Errorf("vector lives in pack %q but from is %q", pack, v.From)
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
				wantS, isString := v.Model[k].(string)
				if !isString {
					t.Errorf("model[%s]: expected value must be in string form", k)
					continue
				}
				if k == kindKey {
					if ent.Kind.Format != v.From || ent.Kind.Name != wantS {
						t.Errorf("decode selected kind (%q, %q), want (%q, %q)", ent.Kind.Format, ent.Kind.Name, v.From, wantS)
					}
					continue
				}
				if msg := checkModelKey(ent.item(), k, wantS, complete); msg != "" {
					t.Errorf("model[%s]: %s", k, msg)
				}
			}
		})
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
