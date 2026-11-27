//! Token parts (engine-spec v0.64): the text of one place split at a
//! separator, its parts bound to keys. The lines of one scope with one
//! locator, at least one of them a part line, are a part group.

use super::*;

/// The parameters of `part:<sep>:<n>`: the separator as `tokens` writes it
/// (engine-spec v0.18), then a number from 0 to 255 without leading zeros.
pub(crate) fn params(args: &str) -> Option<(char, u8)> {
    let (sep, n) = args.split_once(':')?;
    let sep = token_sep(sep)?;
    if n.is_empty() || !n.bytes().all(|b| b.is_ascii_digit()) || (n.len() > 1 && n.starts_with('0')) {
        return None;
    }
    Some((sep, n.parse::<u8>().ok()?))
}

/// Part `n` of a token; a missing part is a failed transform (ruling 5).
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "text"))]
pub(crate) fn nth(token: &str, sep: char, n: u8) -> Result<&str, Error> {
    token.split(sep).nth(n as usize).ok_or_else(|| Error { msg: format!("`{}` has no part {}", token, n) })
}

// ---------------------------------------------------------------------------
// Load checks
// ---------------------------------------------------------------------------

/// What a part line, and `unlisted`, owe their wire and transform.
pub(crate) fn check_field(wire: Wire, f: &FieldDef, in_group: bool) -> Result<(), Error> {
    let part = matches!(f.transform, Transform::Part(..));
    if f.unlisted && (!part || f.via.is_none()) {
        return bad(f.line, "`unlisted` is valid only on a `part` line with `via`");
    }
    if !part {
        return Ok(());
    }
    check_place(wire, &f.locator, f.line, in_group)?;
    // engine-spec v0.56 ruling 15: nor `null`, `implicit`, `range` (with or
    // without `wrap`); range sentinels come with `absent`
    if f.absent_arg.is_some() || f.with.is_some() || f.swap || f.trim || f.stop.is_some() || f.null || f.implicit || f.range.is_some() {
        return bad(f.line, "a `part` line takes only `via`, `unlisted` and, on text, `optional`");
    }
    Ok(())
}

/// A `const … part` line: its place, and its text once resolved.
pub(crate) fn check_const(wire: Wire, c: &WhenDef, in_group: bool) -> Result<(), Error> {
    let (sep, _) = match c.part {
        Some(p) => p,
        None => return Ok(()),
    };
    check_place(wire, &c.locator, c.line, in_group)?;
    let text = c.value.strip_prefix('=').unwrap_or(&c.value);
    if text.is_empty() || text.contains(sep) {
        return bad(c.line, format!("the text `{}` of a `const` part is empty or holds its separator", c.value));
    }
    Ok(())
}

fn check_place(wire: Wire, locator: &str, line: usize, in_group: bool) -> Result<(), Error> {
    match wire {
        Wire::Xml | Wire::Json => Ok(()),
        Wire::GeoJson if !in_group && locator.starts_with("geometry.") => bad(line, "`part` is not valid on a coordinate"),
        Wire::GeoJson => Ok(()),
        Wire::Text if locator.bytes().all(|b| b.is_ascii_digit()) => Ok(()),
        Wire::Text => bad(line, "`part` is not valid on a column or a pair"),
        _ => bad(line, "`part` is valid only on the xml, json, geojson and text wires"),
    }
}

