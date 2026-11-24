package goatxf

import (
	"bytes"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// Spec 0.93, rulings 5 and 6: a load with a licence profile sets the
// engine's distribution limit to public.

const ctlSource = `source "goat-transformers spec/engine-spec.md, Version 0.93 (test fixture)"` + "\n"

func ctlModule(name, dist string) string {
	return "module " + name + "\nversion 0.93.0\ndistribution " + dist + "\n" + ctlSource
}

func ctlPack(format, dist string) string {
	return "format " + format + "\nversion 0.93.0\ndistribution " + dist + "\n" + ctlSource + "wire json\nfield lat pos.lat float\n"
}

const ctlCore = "module core\nversion 0.93.0\ndistribution public\n" + ctlSource + "key lat float - \"a test key\"\n"

const ctlTable = `[licences."Apache-2.0"]
commercial = "yes"
share_alike = false
field_of_use = []
distribution = "public"

[licences."CC-BY-SA-4.0"]
commercial = "yes"
share_alike = true
field_of_use = []
distribution = "public"
`

// ctlTree writes files (path relative to the tree's root: text) and returns
// the root. The tree's packs directory is root/packs and its modules
// root/model.
func ctlTree(t *testing.T, files map[string]string) string {
	t.Helper()
	root := t.TempDir()
	for name, text := range files {
		path := filepath.Join(root, name)
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return root
}

// ctlStandard is a tree with a public core, a public module, a controlled
// module, a public pack, a controlled pack, and a public pack under a
// share-alike licence (outside open).
func ctlStandard(t *testing.T) string {
	return ctlTree(t, map[string]string{
		"licences.toml":            ctlTable,
		"model/core.def":           ctlCore,
		"model/extra.def":          ctlModule("extra", "public"),
		"model/ctl.def":            ctlModule("ctl", "controlled"),
		"packs/pub/pack.def":       ctlPack("c-pub", "public"),
		"packs/ctl/pack.def":       ctlPack("c-ctl", "controlled"),
		"packs/sa/pack.def":        ctlPack("c-sa", "public"),
		"packs/sa/REUSE.toml":      "SPDX-License-Identifier = \"CC-BY-SA-4.0\"\n",
		"other/model/core.def":     ctlCore,
		"other/packs/pub/pack.def": ctlPack("c-pub", "public"),
	})
}

func dirs(root string) (models, packs string) {
	return filepath.Join(root, "model"), filepath.Join(root, "packs")
}

// changeOnLoad makes the text loaded for each file whose path ends in suffix
// read as controlled, as if the file changed after its profile was read.
func changeOnLoad(t *testing.T, suffix string) {
	t.Helper()
	beforeProfileLoad = func(path string, text []byte) []byte {
		if strings.HasSuffix(filepath.ToSlash(path), suffix) {
			return bytes.Replace(text, []byte("distribution public"), []byte("distribution controlled"), 1)
		}
		return text
	}
	t.Cleanup(func() { beforeProfileLoad = nil })
}

// Ruling 5, first sentence: with a profile the limit is public, without a
// message also when the caller asked for controlled.
func TestProfileSetsLimitPublic(t *testing.T) {
	models, packs := dirs(ctlStandard(t))
	for _, profile := range []string{"open", "open+copyleft", "everything"} {
		e, err := LoadToolProfile(models, packs, DistControlled, nil, profile)
		if err != nil {
			t.Fatalf("%s: %v", profile, err)
		}
		if got := e.MaxDistribution(); got != DistPublic {
			t.Errorf("%s: limit %s after a load with a profile, want public", profile, got)
		}
		_, listed, err := LoadToolLicences(models, packs, DistControlled, nil, profile)
		if err != nil {
			t.Fatalf("licences %s: %v", profile, err)
		}
		for _, l := range listed {
			if l.Dir == "ctl" {
				t.Errorf("licences %s lists the controlled pack", profile)
			}
		}
	}
	// No profile: nothing changes (ruling 7).
	e, err := LoadToolProfile(models, packs, DistControlled, nil, "")
	if err != nil {
		t.Fatal(err)
	}
	if got := e.MaxDistribution(); got != DistControlled {
		t.Errorf("no profile: limit %s, want controlled", got)
	}
	_, listed, err := LoadToolLicences(models, packs, DistControlled, nil, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(listed) != 3 {
		t.Errorf("licences with no profile: %v, want three packs", listed)
	}
}

// Ruling 5, last sentence: by ruling 2 nothing a profile holds reads as
// controlled, so with the limit public a tree with controlled files loads,
// without them, also when the caller asked for public.
func TestProfileSkipsBeforeTheLimit(t *testing.T) {
	models, packs := dirs(ctlStandard(t))
	e, err := LoadToolProfile(models, packs, DistPublic, nil, "everything")
	if err != nil {
		t.Fatalf("profile everything, limit public: %v", err)
	}
	if got := formatNames(e); !reflect.DeepEqual(got, []string{"c-pub", "c-sa"}) {
		t.Errorf("formats %v, want [c-pub c-sa]", got)
	}
	if _, ok := e.modules["ctl"]; ok {
		t.Errorf("the controlled module was loaded")
	}
}

// Ruling 5, second sentence: a file that reads as controlled when it is
// loaded is distribution-refused and the load fails, as any load failure.
func TestProfileRefusesAFileThatChanged(t *testing.T) {
	models, packs := dirs(ctlStandard(t))
	for _, c := range []struct{ file, module, format string }{
		{"packs/pub/pack.def", "", "c-pub"},
		{"model/extra.def", "extra", ""},
		{"model/core.def", "core", ""},
	} {
		t.Run(c.file, func(t *testing.T) {
			changeOnLoad(t, c.file)
			e, err := LoadToolProfile(models, packs, DistControlled, nil, "open")
			if !IsKind(err, ErrDistributionRefused) {
				t.Fatalf("got %v, want distribution-refused", err)
			}
			if e != nil {
				t.Errorf("the load failed and still returned an engine")
			}
			le := err.(*Error)
			if le.Module != c.module || le.Format != c.format {
				t.Errorf("error names module %q format %q, want %q %q", le.Module, le.Format, c.module, c.format)
			}
			if _, _, err := LoadToolLicences(models, packs, DistControlled, nil, "open"); !IsKind(err, ErrDistributionRefused) {
				t.Errorf("licences: got %v, want distribution-refused", err)
			}
			// The same on an instance; the limit stays public after the failure.
			inst := New()
			if err := inst.LoadTool(models, packs, nil, "open"); !IsKind(err, ErrDistributionRefused) {
				t.Errorf("instance: got %v, want distribution-refused", err)
			}
			if got := inst.MaxDistribution(); got != DistPublic {
				t.Errorf("instance: limit %s after the failed load, want public", got)
			}
		})
	}
	// Without a profile the change is loaded as it reads: no limit applies.
	changeOnLoad(t, "packs/pub/pack.def")
	if _, _, err := LoadToolLicences(models, packs, DistControlled, []string{"pub"}, ""); err != nil {
		t.Errorf("licences with no profile: %v", err)
	}
}

// Ruling 6, first sentence: the limit is the instance's from the load with a
// profile on, the lower of public and what the caller sets before or after;
// setting controlled afterwards is no error and has no effect.
func TestProfileLimitIsTheInstances(t *testing.T) {
	models, packs := dirs(ctlStandard(t))
	e := New()
	if err := e.SetMaxDistribution(DistControlled); err != nil {
		t.Fatal(err)
	}
	if err := e.LoadTool(models, packs, nil, "open"); err != nil {
		t.Fatal(err)
	}
	if got := formatNames(e); !reflect.DeepEqual(got, []string{"c-pub"}) {
		t.Errorf("formats %v, want [c-pub]", got)
	}
	if got := e.MaxDistribution(); got != DistPublic {
		t.Errorf("limit %s, want public", got)
	}
	if err := e.SetMaxDistribution(DistControlled); err != nil {
		t.Errorf("setting controlled afterwards: %v, want no error", err)
	}
	if got := e.MaxDistribution(); got != DistPublic {
		t.Errorf("limit %s after setting controlled, want public", got)
	}
	if err := e.SetMaxDistribution(DistPublic); err != nil || e.MaxDistribution() != DistPublic {
		t.Errorf("setting public afterwards: %v, %s", err, e.MaxDistribution())
	}
	if err := e.SetMaxDistribution("secret"); !IsKind(err, ErrBadDirective) {
		t.Errorf("setting an unknown limit afterwards: %v, want bad-directive", err)
	}
}

// Ruling 6, first sentence, end: a controlled text loaded directly later is
// distribution-refused.
func TestProfileThenDirectLoad(t *testing.T) {
	models, packs := dirs(ctlStandard(t))
	e := New()
	if err := e.LoadTool(models, packs, nil, "open"); err != nil {
		t.Fatal(err)
	}
	e.SetMaxDistribution(DistControlled)
	if err := e.LoadModel([]byte(ctlModule("later", "controlled")), "later.def"); !IsKind(err, ErrDistributionRefused) {
		t.Errorf("controlled module after the load: %v, want distribution-refused", err)
	}
	if err := e.LoadPack([]byte(ctlPack("c-later", "controlled")), "later/pack.def"); !IsKind(err, ErrDistributionRefused) {
		t.Errorf("controlled pack after the load: %v, want distribution-refused", err)
	}
	if err := e.LoadPack([]byte(ctlPack("c-later", "public")), "later/pack.def"); err != nil {
		t.Errorf("public pack after the load: %v", err)
	}
	// Also when the load with a profile failed (the limit was set before).
	bad := ctlTree(t, map[string]string{"licences.toml": "not a table\n", "model/core.def": ctlCore, "packs/.keep": ""})
	f := New()
	if err := f.LoadTool(filepath.Join(bad, "model"), filepath.Join(bad, "packs"), nil, "open"); !IsKind(err, ErrBadLicence) {
		t.Fatalf("bad table: %v, want bad-licence", err)
	}
	if err := f.LoadModel([]byte(ctlCore), "core.def"); err != nil {
		t.Fatal(err)
	}
	if err := f.LoadPack([]byte(ctlPack("c-later", "controlled")), "later/pack.def"); !IsKind(err, ErrDistributionRefused) {
		t.Errorf("controlled pack after a failed load with a profile: %v, want distribution-refused", err)
	}
}

// Ruling 6, second sentence: a load with a profile on an instance that
// already holds a controlled module or pack is distribution-refused before
// anything is read.
func TestProfileOnAnInstanceHoldingControlled(t *testing.T) {
	models, packs := dirs(ctlStandard(t))
	// A licences.toml that is bad-licence when read: it is not read.
	bad := ctlTree(t, map[string]string{"licences.toml": "not a table\n", "model/core.def": ctlCore,
		"packs/pub/pack.def": ctlPack("c-pub", "public")})
	badModels, badPacks := dirs(bad)

	holdsModule := New()
	if err := holdsModule.LoadModel([]byte(ctlCore), "core.def"); err != nil {
		t.Fatal(err)
	}
	if err := holdsModule.LoadModel([]byte(ctlModule("held", "controlled")), "held.def"); err != nil {
		t.Fatal(err)
	}
	holdsPack := New()
	if err := holdsPack.LoadModel([]byte(ctlCore), "core.def"); err != nil {
		t.Fatal(err)
	}
	if err := holdsPack.LoadPack([]byte(ctlPack("c-held", "controlled")), "held/pack.def"); err != nil {
		t.Fatal(err)
	}
	for name, e := range map[string]*Engine{"module": holdsModule, "pack": holdsPack} {
		before := formatNames(e)
		if err := e.LoadTool(badModels, badPacks, nil, "open"); !IsKind(err, ErrDistributionRefused) {
			t.Errorf("holds a controlled %s, bad table: %v, want distribution-refused", name, err)
		}
		if _, err := e.LoadToolLicences(models, packs, nil, "everything"); !IsKind(err, ErrDistributionRefused) {
			t.Errorf("holds a controlled %s, licences: %v, want distribution-refused", name, err)
		}
		if got := formatNames(e); !reflect.DeepEqual(got, before) {
			t.Errorf("holds a controlled %s: formats %v after the refusal, want %v", name, got, before)
		}
		// The order: the limit is set after that check, so it is unchanged.
		if got := e.MaxDistribution(); got != DistControlled {
			t.Errorf("holds a controlled %s: limit %s after the refusal, want controlled", name, got)
		}
		// With no profile there is no such check.
		if err := e.LoadTool(filepath.Join(bad, "other"), filepath.Join(bad, "none"), nil, ""); err == nil || IsKind(err, ErrDistributionRefused) {
			t.Errorf("holds a controlled %s, no profile: %v, want the packs directory failure", name, err)
		}
	}
	// An instance that holds only public files is not refused.
	e := New()
	if err := e.LoadModel([]byte(ctlCore), "core.def"); err != nil {
		t.Fatal(err)
	}
	if err := e.LoadTool(filepath.Join(ctlStandard(t), "other", "model"), filepath.Join(ctlStandard(t), "other", "packs"), nil, "open"); !IsKind(err, ErrDuplicateModule) {
		t.Errorf("holds public core, loads another core: %v, want duplicate-module", err)
	}
}

// Ruling 6, the order: a profile name that is none of the three is
// bad-licence first, with the limit unchanged; then the instance check; then
// the limit is public, and stays so when the load fails later.
func TestProfileLoadOrder(t *testing.T) {
	models, packs := dirs(ctlStandard(t))
	held := New()
	if err := held.LoadModel([]byte(ctlModule("held", "controlled")), "held.def"); err != nil {
		t.Fatal(err)
	}
	if err := held.LoadTool(models, packs, nil, "Open"); !IsKind(err, ErrBadLicence) {
		t.Errorf("bad name on an instance holding controlled: %v, want bad-licence first", err)
	}
	if got := held.MaxDistribution(); got != DistControlled {
		t.Errorf("limit %s after a bad profile name, want controlled", got)
	}
	if err := held.LoadTool(models, packs, nil, "open"); !IsKind(err, ErrDistributionRefused) {
		t.Errorf("then the instance check: %v, want distribution-refused", err)
	}
	// A later failure leaves the limit public.
	bad := ctlTree(t, map[string]string{"licences.toml": "not a table\n", "packs/.keep": ""})
	e := New()
	if err := e.LoadTool(filepath.Join(bad, "model"), filepath.Join(bad, "packs"), nil, "everything"); !IsKind(err, ErrBadLicence) {
		t.Fatalf("bad table: %v, want bad-licence", err)
	}
	if got := e.MaxDistribution(); got != DistPublic {
		t.Errorf("limit %s after a load with a profile that failed later, want public", got)
	}
	// The package function checks the name before the limit argument.
	if _, err := LoadToolProfile(models, packs, "secret", nil, "Open"); !IsKind(err, ErrBadLicence) {
		t.Errorf("bad name and bad limit: %v, want bad-licence", err)
	}
}

// Ruling 6, last sentence: a later load with no profile is bounded by the
// limit, not by the profile.
func TestProfileThenLoadWithoutProfile(t *testing.T) {
	models, packs := dirs(ctlStandard(t))
	e := New()
	if err := e.LoadTool(models, packs, []string{"pub"}, "open"); err != nil {
		t.Fatal(err)
	}
	// c-sa is outside open, and public: it loads.
	if err := e.LoadTool(filepath.Join(ctlStandard(t), "none"), packs, []string{"sa"}, ""); err != nil {
		t.Errorf("a public pack outside the profile, no profile: %v", err)
	}
	if got := formatNames(e); !reflect.DeepEqual(got, []string{"c-pub", "c-sa"}) {
		t.Errorf("formats %v, want [c-pub c-sa]", got)
	}
	// c-ctl is controlled: the limit refuses it.
	if err := e.LoadTool(filepath.Join(ctlStandard(t), "none"), packs, []string{"ctl"}, ""); !IsKind(err, ErrDistributionRefused) {
		t.Errorf("a controlled pack, no profile: %v, want distribution-refused", err)
	}
}

// Spec 0.93, ruling 2 (fail closed): with a profile a module file that 2b
// gives no name is not loaded, also when it is shown public, and a pack or
// module that uses it is unknown-module; core is no exception. With no
// profile nothing changes.
func TestProfileModuleWithoutAName(t *testing.T) {
	body := "\nversion 0.93.0\ndistribution public\n" + ctlSource + "key k int - \"a test key\"\n"
	usesPack := "format c-uses\nversion 0.93.0\ndistribution public\nuses mx\n" + ctlSource + "wire json\nfield mx.k pos.k int\n"
	for _, line := range []string{"module mx # note", `module "mx"`} {
		tree := ctlTree(t, map[string]string{
			"model/core.def":       ctlCore,
			"model/mx.def":         line + body,
			"packs/uses/pack.def":  usesPack,
			"packs/plain/pack.def": ctlPack("c-plain", "public"),
		})
		models, packs := dirs(tree)
		byModule := ctlTree(t, map[string]string{
			"model/core.def": ctlCore,
			"model/mx.def":   line + body,
			"model/user.def": "module user\nuses mx" + body,
			"packs/.keep":    "",
		})
		noteCore := ctlTree(t, map[string]string{
			"model/core.def":       "module core # note\nversion 0.93.0\ndistribution public\n" + ctlSource + "key lat float - \"a test key\"\n",
			"packs/plain/pack.def": ctlPack("c-plain", "public"),
		})
		for _, profile := range []string{"open", "open+copyleft", "everything"} {
			if _, err := LoadToolProfile(models, packs, DistControlled, []string{"uses"}, profile); !IsKind(err, ErrUnknownModule) {
				t.Errorf("%q, %s, a pack that uses it: %v, want unknown-module", line, profile, err)
			}
			if e, err := LoadToolProfile(models, packs, DistControlled, []string{"plain"}, profile); err != nil {
				t.Errorf("%q, %s, a pack that does not use it: %v", line, profile, err)
			} else if _, ok := e.modules["mx"]; ok {
				t.Errorf("%q, %s: the module was loaded", line, profile)
			}
			if _, _, err := LoadToolLicences(models, packs, DistControlled, []string{"uses"}, profile); !IsKind(err, ErrUnknownModule) {
				t.Errorf("%q, %s, licences: %v, want unknown-module", line, profile, err)
			}
			m, p := dirs(byModule)
			if _, err := LoadToolProfile(m, p, DistControlled, nil, profile); !IsKind(err, ErrUnknownModule) {
				t.Errorf("%q, %s, a module that uses it: %v, want unknown-module", line, profile, err)
			}
			m, p = dirs(noteCore)
			if _, err := LoadToolProfile(m, p, DistControlled, nil, profile); !IsKind(err, ErrUnknownModule) {
				t.Errorf("core with %q, %s: %v, want unknown-module", "module core # note", profile, err)
			}
		}
		// No profile: everything loads, licences included.
		if e, err := LoadToolProfile(models, packs, DistControlled, nil, ""); err != nil {
			t.Errorf("%q, no profile: %v", line, err)
		} else if got := formatNames(e); !reflect.DeepEqual(got, []string{"c-plain", "c-uses"}) {
			t.Errorf("%q, no profile: formats %v", line, got)
		}
		if _, listed, err := LoadToolLicences(models, packs, DistControlled, nil, ""); err != nil || len(listed) != 2 {
			t.Errorf("%q, licences with no profile: %v, %v", line, listed, err)
		}
		m, p := dirs(byModule)
		if _, err := LoadToolProfile(m, p, DistControlled, nil, ""); err != nil {
			t.Errorf("%q, no profile, a module that uses it: %v", line, err)
		}
		m, p = dirs(noteCore)
		if _, err := LoadToolProfile(m, p, DistControlled, nil, ""); err != nil {
			t.Errorf("core with a note, no profile: %v", err)
		}
	}
}
