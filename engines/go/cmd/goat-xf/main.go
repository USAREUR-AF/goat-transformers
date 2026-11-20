// Command goat-xf is the Go engine's command-line tool. It follows the
// command-line contract of spec/engine-spec.md, Version 0.23:
//
//	goat-xf convert --from <format> --to <format> [--set <key>=<value>]... <options>
//	goat-xf list-formats <options>
//	goat-xf capability --from <format> --to <format> <options>
//	goat-xf matrix <options>
//	goat-xf help
//
// <options> are --packs <dir> (default packs), --models <dir> (default the
// --packs text followed by /../model), --packs-only <name>[,<name>...],
// --max-items <n> (default 100000) and --max-distribution public|controlled
// (default controlled). Exit status 0 on success, 1 for a load or call
// failure (standard error's first line begins with the kind and a colon), 2
// for a usage error, checked before anything is loaded.
package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	goatxf "github.com/USAREUR-AF/goat-transformers/engines/go"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr))
}

const usageText = `usage:
  goat-xf convert --from <format> --to <format> [--set <key>=<value>]... <options>   (stdin -> stdout)
  goat-xf list-formats <options>
  goat-xf capability --from <format> --to <format> <options>
  goat-xf matrix <options>
  goat-xf help
<options>, in any order, each at most once:
  --packs <dir>                              the directory whose subdirectories are packs (default packs)
  --models <dir>                             the directory of model modules (default <packs>/../model)
  --packs-only <name>[,<name>...]            load only these subdirectories of --packs, in the order given
  --max-items <n>                            the limit on list items one decode holds (default 100000)
  --max-distribution <public|controlled>     the distribution limit (default controlled)
`

// options are the arguments of one run, after they are checked.
type options struct {
	cmd       string
	from, to  string
	sets      []goatxf.KeyValue
	packs     string
	models    string
	hasModels bool
	only      []string // nil: every pack
	maxItems  int64
	maxDist   string
}

// usageError is a usage error of the contract: exit 2.
type usageError string

func (u usageError) Error() string { return string(u) }

// parse checks every argument (spec 0.23, Arguments and Usage errors).
func parse(args []string) (*options, error) {
	if len(args) == 0 {
		return nil, usageError("no subcommand")
	}
	o := &options{cmd: args[0], packs: "packs", maxItems: goatxf.DefaultMaxItems, maxDist: goatxf.DistControlled}
	takes := map[string]bool{"--packs": true, "--models": true, "--packs-only": true, "--max-items": true, "--max-distribution": true}
	switch o.cmd {
	case "convert":
		takes["--from"], takes["--to"], takes["--set"] = true, true, true
	case "capability":
		takes["--from"], takes["--to"] = true, true
	case "list-formats", "matrix":
	default:
		return nil, usageError(fmt.Sprintf("unknown subcommand %q", o.cmd))
	}
	seen := map[string]bool{}
	rest := args[1:]
	for i := 0; i < len(rest); i += 2 {
		name := rest[i]
		if !takes[name] {
			return nil, usageError(fmt.Sprintf("%s takes no option %q", o.cmd, name))
		}
		if i+1 == len(rest) {
			return nil, usageError(fmt.Sprintf("%s needs a value", name))
		}
		value := rest[i+1]
		if name != "--set" && seen[name] {
			return nil, usageError(fmt.Sprintf("%s given twice", name))
		}
		seen[name] = true
		switch name {
		case "--from":
			o.from = value
		case "--to":
			o.to = value
		case "--set":
			key, val, ok := strings.Cut(value, "=")
			if !ok || key == "" {
				return nil, usageError(fmt.Sprintf("--set takes <key>=<value>, got %q", value))
			}
			o.sets = append(o.sets, goatxf.KeyValue{Key: key, Value: val})
		case "--packs":
			o.packs = value
		case "--models":
			o.models, o.hasModels = value, true
		case "--packs-only":
			names := strings.Split(value, ",")
			for _, n := range names {
				if n == "" {
					return nil, usageError(fmt.Sprintf("--packs-only holds an empty name: %q", value))
				}
			}
			o.only = names
		case "--max-items":
			n, ok := maxItems(value)
			if !ok {
				return nil, usageError(fmt.Sprintf("--max-items takes digits 0 to 9 for a value of at most 2^63-1, got %q", value))
			}
			o.maxItems = n
		case "--max-distribution":
			if value != goatxf.DistPublic && value != goatxf.DistControlled {
				return nil, usageError(fmt.Sprintf("--max-distribution takes public or controlled, got %q", value))
			}
			o.maxDist = value
		}
	}
	if o.cmd == "convert" || o.cmd == "capability" {
		if !seen["--from"] || !seen["--to"] {
			return nil, usageError(o.cmd + " needs --from and --to")
		}
	}
	if !o.hasModels {
		// The --packs text as given, followed by /../model, resolved by the
		// operating system: not cleaned, so a symbolic link is followed.
		o.models = o.packs + "/../model"
	}
	return o, nil
}

