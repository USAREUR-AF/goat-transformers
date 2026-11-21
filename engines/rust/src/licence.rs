//! Licence profiles in the loaders (engine-spec 0.29) and the loader of a
//! whole tree, a model directory and a packs directory, as the command-line
//! contract loads it (engine-spec 0.23, Loading).
//!
//! With no profile asked for, no licence file is read and the tree loads as
//! before. With one, `licences.toml` beside the packs directory, each module's
//! `<m>.def.license` and each pack's `REUSE.toml` are read by the line forms
//! of ruling 1 (no TOML library), and a module or pack whose profile the
//! asked-for profile does not hold is skipped as if it were not there.

use crate::{Engine, Error, Pack};
use std::collections::HashMap;
use std::ffi::OsString;
use std::path::{Path, PathBuf};

/// One of the three named profiles, narrowest first. A pack or module that
/// is in none of them has no `Profile` (`Option::None`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Profile {
    Open,
    OpenCopyleft,
    Everything,
}

impl Profile {
    /// The profile of this name; any other text is None.
    pub fn from_name(name: &str) -> Option<Profile> {
        match name {
            "open" => Some(Profile::Open),
            "open+copyleft" => Some(Profile::OpenCopyleft),
            "everything" => Some(Profile::Everything),
            _ => None,
        }
    }
    /// As `from_name`, but a name that is not a profile is `bad-licence`
    /// (ruling 3a: refused by a library before anything is read).
    pub fn parse(name: &str) -> Result<Profile, Error> {
        Profile::from_name(name).ok_or_else(|| Error {
            msg: format!("bad-licence: `{}` is not a profile (open, open+copyleft or everything)", name),
        })
    }
    pub fn name(self) -> &'static str {
        match self {
            Profile::Open => "open",
            Profile::OpenCopyleft => "open+copyleft",
            Profile::Everything => "everything",
        }
    }
    /// Does this profile hold something whose own profile is `p`? Nothing
    /// holds what is in no profile.
    pub fn holds(self, p: Option<Profile>) -> bool {
        matches!(p, Some(q) if q <= self)
    }
}

/// The name of a profile, or `none` for what is in no profile.
pub fn profile_name(p: Option<Profile>) -> &'static str {
    p.map_or("none", Profile::name)
}

// Internally a profile is a rank, so that "the widest" is a maximum:
// 0 open, 1 open+copyleft, 2 everything, 3 none.
const NONE: u8 = 3;
fn rank_profile(r: u8) -> Option<Profile> {
    match r {
        0 => Some(Profile::Open),
        1 => Some(Profile::OpenCopyleft),
        2 => Some(Profile::Everything),
        _ => None,
    }
}

/// What to load, and how (`Engine::load_tree`).
#[derive(Clone, Debug, Default)]
pub struct LoadOptions {
    /// The directory of model modules. None: the packs path as given,
    /// followed by `/../model`, resolved by the operating system.
    pub models: Option<PathBuf>,
    /// Load only these subdirectories of the packs directory, in this order
    /// (a name given twice is loaded twice). None: every pack directory.
    pub packs_only: Option<Vec<String>>,
    /// `open`, `open+copyleft` or `everything`; any other text is
    /// `bad-licence` before anything is read. None: no profile, and no
    /// licence file is read unless `read_licences` is set.
    pub profile: Option<String>,
    /// Read every licence file even with no profile (what the `licences`
    /// subcommand does), so that each loaded pack reports its licence.
    pub read_licences: bool,
}

/// The licence of a loaded pack and the pack's own profile (ruling 2c).
#[derive(Clone, Debug, PartialEq)]
pub struct PackLicence {
    pub licence: String,
    /// None: the pack is in no profile.
    pub profile: Option<Profile>,
}

/// One pack `Engine::load_tree` loaded.
#[derive(Clone, Debug, PartialEq)]
pub struct LoadedPack {
    /// The name of the pack's directory under the packs directory.
    pub dir: String,
    /// The pack's `format` value.
    pub format: String,
    /// Present when licences were read (a profile, or `read_licences`).
    pub licence: Option<PackLicence>,
}

fn bad(msg: String) -> Error {
    Error { msg: format!("bad-licence: {}", msg) }
}

/// `<path text as given>` followed by `suffix`, resolved by the OS later.
fn beside(packs: &Path, suffix: &str) -> PathBuf {
    let mut s: OsString = packs.as_os_str().to_owned();
    s.push(suffix);
    PathBuf::from(s)
}

