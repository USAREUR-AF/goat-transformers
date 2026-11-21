// Command goat-bench runs the benchmark of spec/engine-spec.md, Version 0.25,
// ruling 2, over a benchmark set (default bench/set.json):
//
//	goat-bench [<set.json>]
//
// The paths of the set's vectors are relative to the directory that holds
// the set's directory (the repository root for bench/set.json); the packs
// directory is <root>/packs and the model modules are <root>/model.
//
// It loads into one engine only the packs the vectors name in `from` and
// `to` (a format's pack is the subdirectory of that name), and the modules
// those packs use, and times the load. Then, for each vector in order, it
// converts the input once and checks the output against `expect`, and then
// converts the input `iterations` times and times that. Standard output gets
// one line per vector and then one line for the load, each a JSON object
// (ruling 2c), and nothing else; the lines are written once every vector has
// passed. Any failure writes its message on standard error and exits 1 with
// standard output empty; a usage error exits 2.
package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	goatxf "github.com/USAREUR-AF/goat-transformers/engines/go"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

// set is bench/set.json (ruling 2a).
type set struct {
	About      string   `json:"about"`
	Iterations int64    `json:"iterations"`
	Vectors    []string `json:"vectors"`
}

// vector holds the members of a conversion vector the benchmark uses
// (spec/vector-format.md); other members are ignored.
type vector struct {
	From      string            `json:"from"`
	To        string            `json:"to"`
	Input     *string           `json:"input"`
	InputB64  *string           `json:"input_b64"`
	Expect    *string           `json:"expect"`
	ExpectB64 *string           `json:"expect_b64"`
	Context   map[string]string `json:"context"`
	MaxItems  *json.Number      `json:"max_items"`
}

func bytesOf(text, b64 *string, what string) ([]byte, error) {
	switch {
	case text != nil && b64 != nil:
		return nil, fmt.Errorf("sets both %s and %s_b64", what, what)
	case text != nil:
		return []byte(*text), nil
	case b64 != nil:
		b, err := base64.StdEncoding.DecodeString(*b64)
		if err != nil {
			return nil, fmt.Errorf("%s_b64: %v", what, err)
		}
		return b, nil
	}
	return nil, fmt.Errorf("has neither %s nor %s_b64", what, what)
}

// jsonString writes s as a JSON string, without HTML escaping.
func jsonString(s string) string {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(s)
	return strings.TrimSuffix(b.String(), "\n")
}

type loaded struct {
	path   string
	v      vector
	input  []byte
	expect []byte
}

func run(args []string, stdout, stderr io.Writer) int {
	setPath := filepath.Join("bench", "set.json")
	switch len(args) {
	case 0:
	case 1:
		if args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
			fmt.Fprintln(stdout, "usage: goat-bench [<set.json>]   (default bench/set.json)")
			return 0
		}
		setPath = args[0]
	default:
		fmt.Fprintln(stderr, "usage: goat-bench [<set.json>]")
		return 2
	}
	fail := func(format string, a ...any) int {
		fmt.Fprintf(stderr, "goat-bench: "+format+"\n", a...)
		return 1
	}
	raw, err := os.ReadFile(setPath)
	if err != nil {
		return fail("%v", err)
	}
	var s set
	if err := json.Unmarshal(raw, &s); err != nil {
		return fail("%s: %v", setPath, err)
	}
	if s.Iterations <= 0 || len(s.Vectors) == 0 {
		return fail("%s: iterations must be 1 or more and vectors must not be empty", setPath)
	}
	root := filepath.Dir(filepath.Dir(setPath))
	packsDir := filepath.Join(root, "packs")

	// Read every vector before the load, so the load time holds no vector.
	vecs := make([]loaded, 0, len(s.Vectors))
	var names []string
	seen := map[string]bool{}
	for _, p := range s.Vectors {
		b, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(p)))
		if err != nil {
			return fail("%v", err)
		}
		var v vector
		if err := json.Unmarshal(b, &v); err != nil {
			return fail("%s: %v", p, err)
		}
		in, err := bytesOf(v.Input, v.InputB64, "input")
		if err != nil {
			return fail("%s: %v", p, err)
		}
		want, err := bytesOf(v.Expect, v.ExpectB64, "expect")
		if err != nil {
			return fail("%s: %v", p, err)
		}
		for _, f := range []string{v.From, v.To} {
			if !seen[f] {
				seen[f] = true
				names = append(names, f)
			}
		}
		vecs = append(vecs, loaded{path: p, v: v, input: in, expect: want})
	}

	start := time.Now()
	eng, err := goatxf.LoadPacksOnly(goatxf.DefaultModelsDir(packsDir), packsDir, goatxf.DistControlled, names)
	loadNs := time.Since(start).Nanoseconds()
	if err != nil {
		return fail("loading %s: %v", strings.Join(names, ","), err)
	}

	var out strings.Builder
	for _, l := range vecs {
		if l.v.MaxItems != nil {
			n, err := strconv.ParseInt(l.v.MaxItems.String(), 10, 64)
			if err != nil || n < 0 {
				return fail("%s: max_items %q is not an integer of 0 or more", l.path, l.v.MaxItems.String())
			}
			eng.SetMaxItems(n)
		} else {
			eng.SetMaxItems(goatxf.DefaultMaxItems)
		}
		got, err := eng.ConvertWith(l.v.From, l.v.To, l.input, l.v.Context)
		if err != nil {
			return fail("%s: convert %s -> %s: %v", l.path, l.v.From, l.v.To, err)
		}
		if !bytes.Equal(got, l.expect) {
			return fail("%s: convert %s -> %s: output differs from expect\n got: %s\nwant: %s", l.path, l.v.From, l.v.To, got, l.expect)
		}
		start := time.Now()
		for i := int64(0); i < s.Iterations; i++ {
			if _, err := eng.ConvertWith(l.v.From, l.v.To, l.input, l.v.Context); err != nil {
				return fail("%s: iteration %d: %v", l.path, i, err)
			}
		}
		ns := time.Since(start).Nanoseconds()
		fmt.Fprintf(&out, "{\"vector\": %s, \"iterations\": %d, \"ns_per_op\": %d}\n", jsonString(l.path), s.Iterations, ns/s.Iterations)
	}
	fmt.Fprintf(&out, "{\"load\": %d, \"ns\": %d}\n", len(eng.Formats()), loadNs)
	io.WriteString(stdout, out.String())
	return 0
}
