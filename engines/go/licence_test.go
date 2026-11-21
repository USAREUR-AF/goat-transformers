package goatxf

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

const licenceFixtures = "../../packs/conformance/tool-fixtures"

func formatNames(e *Engine) []string {
	var out []string
	for _, p := range e.Formats() {
		out = append(out, p.Format)
	}
	return out
}

// TestLoadToolProfile: spec 0.29, ruling 3, through the library loader.
func TestLoadToolProfile(t *testing.T) {
	packs := filepath.Join(licenceFixtures, "licences-a", "packs")
	models := filepath.Join(licenceFixtures, "licences-a", "model")
	cases := []struct {
		profile string
		want    []string
	}{
		{"open", []string{"lic-aa", "lic-plain"}},
		{"open+copyleft", []string{"lic-aa", "lic-copyleft", "lic-plain", "lic-uses-sa"}},
		{"everything", []string{"lic-aa", "lic-copyleft", "lic-fou", "lic-nc", "lic-not-in-table", "lic-plain",
			"lic-unstated", "lic-uses-book", "lic-uses-derived", "lic-uses-sa"}},
		{"", []string{"lic-aa", "lic-closed", "lic-copyleft", "lic-fou", "lic-nc", "lic-not-in-table", "lic-plain",
			"lic-unstated", "lic-uses-book", "lic-uses-derived", "lic-uses-sa"}},
	}
	for _, c := range cases {
		e, err := LoadToolProfile(models, packs, DistControlled, nil, c.profile)
		if err != nil {
			t.Fatalf("profile %q: %v", c.profile, err)
		}
		if got := formatNames(e); !reflect.DeepEqual(got, c.want) {
			t.Errorf("profile %q: formats %v, want %v", c.profile, got, c.want)
		}
	}
	// A module outside the profile is not loaded: book is CC-BY-NC-SA.
	e, err := LoadToolProfile(models, packs, DistControlled, nil, "open")
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := e.modules["book"]; ok {
		t.Errorf("open loaded module book")
	}
	if _, ok := e.modules["sa"]; ok {
		t.Errorf("open loaded module sa")
	}
	if _, err := LoadToolProfile(models, packs, DistControlled, nil, "Open"); !IsKind(err, ErrBadLicence) {
		t.Errorf("profile Open: %v, want bad-licence", err)
	}
	// With no profile no licence file is read: a bad table is not seen.
	bad := filepath.Join(licenceFixtures, "licences-bad-table")
	if _, err := LoadToolProfile(filepath.Join(bad, "model"), filepath.Join(bad, "packs"), DistControlled, nil, ""); err != nil {
		t.Errorf("no profile, bad table: %v", err)
	}
	if _, err := LoadToolProfile(filepath.Join(bad, "model"), filepath.Join(bad, "packs"), DistControlled, nil, "everything"); !IsKind(err, ErrBadLicence) {
		t.Errorf("profile everything, bad table: %v, want bad-licence", err)
	}
	// A pack outside the profile is skipped before its failure.
	cc := filepath.Join(licenceFixtures, "licences-core-copyleft")
	e, err = LoadToolProfile(filepath.Join(cc, "model"), filepath.Join(cc, "packs"), DistControlled, nil, "open+copyleft")
	if err != nil {
		t.Fatalf("core-copyleft: %v", err)
	}
	if got := formatNames(e); !reflect.DeepEqual(got, []string{"lic-plain"}) {
		t.Errorf("core-copyleft: %v", got)
	}
}

func TestLoadToolLicences(t *testing.T) {
	packs := filepath.Join(licenceFixtures, "licences-a", "packs")
	models := filepath.Join(licenceFixtures, "licences-a", "model")
	_, listed, err := LoadToolLicences(models, packs, DistControlled, []string{"zz-first-by-format", "closed", "uses-sa"}, "")
	if err != nil {
		t.Fatal(err)
	}
	want := []PackLicence{
		{"closed", "lic-closed", "OGL-UK-3.0", "none"},
		{"uses-sa", "lic-uses-sa", "Apache-2.0", "open+copyleft"},
		{"zz-first-by-format", "lic-aa", "Apache-2.0", "open"},
	}
	if !reflect.DeepEqual(listed, want) {
		t.Errorf("got %v, want %v", listed, want)
	}
}

