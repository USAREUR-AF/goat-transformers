//! Load a chosen set of packs from a tree: a directory holding `model/` and
//! `packs/`, such as a checkout of the library or a bundle written by
//! `tools/goat-pkg bundle`.

use super::*;
use std::path::Path;

impl Engine {
    /// Load the named packs from `<root>/packs/<name>/pack.def`, and before
    /// them the model modules they need from `<root>/model/*.def`: `core`,
    /// every module a named pack `uses`, and every module one of those `uses`,
    /// each after the modules it uses. Nothing else in the tree is read into
    /// the engine. A module that is already loaded is not loaded again, so the
    /// call can be repeated with more packs.
    ///
    /// ```no_run
    /// let mut engine = goat_transformers::Engine::new();
    /// engine.load_tree(std::path::Path::new("vendor/goat"), &["cot-xml", "geojson"]).unwrap();
    /// ```
    pub fn load_tree(&mut self, root: &Path, packs: &[&str]) -> Result<(), Error> {
        let read = |p: &Path| std::fs::read_to_string(p).map_err(|e| Error { msg: format!("cannot read {}: {}", p.display(), e) });
        // the named packs, parsed once: their `uses` lines choose the modules
        let mut chosen: Vec<(std::path::PathBuf, Pack)> = Vec::new();
        for name in packs {
            let def = root.join("packs").join(name).join("pack.def");
            if !def.is_file() {
                return err(format!("unknown-format: no pack `{}` under {}", name, root.join("packs").display()));
            }
            let pack = Pack::parse(&read(&def)?).map_err(|e| Error { msg: format!("{} (in {})", e.msg, def.display()) })?;
            if !chosen.iter().any(|(p, _)| *p == def) {
                chosen.push((def, pack));
            }
        }
        // every module file of the tree: its path, text, name and `uses` lines
        let model_dir = root.join("model");
        let mut files: Vec<std::path::PathBuf> = match std::fs::read_dir(&model_dir) {
            Ok(rd) => rd.flatten().map(|e| e.path()).filter(|p| p.extension().and_then(|s| s.to_str()) == Some("def")).collect(),
            Err(_) => Vec::new(),
        };
        files.sort_by(|a, b| a.file_name().cmp(&b.file_name()));
        let mut heads: BTreeMap<String, (std::path::PathBuf, String, Vec<String>)> = BTreeMap::new();
        for f in files {
            let text = read(&f)?;
            let (mut name, mut uses) = (String::new(), Vec::new());
            for line in text.lines() {
                match tokenize(line) {
                    Ok(t) if t.len() == 2 && t[0] == "module" && name.is_empty() => name = t[1].clone(),
                    Ok(t) if t.len() == 2 && t[0] == "uses" => uses.push(t[1].clone()),
                    _ => {}
                }
            }
            heads.entry(name).or_insert((f, text, uses));
        }
        // `core` first, then what each pack uses in the order the packs were
        // named; a module no file declares is left to the pack's own load,
        // which reports `unknown-module`
        let mut wanted: Vec<String> = vec!["core".to_string()];
        for (_, pack) in &chosen {
            wanted.extend(pack.uses.iter().cloned());
        }
        let mut visiting: Vec<String> = Vec::new();
        for name in wanted {
            self.load_tree_module(&name, &heads, &mut visiting)?;
        }
        for (def, pack) in chosen {
            self.load(pack).map_err(|e| Error { msg: format!("{} (in {})", e.msg, def.display()) })?;
        }
        Ok(())
    }

    fn load_tree_module(
        &mut self,
        name: &str,
        heads: &BTreeMap<String, (std::path::PathBuf, String, Vec<String>)>,
        visiting: &mut Vec<String>,
    ) -> Result<(), Error> {
        if self.modules.contains_key(name) {
            return Ok(());
        }
        let (file, text, uses) = match heads.get(name) {
            Some(h) => h,
            None => return Ok(()),
        };
        if visiting.iter().any(|v| v == name) {
            return err(format!("bad-directive: the `uses` lines of model modules {} form a cycle", visiting.join(", ")));
        }
        visiting.push(name.to_string());
        for u in uses {
            if u != name {
                self.load_tree_module(u, heads, visiting)?;
            }
        }
        visiting.pop();
        self.load_model(text).map_err(|e| Error { msg: format!("{} (in {})", e.msg, file.display()) })
    }
}
