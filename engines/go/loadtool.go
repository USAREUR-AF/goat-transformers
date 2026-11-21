package goatxf

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
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
//
// LoadTool reads no licence file: it is LoadToolProfile with no profile.
func LoadTool(modelsDir, packsDir, maxDistribution string, only []string) (*Engine, error) {
	e, _, err := loadTool(modelsDir, packsDir, maxDistribution, only, "", false)
	return e, err
}

// LoadToolProfile is LoadTool with a licence profile (spec/engine-spec.md,
// Version 0.29): "open", "open+copyleft" or "everything", or "" for none.
// With a profile it first reads packsDir + "/../licences.toml" and, for each
// module file, its licence (<file>.license) and its `module` and `uses`
// lines; it loads only the modules and packs the profile holds, and a pack it
// does not hold is skipped without being read further. A licence file that
// cannot be read as the specification says, or a profile name that is not one
// of the three, is bad-licence. With "" it reads no licence file and is
// LoadTool.
func LoadToolProfile(modelsDir, packsDir, maxDistribution string, only []string, profile string) (*Engine, error) {
	e, _, err := loadTool(modelsDir, packsDir, maxDistribution, only, profile, profile != "")
	return e, err
}

// LoadToolLicences is LoadToolProfile that always reads the licence files,
// with or without a profile, and also returns the licence and profile of
// each loaded pack in byte order of its directory name (the `licences`
// subcommand, spec 0.29, ruling 4c). With profile "" every module and pack
// is held.
func LoadToolLicences(modelsDir, packsDir, maxDistribution string, only []string, profile string) (*Engine, []PackLicence, error) {
	return loadTool(modelsDir, packsDir, maxDistribution, only, profile, true)
}

func loadTool(modelsDir, packsDir, maxDistribution string, only []string, profile string, licences bool) (*Engine, []PackLicence, error) {
	held := rankNone // with no profile every rank is held
	if profile != "" {
		r, ok := profileRank(profile)
		if !ok {
			return nil, nil, &Error{Kind: ErrBadLicence, Detail: fmt.Sprintf("%q is not a profile: open, open+copyleft or everything", profile)}
		}
		held = r
	}
	e := New()
	if err := e.SetMaxDistribution(maxDistribution); err != nil {
		return nil, nil, err
	}
	files := listModuleFiles(modelsDir)
	var table licenceTable
	var byName map[string]int
	if licences {
		t, mods, names, err := licensedModules(packsDir+"/../licences.toml", files)
		if err != nil {
			return nil, nil, err
		}
		table, byName = t, names
		files = files[:0:0]
		for _, m := range mods {
			if m.rank <= held {
				files = append(files, m.file)
			}
		}
	}
	ordered, err := orderModuleFiles(files)
	if err != nil {
		return nil, nil, err
	}
	for _, f := range ordered {
		if err := f.load(e); err != nil {
			return nil, nil, err
		}
	}
	var listed []PackLicence
	load := func(name string) error {
		path := filepath.Join(packsDir, name, "pack.def")
		text, rerr := os.ReadFile(path)
		var lic string
		var rank int
		if licences {
			var err error
			if lic, err = readPackLicence(filepath.Join(packsDir, name, "REUSE.toml")); err != nil {
				return err
			}
			var uses []string
			if rerr == nil {
				_, uses = profileHeader(text)
			}
			if rank = packRank(table, byName, lic, uses); rank > held {
				return nil // skipped: not otherwise read or checked
			}
		}
		if rerr != nil {
			return &Error{Kind: ErrBadDirective, Source: path, Detail: rerr.Error()}
		}
		p, err := ParsePack(text, path)
		if err != nil {
			return err
		}
		if err := e.AddPack(p); err != nil {
			return err
		}
		if licences {
			listed = append(listed, PackLicence{Dir: name, Format: p.Format, Licence: lic, Profile: profileName(rank)})
		}
		return nil
	}
	if only != nil {
		for _, name := range only {
			if !holdsPack(packsDir, name) {
				return nil, nil, &Error{Kind: ErrUnknownFormat, Format: name, Source: packsDir,
					Detail: fmt.Sprintf("%q is not a subdirectory of the packs directory holding pack.def", name)}
			}
			if err := load(name); err != nil {
				return nil, nil, err
			}
		}
	} else {
		entries, err := os.ReadDir(packsDir)
		if err != nil {
			return nil, nil, fmt.Errorf("cannot read the packs directory %s: %v", packsDir, err)
		}
		for _, ent := range entries { // os.ReadDir sorts by name, byte order
			name := ent.Name()
			if strings.HasPrefix(name, ".") || !holdsPack(packsDir, name) {
				continue
			}
			if err := load(name); err != nil {
				return nil, nil, err
			}
		}
	}
	sort.SliceStable(listed, func(i, j int) bool { return listed[i].Dir < listed[j].Dir })
	return e, listed, nil
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
