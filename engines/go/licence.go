package goatxf

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"strings"
	"syscall"
	"unicode/utf8"
)

// The licence profiles of spec/engine-spec.md, Version 0.29. Each holds
// itself and the profiles before it.
const (
	ProfileOpen         = "open"
	ProfileOpenCopyleft = "open+copyleft"
	ProfileEverything   = "everything"
)

// Profile ranks, in the order open < open+copyleft < everything < none.
const (
	rankOpen = iota
	rankOpenCopyleft
	rankEverything
	rankNone
)

// profileRank gives the rank of one of the three profile names.
func profileRank(name string) (int, bool) {
	switch name {
	case ProfileOpen:
		return rankOpen, true
	case ProfileOpenCopyleft:
		return rankOpenCopyleft, true
	case ProfileEverything:
		return rankEverything, true
	}
	return 0, false
}

// profileName writes a rank: the profile's name, or none.
func profileName(rank int) string {
	switch rank {
	case rankOpen:
		return ProfileOpen
	case rankOpenCopyleft:
		return ProfileOpenCopyleft
	case rankEverything:
		return ProfileEverything
	}
	return "none"
}

// ValidProfile reports whether name is one of the three profiles.
func ValidProfile(name string) bool {
	_, ok := profileRank(name)
	return ok
}

// DefaultLicence is the licence of a pack or module with no licence file,
// and the one row of the table when licences.toml does not exist.
const DefaultLicence = "Apache-2.0"

func badLicence(path string, line int, format string, args ...any) error {
	return &Error{Kind: ErrBadLicence, Source: path, Line: line, Detail: fmt.Sprintf(format, args...)}
}

// notExist reports whether a failure to read a file means it does not exist
// (ruling 1, Where): no entry has that name, or a part of the path before
// the last is not a directory or does not exist.
func notExist(err error) bool {
	return errors.Is(err, fs.ErrNotExist) || errors.Is(err, syscall.ENOENT) || errors.Is(err, syscall.ENOTDIR)
}

// licenceLines cuts text into lines as ruling 1 says: at each line feed, one
// carriage return directly before a line feed or at the end of the file
// removed with it, each line trimmed of spaces and tabs at both ends.
func licenceLines(text string) []string {
	parts := strings.Split(text, "\n")
	for i, p := range parts {
		p = strings.TrimSuffix(p, "\r")
		parts[i] = strings.Trim(p, " \t")
	}
	return parts
}

// readLicenceFile reads one file of ruling 1. exists is false when the file
// does not exist; any other failure, and text that is not UTF-8, is
// bad-licence.
func readLicenceFile(path string) (lines []string, exists bool, err error) {
	b, rerr := os.ReadFile(path)
	if rerr != nil {
		if notExist(rerr) {
			return nil, false, nil
		}
		return nil, true, badLicence(path, 0, "cannot read the licence file: %v", rerr)
	}
	if !utf8.Valid(b) {
		return nil, true, badLicence(path, 0, "the licence file is not valid UTF-8")
	}
	return licenceLines(string(b)), true, nil
}

// isLicenceID: one or more of A-Z, a-z, 0-9, '.', '-' and '+'.
func isLicenceID(s string) bool {
	if s == "" {
		return false
	}
	for i := 0; i < len(s); i++ {
		c := s[i]
		if !(c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '.' || c == '-' || c == '+') {
			return false
		}
	}
	return true
}

// isBlank: a space or a tab.
func isBlank(c byte) bool { return c == ' ' || c == '\t' }

// REUSE-IgnoreStart: the quoted licence lines below are data
const spdxTag = "SPDX-License-Identifier"

// readPackLicence reads <pack>/REUSE.toml (ruling 1a).
func readPackLicence(path string) (string, error) {
	lines, exists, err := readLicenceFile(path)
	if err != nil {
		return "", err
	}
	if !exists {
		return DefaultLicence, nil
	}
	id, n := "", 0
	for i, ln := range lines {
		if !strings.HasPrefix(ln, spdxTag) {
			continue
		}
		rest := ln[len(spdxTag):]
		if rest == "" || !(isBlank(rest[0]) || rest[0] == '=') {
			continue // SPDX-License-Identifier: and the like are passed over
		}
		rest = strings.TrimLeft(rest, " \t")
		ok := false
		if strings.HasPrefix(rest, "=") {
			v := strings.TrimLeft(rest[1:], " \t")
			if len(v) >= 2 && v[0] == '"' && v[len(v)-1] == '"' && isLicenceID(v[1:len(v)-1]) {
				ok = true
				id = v[1 : len(v)-1]
			}
		}
		if !ok {
			return "", badLicence(path, i+1, "%s line is not %s = \"<licence id>\"", spdxTag, spdxTag)
		}
		n++
	}
	if n != 1 {
		return "", badLicence(path, 0, "the file holds %d licence lines, not exactly one", n)
	}
	return id, nil
}

