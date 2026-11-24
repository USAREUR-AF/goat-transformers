//! Engine-spec 0.25, ruling 1: what a loaded pack's lines compute once.
//!
//! `Engine::load` computes one `Layout` per pack, after the pack is checked
//! and its keys' types are read, and keeps it beside the pack for the life of
//! the engine instance. A conversion reads it and never writes it: nothing
//! of one conversion is left for the next (1b), and one instance may convert
//! on several threads at once (1c).
//!
//! A line is found by the address of its locator text (pointer and length):
//! the text of a loaded pack is never changed or freed while the engine
//! lives, so the address names that one line. A scope (the lines in force for
//! one kind, or the body of one group) is found by the address of its
//! `KindDef` or `GroupDef`, which sit in the pack's vectors and never move.
//! Whatever the layout does not hold (a codec called without an engine, a
//! line built during a conversion) is computed as before the layout existed,
//! so the layout changes how much work a conversion does and never its
//! result.

use super::*;
use std::hash::{BuildHasherDefault, Hasher};

/// The hasher of the layout's tables. Their keys are addresses and the
/// pack's own locator texts, never input, so a fast hash that an input
/// could not aim at is enough (FxHash's mixing step).
#[derive(Default, Clone, Copy)]
#[allow(dead_code)]
pub(crate) struct LineHasher(u64);
impl Hasher for LineHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for c in bytes.chunks(8) {
            let mut b = [0u8; 8];
            b[..c.len()].copy_from_slice(c);
            self.write_u64(u64::from_le_bytes(b));
        }
    }
    fn write_u8(&mut self, n: u8) {
        self.write_u64(n as u64)
    }
    fn write_u32(&mut self, n: u32) {
        self.write_u64(n as u64)
    }
    fn write_usize(&mut self, n: usize) {
        self.write_u64(n as u64)
    }
    fn write_u64(&mut self, n: u64) {
        self.0 = (self.0.rotate_left(5) ^ n).wrapping_mul(0x51_7c_c1_b7_27_22_0a_95);
    }
}

/// A table of the layout.
#[allow(dead_code)]
pub(crate) type Map<K, V> = HashMap<K, V, BuildHasherDefault<LineHasher>>;

/// The key of a line: its locator text's address and length.
#[allow(dead_code)]
pub(crate) fn line_key(locator: &str) -> (usize, usize) {
    (locator.as_ptr() as usize, locator.len())
}

/// The key of the scope a selection opened: its kind, or 0 for the common
/// lines of a pack without kinds.
#[allow(dead_code)]
pub(crate) fn kind_key(kind: Option<&KindDef>) -> usize {
    kind.map_or(0, |k| k as *const KindDef as usize)
}

/// The key of the scope of a group's items.
#[allow(dead_code)]
pub(crate) fn group_key(g: &GroupDef) -> usize {
    g as *const GroupDef as usize
}

/// The protobuf lines of one scope by the first field number of their path:
/// a line whose first field does not occur in the message reads nothing, so
/// a decode visits only the lines of the fields that occur (1a: "the index
/// of a protobuf message's field numbers").
#[cfg(feature = "protobuf")]
#[derive(Default, Debug)]
pub(crate) struct PbScope {
    /// first field number -> places in `Sel::fields`, ascending
    pub fields: Map<u32, Vec<usize>>,
    /// first field number -> places in `Sel::groups`, ascending
    pub groups: Map<u32, Vec<usize>>,
}

/// The xml lines of one scope that do not depend on the entity: the
/// `element` lines with the line each is placed at, and the first line that
/// names each locator among the fields, the fixed values and the elements
/// (ruling 23 of 0.9). Encode adds the groups the entity writes.
#[cfg(feature = "xml")]
#[derive(Default, Debug)]
pub(crate) struct XmlScope {
    pub elements: Vec<(usize, String)>,
    /// the first such line of each field, fixed value and group, by the
    /// address of its locator (`xml::static_firsts`)
    pub firsts: Map<(usize, usize), usize>,
}

