package goatxf

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// LoadTool builds an engine the way the command-line tool loads
// (spec/engine-spec.md, Version 0.23, Loading), stopping at the first
// failure:
//
//  1. every module of modelsDir: core.def first, then each other file whose
//     name ends in .def, in byte order of file name, a module after the
//     modules it uses; a modelsDir that does not exist or is not a directory
//     loads no modules;
//  2. with only non-nil, the named subdirectories of packsDir in the order
//     given, a name given twice loaded twice (so the second is
//     duplicate-format); a name that is not one path component, or that is
//     not a subdirectory holding pack.def, is unknown-format when it is
//     reached. With only nil, every entry of packsDir that is a directory (a
//     symbolic link to one included) holding pack.def, other than names
//     beginning with ".", in byte order of name.
//
// A packsDir that cannot be read (only nil) returns an error that is not an
// *Error: the contract gives that case no kind.
func LoadTool(modelsDir, packsDir, maxDistribution string, only []string) (*Engine, error) {
	e := New()
	if err := e.SetMaxDistribution(maxDistribution); err != nil {
		return nil, err
	}
	files, err := readModuleFiles(modelsDir)
	if err != nil {
		return nil, err
	}
	for _, f := range files {
		if err := f.load(e); err != nil {
			return nil, err
		}
	}
	load := func(name string) error {
		p, err := ParsePackFile(filepath.Join(packsDir, name, "pack.def"))
		if err != nil {
			return err
		}
		return e.AddPack(p)
	}
	if only != nil {
		for _, name := range only {
			if !holdsPack(packsDir, name) {
				return nil, &Error{Kind: ErrUnknownFormat, Format: name, Source: packsDir,
					Detail: fmt.Sprintf("%q is not a subdirectory of the packs directory holding pack.def", name)}
			}
			if err := load(name); err != nil {
				return nil, err
			}
		}
		return e, nil
	}
	entries, err := os.ReadDir(packsDir)
	if err != nil {
		return nil, fmt.Errorf("cannot read the packs directory %s: %v", packsDir, err)
	}
	for _, ent := range entries { // os.ReadDir sorts by name, byte order
		name := ent.Name()
		if strings.HasPrefix(name, ".") || !holdsPack(packsDir, name) {
			continue
		}
		if err := load(name); err != nil {
			return nil, err
		}
	}
	return e, nil
}

// holdsPack reports whether name is one path component naming a directory of
// packsDir (a symbolic link to one included) that holds a file pack.def.
func holdsPack(packsDir, name string) bool {
	if name == "" || name == "." || name == ".." || strings.ContainsAny(name, `/\`) {
		return false
	}
	dir := filepath.Join(packsDir, name)
	if st, err := os.Stat(dir); err != nil || !st.IsDir() {
		return false
	}
	st, err := os.Stat(filepath.Join(dir, "pack.def"))
	return err == nil && !st.IsDir()
}
