package goatxf

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

const loadVectorsDir = packsDir + "/conformance/load-vectors"

type loadVector struct {
	Name            string   `json:"name"`
	Models          []string `json:"models"`
	Pack            *string  `json:"pack"`
	MaxDistribution *string  `json:"max_distribution"`
	ExpectError     *string  `json:"expect_error"`
}

// runLoadVector starts an empty engine, loads the modules in order and then
// the pack, and returns the first failure.
func runLoadVector(v *loadVector) error {
	eng := New()
	if v.MaxDistribution != nil {
		if err := eng.SetMaxDistribution(*v.MaxDistribution); err != nil {
			return err
		}
	}
	for i, m := range v.Models {
		if err := eng.LoadModel([]byte(m), fmt.Sprintf("models[%d]", i)); err != nil {
			return err
		}
	}
	return eng.LoadPack([]byte(*v.Pack), "pack")
}

// TestLoadVectors runs every load vector (spec/vector-format.md, "Load
// vectors"): with expect_error the first failure must be of that kind and its
// message must begin with the kind and a colon; without it nothing may fail.
func TestLoadVectors(t *testing.T) {
	files, err := filepath.Glob(filepath.Join(loadVectorsDir, "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(files)
	if len(files) == 0 {
		t.Fatalf("no load vectors under %s", loadVectorsDir)
	}
	run, passed := 0, 0
	var failed []string
	names := map[string]string{}
	for _, file := range files {
		raw, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		var v loadVector
		dec := json.NewDecoder(bytes.NewReader(raw))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&v); err != nil {
			t.Fatalf("%s: %v", file, err)
		}
		if v.Name == "" || v.Models == nil || v.Pack == nil {
			t.Fatalf("%s: name, models and pack are required", file)
		}
		if prev, dup := names[v.Name]; dup {
			t.Fatalf("%s: load vector name %q already used by %s", file, v.Name, prev)
		}
		names[v.Name] = file
		run++
		ok := t.Run(v.Name, func(t *testing.T) {
			err := runLoadVector(&v)
			if v.ExpectError == nil {
				if err != nil {
					t.Fatalf("load must succeed, got: %v", err)
				}
				return
			}
			want := *v.ExpectError
			if err == nil {
				t.Fatalf("load succeeded, want error %s", want)
			}
			e, isErr := err.(*Error)
			if !isErr || string(e.Kind) != want {
				t.Fatalf("got %v, want error kind %s", err, want)
			}
			if !strings.HasPrefix(err.Error(), want+":") {
				t.Errorf("message %q does not begin with %q", err.Error(), want+":")
			}
		})
		if ok {
			passed++
		} else {
			failed = append(failed, v.Name)
		}
	}
	summary := fmt.Sprintf("load vectors: %d run, %d passed, %d failed", run, passed, run-passed)
	fmt.Println(summary)
	t.Log(summary)
	for _, name := range failed {
		t.Errorf("FAILED load vector: %s", name)
	}
}

// TestDirectoryLoaderAndLimit loads the repository's model/ and packs/ the
// way the CLI does, under both limits.
func TestDirectoryLoaderAndLimit(t *testing.T) {
	for _, limit := range []string{DistControlled, DistPublic} {
		eng, err := LoadDirs(DefaultModelsDir(packsDir), packsDir, limit)
		if err != nil {
			t.Fatalf("limit %s: %v", limit, err)
		}
		if len(eng.Modules()) == 0 || len(eng.Formats()) == 0 {
			t.Errorf("limit %s: %d modules, %d packs loaded", limit, len(eng.Modules()), len(eng.Formats()))
		}
	}
	if _, err := LoadDirs(DefaultModelsDir(packsDir), packsDir, "secret"); err == nil {
		t.Error("an unknown distribution limit must be refused")
	}
}

// TestLoadPacksOnly loads named packs of the repository with only the
// modules they need.
func TestLoadPacksOnly(t *testing.T) {
	models := DefaultModelsDir(packsDir)
	eng, err := LoadPacksOnly(models, packsDir, DistControlled, []string{"cot-xml", "geojson", "cot-xml"})
	if err != nil {
		t.Fatal(err)
	}
	if got := len(eng.Formats()); got != 2 {
		t.Errorf("%d packs loaded, want 2", got)
	}
	// Exactly core, what the two packs use, and what those modules use.
	want := map[string]bool{CoreModule: true}
	for _, p := range eng.Formats() {
		for _, u := range p.Uses {
			want[u] = true
		}
	}
	for grew := true; grew; {
		grew = false
		for _, m := range eng.Modules() {
			if !want[m.Name] {
				continue
			}
			for _, u := range m.Uses {
				if !want[u] {
					want[u], grew = true, true
				}
			}
		}
	}
	if got := len(eng.Modules()); got != len(want) {
		t.Errorf("%d modules loaded, want %d", got, len(want))
	}
	for _, m := range eng.Modules() {
		if !want[m.Name] {
			t.Errorf("module %s loaded and no named pack needs it", m.Name)
		}
	}
	all, err := Load(packsDir)
	if err != nil {
		t.Fatal(err)
	}
	if len(eng.Modules()) >= len(all.Modules()) {
		t.Errorf("the named load holds %d modules, the full load %d", len(eng.Modules()), len(all.Modules()))
	}
	in := []byte(`<event uid="J-1" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.5" lon="-85.5" hae="1" ce="2" le="3"/></event>`)
	a, errA := eng.Convert("cot-xml", "geojson", in)
	b, errB := all.Convert("cot-xml", "geojson", in)
	if errA != nil || errB != nil || string(a) != string(b) {
		t.Errorf("named load converts to %s (%v), full load to %s (%v)", a, errA, b, errB)
	}
	if _, err := LoadPacksOnly(models, packsDir, DistControlled, []string{"no-such-pack"}); !IsKind(err, ErrUnknownFormat) {
		t.Errorf("an unknown pack name: got %v, want unknown-format", err)
	}
	if _, err := LoadPacksOnly(models, packsDir, DistControlled, nil); !IsKind(err, ErrUnknownFormat) {
		t.Errorf("no pack named: got %v, want unknown-format", err)
	}
	if _, err := LoadPacksOnly(models, packsDir, DistControlled, []string{"../packs/geojson"}); !IsKind(err, ErrUnknownFormat) {
		t.Errorf("a path for a pack name: got %v, want unknown-format", err)
	}
}