#[derive(Default, Debug)]
pub(crate) struct Layout {
    /// the entries of `model_keys`, when the pack is first reached as an
    /// `inner` one (ruling 20 of 0.52)
    #[cfg(feature = "bits")]
    pub keys: std::sync::OnceLock<std::collections::HashSet<String>>,
    /// protobuf: the field-number path of every locator
    #[cfg(feature = "protobuf")]
    pub pb_paths: Map<(usize, usize), Vec<u32>>,
    /// protobuf: the index of every scope
    #[cfg(feature = "protobuf")]
    pub pb_scopes: Map<usize, PbScope>,
    /// bits, fixed layout: (first message bit, bit length) of every locator
    #[cfg(feature = "bits")]
    pub bits_spans: Map<(usize, usize), (u64, u32)>,
    /// bits, fixed layout: (word, bit) of every group locator
    #[cfg(feature = "bits")]
    pub bits_groups: Map<(usize, usize), (usize, u32)>,
    /// text: every locator as the codec reads it (None: it does not read as one)
    #[cfg(feature = "text")]
    pub text_locs: Map<(usize, usize), Option<text::Loc>>,
    /// tlv: every locator as the codec reads it (None: it does not read as
    /// one under the pack's `tag`)
    #[cfg(feature = "tlv")]
    pub tlv_locs: Map<(usize, usize), Option<tlv::Loc>>,
    /// tlv: the tags the lines of each scope name, as a tree
    #[cfg(feature = "tlv")]
    pub tlv_names: Map<usize, tlv::Names>,
    /// xml: the entity-independent lines of every scope
    #[cfg(feature = "xml")]
    pub xml_scopes: Map<usize, XmlScope>,
}