// readModuleLicence reads <models>/<m>.def.license (ruling 1b).
func readModuleLicence(path string) (string, error) {
	lines, exists, err := readLicenceFile(path)
	if err != nil {
		return "", err
	}
	if !exists {
		return DefaultLicence, nil
	}
	tag := spdxTag + ":"
	id, n := "", 0
	for i, ln := range lines {
		if !strings.HasPrefix(ln, tag) {
			continue // SPDX-License-Identifier = ... and the like are passed over
			// REUSE-IgnoreEnd
		}
		rest := ln[len(tag):]
		v := strings.TrimLeft(rest, " \t")
		if len(v) == len(rest) || !isLicenceID(v) {
			return "", badLicence(path, i+1, "%s line is not %s <licence id>", tag, tag)
		}
		id = v
		n++
	}
	if n != 1 {
		return "", badLicence(path, 0, "the file holds %d licence lines, not exactly one", n)
	}
	return id, nil
}

// licenceRow is one row of licences.toml (ruling 1c).
type licenceRow struct {
	commercial   string // yes, no or unknown
	shareAlike   bool
	fieldOfUse   bool // a field of use is given
	distribution string
}

// rank is the profile of a licence of the table (ruling 2a).
func (r *licenceRow) rank() int {
	switch {
	case r.distribution == DistControlled:
		return rankNone
	case r.commercial == "yes" && !r.fieldOfUse && !r.shareAlike:
		return rankOpen
	case r.commercial == "yes" && !r.fieldOfUse:
		return rankOpenCopyleft
	}
	return rankEverything
}

// licenceTable is licences.toml, read.
type licenceTable map[string]*licenceRow

// rank is the profile of a licence (ruling 2a); one not in the table is in
// everything.
func (t licenceTable) rank(id string) int {
	if r, ok := t[id]; ok {
		return r.rank()
	}
	return rankEverything
}

// keyValue reads `<key>`, any spaces or tabs, `=`, any spaces or tabs, and
// returns what follows; ok is false when ln is not of that form.
func keyValue(ln, key string) (string, bool) {
	if !strings.HasPrefix(ln, key) {
		return "", false
	}
	rest := strings.TrimLeft(ln[len(key):], " \t")
	if !strings.HasPrefix(rest, "=") {
		return "", false
	}
	return strings.TrimLeft(rest[1:], " \t"), true
}

// readLicenceTable reads licences.toml (ruling 1c).
func readLicenceTable(path string) (licenceTable, error) {
	lines, exists, err := readLicenceFile(path)
	if err != nil {
		return nil, err
	}
	if !exists {
		return licenceTable{DefaultLicence: {commercial: "yes", distribution: DistPublic}}, nil
	}
	table := licenceTable{}
	var row *licenceRow
	rowID, rowLine := "", 0
	var seen map[string]bool
	required := []string{"commercial", "share_alike", "field_of_use", "distribution"}
	closeRow := func() error {
		if row == nil {
			return nil
		}
		for _, k := range required {
			if !seen[k] {
				return badLicence(path, rowLine, "the row of %s has no %s line", rowID, k)
			}
		}
		return nil
	}
	for i, ln := range lines {
		lineNo := i + 1
		if ln == "" || strings.HasPrefix(ln, "#") {
			continue
		}
		if strings.HasPrefix(ln, "[") {
			const head, tail = `[licences."`, `"]`
			if !strings.HasPrefix(ln, head) || !strings.HasSuffix(ln, tail) || len(ln) < len(head)+len(tail) ||
				!isLicenceID(ln[len(head):len(ln)-len(tail)]) {
				return nil, badLicence(path, lineNo, "%q is not a row header [licences.\"<licence id>\"]", ln)
			}
			if err := closeRow(); err != nil {
				return nil, err
			}
			rowID, rowLine = ln[len(head):len(ln)-len(tail)], lineNo
			if _, dup := table[rowID]; dup {
				return nil, badLicence(path, lineNo, "a second row of %s", rowID)
			}
			row = &licenceRow{}
			table[rowID] = row
			seen = map[string]bool{}
			continue
		}
		if row == nil {
			return nil, badLicence(path, lineNo, "a line before the first row: %q", ln)
		}
		key, ok := "", false
		for _, k := range required {
			v, isKey := keyValue(ln, k)
			if !isKey {
				continue
			}
			key = k
			switch k {
			case "commercial":
				switch v {
				case `"yes"`, `"no"`, `"unknown"`:
					row.commercial, ok = v[1:len(v)-1], true
				}
			case "share_alike":
				switch v {
				case "true", "false":
					row.shareAlike, ok = v == "true", true
				}
			case "field_of_use":
				if v == "[]" {
					row.fieldOfUse, ok = false, true
				} else if len(v) >= 4 && strings.HasPrefix(v, `["`) && strings.HasSuffix(v, `"]`) {
					row.fieldOfUse, ok = true, true
				}
			case "distribution":
				switch v {
				case `"public"`, `"controlled"`:
					row.distribution, ok = v[1:len(v)-1], true
				}
			}
			break
		}
		if key == "" {
			for _, k := range []string{"name", "url", "attribution"} {
				if strings.HasPrefix(ln, k) && len(ln) > len(k) && (isBlank(ln[len(k)]) || ln[len(k)] == '=') {
					key, ok = k, true
					break
				}
			}
		}
		if key == "" {
			return nil, badLicence(path, lineNo, "%q is not a line of a row", ln)
		}
		if !ok {
			return nil, badLicence(path, lineNo, "%q: the value of %s is not one the table allows", ln, key)
		}
		if seen[key] {
			return nil, badLicence(path, lineNo, "a second %s line in the row of %s", key, rowID)
		}
		seen[key] = true
	}
	if err := closeRow(); err != nil {
		return nil, err
	}
	return table, nil
}

