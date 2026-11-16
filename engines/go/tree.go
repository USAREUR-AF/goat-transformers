package goatxf

import (
	"io/fs"
	"os"
	"path"
	"sort"
	"strings"
)

// LoadTree loads the named packs from the tree at root: a directory holding
// model/ and packs/, such as a checkout of the library or a bundle written by
// tools/goat-pkg bundle. See LoadFS.
func (e *Engine) LoadTree(root string, packs []string) error {
	return e.LoadFS(os.DirFS(root), packs)
}

// LoadFS loads the named packs from packs/<name>/pack.def of fsys, and before
// them the model modules they need from model/*.def: core, every module a
// named pack uses, and every module one of those uses, each after the modules
// it uses. Nothing else in the tree is loaded. A module that is already
// loaded is not loaded again, so the call can be repeated with more packs.
//
// fsys can be an embed.FS, which compiles the packs into the program.
func (e *Engine) LoadFS(fsys fs.FS, packs []string) error {
	var chosen []*Pack
	seen := map[string]bool{}
	for _, name := range packs {
		if seen[name] {
			continue
		}
		seen[name] = true
		file := path.Join("packs", name, "pack.def")
		text, err := fs.ReadFile(fsys, file)
		if err != nil {
			return &Error{Kind: ErrUnknownFormat, Format: name, Source: file, Detail: "no pack " + name + " in the tree: " + err.Error()}
		}
		p, err := ParsePack(text, file)
		if err != nil {
			return err
		}
		chosen = append(chosen, p)
	}
	// Every module file of the tree: its text and its `module` and `uses`
	// lines. A file that does not read is left out, and the pack that needs
	// its module then fails with unknown-module.
	type head struct {
		file string
		text []byte
		uses []string
	}
	heads := map[string]*head{}
	files, _ := fs.Glob(fsys, "model/*.def")
	sort.Strings(files)
	for _, f := range files {
		text, err := fs.ReadFile(fsys, f)
		if err != nil {
			continue
		}
		h := &head{file: f, text: text}
		name := ""
		for _, ln := range strings.Split(string(text), "\n") {
			toks, err := tokenize(ln)
			if err != nil || len(toks) != 2 {
				continue
			}
			switch toks[0] {
			case "module":
				if name == "" {
					name = toks[1]
				}
			case "uses":
				h.uses = append(h.uses, toks[1])
			}
		}
		if _, dup := heads[name]; name != "" && !dup {
			heads[name] = h
		}
	}
	visiting := map[string]bool{}
	var load func(name string) error
	load = func(name string) error {
		h, ok := heads[name]
		if _, loaded := e.modules[name]; loaded || !ok {
			return nil
		}
		if visiting[name] {
			return &Error{Kind: ErrBadDirective, Module: name, Source: h.file, Detail: "module " + name + " is in a cycle of uses lines"}
		}
		visiting[name] = true
		for _, u := range h.uses {
			if u != name {
				if err := load(u); err != nil {
					return err
				}
			}
		}
		delete(visiting, name)
		return e.LoadModel(h.text, h.file)
	}
	if err := load(CoreModule); err != nil {
		return err
	}
	for _, p := range chosen {
		for _, u := range p.Uses {
			if err := load(u); err != nil {
				return err
			}
		}
	}
	for _, p := range chosen {
		if err := e.AddPack(p); err != nil {
			return err
		}
	}
	return nil
}
