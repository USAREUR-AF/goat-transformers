package goatxf

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"testing"
)

const capabilityVectorsDir = packsDir + "/conformance/capability-vectors"

type capabilityVector struct {
	Name    string   `json:"name"`
	From    string   `json:"from"`
	To      string   `json:"to"`
	Grade   string   `json:"grade"`
	Carried []string `json:"carried"`
	Dropped []string `json:"dropped"`
}

// TestCapabilityVectors runs every capability vector (spec/vector-format.md,
// "Capability vectors"; ruling 6 of 0.11): the engine loads the model modules
// and the two packs, and capability(from, to) must give the vector's grade
// and both lists, entry for entry and in order.
func TestCapabilityVectors(t *testing.T) {
	files, err := filepath.Glob(filepath.Join(capabilityVectorsDir, "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(files)
	if len(files) == 0 {
		t.Fatalf("no capability vectors under %s", capabilityVectorsDir)
	}
	run, passed := 0, 0
	var failed []string
	names := map[string]string{}
	for _, file := range files {
		raw, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		var v capabilityVector
		dec := json.NewDecoder(bytes.NewReader(raw))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&v); err != nil {
			t.Fatalf("%s: %v", file, err)
		}
		if v.Name == "" || v.From == "" || v.To == "" || v.Grade == "" || v.Carried == nil || v.Dropped == nil {
			t.Fatalf("%s: name, from, to, grade, carried and dropped are required", file)
		}
		if prev, dup := names[v.Name]; dup {
			t.Fatalf("%s: capability vector name %q already used by %s", file, v.Name, prev)
		}
		names[v.Name] = file
		run++
		ok := t.Run(v.Name, func(t *testing.T) {
			formats := []string{v.From}
			if v.To != v.From {
				formats = append(formats, v.To)
			}
			// With the packs their `inner` lines name (spec 0.34, Vectors).
			formats = WithInnerPacks(packsDir, formats)
			eng, err := LoadPacksOnly(DefaultModelsDir(packsDir), packsDir, DistControlled, formats)
			if err != nil {
				t.Fatalf("load: %v", err)
			}
			c, err := eng.Capability(v.From, v.To)
			if err != nil {
				t.Fatalf("capability(%s, %s): %v", v.From, v.To, err)
			}
			if c.Grade != v.Grade {
				t.Errorf("grade %s, want %s", c.Grade, v.Grade)
			}
			if !reflect.DeepEqual(c.Carried, v.Carried) {
				t.Errorf("carried %q, want %q", c.Carried, v.Carried)
			}
			if !reflect.DeepEqual(c.Dropped, v.Dropped) {
				t.Errorf("dropped %q, want %q", c.Dropped, v.Dropped)
			}
		})
		if ok {
			passed++
		} else {
			failed = append(failed, v.Name)
		}
	}
	summary := fmt.Sprintf("capability vectors: %d run, %d passed, %d failed", run, passed, run-passed)
	fmt.Println(summary)
	t.Log(summary)
	for _, name := range failed {
		t.Errorf("FAILED capability vector: %s", name)
	}
}

// TestCapabilityUnknownFormat: a format that is not loaded is unknown-format
// (ruling 6f of 0.11).
func TestCapabilityUnknownFormat(t *testing.T) {
	eng, err := LoadPacksOnly(DefaultModelsDir(packsDir), packsDir, DistControlled, []string{"conformance-cap-a"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := eng.Capability("conformance-cap-a", "no-such-format"); !IsKind(err, ErrUnknownFormat) {
		t.Errorf("unknown target: got %v, want unknown-format", err)
	}
	if _, err := eng.Capability("no-such-format", "conformance-cap-a"); !IsKind(err, ErrUnknownFormat) {
		t.Errorf("unknown source: got %v, want unknown-format", err)
	}
}