impl Layout {
    /// The layout of a loaded pack.
    #[allow(unused_variables, unused_mut)]
    pub(crate) fn of(p: &Pack) -> Layout {
        let mut lay = Layout::default();
        // every selection a decode or an encode can open: the common lines
        // alone (a pack without kinds), or with one kind
        let mut scopes: Vec<(usize, Sel)> = Vec::new();
        #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
        {
            if p.kinds.is_empty() {
                scopes.push((0, p.sel(None)));
            }
            for k in &p.kinds {
                scopes.push((kind_key(Some(k)), p.sel(Some(k))));
            }
        }
        #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text"))]
        let groups: Vec<(usize, Sel)> = p.every_group().into_iter().map(|g| (group_key(g), g.body())).collect();
        #[cfg(not(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text")))]
        let groups: Vec<(usize, Sel)> = Vec::new();
        match p.wire {
            #[cfg(feature = "protobuf")]
            Wire::Protobuf => {
                let mut locators: Vec<&str> = Vec::new();
                for (_, s) in scopes.iter().chain(groups.iter()) {
                    locators.extend(s.fields.iter().map(|f| f.locator.as_str()));
                    locators.extend(s.whens.iter().chain(s.consts.iter()).map(|w| w.locator.as_str()));
                    locators.extend(s.groups.iter().map(|g| g.locator.as_str()));
                }
                for l in locators {
                    if let Ok(path) = protobuf::parse_path(l) {
                        lay.pb_paths.insert(line_key(l), path);
                    }
                }
                for (key, s) in scopes.iter().chain(groups.iter()) {
                    if let Some(ix) = lay.pb_scope_of(s) {
                        lay.pb_scopes.insert(*key, ix);
                    }
                }
            }
            #[cfg(feature = "bits")]
            Wire::Bits if p.seq.is_none() => {
                let mut locators: Vec<&str> = Vec::new();
                for (_, s) in scopes.iter().chain(groups.iter()) {
                    locators.extend(s.fields.iter().map(|f| f.locator.as_str()));
                    locators.extend(s.whens.iter().chain(s.consts.iter()).map(|w| w.locator.as_str()));
                    locators.extend(s.groups.iter().map(|g| g.locator.as_str()));
                    locators.extend(s.gates.iter().map(|g| g.locator.as_str()));
                }
                for (_, s) in scopes.iter().chain(groups.iter()) {
                    for g in &s.groups {
                        if let Ok(at) = bits::parse_group_locator(&g.locator) {
                            lay.bits_groups.insert(line_key(&g.locator), at);
                        }
                    }
                }
                let none = Layout::default();
                for l in locators {
                    if let Ok(span) = bits::span(p, &none, l) {
                        lay.bits_spans.insert(line_key(l), span);
                    }
                }
            }
            #[cfg(feature = "text")]
            Wire::Text => {
                for (_, s) in scopes.iter().chain(groups.iter()) {
                    let lines = s.fields.iter().map(|f| f.locator.as_str()).chain(s.whens.iter().chain(s.consts.iter()).map(|w| w.locator.as_str()));
                    for l in lines {
                        lay.text_locs.entry(line_key(l)).or_insert_with(|| text::Loc::parse(l).ok());
                    }
                }
            }
            #[cfg(feature = "tlv")]
            Wire::Tlv => {
                for (key, s) in &scopes {
                    let lines = s.fields.iter().map(|f| f.locator.as_str()).chain(s.whens.iter().chain(s.consts.iter()).map(|w| w.locator.as_str()));
                    for l in lines {
                        lay.tlv_locs.entry(line_key(l)).or_insert_with(|| tlv::Loc::parse(l, p.tlv.tag).ok());
                    }
                    lay.tlv_names.insert(*key, tlv::names(p, s));
                }
            }
            #[cfg(feature = "xml")]
            Wire::Xml => {
                for (key, s) in scopes.iter().chain(groups.iter()) {
                    let elements = xml::element_lines(s);
                    let firsts = xml::static_firsts(s, &elements);
                    lay.xml_scopes.insert(
                        *key,
                        XmlScope {
                            firsts,
                            elements: elements.into_iter().map(|(n, l)| (n, l.to_string())).collect(),
                        },
                    );
                }
            }
            _ => {}
        }
        lay
    }

    /// The path of a protobuf locator.
    #[cfg(feature = "protobuf")]
    pub(crate) fn pb_path<'a>(&'a self, locator: &str) -> Result<std::borrow::Cow<'a, [u32]>, Error> {
        match self.pb_paths.get(&line_key(locator)) {
            Some(path) => Ok(std::borrow::Cow::Borrowed(path.as_slice())),
            None => protobuf::parse_path(locator).map(std::borrow::Cow::Owned),
        }
    }

    /// The index of one scope; None when a locator of it has no path (the
    /// decode then visits every line, and meets that locator's error in
    /// line order).
    #[cfg(feature = "protobuf")]
    fn pb_scope_of(&self, s: &Sel) -> Option<PbScope> {
        let mut ix = PbScope::default();
        for (i, f) in s.fields.iter().enumerate().filter(|(_, f)| f.locator != ".") {
            ix.fields.entry(*self.pb_paths.get(&line_key(&f.locator))?.first()?).or_default().push(i);
        }
        for (i, g) in s.groups.iter().enumerate() {
            ix.groups.entry(*self.pb_paths.get(&line_key(&g.locator))?.first()?).or_default().push(i);
        }
        Some(ix)
    }

    /// A tlv locator as `tlv::loc` reads it.
    #[cfg(feature = "tlv")]
    pub(crate) fn tlv_loc<'a>(&'a self, p: &Pack, locator: &str) -> Option<std::borrow::Cow<'a, tlv::Loc>> {
        match self.tlv_locs.get(&line_key(locator)) {
            Some(l) => l.as_ref().map(std::borrow::Cow::Borrowed),
            None => tlv::Loc::parse(locator, p.tlv.tag).ok().map(std::borrow::Cow::Owned),
        }
    }
}