/// The part groups of one reading scope: common lines plus one kind, or one
/// group body. `text`: the directives of a `text` pack.
pub(crate) fn check_scope(
    text: Option<&text::TextConf>,
    fields: &[&FieldDef],
    whens: &[&WhenDef],
    consts: &[&WhenDef],
    groups: &[&GroupDef],
) -> Result<(), Error> {
    let mut places: Vec<&str> = Vec::new();
    let of_fields = fields.iter().filter(|f| matches!(f.transform, Transform::Part(..))).map(|f| f.locator.as_str());
    for l in of_fields.chain(consts.iter().filter(|c| c.part.is_some()).map(|c| c.locator.as_str())) {
        if !places.contains(&l) {
            places.push(l);
        }
    }
    for place in places {
        // (line, separator, number) of each part line
        let mut parts: Vec<(usize, char, u8)> = Vec::new();
        let mut keys: Vec<&str> = Vec::new();
        let mut whole: Option<&FieldDef> = None;
        for f in fields.iter().filter(|f| f.locator == place) {
            match f.transform {
                Transform::Part(sep, n) => {
                    parts.push((f.line, sep, n));
                    keys.push(&f.model_key);
                }
                Transform::StringT
                    if f.via.is_none()
                        && f.with.is_none()
                        && f.absent_arg.is_none()
                        && !f.swap
                        && !f.trim
                        && !f.unlisted
                        // engine-spec v0.56 ruling 15
                        && !f.null
                        && !f.implicit
                        && f.range.is_none() =>
                {
                    if whole.is_some() {
                        return bad(f.line, format!("a second whole line on `{}`", place));
                    }
                    whole = Some(f);
                }
                _ => return bad(f.line, format!("`{}` is split into parts; this line is not its whole line", place)),
            }
        }
        for c in consts.iter().filter(|c| c.locator == place) {
            match c.part {
                Some((sep, n)) => parts.push((c.line, sep, n)),
                None => return bad(c.line, format!("a `const` on `{}`, which is split into parts", place)),
            }
        }
        if let Some(w) = whens.iter().find(|w| w.locator == place) {
            return bad(w.line, format!("a `when` on `{}`, which is split into parts", place));
        }
        if let Some(g) = groups.iter().find(|g| g.locator == place) {
            return bad(g.line, format!("a `group` on `{}`, which is split into parts", place));
        }
        let (line, sep, _) = parts[0];
        if let Some((l, _, _)) = parts.iter().find(|(_, s, _)| *s != sep) {
            return bad(*l, format!("two separators on `{}`", place));
        }
        for (i, (l, _, n)) in parts.iter().enumerate() {
            if parts[..i].iter().any(|(_, _, m)| m == n) {
                return bad(*l, format!("part {} of `{}` is named twice", n, place));
            }
        }
        // no number is named twice, so fewer lines than numbers is a gap
        let highest = parts.iter().map(|(_, _, n)| *n as usize).max().unwrap_or(0);
        if parts.len() != highest + 1 {
            return bad(line, format!("a part of `{}` from 0 to {} is named by no line", place, highest));
        }
        if keys.is_empty() {
            return bad(line, format!("no `field` line names a part of `{}`", place));
        }
        if let Some(f) = whole.filter(|f| keys.contains(&f.model_key.as_str())) {
            return bad(f.line, format!("`{}` is both the whole of `{}` and a part of it", f.model_key, place));
        }
        if let Some(conf) = text {
            if conf.delimiter.map_or(false, |d| d as char == sep) || (conf.nmea && sep == '*') {
                return bad(line, format!("the separator of `{}` is the delimiter, or `*` under `checksum nmea`", place));
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Encode
// ---------------------------------------------------------------------------

/// One part group of the lines in force.
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "text"))]
pub(crate) struct Group<'a> {
    /// the locator, of the group's first `field` line
    pub locator: &'a str,
    /// the group's first line (ruling 8)
    pub line: usize,
    whole: Option<&'a FieldDef>,
    fields: Vec<(u8, &'a FieldDef)>,
    consts: Vec<(u8, &'a WhenDef)>,
    sep: char,
}

/// The part groups of a scope, in the order of their first lines.
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "text"))]
pub(crate) fn groups<'a>(sel: &Sel<'a>) -> Vec<Group<'a>> {
    let mut out: Vec<Group<'a>> = Vec::new();
    for f in &sel.fields {
        if let Transform::Part(sep, n) = f.transform {
            match out.iter_mut().find(|g| g.locator == f.locator) {
                Some(g) => g.fields.push((n, *f)),
                None => out.push(Group {
                    locator: &f.locator,
                    line: f.line,
                    whole: None,
                    fields: vec![(n, *f)],
                    consts: Vec::new(),
                    sep,
                }),
            }
        }
    }
    for g in out.iter_mut() {
        g.whole = sel.fields.iter().copied().find(|f| f.locator == g.locator && !matches!(f.transform, Transform::Part(..)));
        g.consts = sel
            .consts
            .iter()
            .copied()
            .filter(|c| c.locator == g.locator)
            .filter_map(|c| c.part.map(|(_, n)| (n, c)))
            .collect();
        let lines = g.fields.iter().map(|(_, f)| f.line).chain(g.whole.map(|f| f.line)).chain(g.consts.iter().map(|(_, c)| c.line));
        g.line = lines.min().unwrap_or(g.line);
    }
    out.sort_by_key(|g| g.line);
    out
}