/// The module files of a model directory, in the order Version 0.23,
/// Loading, 1 gives: `core.def` first, then every other regular file (or
/// symbolic link to one) whose name ends in `.def`, in byte order of name.
/// A directory that cannot be read has none.
pub(crate) fn module_files(dir: &Path) -> Vec<PathBuf> {
    let rd = match std::fs::read_dir(dir) {
        Ok(rd) => rd,
        Err(_) => return Vec::new(),
    };
    let mut files: Vec<PathBuf> = rd
        .flatten()
        .filter(|e| e.file_name().as_encoded_bytes().ends_with(b".def"))
        .map(|e| e.path())
        .filter(|p| p.is_file())
        .collect();
    files.sort_by(|a, b| {
        let not_core = |p: &PathBuf| p.file_name().map(|n| n.as_encoded_bytes()) != Some(b"core.def".as_slice());
        let name = |p: &PathBuf| p.file_name().map(|n| n.as_encoded_bytes().to_vec());
        (not_core(a), name(a)).cmp(&(not_core(b), name(b)))
    });
    files
}

/// Ruling 1, Lines: a licence file's text, or None when it does not exist:
/// no entry has that name (ENOENT), or a part of the path before the last is
/// not a directory (ENOTDIR). Any other failure to read it, and text that is
/// not UTF-8, is `bad-licence`.
fn read_licence_file(path: &Path) -> Result<Option<String>, Error> {
    match std::fs::read(path) {
        Ok(bytes) => String::from_utf8(bytes)
            .map(Some)
            .map_err(|_| bad(format!("{} is not UTF-8", path.display()))),
        Err(e) if matches!(e.kind(), std::io::ErrorKind::NotFound | std::io::ErrorKind::NotADirectory) => Ok(None),
        Err(e) => Err(bad(format!("cannot read {}: {}", path.display(), e))),
    }
}

/// Cut at each line feed; one carriage return before a line feed or at the
/// end of the file goes with it; then trim spaces and tabs at both ends.
fn lines(text: &str) -> impl Iterator<Item = &str> {
    text.split('\n').map(|l| l.strip_suffix('\r').unwrap_or(l).trim_matches(|c| c == ' ' || c == '\t'))
}

/// A licence id: one or more of `A`-`Z`, `a`-`z`, `0`-`9`, `.`, `-`, `+`.
fn is_id(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'-' || b == b'+')
}

/// A name of a `module` or `uses` line: `A`-`Z`, `a`-`z`, `0`-`9`, `_`, `-`.
fn is_name(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

fn ws(c: char) -> bool {
    c == ' ' || c == '\t'
}

/// `<word>`, one or more spaces or tabs, then the rest: the rest, if any.
fn after_word<'a>(line: &'a str, word: &str) -> Option<&'a str> {
    let rest = line.strip_prefix(word)?;
    let trimmed = rest.trim_start_matches(ws);
    if trimmed.len() == rest.len() {
        return None;
    }
    Some(trimmed)
}

/// `<key>`, any spaces or tabs, `=`, any spaces or tabs: the value after.
fn key_value<'a>(line: &'a str, key: &str) -> Option<&'a str> {
    let rest = line.strip_prefix(key)?.trim_start_matches(ws);
    Some(rest.strip_prefix('=')?.trim_start_matches(ws))
}

/// Ruling 1a: the licence of a pack, from its `REUSE.toml`.
fn pack_licence(path: &Path) -> Result<String, Error> {
    // REUSE-IgnoreStart: the quoted licence lines below are data
    const TAG: &str = "SPDX-License-Identifier";
    let text = match read_licence_file(path)? {
        Some(t) => t,
        None => return Ok("Apache-2.0".to_string()),
    };
    let mut found: Vec<String> = Vec::new();
    for line in lines(&text) {
        let rest = match line.strip_prefix(TAG) {
            Some(r) if r.starts_with([' ', '\t', '=']) => r,
            _ => continue,
        };
        let id = key_value(rest, "")
            .and_then(|v| v.strip_prefix('"'))
            .and_then(|v| v.strip_suffix('"'))
            .filter(|id| is_id(id));
        match id {
            Some(id) => found.push(id.to_string()),
            None => return Err(bad(format!("{}: `{}` is not a licence line", path.display(), line))),
        }
    }
    one_licence(path, found)
}

/// Ruling 1b: the licence of a module, from its `<m>.def.license`.
fn module_licence(path: &Path) -> Result<String, Error> {
    const TAG: &str = "SPDX-License-Identifier:";
    // REUSE-IgnoreEnd
    let text = match read_licence_file(path)? {
        Some(t) => t,
        None => return Ok("Apache-2.0".to_string()),
    };
    let mut found: Vec<String> = Vec::new();
    for line in lines(&text) {
        if !line.starts_with(TAG) {
            continue;
        }
        match after_word(line, TAG).filter(|id| is_id(id)) {
            Some(id) => found.push(id.to_string()),
            None => return Err(bad(format!("{}: `{}` is not a licence line", path.display(), line))),
        }
    }
    one_licence(path, found)
}

