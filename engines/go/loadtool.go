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
	if profile != "" && !ValidProfile(profile) {
		return nil, nil, notAProfile(profile)
	}
	e := New()
	if err := e.SetMaxDistribution(maxDistribution); err != nil {
		return nil, nil, err
	}
	listed, err := e.loadTool(modelsDir, packsDir, only, profile, licences)
	if err != nil {
		return nil, nil, err
	}
	return e, listed, nil
}

func notAProfile(profile string) error {
	return &Error{Kind: ErrBadLicence, Detail: fmt.Sprintf("%q is not a profile: open, open+copyleft or everything", profile)}
}

// LoadTool loads into e as the package function LoadToolProfile does, with
// e's own limits, stopping at the first failure; what loaded before a
// failure stays loaded. With a profile (spec/engine-spec.md, Version 0.93,
// ruling 6): a name that is not one of the three is bad-licence and changes
// nothing; then, when e already holds a module or pack marked other than
// public, the load is distribution-refused before any file is read; then e's
// distribution limit becomes public for the rest of its life, also when the
// load fails later, whatever SetMaxDistribution is given before or after. A
// later load without a profile is bounded by that limit, not by the profile.
// With profile "" it reads no licence file and changes no limit.
func (e *Engine) LoadTool(modelsDir, packsDir string, only []string, profile string) error {
	_, err := e.loadTool(modelsDir, packsDir, only, profile, profile != "")
	return err
}

// LoadToolLicences is LoadTool that always reads the licence files and also
// returns each pack it loaded, as the package function LoadToolLicences does.
func (e *Engine) LoadToolLicences(modelsDir, packsDir string, only []string, profile string) ([]PackLicence, error) {
	return e.loadTool(modelsDir, packsDir, only, profile, true)
}

// beforeProfileLoad, when set (only by tests), is given the text of each
// module file and pack.def after its profile was read and returns the text
// that is loaded: it stands for a file that changed between the two reads
// (spec 0.93, ruling 5). This engine reads each file once.
var beforeProfileLoad func(path string, text []byte) []byte

func (e *Engine) loadTool(modelsDir, packsDir string, only []string, profile string, licences bool) ([]PackLicence, error) {
	held := rankNone // with no profile every rank is held
	if profile != "" {
		r, ok := profileRank(profile)
		if !ok {
			return nil, notAProfile(profile)
		}
		if e.holdsControlled() {
			return nil, &Error{Kind: ErrDistributionRefused, Source: packsDir,
				Detail: "a load with a licence profile on an engine that already holds a controlled module or pack"}
		}
		e.profiled = true
		held = r
	}
	files := listModuleFiles(modelsDir)
	var table licenceTable
	var byName map[string]int
	if licences {
		t, mods, names, err := licensedModules(packsDir+"/../licences.toml", files)
		if err != nil {
			return nil, err
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
		return nil, err
	}
	for _, f := range ordered {
		if beforeProfileLoad != nil && licences && f.err == nil {
			f = &moduleFile{path: f.path, text: beforeProfileLoad(f.path, f.text), name: f.name, uses: f.uses}
		}
		if err := f.load(e); err != nil {
			return nil, err
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
			if rank = packRank(table, byName, lic, uses, shownPublic(text, rerr == nil)); rank > held {
				return nil // skipped: not otherwise read or checked
			}
			if beforeProfileLoad != nil && rerr == nil {
				text = beforeProfileLoad(path, text)
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
				return nil, &Error{Kind: ErrUnknownFormat, Format: name, Source: packsDir,
					Detail: fmt.Sprintf("%q is not a subdirectory of the packs directory holding pack.def", name)}
			}
			if err := load(name); err != nil {
				return nil, err
			}
		}
	} else {
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
	}
	sort.SliceStable(listed, func(i, j int) bool { return listed[i].Dir < listed[j].Dir })
	return listed, nil
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
