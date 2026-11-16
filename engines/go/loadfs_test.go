package goatxf_test

import (
	"fmt"
	"io/fs"
	"os"
	"testing"

	goatxf "github.com/USAREUR-AF/goat-transformers/engines/go"
)

const cotEvent = `<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>`

// Load two packs and the modules they need, and convert a message. The
// directories here are the repository's; a bundle written by tools/goat-pkg
// bundle has the same shape.
func ExampleLoadPacksOnly() {
	engine, err := goatxf.LoadPacksOnly("../../model", "../../packs", goatxf.DistControlled, []string{"cot-xml", "geojson"})
	if err != nil {
		fmt.Println(err)
		return
	}
	out, err := engine.Convert("cot-xml", "geojson", []byte(cotEvent))
	if err != nil {
		fmt.Println(err)
		return
	}
	fmt.Println(string(out))
	// Output:
	// {"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}
}

// LoadFS takes any fs.FS. Given an embed.FS over a vendored bundle
// (`//go:embed model packs`), the packs are compiled into the program and no
// file is read when it runs; os.DirFS stands in for it here.
func ExampleEngine_LoadFS() {
	var tree fs.FS = os.DirFS("../..")
	engine := goatxf.New()
	if err := engine.LoadFS(tree, []string{"geojson", "canonical-track-v2"}); err != nil {
		fmt.Println(err)
		return
	}
	for _, p := range engine.Formats() {
		fmt.Println(p.Format)
	}
	// Output:
	// canonical-track-v2
	// geojson
}

func TestLoadFSFollowsUsesAndRepeats(t *testing.T) {
	names := func(e *goatxf.Engine) string {
		s := ""
		for _, m := range e.Modules() {
			s += m.Name + " "
		}
		return s
	}
	tree := os.DirFS("../..")
	e := goatxf.New()
	// asterix-cat062 uses cat062, and cat062 uses track
	if err := e.LoadFS(tree, []string{"asterix-cat062"}); err != nil {
		t.Fatal(err)
	}
	if got := names(e); got != "cat062 core track " {
		t.Fatalf("modules: %q", got)
	}
	if err := e.LoadFS(tree, []string{"canonical-track-v2"}); err != nil {
		t.Fatal(err)
	}
	if len(e.Formats()) != 2 || names(e) != "cat062 core track " {
		t.Fatalf("after the second load: %d formats, modules %q", len(e.Formats()), names(e))
	}
	if err := goatxf.New().LoadFS(tree, []string{"no-such-format"}); !goatxf.IsKind(err, goatxf.ErrUnknownFormat) {
		t.Fatalf("a pack the tree does not hold: %v", err)
	}
}