fn one_licence(path: &Path, mut found: Vec<String>) -> Result<String, Error> {
    match found.len() {
        1 => Ok(found.remove(0)),
        0 => Err(bad(format!("{} holds no licence line", path.display()))),
        n => Err(bad(format!("{} holds {} licence lines; it must hold one", path.display(), n))),
    }
}

/// Ruling 1c: the table of `licences.toml`, as licence id -> profile rank
/// (ruling 2a).
fn table(path: &Path) -> Result<HashMap<String, u8>, Error> {
    let text = match read_licence_file(path)? {
        Some(t) => t,
        None => return Ok(HashMap::from([("Apache-2.0".to_string(), 0)])),
    };
    // one row: commercial, share_alike, field_of_use (non-empty), distribution
    // controlled; and the skipped name, url, attribution, each seen at most once
    #[derive(Default)]
    struct Row {
        id: String,
        commercial: Option<String>,
        share_alike: Option<bool>,
        field_of_use: Option<bool>,
        controlled: Option<bool>,
        skipped: [bool; 3],
    }
    fn close(path: &Path, row: Row, out: &mut HashMap<String, u8>) -> Result<(), Error> {
        let (commercial, sa, fou, controlled) = match (row.commercial, row.share_alike, row.field_of_use, row.controlled) {
            (Some(c), Some(s), Some(f), Some(d)) => (c, s, f, d),
            _ => {
                return Err(bad(format!(
                    "{}: the row of `{}` lacks one of commercial, share_alike, field_of_use and distribution",
                    path.display(),
                    row.id
                )))
            }
        };
        let rank = if controlled {
            NONE
        } else if commercial == "yes" && !fou {
            if sa {
                1
            } else {
                0
            }
        } else {
            2
        };
        out.insert(row.id, rank);
        Ok(())
    }
    let mut out: HashMap<String, u8> = HashMap::new();
    let mut row: Option<Row> = None;
    for line in lines(&text) {
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let wrong = || bad(format!("{}: `{}` is not a line of the table", path.display(), line));
        if let Some(id) = line.strip_prefix("[licences.\"").and_then(|r| r.strip_suffix("\"]")).filter(|id| is_id(id)) {
            if let Some(r) = row.take() {
                close(path, r, &mut out)?;
            }
            if out.contains_key(id) {
                return Err(bad(format!("{}: a second row of `{}`", path.display(), id)));
            }
            row = Some(Row { id: id.to_string(), ..Row::default() });
            continue;
        }
        let r = row.as_mut().ok_or_else(wrong)?;
        let twice = |set: bool| if set { Err(wrong()) } else { Ok(()) };
        if let Some(v) = key_value(line, "commercial") {
            twice(r.commercial.is_some())?;
            r.commercial = Some(match v {
                "\"yes\"" => "yes",
                "\"no\"" => "no",
                "\"unknown\"" => "unknown",
                _ => return Err(wrong()),
            }
            .to_string());
        } else if let Some(v) = key_value(line, "share_alike") {
            twice(r.share_alike.is_some())?;
            r.share_alike = Some(match v {
                "true" => true,
                "false" => false,
                _ => return Err(wrong()),
            });
        } else if let Some(v) = key_value(line, "field_of_use") {
            twice(r.field_of_use.is_some())?;
            r.field_of_use = Some(if v == "[]" {
                false
            } else if v.len() >= 4 && v.starts_with("[\"") && v.ends_with("\"]") {
                true
            } else {
                return Err(wrong());
            });
        } else if let Some(v) = key_value(line, "distribution") {
            twice(r.controlled.is_some())?;
            r.controlled = Some(match v {
                "\"public\"" => false,
                "\"controlled\"" => true,
                _ => return Err(wrong()),
            });
        } else if let Some(i) = ["name", "url", "attribution"]
            .iter()
            .position(|w| line.strip_prefix(w).map_or(false, |r| r.starts_with([' ', '\t', '='])))
        {
            twice(r.skipped[i])?;
            r.skipped[i] = true;
        } else {
            return Err(wrong());
        }
    }
    if let Some(r) = row.take() {
        close(path, r, &mut out)?;
    }
    Ok(out)
}