// maxItems reads one or more digits 0 to 9 alone, leading zeros allowed, as
// a value of at most 2^63-1.
func maxItems(s string) (int64, bool) {
	if s == "" || strings.TrimLeft(s, "0123456789") != "" {
		return 0, false
	}
	t := strings.TrimLeft(s, "0")
	if t == "" {
		return 0, true
	}
	n, err := strconv.ParseInt(t, 10, 64)
	return n, err == nil
}

func run(args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	if len(args) > 0 && (args[0] == "help" || args[0] == "-h" || args[0] == "--help") {
		io.WriteString(stdout, usageText)
		return 0
	}
	o, err := parse(args)
	if err != nil {
		fmt.Fprintf(stderr, "goat-xf: %v\n%s", err, usageText)
		return 2
	}
	fail := func(err error) int {
		fmt.Fprintln(stderr, err)
		return 1
	}
	eng, err := goatxf.LoadTool(o.models, o.packs, o.maxDist, o.only)
	if err != nil {
		return fail(err)
	}
	eng.SetMaxItems(o.maxItems)
	var out []byte
	switch o.cmd {
	case "convert":
		// from, then to, before standard input is read.
		if _, err := eng.Pack(o.from); err != nil {
			return fail(err)
		}
		if _, err := eng.Pack(o.to); err != nil {
			return fail(err)
		}
		in, err := io.ReadAll(stdin)
		if err != nil {
			return fail(fmt.Errorf("goat-xf: reading standard input: %v", err))
		}
		// No --set: no context is given (o.sets is nil).
		out, err = eng.ConvertOrdered(o.from, o.to, in, o.sets)
		if err != nil {
			return fail(err)
		}
	case "list-formats":
		var b strings.Builder
		for _, p := range eng.Formats() {
			fmt.Fprintf(&b, "%s\t%s\t%s\n", p.Format, p.Version, p.Wire)
		}
		out = []byte(b.String())
	case "capability":
		c, err := eng.Capability(o.from, o.to)
		if err != nil {
			return fail(err)
		}
		out = []byte(capabilityLine(o.from, o.to, c))
	case "matrix":
		var b strings.Builder
		b.WriteString("from\tto\tgrade\tcarried\tdropped\n")
		formats := eng.Formats()
		for _, src := range formats {
			for _, dst := range formats {
				c, err := eng.Capability(src.Format, dst.Format)
				if err != nil {
					return fail(err)
				}
				b.WriteString(capabilityLine(src.Format, dst.Format, c))
			}
		}
		out = []byte(b.String())
	}
	w := bufio.NewWriter(stdout)
	w.Write(out)
	if err := w.Flush(); err != nil {
		fmt.Fprintf(stderr, "goat-xf: writing standard output: %v\n", err)
		return 1
	}
	return 0
}

// capabilityLine is one line of the matrix form: from, to, grade, carried,
// dropped, separated by tabs, the entries of a list joined by a space.
func capabilityLine(from, to string, c *goatxf.Capability) string {
	return from + "\t" + to + "\t" + c.Grade + "\t" + strings.Join(c.Carried, " ") + "\t" + strings.Join(c.Dropped, " ") + "\n"
}