func writeFile(t *testing.T, path, text string) string {
	t.Helper()
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLicenceFiles(t *testing.T) {
	dir := t.TempDir()
	reuse := func(text string) (string, error) {
		return readPackLicence(writeFile(t, filepath.Join(dir, "REUSE.toml"), text))
	}
	modLic := func(text string) (string, error) {
		return readModuleLicence(writeFile(t, filepath.Join(dir, "m.def.license"), text))
	}
	for _, c := range []struct {
		text, want string // want "" is bad-licence
	}{
		// REUSE-IgnoreStart: the quoted licence lines below are data
		{"SPDX-License-Identifier = \"MIT\"\n", "MIT"},
		{"  SPDX-License-Identifier\t=\"MIT\"\r\n", "MIT"},
		{"SPDX-License-Identifier = \"MIT\"\r", "MIT"},
		{"SPDX-License-Identifier: GPL-3.0\nSPDX-License-Identifier = \"MIT\"\n", "MIT"},
		{"SPDX-License-IdentifierX = \"x\"\nSPDX-License-Identifier = \"MIT\"\n", "MIT"},
		{"\xef\xbb\xbfSPDX-License-Identifier = \"MIT\"\n", ""},
		{"SPDX-License-Identifier = \"MIT\" # c\n", ""},
		{"SPDX-License-Identifier = \"MIT\"\nSPDX-License-Identifier = \"MIT\"\n", ""},
		{"SPDX-License-Identifier = \"a b\"\n", ""},
		{"nothing\n", ""},
		{"SPDX-License-Identifier = \"MIT\"\n\xff\n", ""},
	} {
		got, err := reuse(c.text)
		if c.want == "" && !IsKind(err, ErrBadLicence) || c.want != "" && (err != nil || got != c.want) {
			t.Errorf("REUSE.toml %q: %q, %v; want %q", c.text, got, err, c.want)
		}
	}
	for _, c := range []struct {
		text, want string
	}{
		{"SPDX-License-Identifier: MIT\n", "MIT"},
		{"SPDX-License-Identifier:\t\tMIT \r\n", "MIT"},
		{"SPDX-License-Identifier = \"GPL\"\nSPDX-License-Identifier: MIT\n", "MIT"},
		{"SPDX-License-Identifier:MIT\n", ""},
		{"SPDX-License-Identifier:\n", ""},
		{"SPDX-License-Identifier: MIT OR GPL\n", ""},
		// REUSE-IgnoreEnd
		{"", ""},
	} {
		got, err := modLic(c.text)
		if c.want == "" && !IsKind(err, ErrBadLicence) || c.want != "" && (err != nil || got != c.want) {
			t.Errorf(".def.license %q: %q, %v; want %q", c.text, got, err, c.want)
		}
	}
	// Does not exist (no entry, or a part before the last is not a
	// directory): Apache-2.0. A directory: bad-licence.
	if got, err := readPackLicence(filepath.Join(dir, "absent")); err != nil || got != DefaultLicence {
		t.Errorf("absent: %q, %v", got, err)
	}
	if got, err := readPackLicence(filepath.Join(dir, "REUSE.toml", "x")); err != nil || got != DefaultLicence {
		t.Errorf("under a file: %q, %v", got, err)
	}
	if _, err := readPackLicence(dir); !IsKind(err, ErrBadLicence) {
		t.Errorf("a directory: %v, want bad-licence", err)
	}
}

func TestLicenceTable(t *testing.T) {
	dir := t.TempDir()
	const row = "[licences.\"MIT\"]\ncommercial = \"yes\"\nshare_alike = false\nfield_of_use = []\ndistribution = \"public\"\n"
	read := func(text string) (licenceTable, error) {
		return readLicenceTable(writeFile(t, filepath.Join(dir, "licences.toml"), text))
	}
	tab, err := read("# c\n\n" + row + "name = \"x\"\nurl=\"u\"\nattribution\t= true\n" +
		"[licences.\"A+\"]\n distribution=\"controlled\"\ncommercial=\"yes\"\nshare_alike=false\nfield_of_use=[\"\"]\n" +
		"[licences.\"B\"]\ncommercial = \"yes\"\nshare_alike = true\nfield_of_use = []\ndistribution = \"public\"\n" +
		"[licences.\"C\"]\ncommercial = \"yes\"\nshare_alike = false\nfield_of_use = [\"x\"]\ndistribution = \"public\"\n")
	if err != nil {
		t.Fatal(err)
	}
	for id, want := range map[string]int{"MIT": rankOpen, "A+": rankNone, "B": rankOpenCopyleft, "C": rankEverything, "D": rankEverything} {
		if got := tab.rank(id); got != want {
			t.Errorf("rank %s: %d, want %d", id, got, want)
		}
	}
	for _, bad := range []string{
		"x = 1\n" + row,
		row + "field_of_use = []\n",
		row + "name = 1\nname = 2\n",
		row + "names = 1\n",
		row + "other = 1\n",
		row + row,
		"[licences.\"MIT\"]\ncommercial = \"yes\"\nshare_alike = false\nfield_of_use = [ ]\ndistribution = \"public\"\n",
		"[licences.\"MIT\"]\ncommercial = \"yes\"\nshare_alike = false\nfield_of_use = []\ndistribution = \"public\" # c\n",
		"[licences.\"MIT\"]\ncommercial = \"maybe\"\nshare_alike = false\nfield_of_use = []\ndistribution = \"public\"\n",
		"[licences.\"MIT\"]\ncommercial = \"yes\"\nshare_alike = false\nfield_of_use = []\n",
		"[licences. \"MIT\"]\ncommercial = \"yes\"\nshare_alike = false\nfield_of_use = []\ndistribution = \"public\"\n",
		row + "[other]\n",
		"\xef\xbb\xbf" + row,
	} {
		if _, err := read(bad); !IsKind(err, ErrBadLicence) {
			t.Errorf("table %q: %v, want bad-licence", bad, err)
		}
	}
	tab, err = readLicenceTable(filepath.Join(dir, "absent.toml"))
	if err != nil || len(tab) != 1 || tab.rank(DefaultLicence) != rankOpen {
		t.Errorf("absent table: %v, %v", tab, err)
	}
}

func TestProfileHeader(t *testing.T) {
	name, uses := profileHeader([]byte("module  a\r\nmodule b\nuses x # c\nuses \"y\"\n\tuses\tz-1_\nusesq\nuses\n"))
	if name != "a" || !reflect.DeepEqual(uses, []string{"z-1_"}) {
		t.Errorf("got %q %v", name, uses)
	}
	if name, uses := profileHeader([]byte("module a\n\xff")); name != "" || uses != nil {
		t.Errorf("not UTF-8: %q %v", name, uses)
	}
}

// TestDefFilesRegularOnly: spec 0.23, Loading, 1: a module file is a regular
// file or a symbolic link to one.
func TestDefFilesRegularOnly(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "b.def"), "")
	if err := os.Mkdir(filepath.Join(dir, "d.def"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("b.def", filepath.Join(dir, "c.def")); err != nil {
		t.Skip(err)
	}
	if err := os.Symlink("absent", filepath.Join(dir, "e.def")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("d.def", filepath.Join(dir, "f.def")); err != nil {
		t.Fatal(err)
	}
	got := defFiles(dir)
	want := []string{filepath.Join(dir, "b.def"), filepath.Join(dir, "c.def")}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
}