/// Ruling 2b: the first `module` name and the `uses` names of a module file
/// or a `pack.def`. A file that cannot be read or is not UTF-8 has none.
fn name_lines(path: &Path) -> (Option<String>, Vec<String>) {
    let text = match std::fs::read(path).ok().and_then(|b| String::from_utf8(b).ok()) {
        Some(t) => t,
        None => return (None, Vec::new()),
    };
    let (mut module, mut uses) = (None, Vec::new());
    for line in lines(&text) {
        if let Some(n) = after_word(line, "module").filter(|n| is_name(n)) {
            if module.is_none() {
                module = Some(n.to_string());
            }
        } else if let Some(n) = after_word(line, "uses").filter(|n| is_name(n)) {
            uses.push(n.to_string());
        }
    }
    (module, uses)
}

/// What the pre-pass of ruling 3b learned.
struct Licences {
    table: HashMap<String, u8>,
    /// module name -> the widest profile rank of the module files of that name
    by_name: HashMap<String, u8>,
    /// the profile rank of each module file, in the order of `module_files`
    file_rank: Vec<u8>,
}

impl Licences {
    /// Ruling 3b: the table, then each module file's licence and lines;
    /// then every module's profile (2b).
    fn read(packs: &Path, files: &[PathBuf]) -> Result<Licences, Error> {
        let table = table(&beside(packs, "/../licences.toml"))?;
        let mut own: Vec<u8> = Vec::new();
        let mut names: Vec<(Option<String>, Vec<String>)> = Vec::new();
        for f in files {
            let lic = module_licence(&beside(f, ".license"))?;
            own.push(*table.get(&lic).unwrap_or(&2));
            names.push(name_lines(f));
        }
        // the widest over what each module uses, directly or through others:
        // a fixed point, so that a cycle of `uses` ends
        let mut rank = own.clone();
        loop {
            let mut by_name: HashMap<String, u8> = HashMap::new();
            for (i, (name, _)) in names.iter().enumerate() {
                if let Some(n) = name {
                    let e = by_name.entry(n.clone()).or_insert(0);
                    *e = (*e).max(rank[i]);
                }
            }
            let mut changed = false;
            for (i, (_, uses)) in names.iter().enumerate() {
                for u in uses {
                    if let Some(&r) = by_name.get(u) {
                        if r > rank[i] {
                            rank[i] = r;
                            changed = true;
                        }
                    }
                }
            }
            if !changed {
                return Ok(Licences { table, by_name, file_rank: rank });
            }
        }
    }

    /// Ruling 2c: a pack's licence and profile rank.
    fn pack(&self, dir: &Path, def: &Path) -> Result<(String, u8), Error> {
        let lic = pack_licence(&dir.join("REUSE.toml"))?;
        let mut rank = *self.table.get(&lic).unwrap_or(&2);
        let (_, uses) = name_lines(def);
        for name in std::iter::once("core").chain(uses.iter().map(String::as_str)) {
            if let Some(&r) = self.by_name.get(name) {
                rank = rank.max(r);
            }
        }
        Ok((lic, rank))
    }
}

/// A `--packs-only` name: one path component, not `.` or `..`.
fn plain_name(name: &str) -> bool {
    !(name.is_empty() || name == "." || name == ".." || name.contains('/') || name.contains('\\'))
}

