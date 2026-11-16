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
