//go:build goat_wires

package goatxf

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// TestReducedBuild is the reduced-build check of spec/engine-spec.md, Version
// 0.24 ("What pins it"). It runs only in a build that names its wires (the tag
// goat_wires); reduced-check.sh runs it in the build with xml, json and
// geojson. It loads the modules and every pack on a wire of the build and
// runs every conversion vector whose `from` and `to` are among those packs;
// each must pass as in the full build (ruling 1b). Every pack on a wire of the
// specification the build lacks must fail to load with unknown-wire, at its
// `wire` line, with a message that names the wire and says this build does
// not have it (ruling 1c); one pack of each such wire is named in the output.
// A `wire` value that is no wire stays unknown-wire with the message it had.
func TestReducedBuild(t *testing.T) {
	built := map[string]bool{}
	for _, w := range BuiltWires() {
		built[w] = true
	}
	if len(built) == len(allWires) {
		t.Fatalf("this build has all eight wires; build with -tags goat_wires,goat_wire_<wire>,...")
	}
	fmt.Printf("reduced build: wires %s\n", strings.Join(BuiltWires(), ", "))

	eng := New()
	if err := eng.SetMaxDistribution(DistControlled); err != nil {
		t.Fatal(err)
	}
	files, err := moduleFiles(DefaultModelsDir(packsDir))
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range files {
		text, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		if err := eng.LoadModel(text, f); err != nil {
			t.Fatalf("module %s: %v", f, err)
		}
	}

	entries, err := os.ReadDir(packsDir)
	if err != nil {
		t.Fatal(err)
	}
	refused := map[string]int{}         // wire -> packs refused
	firstRefused := map[string]string{} // wire -> the first pack refused, with its message
	loadedPacks := 0
	for _, ent := range entries {
		path := filepath.Join(packsDir, ent.Name(), "pack.def")
		if _, err := os.Stat(path); err != nil {
			continue
		}
		wire, wireLine := packWireLine(t, path)
		p, err := ParsePackFile(path)
		if built[wire] {
			if err != nil {
				t.Errorf("pack %s on wire %s, which this build has: %v", ent.Name(), wire, err)
				continue
			}
			if err := eng.AddPack(p); err != nil {
				t.Errorf("pack %s: %v", ent.Name(), err)
				continue
			}
			loadedPacks++
			continue
		}
		if !isWireOfSpec(wire) {
			t.Errorf("pack %s: wire %q is no wire of the specification", ent.Name(), wire)
			continue
		}
		if msg := checkMissingWire(err, wire, wireLine); msg != "" {
			t.Errorf("pack %s on wire %s: %s", ent.Name(), wire, msg)
			continue
		}
		refused[wire]++
		if _, has := firstRefused[wire]; !has {
			firstRefused[wire] = ent.Name() + ": " + err.Error()
		}
	}
	for _, w := range allWires {
		if built[w] {
			continue
		}
		if refused[w] == 0 {
			t.Errorf("no pack on wire %s was loaded to check unknown-wire", w)
			continue
		}
		fmt.Printf("unknown-wire load: wire %s, %d pack(s) refused, e.g. %s\n", w, refused[w], firstRefused[w])
	}

	// A wire value that is no wire is unknown-wire with the message of 0.11,
	// which does not say the build lacks it.
	bogus := []byte("format x-no-wire\nversion 1\nwire morse\n")
	if _, err := ParsePack(bogus, "x-no-wire/pack.def"); err == nil || !IsKind(err, ErrUnknownWire) {
		t.Errorf("wire morse: got %v, want unknown-wire", err)
	} else if strings.Contains(err.Error(), "does not have") {
		t.Errorf("wire morse: message %q reads as a wire the build lacks", err.Error())
	}

	vfiles, err := filepath.Glob(filepath.Join(packsDir, "*", "vectors", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(vfiles)
	run, passed, skipped := 0, 0, 0
	var failed []string
	for _, file := range vfiles {
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
		fromPack, fromLoaded := eng.packs[v.From]
		toPack, toLoaded := eng.packs[v.To]
		if !fromLoaded || !toLoaded {
			skipped++
			continue
		}
		// ruling 1 of 0.34: the reduced-build check runs no vector of an outer
		// pack, since whether its inner pack loads differs between builds
		if len(fromPack.innerFormats) > 0 || len(toPack.innerFormats) > 0 {
			skipped++
			continue
		}
		run++
		id := pack + "/" + v.Name
		if t.Run(id, func(t *testing.T) { checkVector(t, eng, pack, v) }) {
			passed++
		} else {
			failed = append(failed, id)
		}
	}
	fmt.Printf("reduced build: %d packs loaded; conversion vectors: %d run, %d passed, %d failed (%d not on the wires of this build)\n",
		loadedPacks, run, passed, run-passed, skipped)
	if run == 0 {
		t.Errorf("no conversion vector ran")
	}
	for _, id := range failed {
		t.Errorf("FAILED conversion vector: %s", id)
	}
}

// packWireLine reads the value and line number of a pack's `wire` line.
func packWireLine(t *testing.T, path string) (string, int) {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 64*1024), 1<<20)
	n := 0
	for sc.Scan() {
		n++
		fs := strings.Fields(sc.Text())
		if len(fs) == 2 && fs[0] == "wire" {
			return fs[1], n
		}
	}
	t.Fatalf("%s has no wire line", path)
	return "", 0
}

func isWireOfSpec(w string) bool {
	for _, x := range allWires {
		if w == x {
			return true
		}
	}
	return false
}

// checkMissingWire checks the error of a pack whose wire the build lacks
// (ruling 1c of 0.24) and returns what is wrong, "" when it is right.
func checkMissingWire(err error, wire string, wireLine int) string {
	if err == nil {
		return "loaded, want unknown-wire"
	}
	if !IsKind(err, ErrUnknownWire) || !strings.HasPrefix(err.Error(), string(ErrUnknownWire)+":") {
		return fmt.Sprintf("got %v, want unknown-wire", err)
	}
	if !strings.Contains(err.Error(), fmt.Sprintf("%q", wire)) || !strings.Contains(err.Error(), "this build does not have it") {
		return fmt.Sprintf("message %q does not name the wire and say this build does not have it", err.Error())
	}
	var e *Error
	if pe, ok := err.(*Error); ok {
		e = pe
	}
	if e == nil || e.Line != wireLine {
		return fmt.Sprintf("raised at %v, want at the wire line %d (line check 6)", err, wireLine)
	}
	return ""
}