impl Engine {
    /// Load a tree as the command-line contract does (engine-spec 0.23,
    /// Loading), with an optional licence profile (engine-spec 0.29):
    ///
    /// 1. the model modules of `opts.models` (default `<packs>/../model`);
    /// 2. the packs of `packs`: those of `opts.packs_only` in that order, or
    ///    every subdirectory holding `pack.def`, not beginning with `.`, in
    ///    byte order of name.
    ///
    /// With `opts.profile`, `licences.toml`, the module licences and each
    /// pack's `REUSE.toml` are read first (ruling 3), and the modules and
    /// packs the profile does not hold are skipped. Stops at the first
    /// failure. Returns the packs loaded, in the order loaded.
    pub fn load_tree(&mut self, packs: &Path, opts: &LoadOptions) -> Result<Vec<LoadedPack>, Error> {
        let profile = opts.profile.as_deref().map(Profile::parse).transpose()?;
        let models = opts.models.clone().unwrap_or_else(|| beside(packs, "/../model"));
        let files = module_files(&models);
        let licences = if profile.is_some() || opts.read_licences { Some(Licences::read(packs, &files)?) } else { None };
        let held = |rank: u8| profile.map_or(true, |p| p.holds(rank_profile(rank)));
        let files: Vec<PathBuf> = match &licences {
            Some(l) => files.into_iter().zip(&l.file_rank).filter(|(_, &r)| held(r)).map(|(f, _)| f).collect(),
            None => files,
        };
        self.load_model_files(files)?;

        // the packs reached, in order: (directory name, directory)
        let mut reached: Vec<(String, PathBuf)> = Vec::new();
        match &opts.packs_only {
            Some(names) => reached.extend(names.iter().map(|n| (n.clone(), packs.join(n)))),
            None => {
                let rd = std::fs::read_dir(packs).map_err(|e| Error { msg: format!("cannot read {}: {}", packs.display(), e) })?;
                let mut names: Vec<String> = Vec::new();
                for entry in rd {
                    let entry = entry.map_err(|e| Error { msg: format!("cannot read {}: {}", packs.display(), e) })?;
                    let name = entry.file_name().into_string().map_err(|n| Error {
                        msg: format!("cannot read {}: a name that is not UTF-8 ({:?})", packs.display(), n),
                    })?;
                    if !name.starts_with('.') && packs.join(&name).join("pack.def").is_file() {
                        names.push(name);
                    }
                }
                names.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
                reached.extend(names.into_iter().map(|n| {
                    let d = packs.join(&n);
                    (n, d)
                }));
            }
        }
        let mut loaded = Vec::new();
        for (name, dir) in reached {
            let def = dir.join("pack.def");
            if opts.packs_only.is_some() && (!plain_name(&name) || !def.is_file()) {
                return Err(Error {
                    msg: format!("unknown-format: `{}` is not a pack directory of {}", name, packs.display()),
                });
            }
            let licence = match &licences {
                Some(l) => {
                    let (licence, rank) = l.pack(&dir, &def)?;
                    if !held(rank) {
                        continue;
                    }
                    Some(PackLicence { licence, profile: rank_profile(rank) })
                }
                None => None,
            };
            let format = self.load_pack_file(&def)?;
            loaded.push(LoadedPack { dir: name, format, licence });
        }
        Ok(loaded)
    }

    /// Load one `pack.def`; its format.
    fn load_pack_file(&mut self, def: &Path) -> Result<String, Error> {
        let within = |e: Error| Error { msg: format!("{} (in {})", e.msg, def.display()) };
        let bytes = std::fs::read(def).map_err(|e| Error { msg: format!("cannot read {}: {}", def.display(), e) })?;
        let text = String::from_utf8(bytes).map_err(|_| Error { msg: format!("cannot read {}: not UTF-8", def.display()) })?;
        let pack = Pack::parse(&text).map_err(within)?;
        let format = pack.format.clone();
        self.load(pack).map_err(within)?;
        Ok(format)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn table_of(text: &str) -> Result<HashMap<String, u8>, Error> {
        let dir = std::env::temp_dir().join(format!("goat-xf-table-{}-{}", std::process::id(), text.len()));
        std::fs::create_dir_all(&dir).unwrap();
        let f = dir.join("licences.toml");
        std::fs::write(&f, text).unwrap();
        let t = table(&f);
        let _ = std::fs::remove_dir_all(&dir);
        t
    }

    const ROW: &str = "[licences.\"X-1\"]\ncommercial = \"yes\"\nshare_alike = false\nfield_of_use = []\ndistribution = \"public\"\n";

    #[test]
    fn table_lines() {
        assert_eq!(table_of(ROW).unwrap().get("X-1"), Some(&0));
        assert_eq!(table_of(&ROW.replace("[]", "[\"\"]")).unwrap().get("X-1"), Some(&2));
        assert_eq!(table_of(&ROW.replace("public", "controlled")).unwrap().get("X-1"), Some(&NONE));
        assert_eq!(table_of(&ROW.replace("false", "true")).unwrap().get("X-1"), Some(&1));
        for wrong in [
            ROW.replace("[]", "[ ]"),
            ROW.replace("\"public\"", "\"public\" # c"),
            format!("x = 1\n{}", ROW),
            format!("{}{}", ROW, ROW),
            ROW.replace("distribution = \"public\"\n", ""),
            format!("{}name = 1\nname = 2\n", ROW),
            format!("{}[other]\n", ROW),
            format!("\u{feff}{}", ROW),
        ] {
            assert!(table_of(&wrong).unwrap_err().msg.starts_with("bad-licence:"), "{:?}", wrong);
        }
        assert!(table_of(&format!("{}name\t= \"x\"\nurl=1\nattribution = true\n", ROW)).is_ok());
    }

    #[test]
    fn line_forms() {
        assert_eq!(lines("a \r\n\tb\r").collect::<Vec<_>>(), vec!["a", "b"]);
        assert_eq!(after_word("uses  x", "uses"), Some("x"));
        assert_eq!(after_word("usesx", "uses"), None);
        assert_eq!(key_value("share_alike\t=  true", "share_alike"), Some("true"));
    }
}
