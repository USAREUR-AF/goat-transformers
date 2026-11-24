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

// ---------------------------------------------------------------------------
// Engine-spec 0.93, ruling 6: the instance's distribution limit after a load
// with a profile. Each test builds its own tree under the temporary directory.
// ---------------------------------------------------------------------------

use goat_transformers::Distribution;

/// A tree of files under the temporary directory, removed when dropped.
struct Tree(PathBuf);

impl Tree {
    fn new(tag: &str, files: &[(&str, &str)]) -> Tree {
        let root = std::env::temp_dir().join(format!("goat-xf-093-{}-{}", tag, std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        for (path, text) in files {
            let f = root.join(path);
            std::fs::create_dir_all(f.parent().unwrap()).unwrap();
            std::fs::write(&f, text).unwrap();
        }
        std::fs::create_dir_all(root.join("packs")).unwrap();
        Tree(root)
    }
    fn packs(&self) -> PathBuf {
        self.0.join("packs")
    }
}

impl Drop for Tree {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

const CORE: &str = "module core\nversion 1.0.0\ndistribution public\nsource \"t\"\nkey lat float -\n";
const CTL_MODULE: &str = "module ctl\nversion 1.0.0\ndistribution controlled\nsource \"t\"\n";
const BAD_TABLE: &str = "this is not a line of the table\n";

fn pack(format: &str, distribution: &str) -> String {
    format!("format {}\nversion 1.0.0\ndistribution {}\nsource \"t\"\nwire json\nfield lat pos.lat float\n", format, distribution)
}

/// A public core and one public pack, under the default licence table.
fn public_tree(tag: &str) -> Tree {
    Tree::new(tag, &[("model/core.def", CORE), ("packs/pub/pack.def", &pack("c-pub", "public"))])
}

fn refused(r: Result<(), goat_transformers::Error>) {
    let e = r.unwrap_err();
    assert!(e.msg.starts_with("distribution-refused:"), "{}", e.msg);
}

/// "its limit is the lower of `public` and what a caller sets before": a
/// caller that set `controlled` before the load with a profile gets
/// `public`, so a controlled text loaded directly later is refused, a
/// module as a pack.
#[test]
fn a_profile_load_lowers_a_limit_set_before() {
    let t = public_tree("before");
    let mut e = Engine::new();
    e.set_max_distribution(Distribution::Controlled);
    e.load_tree(&t.packs(), &with(Some("open"))).unwrap();
    assert_eq!(e.formats(), vec!["c-pub"]);
    refused(e.load_def(&pack("c-later", "controlled")));
    refused(e.load_model(CTL_MODULE));
    assert_eq!(e.formats(), vec!["c-pub"]);
    assert_eq!(e.modules(), vec!["core"]);
}

/// "Setting `controlled` afterwards is no error and has no effect."
#[test]
fn setting_controlled_after_a_profile_load_has_no_effect() {
    let t = public_tree("after");
    let mut e = Engine::new();
    e.load_tree(&t.packs(), &with(Some("everything"))).unwrap();
    e.set_max_distribution(Distribution::Controlled); // no error: it returns nothing
    refused(e.load_def(&pack("c-later", "controlled")));
    // and setting public is still public
    e.set_max_distribution(Distribution::Public);
    refused(e.load_def(&pack("c-later", "controlled")));
    e.load_def(&pack("c-later", "public")).unwrap();
}

/// "A load with a profile on an instance that already holds a controlled
/// module ... is `distribution-refused` before anything is read": a broken
/// `licences.toml`, which would be `bad-licence`, is never read; the call
/// leaves no trace and the limit unchanged (ruling 6).
#[test]
fn an_instance_holding_a_controlled_module_is_refused_first() {
    let t = Tree::new("holds-module", &[("licences.toml", BAD_TABLE), ("model/core.def", CORE)]);
    let mut e = Engine::new();
    e.load_model(CORE).unwrap();
    e.load_model(CTL_MODULE).unwrap();
    let err = e.load_tree(&t.packs(), &with(Some("open"))).unwrap_err();
    assert!(err.msg.starts_with("distribution-refused:"), "{}", err.msg);
    // no trace: the refused call loaded nothing
    assert_eq!(e.modules(), vec!["core", "ctl"]);
    assert!(e.formats().is_empty(), "{:?}", e.formats());
    // the limit is unchanged: a controlled pack still loads directly
    e.load_def(&pack("c-ctl", "controlled")).unwrap();
}

/// The same for an instance that already holds a controlled pack.
#[test]
fn an_instance_holding_a_controlled_pack_is_refused_first() {
    let t = Tree::new("holds-pack", &[("licences.toml", BAD_TABLE), ("model/core.def", CORE)]);
    let mut e = Engine::new();
    e.load_model(CORE).unwrap();
    e.load_def(&pack("c-ctl", "controlled")).unwrap();
    let err = e.load_tree(&t.packs(), &with(Some("everything"))).unwrap_err();
    assert!(err.msg.starts_with("distribution-refused:"), "{}", err.msg);
    // no trace: the refused call loaded nothing
    assert_eq!(e.formats(), vec!["c-ctl"]);
    assert_eq!(e.modules(), vec!["core"]);
    // the limit is unchanged: a controlled pack still loads directly
    e.load_def(&pack("c-ctl-2", "controlled")).unwrap();
}

/// "The order: a profile name that is none of the three is `bad-licence`
/// first, with the limit unchanged; then that instance check": on an
/// instance holding a controlled module the bad name wins, and afterwards a
/// controlled text still loads; a good name on a fresh instance then sets
/// the limit, as the contrast.
#[test]
fn a_bad_profile_name_comes_first_and_leaves_the_limit() {
    let t = public_tree("bad-name");
    let mut e = Engine::new();
    e.load_model(CORE).unwrap();
    e.load_model(CTL_MODULE).unwrap();
    let err = e.load_tree(&t.packs(), &with(Some("Open"))).unwrap_err();
    assert!(err.msg.starts_with("bad-licence:"), "{}", err.msg);
    e.load_def(&pack("c-ctl", "controlled")).unwrap();

    let mut e = Engine::new();
    let err = e.load_tree(&t.packs(), &with(Some("all"))).unwrap_err();
    assert!(err.msg.starts_with("bad-licence:"), "{}", err.msg);
    e.load_model(CORE).unwrap();
    e.load_def(&pack("c-ctl", "controlled")).unwrap();
    let mut e = Engine::new();
    e.load_tree(&t.packs(), &with(Some("open"))).unwrap();
    refused(e.load_def(&pack("c-ctl", "controlled")));
}

/// "then the limit is `public`, and stays so when the load fails later": a
/// broken `licences.toml` fails the load after the limit is set.
#[test]
fn the_limit_stays_public_when_the_profile_load_fails() {
    let t = Tree::new("fails", &[("licences.toml", BAD_TABLE), ("model/core.def", CORE)]);
    let mut e = Engine::new();
    let err = e.load_tree(&t.packs(), &with(Some("open"))).unwrap_err();
    assert!(err.msg.starts_with("bad-licence:"), "{}", err.msg);
    assert!(e.modules().is_empty());
    e.load_model(CORE).unwrap();
    refused(e.load_model(CTL_MODULE));
    refused(e.load_def(&pack("c-ctl", "controlled")));
}

/// "A later load with no profile is bounded by the limit, not by the
/// profile": after an `open` load, a tree loaded with no profile loads a
/// public pack under a non-commercial licence, and refuses a controlled one.
#[test]
fn a_later_load_without_a_profile_is_bounded_by_the_limit() {
    let first = public_tree("later-1");
    let mut e = Engine::new();
    e.load_tree(&first.packs(), &with(Some("open"))).unwrap();
    // no model directory: no module is loaded again (ruling 4 of 0.4)
    let nc_reuse = "version = 1\n[[annotations]]\npath = \"**\"\nSPDX-License-Identifier = \"CC-BY-NC-SA-4.0\"\n";
    let second = Tree::new(
        "later-2",
        &[
            ("packs/nc/REUSE.toml", nc_reuse),
            ("packs/nc/pack.def", &pack("c-nc", "public")),
            ("packs/zz-ctl/pack.def", &pack("c-ctl", "controlled")),
        ],
    );
    let only = |n: &str| LoadOptions { packs_only: Some(vec![n.to_string()]), ..LoadOptions::default() };
    e.load_tree(&second.packs(), &only("nc")).unwrap();
    assert_eq!(e.formats(), vec!["c-nc", "c-pub"]);
    let err = e.load_tree(&second.packs(), &only("zz-ctl")).unwrap_err();
    assert!(err.msg.starts_with("distribution-refused:"), "{}", err.msg);
    assert_eq!(e.formats(), vec!["c-nc", "c-pub"]);
}

/// Ruling 7: reading the licences with no profile (the `licences`
/// subcommand) changes nothing; the instance keeps its `controlled` limit
/// and a pack that is not shown public is listed as in none.
#[test]
fn reading_licences_without_a_profile_keeps_the_limit() {
    let t = Tree::new("no-profile", &[("model/core.def", CORE), ("packs/ctl/pack.def", &pack("c-ctl", "controlled"))]);
    let mut e = Engine::new();
    let read = LoadOptions { read_licences: true, ..LoadOptions::default() };
    let loaded = e.load_tree(&t.packs(), &read).unwrap();
    assert_eq!(loaded[0].licence.as_ref().unwrap().profile, None);
    e.load_def(&pack("c-ctl-2", "controlled")).unwrap();
}

/// 0.93 with 0.34: an `inner` pack whose own `pack.def` is controlled is in
/// no profile, so a load with a profile skips it and the outer pack's decode
/// is `unknown-format` at the `inner` line ("a pack refused at load ... by a
/// licence profile (0.29), is not loaded"); with no profile it loads and the
/// public outer pack is `distribution-violation` there; a public inner pack
/// is loaded by the profile and decodes.
#[cfg(feature = "bits")]
#[test]
fn a_profile_load_with_inner_packs() {
    let core = "module core\nversion 1.0.0\ndistribution public\nsource \"t\"\nkey n int -\n";
    let head = |f: &str, d: &str| format!("format {}\nversion 1.0.0\ndistribution {}\nsource \"t\"\nwire bits\nlayout sequential\nbit_order msb\n", f, d);
    let outer = format!("{}inner c-in\n", head("c-out", "public"));
    let tree = |tag: &str, d: &str| {
        Tree::new(
            tag,
            &[("model/core.def", core), ("packs/in/pack.def", &format!("{}field n 8 uint\n", head("c-in", d))), ("packs/out/pack.def", &outer)],
        )
    };
    let t = tree("inner-ctl", "controlled");
    let mut e = Engine::new();
    e.load_tree(&t.packs(), &with(Some("open"))).unwrap();
    assert_eq!(e.formats(), vec!["c-out"]);
    let err = e.decode("c-out", "07").unwrap_err();
    assert!(err.msg.starts_with("unknown-format:"), "{}", err.msg);

    let mut e = Engine::new();
    e.load_tree(&t.packs(), &with(None)).unwrap();
    let err = e.decode("c-out", "07").unwrap_err();
    assert!(err.msg.starts_with("distribution-violation:"), "{}", err.msg);

    let t = tree("inner-pub", "public");
    let mut e = Engine::new();
    e.load_tree(&t.packs(), &with(Some("open"))).unwrap();
    let ent = e.decode("c-out", "07").unwrap();
    assert_eq!(ent.fields.get("n"), Some(&goat_transformers::Value::I64(7)));
}

// ---------------------------------------------------------------------------
// A controlled inner pack (engine-spec 0.34) never loads. The outer pack is
// public and loads alone (0.34: "Nothing about the inner pack is checked at
// load: packs load in any order, and each loads alone."); the inner pack is
// not loaded, so decode and encode of the outer pack are `unknown-format` at
// the `inner` line (0.34, Reaching the `inner` line, 1: "the inner format is
// loaded: otherwise `unknown-format` (a pack refused at load, by a build
// without its wire (0.24), a distribution limit or a licence profile (0.29),
// is not loaded)"), and `model_keys` gives the outer pack's own keys only
// (0.34, Capability: "An `inner` line whose pack does not pass the checks
// adds nothing, and `model_keys` and the capability report do not fail
// because of it").
// ---------------------------------------------------------------------------

#[cfg(feature = "bits")]
mod controlled_inner {
    use super::*;
    use goat_transformers::{Entity, Value};

    const CORE: &str = "module core\nversion 1.0.0\ndistribution public\nsource \"t\"\nkey m int -\nkey n int -\n";
    const CTL: &str = "module ctl\nversion 1.0.0\ndistribution controlled\nsource \"t\"\nkey k int -\n";

    fn head(format: &str, distribution: &str, uses: &str) -> String {
        format!(
            "format {}\nversion 1.0.0\ndistribution {}\nsource \"t\"\n{}wire bits\nlayout sequential\nbit_order msb\n",
            format, distribution, uses
        )
    }
    fn outer() -> String {
        format!("{}field m 8 uint\ninner c-in\n", head("c-out", "public", ""))
    }

    /// What every case shares: the outer pack is loaded, the inner is not,
    /// and the outer pack's use fails at its `inner` line.
    fn outer_alone(e: &Engine) {
        assert_eq!(e.formats(), vec!["c-out"]);
        let err = e.decode("c-out", "0107").unwrap_err();
        assert!(err.msg.starts_with("unknown-format:"), "decode: {}", err.msg);
        let mut ent = Entity::default();
        ent.fields.insert("m".to_string(), Value::I64(1));
        ent.fields.insert("n".to_string(), Value::I64(7));
        let err = e.encode("c-out", &ent).unwrap_err();
        assert!(err.msg.starts_with("unknown-format:"), "encode: {}", err.msg);
        assert_eq!(e.model_keys("c-out"), vec!["m"]);
        let err = e.decode("c-in", "07").unwrap_err();
        assert!(err.msg.starts_with("unknown-format:"), "{}", err.msg);
    }

    /// (1) A load with a profile; the inner `pack.def` is not shown public
    /// (it says `distribution controlled`), so its profile is none (0.93,
    /// ruling 2) and it is skipped (0.29, 3d and 3e).
    #[test]
    fn an_inner_pack_not_shown_public_is_skipped_by_a_profile() {
        for profile in ["open", "open+copyleft", "everything"] {
            let t = Tree::new(
                "inner-1",
                &[
                    ("model/core.def", CORE),
                    ("packs/a-out/pack.def", &outer()),
                    ("packs/b-in/pack.def", &format!("{}field n 8 uint\n", head("c-in", "controlled", ""))),
                ],
            );
            let mut e = Engine::new();
            let loaded = e.load_tree(&t.packs(), &with(Some(profile))).unwrap();
            assert_eq!(loaded.len(), 1, "{}", profile);
            outer_alone(&e);
        }
    }

    /// (2) A load with a profile; the inner `pack.def` is shown public but
    /// uses a module whose file says `distribution controlled`: that module
    /// is in none (0.93, ruling 2) and not loaded, and "through 2b and 2c of
    /// 0.29, so has every module and pack that uses it": the inner pack is
    /// skipped too.
    #[test]
    fn an_inner_pack_using_a_controlled_module_is_skipped_by_a_profile() {
        for profile in ["open", "open+copyleft", "everything"] {
            let t = Tree::new(
                "inner-2",
                &[
                    ("model/core.def", CORE),
                    ("model/ctl.def", CTL),
                    ("packs/a-out/pack.def", &outer()),
                    ("packs/b-in/pack.def", &format!("{}field n 8 uint\n", head("c-in", "public", "uses ctl\n"))),
                ],
            );
            let mut e = Engine::new();
            let loaded = e.load_tree(&t.packs(), &with(Some(profile))).unwrap();
            assert_eq!(loaded.len(), 1, "{}", profile);
            assert_eq!(e.modules(), vec!["core"]);
            outer_alone(&e);
        }
    }

    /// (3) No profile, a limit of `public`: the inner pack is refused at
    /// load ("the module or pack is within the engine's limit" else
    /// `distribution-refused`, 0.4), the outer pack, loaded alone, stays
    /// loaded and is `unknown-format` at its `inner` line. In either load
    /// order.
    #[test]
    fn an_inner_pack_refused_by_a_public_limit() {
        let inner = format!("{}field n 8 uint\n", head("c-in", "controlled", ""));
        for inner_first in [false, true] {
            let mut e = Engine::new();
            e.set_max_distribution(Distribution::Public);
            e.load_model(CORE).unwrap();
            if inner_first {
                refused(e.load_def(&inner));
                e.load_def(&outer()).unwrap();
            } else {
                e.load_def(&outer()).unwrap();
                refused(e.load_def(&inner));
            }
            outer_alone(&e);
        }
        // the directory loader: the load fails at the inner pack, with the
        // inner pack not loaded
        let t = Tree::new("inner-3", &[("model/core.def", CORE), ("packs/b-in/pack.def", &inner)]);
        let mut e = Engine::new();
        e.set_max_distribution(Distribution::Public);
        let err = e.load_tree(&t.packs(), &with(None)).unwrap_err();
        assert!(err.msg.starts_with("distribution-refused:"), "{}", err.msg);
        assert!(e.formats().is_empty());
    }
}
