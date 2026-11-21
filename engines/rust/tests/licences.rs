//! Engine-spec 0.29: the library loader with a licence profile
//! (`Engine::load_tree`), on the fixture trees of the tool vectors
//! (`packs/conformance/tool-fixtures/licences-*`).
// The fixture packs are on the `json` wire (engine-spec 0.24).
#![cfg(feature = "json")]

use goat_transformers::{Engine, LoadOptions, Profile};
use std::path::{Path, PathBuf};

fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../packs/conformance/tool-fixtures").join(name).join("packs")
}

fn with(profile: Option<&str>) -> LoadOptions {
    LoadOptions { profile: profile.map(str::to_string), ..LoadOptions::default() }
}

/// `open` loads only the packs and modules whose licences it holds; the pack
/// that uses a non-commercial module is skipped, and so is that module.
#[test]
fn profile_open_loads_only_open_packs_and_modules() {
    let mut e = Engine::new();
    let loaded = e.load_tree(&fixture("licences-a"), &with(Some("open"))).unwrap();
    let dirs: Vec<&str> = loaded.iter().map(|p| p.dir.as_str()).collect();
    assert_eq!(dirs, vec!["plain", "zz-first-by-format"]);
    assert_eq!(e.formats(), vec!["lic-aa", "lic-plain"]);
    assert_eq!(e.modules(), vec!["core"]);
    for p in &loaded {
        let l = p.licence.as_ref().unwrap();
        assert_eq!((l.licence.as_str(), l.profile), ("Apache-2.0", Some(Profile::Open)));
    }
    // a skipped format is not there
    assert!(e.convert("lic-nc", "lic-plain", "{}").unwrap_err().msg.starts_with("unknown-format:"));
}

/// `open+copyleft` adds the share-alike module and the packs that use it;
/// the profile of a pack is the widest of its licence and its modules'.
#[test]
fn profile_open_copyleft_takes_the_widest() {
    let mut e = Engine::new();
    let loaded = e.load_tree(&fixture("licences-a"), &with(Some("open+copyleft"))).unwrap();
    let got: Vec<(String, Option<Profile>)> =
        loaded.iter().map(|p| (p.dir.clone(), p.licence.as_ref().unwrap().profile)).collect();
    assert_eq!(
        got,
        vec![
            ("copyleft".to_string(), Some(Profile::OpenCopyleft)),
            ("plain".to_string(), Some(Profile::Open)),
            ("uses-sa".to_string(), Some(Profile::OpenCopyleft)),
            ("zz-first-by-format".to_string(), Some(Profile::Open)),
        ]
    );
    assert_eq!(e.modules(), vec!["core", "sa"]);
}

/// No profile: no licence file is read, so a broken `licences.toml` does not
/// matter and every pack loads; asking for the licences reads them anyway.
#[test]
fn no_profile_reads_no_licence_file() {
    let mut e = Engine::new();
    let loaded = e.load_tree(&fixture("licences-bad-table"), &with(None)).unwrap();
    assert_eq!(loaded.len(), 1);
    assert_eq!(loaded[0].licence, None);
    let read = LoadOptions { read_licences: true, ..LoadOptions::default() };
    let err = Engine::new().load_tree(&fixture("licences-bad-table"), &read).unwrap_err();
    assert!(err.msg.starts_with("bad-licence:"), "{}", err.msg);
    // with no profile a pack in none is loaded, and reported as in none
    let mut e = Engine::new();
    let read = LoadOptions { read_licences: true, ..LoadOptions::default() };
    let loaded = e.load_tree(&fixture("licences-a"), &read).unwrap();
    let closed = loaded.iter().find(|p| p.dir == "closed").unwrap();
    assert_eq!(closed.licence.as_ref().unwrap().profile, None);
}

/// Ruling 3a: a name that is not a profile is `bad-licence` before anything
/// is read; ruling 3b: a bad module licence stops the load before any module.
#[test]
fn bad_names_and_bad_files_load_nothing() {
    let mut e = Engine::new();
    let err = e.load_tree(&fixture("licences-a"), &with(Some("Open"))).unwrap_err();
    assert!(err.msg.starts_with("bad-licence:"), "{}", err.msg);
    assert!(Profile::parse("commercial").unwrap_err().msg.starts_with("bad-licence:"));
    assert!(e.modules().is_empty() && e.formats().is_empty());

    let mut e = Engine::new();
    let err = e.load_tree(&fixture("licences-bad-module"), &with(Some("everything"))).unwrap_err();
    assert!(err.msg.starts_with("bad-licence:"), "{}", err.msg);
    assert!(e.modules().is_empty(), "no module is loaded: {:?}", e.modules());

    // a pack skipped by its profile is never parsed, even when it is broken
    let mut e = Engine::new();
    e.load_tree(&fixture("licences-core-copyleft"), &with(Some("open+copyleft"))).unwrap();
    assert_eq!(e.formats(), vec!["lic-plain"]);
    let err = Engine::new().load_tree(&fixture("licences-core-copyleft"), &with(Some("everything"))).unwrap_err();
    assert!(err.msg.starts_with("unknown-directive:"), "{}", err.msg);
}

/// Ruling 1, Where: a part of the path before the last that is not a
/// directory means the file does not exist, so a packs path naming a regular
/// file reads the default table, not `bad-licence`. The packs directory is
/// then unreadable, which is the engine's own error, without a kind.
#[test]
fn a_file_on_the_way_means_absent() {
    let packs = fixture("licences-a").join("plain/pack.def");
    let opts = LoadOptions {
        profile: Some("everything".to_string()),
        models: Some(fixture("licences-a").join("../model")),
        ..LoadOptions::default()
    };
    let err = Engine::new().load_tree(&packs, &opts).unwrap_err();
    assert!(!err.msg.starts_with("bad-licence:"), "{}", err.msg);
    assert!(err.msg.starts_with("cannot read"), "{}", err.msg);
}

/// `packs_only`: the name checks come first; a skipped name given twice is
/// skipped twice.
#[test]
fn packs_only_with_a_profile() {
    let only = |names: &[&str]| LoadOptions {
        profile: Some("open".to_string()),
        packs_only: Some(names.iter().map(|n| n.to_string()).collect()),
        ..LoadOptions::default()
    };
    let mut e = Engine::new();
    e.load_tree(&fixture("licences-a"), &only(&["nc", "nc", "plain"])).unwrap();
    assert_eq!(e.formats(), vec!["lic-plain"]);
    let err = Engine::new().load_tree(&fixture("licences-a"), &only(&["no-such-pack"])).unwrap_err();
    assert!(err.msg.starts_with("unknown-format:"), "{}", err.msg);
}
