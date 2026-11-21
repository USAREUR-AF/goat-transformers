package goatxf

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"sync"
	"testing"
)

// outcome is everything a conversion vector can observe of an engine: the
// bytes or the error of convert, and the entity and the error of decode.
type outcome struct {
	out       []byte
	convErr   string
	ent       *Entity
	decodeErr string
}

func observe(eng *Engine, v *vector, in []byte) outcome {
	var o outcome
	got, err := eng.ConvertWith(v.From, v.To, in, v.Context)
	o.out = got
	if err != nil {
		o.convErr = err.Error()
	}
	ent, err := eng.Decode(v.From, in)
	o.ent = ent
	if err != nil {
		o.decodeErr = err.Error()
	}
	return o
}

func (o outcome) differs(w outcome) string {
	switch {
	case !bytes.Equal(o.out, w.out):
		return fmt.Sprintf("convert gave %q, want %q", o.out, w.out)
	case o.convErr != w.convErr:
		return fmt.Sprintf("convert error %q, want %q", o.convErr, w.convErr)
	case o.decodeErr != w.decodeErr:
		return fmt.Sprintf("decode error %q, want %q", o.decodeErr, w.decodeErr)
	case !reflect.DeepEqual(o.ent, w.ent):
		return fmt.Sprintf("decode gave %+v, want %+v", o.ent, w.ent)
	}
	return ""
}

type benchCase struct {
	id string
	v  *vector
	in []byte
}

// conversionCases reads every conversion vector under packsDir that runs
// with the default limit on list items; with step > 1 it keeps every
// step-th one.
func conversionCases(t *testing.T, step int) []benchCase {
	files, err := filepath.Glob(filepath.Join(packsDir, "*", "vectors", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(files)
	var cases []benchCase
	for i, file := range files {
		if i%step != 0 {
			continue
		}
		raw, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		v := &vector{}
		if err := json.Unmarshal(raw, v); err != nil {
			t.Fatalf("%s: %v", file, err)
		}
		if v.MaxItems != nil {
			continue // the limit is the instance's setting, not a conversion's
		}
		var in []byte
		switch {
		case v.Input != nil:
			in = []byte(*v.Input)
		case v.InputB64 != nil:
			if in, err = base64.StdEncoding.DecodeString(*v.InputB64); err != nil {
				t.Fatalf("%s: %v", file, err)
			}
		default:
			t.Fatalf("%s: no input", file)
		}
		cases = append(cases, benchCase{id: file, v: v, in: in})
	}
	return cases
}

// TestParseOnceConcurrent checks rulings 1b and 1c of spec 0.25. The
// reference is each vector's outcome on one instance, in file order. A second
// instance, loaded from the same packs, is then used from several goroutines
// at once, each starting at another place of the list, so every vector, the
// failing ones included, follows other conversions, successful and failed,
// in each goroutine and alongside the others. Every outcome must equal the
// reference: the same bytes, the same entity and the same error messages.
// Run it under `go test -race` to also check that no conversion writes what
// another reads.
func TestParseOnceConcurrent(t *testing.T) {
	step := 1
	if testing.Short() {
		step = 16
	}
	cases := conversionCases(t, step)
	if len(cases) == 0 {
		t.Fatal("no vectors")
	}
	ref, err := Load(packsDir)
	if err != nil {
		t.Fatal(err)
	}
	want := make([]outcome, len(cases))
	failing := 0
	for i := range cases {
		want[i] = observe(ref, cases[i].v, cases[i].in)
		if want[i].convErr != "" {
			failing++
		}
	}
	ref = nil
	shared, err := Load(packsDir)
	if err != nil {
		t.Fatal(err)
	}
	const goroutines = 4
	var wg sync.WaitGroup
	var mu sync.Mutex
	var bad []string
	for g := 0; g < goroutines; g++ {
		wg.Add(1)
		go func(g int) {
			defer wg.Done()
			start := g * len(cases) / goroutines
			for k := range cases {
				i := (start + k) % len(cases)
				if msg := observe(shared, cases[i].v, cases[i].in).differs(want[i]); msg != "" {
					mu.Lock()
					bad = append(bad, fmt.Sprintf("goroutine %d, %s: %s", g, cases[i].id, msg))
					mu.Unlock()
				}
			}
		}(g)
	}
	wg.Wait()
	summary := fmt.Sprintf("parse once: %d vectors (%d failing conversions) on %d goroutines at once, %d outcomes differ", len(cases), failing, goroutines, len(bad))
	fmt.Println(summary)
	t.Log(summary)
	for i, b := range bad {
		if i == 20 {
			t.Errorf("... and %d more", len(bad)-20)
			break
		}
		t.Error(b)
	}
}

// TestLoadReadsEachFileOnce checks ruling 1d of spec 0.25 for the module
// files: readModuleFiles gives each file once, with its text, and a second
// load of the same directory into the same instance is duplicate-module.
func TestLoadReadsEachFileOnce(t *testing.T) {
	dir := t.TempDir()
	head := "version 1\ndistribution public\nsource s\n"
	for name, text := range map[string]string{
		"core.def": "module core\n" + head,
		"b.def":    "module b\n" + head + "uses a\n",
		"a.def":    "module a\n" + head,
	} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	files, err := readModuleFiles(dir)
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, f := range files {
		if f.err != nil || len(f.text) == 0 {
			t.Fatalf("%s: text not kept (%v)", f.path, f.err)
		}
		got = append(got, f.name)
	}
	if fmt.Sprint(got) != "[core a b]" {
		t.Fatalf("order %v, want [core a b]", got)
	}
	e := New()
	for _, f := range files {
		if err := f.load(e); err != nil {
			t.Fatal(err)
		}
	}
	for _, f := range files {
		if err := f.load(e); !IsKind(err, ErrDuplicateModule) {
			t.Errorf("second load of %s: got %v, want duplicate-module", f.path, err)
		}
	}
}
