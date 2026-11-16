// Command goat-xf converts messages between formats using the packs under
// --packs.
//
//	goat-xf convert --from cot-xml --to geojson --packs ../../packs < in > out
//	goat-xf convert --from geojson --to cot-xml --set stale_ms=1614456030000 --set how=m-g < in > out
//	goat-xf list-formats --packs ../../packs
//
// Model modules load from --models (default <packs>/../model) before the
// packs. --max-distribution public refuses every controlled module and pack.
// --set <key>=<value>, repeatable, supplies a model key the source message
// does not carry (the `context` of convert, engine-spec 0.6).
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	goatxf "github.com/USAREUR-AF/goat-transformers/engines/go"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr))
}

// setFlag collects repeated --set <key>=<value> arguments.
type setFlag map[string]string

func (s setFlag) String() string { return "" }

func (s setFlag) Set(arg string) error {
	key, value, ok := strings.Cut(arg, "=")
	if !ok || key == "" {
		return fmt.Errorf("want <key>=<value>, got %q", arg)
	}
	s[key] = value
	return nil
}

func usage(w io.Writer) {
	fmt.Fprintln(w, "usage:")
	fmt.Fprintln(w, "  goat-xf convert --from FORMAT --to FORMAT --packs DIR [--set KEY=VALUE ...]   (stdin -> stdout)")
	fmt.Fprintln(w, "  goat-xf list-formats --packs DIR")
	fmt.Fprintln(w, "both take: --models DIR (default <packs>/../model), --max-distribution public|controlled (default controlled)")
}

func run(args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		usage(stderr)
		return 2
	}
	cmd, rest := args[0], args[1:]
	fs := flag.NewFlagSet("goat-xf "+cmd, flag.ContinueOnError)
	fs.SetOutput(stderr)
	packs := fs.String("packs", "packs", "directory holding <format>/pack.def")
	models := fs.String("models", "", "directory holding <module>.def (default <packs>/../model)")
	maxDist := fs.String("max-distribution", goatxf.DistControlled, "refuse modules and packs above this marking: public or controlled")
	load := func() (*goatxf.Engine, error) {
		dir := *models
		if dir == "" {
			dir = goatxf.DefaultModelsDir(*packs)
		}
		return goatxf.LoadDirs(dir, *packs, *maxDist)
	}
	switch cmd {
	case "convert":
		from := fs.String("from", "", "source format")
		to := fs.String("to", "", "target format")
		set := setFlag{}
		fs.Var(set, "set", "model `key=value` supplied by the caller for a key the message lacks; repeatable")
		if err := fs.Parse(rest); err != nil {
			return 2
		}
		if *from == "" || *to == "" || fs.NArg() != 0 {
			usage(stderr)
			return 2
		}
		eng, err := load()
		if err != nil {
			fmt.Fprintln(stderr, "goat-xf:", err)
			return 1
		}
		in, err := io.ReadAll(stdin)
		if err != nil {
			fmt.Fprintln(stderr, "goat-xf: reading stdin:", err)
			return 1
		}
		// No --set means no context is given: a same-format conversion then
		// skips the context fill and the derivations.
		var context map[string]string
		if len(set) > 0 {
			context = set
		}
		out, err := eng.ConvertWith(*from, *to, in, context)
		if err != nil {
			fmt.Fprintln(stderr, "goat-xf:", err)
			return 1
		}
		if _, err := stdout.Write(out); err != nil {
			fmt.Fprintln(stderr, "goat-xf: writing stdout:", err)
			return 1
		}
		return 0
	case "list-formats":
		if err := fs.Parse(rest); err != nil {
			return 2
		}
		if fs.NArg() != 0 {
			usage(stderr)
			return 2
		}
		eng, err := load()
		if err != nil {
			fmt.Fprintln(stderr, "goat-xf:", err)
			return 1
		}
		for _, p := range eng.Formats() {
			fmt.Fprintf(stdout, "%s\t%s\t%s\n", p.Format, p.Version, p.Wire)
		}
		return 0
	case "-h", "--help", "help":
		usage(stdout)
		return 0
	}
	fmt.Fprintf(stderr, "goat-xf: unknown command %q\n", cmd)
	usage(stderr)
	return 2
}