/// A part of a token as decode reads it; None where `unlisted` leaves the
/// line absent.
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "text"))]
fn read(p: &Pack, f: &FieldDef, text: &str) -> Result<Option<Value>, Error> {
    let v = Value::Str(text.to_string());
    if p.unlisted(f, &v) {
        return Ok(None);
    }
    p.to_model(f, v).map(Some)
}

#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "text"))]
impl<'a> Group<'a> {
    /// The token the entity (inside a group, the item) writes; None: nothing
    /// is written (engine-spec v0.64, Encode).
    pub(crate) fn token(&self, p: &Pack, sel: &Sel<'a>, ent: &'a Entity) -> Result<Option<String>, Error> {
        let held = |f: &FieldDef| ent.fields.contains_key(&f.model_key);
        let whole = |f: &FieldDef| self.whole_text(p, sel, ent, f).map(Some).map_err(|e| transform_encode_err(p, f, e));
        // step 1
        if let Some(f) = self.whole.filter(|f| held(f)) {
            return whole(f);
        }
        // step 2: a held value or a `default` for every part field
        let every = self.fields.iter().all(|(_, f)| sel.value_of(ent, f).is_some());
        if every || self.fields.iter().any(|(_, f)| held(f)) {
            let mut parts: Vec<(u8, String)> = self.consts.iter().map(|(n, c)| (*n, c.text.clone())).collect();
            for (n, f) in &self.fields {
                let text = self.part_text(p, sel, ent, f).map_err(|e| transform_encode_err(p, f, e))?;
                parts.push((*n, text));
            }
            parts.sort_by_key(|(n, _)| *n);
            let texts: Vec<String> = parts.into_iter().map(|(_, t)| t).collect();
            return Ok(Some(texts.join(&self.sep.to_string())));
        }
        // step 3: the `default` of the whole line's key
        match self.whole.filter(|f| sel.value_of(ent, f).is_some()) {
            Some(f) => whole(f),
            None => Ok(None),
        }
    }

    /// The text of one part field.
    fn part_text(&self, p: &Pack, sel: &Sel<'a>, ent: &'a Entity, f: &FieldDef) -> Result<String, Error> {
        let v = sel.value_of(ent, f).ok_or(Error { msg: "the part has no value and another part of its token does".into() })?;
        match p.to_wire(f, v)? {
            Value::Str(s) if s.contains(self.sep) => err(format!("`{}` holds the separator", s)),
            Value::Str(s) => Ok(s),
            other => err(format!("`{}` is not text", other.as_display())),
        }
    }

    /// The whole line's text, checked against the part lines (step 1).
    fn whole_text(&self, p: &Pack, sel: &Sel<'a>, ent: &'a Entity, whole: &FieldDef) -> Result<String, Error> {
        let v = sel.value_of(ent, whole).ok_or(Error { msg: "no value".into() })?;
        let token = match p.to_wire(whole, v)? {
            Value::Str(s) => s,
            other => return err(format!("`{}` is not text", other.as_display())),
        };
        for (n, c) in &self.consts {
            let part = nth(&token, self.sep, *n)?;
            if part != c.text {
                return err(format!("part {} of `{}` is not `{}`", n, token, c.text));
            }
        }
        for (n, f) in &self.fields {
            // a key with another line in the scope is not checked (rulings 2 and 18)
            if sel.fields.iter().any(|o| o.line != f.line && o.model_key == f.model_key) {
                continue;
            }
            let value = read(p, f, nth(&token, self.sep, *n)?)?;
            match (ent.fields.get(&f.model_key), value) {
                (Some(_), None) => {
                    return err(format!("part {} of `{}` leaves `{}` absent, and the entity holds it", n, token, f.model_key))
                }
                (Some(h), Some(v)) if *h != v => {
                    return err(format!(
                        "part {} of `{}` reads as {}, and the entity holds `{}` = {}",
                        n,
                        token,
                        v.as_display(),
                        f.model_key,
                        h.as_display()
                    ))
                }
                _ => {}
            }
        }
        Ok(token)
    }
}