// isHeaderName: one or more of A-Z, a-z, 0-9, '_' and '-'.
func isHeaderName(s string) bool {
	if s == "" {
		return false
	}
	for i := 0; i < len(s); i++ {
		c := s[i]
		if !(c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_' || c == '-') {
			return false
		}
	}
	return true
}

// profileHeader reads the `module` and `uses` lines of a module file or a
// pack.def for the profiles (ruling 2b): each line cut and trimmed as ruling
// 1 does, a line that is the word, one or more spaces or tabs, and a name.
// Every other line is passed over; text that is not UTF-8 adds no line.
func profileHeader(text []byte) (name string, uses []string) {
	if !utf8.Valid(text) {
		return "", nil
	}
	for _, ln := range licenceLines(string(text)) {
		for _, word := range []string{"module", "uses"} {
			if !strings.HasPrefix(ln, word) {
				continue
			}
			rest := ln[len(word):]
			v := strings.TrimLeft(rest, " \t")
			if len(v) == len(rest) || !isHeaderName(v) {
				continue
			}
			if word == "module" {
				if name == "" {
					name = v
				}
			} else {
				uses = append(uses, v)
			}
		}
	}
	return name, uses
}

// licensedModule is one module file with what the profiles need of it.
type licensedModule struct {
	file    *moduleFile
	licence string
	name    string
	uses    []string
	rank    int
}

// licensedModules reads licences.toml and, for each module file in the
// order given (spec 0.29, ruling 3b), its licence and its `module` and
// `uses` lines, then computes every module's profile (ruling 2b). It returns
// the table, the modules and the widest profile of each module name.
func licensedModules(tablePath string, files []*moduleFile) (licenceTable, []*licensedModule, map[string]int, error) {
	table, err := readLicenceTable(tablePath)
	if err != nil {
		return nil, nil, nil, err
	}
	mods := make([]*licensedModule, len(files))
	for i, f := range files {
		lic, err := readModuleLicence(f.path + ".license")
		if err != nil {
			return nil, nil, nil, err
		}
		m := &licensedModule{file: f, licence: lic, rank: table.rank(lic)}
		if f.err == nil {
			m.name, m.uses = profileHeader(f.text)
		}
		mods[i] = m
	}
	// The widest of each module's licence and the modules it uses, directly
	// or through others: ranks only grow, so repeat until none changes.
	byName := map[string]int{}
	for changed := true; changed; {
		changed = false
		for _, m := range mods {
			if m.name != "" {
				if r, ok := byName[m.name]; !ok || m.rank > r {
					byName[m.name] = m.rank
					changed = true
				}
			}
		}
		for _, m := range mods {
			for _, u := range m.uses {
				if r, ok := byName[u]; ok && r > m.rank {
					m.rank = r
					changed = true
				}
			}
		}
	}
	return table, mods, byName, nil
}

// packRank is the profile of a pack (ruling 2c): the widest of its licence,
// the module named core and the modules its `uses` lines name.
func packRank(table licenceTable, byName map[string]int, licence string, uses []string) int {
	r := table.rank(licence)
	for _, u := range append([]string{CoreModule}, uses...) {
		if ur, ok := byName[u]; ok && ur > r {
			r = ur
		}
	}
	return r
}

// PackLicence is one line of the `licences` subcommand (spec 0.29, ruling
// 4c): a loaded pack's directory name, its format, its licence and its own
// profile (none when it is in no profile).
type PackLicence struct {
	Dir     string
	Format  string
	Licence string
	Profile string
}
