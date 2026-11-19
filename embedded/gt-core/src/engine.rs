//! The interpreter: decode a message into a fixed value store, fill and
//! derive, encode. Behaviour follows the Rust reference engine
//! (engines/rust/src/lib.rs, module `bits`, and engines/rust/src/seq.rs);
//! the comments name the spec ruling where one decides a point.

use crate::num;
use crate::plan::*;
use crate::{Error, KeyId, Plan, Value};

/// Deepest nesting of blocks and groups the engine follows. The compiler
/// refuses a pack that nests deeper; the engine checks again at run time.
pub const MAX_DEPTH: u8 = 12;

/// The limit on list items one decode holds when the caller sets none
/// (engine-spec ruling 7 of 0.11).
pub const DEFAULT_MAX_ITEMS: u64 = 100_000;
/// Presence fields one format may declare.
pub const MAX_PRESENCE: usize = 16;
/// `length ... whole` lines one message may hold.
pub const MAX_WHOLES: usize = 4;
/// Arguments of one derive line.
pub const MAX_ARGS: usize = 8;

const T_INT: u8 = 0;
const T_FLOAT: u8 = 1;
const T_STR: u8 = 2;
const T_LIST: u8 = 3;

const XF_UINT: u8 = 0;
const XF_TWOS: u8 = 1;
const XF_LINSCALE: u8 = 2;
const XF_USCALE: u8 = 3;
const XF_SSCALE: u8 = 4;
const XF_F32: u8 = 5;
const XF_F64: u8 = 6;
const XF_ASCII: u8 = 7;

const F_SWAP: u8 = 1;
const F_TRIM: u8 = 2;
const F_OPTIONAL: u8 = 4;

const K_CONTEXT: u8 = 1;
const K_LIVE: u8 = 2;

/// text read from the input, first byte at bit `off`
const SRC_INPUT: u8 = 0;
/// the same, bytes in reverse order (`swap`)
const SRC_INPUT_REV: u8 = 1;
/// text of the plan's byte table
const SRC_PLAN: u8 = 2;
/// text the caller set with `set_texts`
const SRC_TEXT: u8 = 3;
/// text of a context value
const SRC_CONTEXT: u8 = 4;

/// Text is never copied: a value holds where its bytes are.
#[derive(Clone, Copy)]
pub struct TextRef {
    src: u8,
    len: u16,
    room: u16,
    off: u32,
}

#[derive(Clone, Copy)]
pub(crate) enum Val {
    Int(i64),
    Float(f64),
    Str(TextRef),
    /// a list and its number of items
    List(u16),
    /// a line of the key failed its transform; a later line may still give the value
    Failed,
    /// a value table refused the key's value
    Hard,
}

#[derive(Clone, Copy)]
pub(crate) struct Slot {
    scope: u16,
    key: u16,
    val: Val,
}

#[derive(Clone, Copy)]
pub(crate) struct ScopeRec {
    parent: u16,
    list: u16,
    index: u16,
    kind: u16,
}

/// The working memory of one conversion: `N` value slots and `N` list items.
/// A slot is 24 bytes and an item 8, so `Scratch<32>` is 1 KiB. The caller
/// owns it; the engine allocates nothing.
pub struct Scratch<const N: usize> {
    slots: [Slot; N],
    scopes: [ScopeRec; N],
}

impl<const N: usize> Scratch<N> {
    pub const fn new() -> Scratch<N> {
        Scratch {
            slots: [Slot { scope: 0, key: 0, val: Val::Failed }; N],
            scopes: [ScopeRec { parent: 0, list: 0, index: 0, kind: NONE16 }; N],
        }
    }
}

impl<const N: usize> Default for Scratch<N> {
    fn default() -> Scratch<N> {
        Scratch::new()
    }
}

/// The message itself (`ROOT`) or one item of a list.
#[derive(Clone, Copy, PartialEq, Debug)]
pub struct Scope(pub u16);

/// The message itself, as opposed to an item of a list.
pub const ROOT: Scope = Scope(0);

/// A value read back from a session.
#[derive(Clone, Copy)]
pub enum Got {
    Int(i64),
    Float(f64),
    /// read the bytes with `Session::text_len` and `Session::text_byte`
    Text(TextRef),
}

// ---------------------------------------------------------------------------
// Bits
// ---------------------------------------------------------------------------

/// `len` (1..=64) bits from message bit `start`. None when the range runs
/// past the input. lsb: bit i is bit `i mod 8` of byte `i div 8`, first bit
/// least significant. msb: bit i is bit `7 - (i mod 8)`, first bit most
/// significant.
fn get_bits(msg: &[u8], start: u64, len: u32, msb: bool) -> Option<u64> {
    if len == 0 || len > 64 || start.checked_add(len as u64)? > msg.len() as u64 * 8 {
        return None;
    }
    let mut v: u64 = 0;
    for k in 0..len as u64 {
        let bit = start + k;
        let byte = *msg.get((bit / 8) as usize)?;
        if msb {
            if byte & (0x80 >> (bit % 8)) != 0 {
                v |= 1u64 << (len as u64 - 1 - k);
            }
        } else if byte & (1 << (bit % 8)) != 0 {
            v |= 1u64 << k;
        }
    }
    Some(v)
}

fn set_bits(msg: &mut [u8], start: u64, len: u32, raw: u64, msb: bool) {
    if len == 0 || len > 64 {
        return;
    }
    for k in 0..len as u64 {
        let bit = start.wrapping_add(k);
        let (on, mask) = if msb {
            (raw & (1u64 << (len as u64 - 1 - k)) != 0, 0x80u8 >> (bit % 8))
        } else {
            (raw & (1u64 << k) != 0, 1u8 << (bit % 8))
        };
        if let Some(b) = usize::try_from(bit / 8).ok().and_then(|i| msg.get_mut(i)) {
            if on {
                *b |= mask;
            } else {
                *b &= !mask;
            }
        }
    }
}

/// The low `len` bits of `raw` with their bytes in reverse order (`swap`).
fn swap_bytes(raw: u64, len: u32) -> u64 {
    if len == 0 || len > 64 || len % 8 != 0 {
        return raw;
    }
    raw.swap_bytes() >> (64 - len)
}

fn mask(len: u32) -> u64 {
    if len >= 64 {
        u64::MAX
    } else {
        (1u64 << len) - 1
    }
}

fn signed(raw: u64, len: u32) -> i64 {
    if len >= 1 && len < 64 && raw & (1u64 << (len - 1)) != 0 {
        (raw as i64).wrapping_sub(1i64 << len)
    } else {
        raw as i64
    }
}

fn words(bits: u64, word_bytes: u16) -> u64 {
    let wb = word_bytes.max(1) as u64 * 8;
    bits.div_ceil(wb) * word_bytes.max(1) as u64
}

// ---------------------------------------------------------------------------
// The session
// ---------------------------------------------------------------------------

/// The defaults in force: the body's, and the selected kind's.
#[derive(Clone, Copy)]
struct Defs {
    body: u32,
    kind: u32,
}

struct BodyInfo {
    /// first line of the common part
    lines: u32,
    /// the first `KIND`, or `end`
    first_kind: u32,
    end: u32,
    /// pool index of (reach, decode need, encode need); fixed layout only
    extent: u16,
}

struct KindInfo {
    whens: u32,
    lines: u32,
    end: u32,
    ordinal: u16,
    excluded: bool,
    extent: u16,
}

/// The cursor of a sequential encode.
struct Wr<'o> {
    out: &'o mut [u8],
    pos: u64,
    /// bytes of `out` in use, all written or zeroed
    hi: usize,
    msb: bool,
    wholes: [(u64, u16, i64); MAX_WHOLES],
    nwholes: usize,
}

impl<'o> Wr<'o> {
    /// `n` zero bits.
    fn zeros(&mut self, n: u64) -> Result<(), Error> {
        let pos = self.pos.checked_add(n).ok_or(Error::OutputFull)?;
        let bytes = usize::try_from(pos.div_ceil(8)).map_err(|_| Error::OutputFull)?;
        if bytes > self.hi {
            self.out.get_mut(self.hi..bytes).ok_or(Error::OutputFull)?.fill(0);
            self.hi = bytes;
        }
        self.pos = pos;
        Ok(())
    }
    fn put(&mut self, len: u32, v: u64) -> Result<(), Error> {
        let at = self.pos;
        self.zeros(len as u64)?;
        set_bits(self.out, at, len, v, self.msb);
        Ok(())
    }
}

/// One conversion in steps: `decode`, `fill`, `complete`, `encode`, with the
/// values readable and settable in between. `convert` runs the four in order.
pub struct Session<'a, 's> {
    plan: &'a Plan<'a>,
    input: &'a [u8],
    texts: &'a [&'a [u8]],
    context: &'a [(KeyId, Value<'a>)],
    slots: &'s mut [Slot],
    scopes: &'s mut [ScopeRec],
    nslots: usize,
    nscopes: usize,
    presence: [u64; MAX_PRESENCE],
    kind: u16,
    failed: bool,
    decoded: bool,
    src_msb: bool,
    // the cursor of a sequential decode
    pos: u64,
    end: u64,
    whole: u64,
    extents: u16,
    // the limit on list items of a decode, and the items the entity holds
    max_items: u64,
    held: u64,
}

impl<'a, 's> Session<'a, 's> {
    pub fn new<const N: usize>(plan: &'a Plan<'a>, scratch: &'s mut Scratch<N>) -> Session<'a, 's> {
        Session {
            plan,
            input: &[],
            texts: &[],
            context: &[],
            slots: &mut scratch.slots[..],
            scopes: &mut scratch.scopes[..],
            nslots: 0,
            nscopes: 0,
            presence: [0; MAX_PRESENCE],
            kind: NONE16,
            failed: false,
            decoded: false,
            src_msb: false,
            pos: 0,
            end: 0,
            whole: 0,
            extents: 0,
            max_items: DEFAULT_MAX_ITEMS,
            held: 0,
        }
    }

    /// Set the limit on list items one decode holds (engine-spec ruling 7 of
    /// 0.11): every item of every list, at every nesting level. A decode
    /// that would hold one item more is `MalformedWire`. 0 refuses any item.
    pub fn set_max_items(&mut self, n: u64) {
        self.max_items = n;
    }

    /// Hold `n` more items, or fail: past the limit is `malformed-wire`,
    /// before any of the items is read (rulings 7a, 7d and 7f).
    fn take_items(&mut self, n: u64) -> Result<(), Error> {
        if n > self.max_items.saturating_sub(self.held) {
            return Err(Error::MalformedWire);
        }
        self.held += n;
        Ok(())
    }

    /// Before a group decodes into a list the scope already holds: those
    /// items are no longer held once the group replaces them (ruling 7g).
    fn replacing(&mut self, scope: u16, list: u16) {
        let old = self.items_under(scope, list, 0);
        self.held = self.held.saturating_sub(old);
    }

    /// The items of a list of a scope, those of its items' lists included.
    fn items_under(&self, scope: u16, list: u16, depth: u8) -> u64 {
        let n = match self.list_len(scope, list) {
            Some(n) => n,
            None => return 0,
        };
        let mut total = n as u64;
        if depth > MAX_DEPTH {
            return total;
        }
        for index in 0..n {
            if let Some(item) = self.item(scope, list, index) {
                let lists = self.slots.get(..self.nslots).unwrap_or(&[]);
                for s in lists.iter().filter(|s| s.scope == item && matches!(s.val, Val::List(_))) {
                    total += self.items_under(item, s.key, depth + 1);
                }
            }
        }
        total
    }

    // -- the store ----------------------------------------------------------

    fn find(&self, scope: u16, key: u16) -> Option<usize> {
        self.slots.get(..self.nslots)?.iter().position(|s| s.scope == scope && s.key == key)
    }

    fn val(&self, scope: u16, key: u16) -> Option<Val> {
        self.find(scope, key).and_then(|i| self.slots.get(i)).map(|s| s.val)
    }

    /// The value of a key that holds one: not a list, not a failure mark.
    fn scalar(&self, scope: u16, key: u16) -> Option<Val> {
        match self.val(scope, key) {
            Some(v @ (Val::Int(_) | Val::Float(_) | Val::Str(_))) => Some(v),
            _ => None,
        }
    }

    fn set(&mut self, scope: u16, key: u16, val: Val) -> Result<(), Error> {
        let i = match self.find(scope, key) {
            Some(i) => i,
            None => {
                let i = self.nslots;
                self.nslots += 1;
                i
            }
        };
        match self.slots.get_mut(i) {
            Some(s) => {
                *s = Slot { scope, key, val };
                Ok(())
            }
            None => {
                self.nslots = self.slots.len();
                Err(Error::ScratchFull)
            }
        }
    }

    fn new_scope(&mut self, parent: u16, list: u16, index: u16) -> Result<u16, Error> {
        let id = self.nscopes;
        if id + 1 >= NONE16 as usize {
            return Err(Error::ScratchFull);
        }
        let rec = self.scopes.get_mut(id).ok_or(Error::ScratchFull)?;
        *rec = ScopeRec { parent, list, index, kind: NONE16 };
        self.nscopes += 1;
        Ok(id as u16 + 1)
    }

    fn item(&self, parent: u16, list: u16, index: u16) -> Option<u16> {
        self.scopes
            .get(..self.nscopes)?
            .iter()
            // the last such item: when two groups of one list are on the wire,
            // the later group's items are the list (ruling 33 of 0.8)
            .rposition(|s| s.parent == parent && s.list == list && s.index == index)
            .map(|i| i as u16 + 1)
    }

    fn list_len(&self, scope: u16, list: u16) -> Option<u16> {
        match self.val(scope, list) {
            Some(Val::List(n)) => Some(n),
            _ => None,
        }
    }

    fn scope_kind(&self, scope: u16) -> u16 {
        if scope == 0 {
            return self.kind;
        }
        self.scopes.get(scope as usize - 1).map_or(NONE16, |s| s.kind)
    }

    /// A key that is present, or a list that has at least one item.
    fn has(&self, scope: u16, key: u16) -> bool {
        match self.val(scope, key) {
            Some(Val::List(n)) => n > 0,
            Some(Val::Int(_) | Val::Float(_) | Val::Str(_)) => true,
            _ => false,
        }
    }

    // -- text ---------------------------------------------------------------

    fn text_at(&self, r: TextRef, i: u16) -> u8 {
        if i >= r.len {
            return 0;
        }
        match r.src {
            SRC_INPUT => get_bits(self.input, r.off as u64 + 8 * i as u64, 8, self.src_msb).unwrap_or(0) as u8,
            SRC_INPUT_REV => {
                let k = (r.room.wrapping_sub(1).wrapping_sub(i)) as u64;
                get_bits(self.input, r.off as u64 + 8 * k, 8, self.src_msb).unwrap_or(0) as u8
            }
            SRC_PLAN => self.plan.byte(r.off as u64 + i as u64).unwrap_or(0),
            SRC_TEXT => self.texts.get(r.off as usize).and_then(|t| t.get(i as usize)).copied().unwrap_or(0),
            _ => match self.context.get(r.off as usize) {
                Some((_, Value::Str(t))) => t.get(i as usize).copied().unwrap_or(0),
                _ => 0,
            },
        }
    }

    fn text_eq(&self, a: TextRef, b: TextRef) -> bool {
        a.len == b.len && (0..a.len).all(|i| self.text_at(a, i) == self.text_at(b, i))
    }

    fn plan_text(word: u64) -> TextRef {
        TextRef { src: SRC_PLAN, len: (word >> 32) as u16, room: 0, off: word as u32 }
    }

    fn typed(ty: u8, word: u64) -> Val {
        match ty {
            T_INT => Val::Int(word as i64),
            T_FLOAT => Val::Float(f64::from_bits(word)),
            _ => Val::Str(Self::plan_text(word)),
        }
    }

    fn same(&self, ty: u8, word: u64, v: Val) -> bool {
        match (ty, v) {
            (T_INT, Val::Int(n)) => n == word as i64,
            (T_FLOAT, Val::Float(x)) => x == f64::from_bits(word),
            (T_STR, Val::Str(t)) => self.text_eq(t, Self::plan_text(word)),
            _ => false,
        }
    }

    // -- value tables -------------------------------------------------------

    /// A value through a table: wire to model (`decode`) or model to wire.
    /// None: the table refuses the value. A value with no entry passes
    /// through when the two sides have one type (engine-spec 0.6).
    fn through(&self, table: u16, v: Val, decode: bool) -> Result<Option<Val>, Error> {
        if table == NONE16 {
            return Ok(Some(v));
        }
        let t = self.plan.table(table)?;
        let (from_ty, to_ty, use_bit, from_ok, to_ok) =
            if decode { (t.native_ty, t.model_ty, 4, 1, 2) } else { (t.model_ty, t.native_ty, 8, 2, 1) };
        for i in 0..t.n as u32 {
            let at = t.first.checked_add(i * 3).ok_or(Error::BadPlan)?;
            let flags = self.plan.pool(at)?;
            if flags & use_bit == 0 || flags & from_ok == 0 {
                continue;
            }
            let (native, model) = (self.plan.pool(at + 1)?, self.plan.pool(at + 2)?);
            let (from, to) = if decode { (native, model) } else { (model, native) };
            if self.same(from_ty, from, v) {
                return Ok(if flags & to_ok != 0 { Some(Self::typed(to_ty, to)) } else { None });
            }
        }
        Ok(if from_ty == to_ty { Some(v) } else { None })
    }

    /// One line whose bits are in the input: the transform's result, through
    /// the table. The key takes the value of the earliest line that succeeds;
    /// a table that refuses a value fails the decode (rulings 4 and 5 of 0.6).
    fn put(&mut self, scope: u16, key: u16, table: u16, v: Option<Val>) -> Result<(), Error> {
        match self.val(scope, key) {
            None | Some(Val::Failed) => {}
            Some(_) => return Ok(()),
        }
        let val = match v {
            None => Val::Failed,
            Some(v) => self.through(table, v, true)?.unwrap_or(Val::Hard),
        };
        self.set(scope, key, val)
    }

    // -- one field ----------------------------------------------------------

    fn scale(&self, o: &Op) -> Result<(f64, f64, f64), Error> {
        let b = o.b as u32;
        Ok((
            f64::from_bits(self.plan.pool(b)?),
            f64::from_bits(self.plan.pool(b + 1)?),
            f64::from_bits(self.plan.pool(b + 2)?),
        ))
    }

    /// The pool index of a field's first sentinel: after its scale, when it
    /// has one (FORMAT.md, FIELD).
    fn sentinels(o: &Op) -> u32 {
        o.b as u32 + if matches!(o.xf, XF_LINSCALE | XF_USCALE | XF_SSCALE) { 3 } else { 0 }
    }

    /// Do the field's bits at `start` hold one of its sentinels? The bits
    /// read as `uint` reads them, after `swap`, before `trim`, the table and
    /// the transform (engine-spec 0.9, ruling 2). The caller has checked the
    /// bits are in the input.
    fn is_sentinel(&self, o: &Op, start: u64) -> Result<bool, Error> {
        let len = o.len as u32;
        if o.nabsent == 0 || len == 0 || len > 64 {
            return Ok(false);
        }
        let mut raw = get_bits(self.input, start, len, self.src_msb).unwrap_or(0);
        if o.flags & F_SWAP != 0 {
            raw = swap_bytes(raw, len);
        }
        let first = Self::sentinels(o);
        for k in 0..o.nabsent as u32 {
            if self.plan.pool(first + k)? == raw {
                return Ok(true);
            }
        }
        Ok(false)
    }

    /// Write the first sentinel of a field into its bits at `start`: the low
    /// `len` bits, then `swap` (engine-spec 0.9, Encode). Nothing when the
    /// field has none.
    fn write_sentinel(&self, o: &Op, start: u64, out: &mut [u8], msb: bool) -> Result<(), Error> {
        let len = o.len as u32;
        if o.nabsent == 0 || len == 0 || len > 64 {
            return Ok(());
        }
        let mut raw = self.plan.pool(Self::sentinels(o))? & mask(len);
        if o.flags & F_SWAP != 0 {
            raw = swap_bytes(raw, len);
        }
        set_bits(out, start, len, raw, msb);
        Ok(())
    }

    /// The value of a field whose bits start at `start`. None: the transform
    /// refuses the bits. The caller has checked the bits are in the input.
    fn read_field(&self, o: &Op, start: u64) -> Result<Option<Val>, Error> {
        let len = o.len as u32;
        let msb = self.src_msb;
        if o.xf == XF_ASCII {
            if len % 8 != 0 || start > u32::MAX as u64 {
                return Err(Error::BadPlan);
            }
            let room = (len / 8) as u16;
            let src = if o.flags & F_SWAP != 0 { SRC_INPUT_REV } else { SRC_INPUT };
            let mut t = TextRef { src, len: room, room, off: start as u32 };
            while t.len > 0 && self.text_at(t, t.len - 1) == 0 {
                t.len -= 1;
            }
            while o.flags & F_TRIM != 0 && t.len > 0 && self.text_at(t, t.len - 1) == 0x20 {
                t.len -= 1;
            }
            let printable = (0..t.len).all(|i| (0x20..=0x7e).contains(&self.text_at(t, i)));
            return Ok(if printable { Some(Val::Str(t)) } else { None });
        }
        if len == 0 || len > 64 {
            return Err(Error::BadPlan);
        }
        let mut raw = get_bits(self.input, start, len, msb).unwrap_or(0);
        if o.flags & F_SWAP != 0 {
            raw = swap_bytes(raw, len);
        }
        Ok(match o.xf {
            XF_UINT => Some(Val::Int(raw as i64)),
            XF_TWOS => Some(Val::Int(signed(raw, len))),
            XF_LINSCALE => {
                let (maxpos, range, _) = self.scale(o)?;
                Some(Val::Float(signed(raw, len) as f64 / maxpos * range))
            }
            XF_USCALE | XF_SSCALE => {
                let (n, d, off) = self.scale(o)?;
                let v = if o.xf == XF_USCALE { raw as f64 } else { signed(raw, len) as f64 };
                // ruling 1 of 0.5: v * num / den, then + offset
                Some(Val::Float(if d != 0.0 { v * n / d + off } else { v * n + off }))
            }
            XF_F32 => {
                let x = f32::from_bits(raw as u32) as f64;
                if num::is_finite(x) {
                    Some(Val::Float(x))
                } else {
                    None
                }
            }
            XF_F64 => {
                let x = f64::from_bits(raw);
                if num::is_finite(x) {
                    Some(Val::Float(x))
                } else {
                    None
                }
            }
            _ => return Err(Error::BadPlan),
        })
    }

    /// Write the wire value of a field into its bits at `start`.
    fn write_field(&self, o: &Op, v: Val, start: u64, out: &mut [u8], msb: bool) -> Result<(), Error> {
        let len = o.len as u32;
        let fail = Error::TransformEncode;
        if o.xf == XF_ASCII {
            let t = match v {
                Val::Str(t) => t,
                _ => return Err(fail),
            };
            let room = (len / 8) as u16;
            // ruling 19 of 0.5
            if t.len > room || !(0..t.len).all(|i| (0x20..=0x7e).contains(&self.text_at(t, i))) {
                return Err(fail);
            }
            for k in 0..room {
                let at = if o.flags & F_SWAP != 0 { room - 1 - k } else { k };
                set_bits(out, start + at as u64 * 8, 8, self.text_at(t, k) as u64, msb);
            }
            return Ok(());
        }
        if len == 0 || len > 64 {
            return Err(Error::BadPlan);
        }
        let m = mask(len);
        // ruling 4b of engine-spec 0.11: a value outside the field's range is
        // refused, never wrapped; `uint` of 64 bits takes every integer
        let mut raw = match (o.xf, v) {
            (XF_UINT, Val::Int(n)) if len == 64 => n as u64,
            (XF_UINT, Val::Int(n)) => {
                if n < 0 || n as u64 > m {
                    return Err(fail);
                }
                n as u64
            }
            (XF_TWOS, Val::Int(n)) => {
                let half = 1i128 << (len - 1);
                if (n as i128) < -half || (n as i128) >= half {
                    return Err(fail);
                }
                n as u64 & m
            }
            (XF_LINSCALE, Val::Float(x)) => {
                let (maxpos, range, _) = self.scale(o)?;
                let r = num::round(x / range * maxpos);
                let half = num::two_pow(len - 1);
                // NaN and the infinities fail the comparison
                if !(r >= -half && r < half) {
                    return Err(fail);
                }
                (r as i64) as u64 & m
            }
            (XF_USCALE | XF_SSCALE, Val::Float(x)) => {
                let (n, d, off) = self.scale(o)?;
                // ruling 1 of 0.5: (x - offset) * den / num, or (x - offset) / factor
                let r = num::round(if d != 0.0 { (x - off) * d / n } else { (x - off) / n });
                if o.xf == XF_USCALE {
                    if !(r >= 0.0 && r < num::two_pow(len)) {
                        return Err(fail);
                    }
                    r as u64
                } else {
                    let half = num::two_pow(len - 1);
                    if !(r >= -half && r < half) {
                        return Err(fail);
                    }
                    (r as i64) as u64 & m
                }
            }
            (XF_F32, Val::Float(x)) => {
                let y = x as f32;
                if !num::is_finite(y as f64) {
                    return Err(fail);
                }
                y.to_bits() as u64
            }
            (XF_F64, Val::Float(x)) => {
                if !num::is_finite(x) {
                    return Err(fail);
                }
                x.to_bits()
            }
            (XF_UINT..=XF_F64, _) => return Err(fail),
            _ => return Err(Error::BadPlan),
        };
        if o.flags & F_SWAP != 0 {
            raw = swap_bytes(raw, len);
        }
        set_bits(out, start, len, raw, msb);
        Ok(())
    }

    // -- the shape of a body --------------------------------------------------

    fn body_info(&self, body: u32) -> Result<BodyInfo, Error> {
        let plan = self.plan;
        let b = plan.op(body)?;
        if b.op != OP_BODY {
            return Err(Error::BadPlan);
        }
        let end = plan.next(body, &b)?;
        let mut lines = body + 1;
        while lines < end && plan.op(lines)?.op == OP_DEFAULT {
            lines += 1;
        }
        let mut first_kind = lines;
        while first_kind < end {
            let o = plan.op(first_kind)?;
            if o.op == OP_KIND {
                break;
            }
            first_kind = plan.next(first_kind, &o)?;
        }
        Ok(BodyInfo { lines, first_kind, end, extent: b.b })
    }

    fn kind_info(&self, k: u32) -> Result<KindInfo, Error> {
        let plan = self.plan;
        let o = plan.op(k)?;
        if o.op != OP_KIND {
            return Err(Error::BadPlan);
        }
        let end = plan.next(k, &o)?;
        let mut lines = k + 1;
        while lines < end && matches!(plan.op(lines)?.op, OP_WHEN | OP_REQ | OP_DEFAULT) {
            lines += 1;
        }
        Ok(KindInfo { whens: k + 1, lines, end, ordinal: o.key, excluded: o.flags & 1 != 0, extent: o.b })
    }

    /// The value encode uses for a key: the entity's, else the `default` of
    /// the selected kind, else of the body (ruling 2 of 0.6).
    fn value_of(&self, scope: u16, key: u16, defs: Defs) -> Result<Option<Val>, Error> {
        if let Some(v) = self.scalar(scope, key) {
            return Ok(Some(v));
        }
        let plan = self.plan;
        for start in [defs.kind, defs.body] {
            if start == NONE32 {
                continue;
            }
            let head = plan.op(start)?;
            let end = plan.next(start, &head)?;
            let mut i = start + 1;
            while i < end {
                let o = plan.op(i)?;
                match o.op {
                    OP_DEFAULT if o.key == key => return Ok(Some(Self::typed(o.xf, plan.pool(o.b as u32)?))),
                    OP_DEFAULT | OP_WHEN | OP_REQ => i += 1,
                    _ => break,
                }
            }
        }
        Ok(None)
    }

    /// The kind an entity, or an item, is written as: its own when it was
    /// decoded from this format, else the first whose `requires` keys are all
    /// present. An item whose own kind the group does not have is selected by
    /// `requires` (ruling 26 of 0.8). NONE32: the body has no kinds.
    fn select(&self, body: &BodyInfo, scope: u16) -> Result<u32, Error> {
        if body.first_kind == body.end {
            return Ok(NONE32);
        }
        let plan = self.plan;
        let mut own = if plan.same && self.decoded { self.scope_kind(scope) } else { NONE16 };
        if own != NONE16 && scope != 0 {
            let mut k = body.first_kind;
            let mut found = false;
            while k < body.end {
                let ki = self.kind_info(k)?;
                found |= ki.ordinal == own;
                k = ki.end;
            }
            if !found {
                own = NONE16;
            }
        }
        let mut k = body.first_kind;
        while k < body.end {
            let ki = self.kind_info(k)?;
            let chosen = if own != NONE16 {
                ki.ordinal == own
            } else {
                let mut all = true;
                for r in ki.whens..ki.lines {
                    let o = plan.op(r)?;
                    if o.op == OP_REQ && !self.has(scope, o.key) {
                        all = false;
                    }
                }
                all
            };
            if chosen {
                // a kind the plan was compiled without
                return if ki.excluded { Err(Error::NoKind) } else { Ok(k) };
            }
            k = ki.end;
        }
        Err(Error::NoKind)
    }

    // -- fixed layout: decode -------------------------------------------------

    fn extent(&self, at: u16) -> Result<(u64, u64, u64), Error> {
        let at = at as u32;
        Ok((self.plan.pool(at)?, self.plan.pool(at + 1)?, self.plan.pool(at + 2)?))
    }

    fn fx_decode(&mut self, fmt: &Format) -> Result<(), Error> {
        let plan = self.plan;
        let input = self.input;
        let msb = fmt.msb;
        let body = self.body_info(fmt.body)?;
        let holds = |o: &Op| -> Result<bool, Error> {
            Ok(get_bits(input, o.a as u64, o.len as u32, msb) == Some(plan.pool(o.b as u32)?))
        };
        let (mut reach0, mut need) = {
            let e = self.extent(body.extent)?;
            (e.0, e.1)
        };
        let mut kind_lines = (0u32, 0u32);
        if body.first_kind != body.end {
            // a common `when` must hold for any message of the format
            let mut i = body.lines;
            while i < body.first_kind {
                let o = plan.op(i)?;
                if o.op == OP_WHEN && !holds(&o)? {
                    return Err(Error::NoKind);
                }
                i = plan.next(i, &o)?;
            }
            let mut k = body.first_kind;
            let mut found = false;
            while k < body.end {
                let ki = self.kind_info(k)?;
                let mut all = true;
                for w in ki.whens..ki.lines {
                    let o = plan.op(w)?;
                    if o.op == OP_WHEN && !holds(&o)? {
                        all = false;
                        break;
                    }
                }
                if all {
                    if ki.excluded {
                        return Err(Error::NoKind);
                    }
                    let e = self.extent(ki.extent)?;
                    reach0 = reach0.max(e.0);
                    need = need.max(e.1);
                    kind_lines = (ki.lines, ki.end);
                    self.kind = ki.ordinal;
                    found = true;
                    break;
                }
                k = ki.end;
            }
            if !found {
                return Err(Error::NoKind);
            }
        }
        // whole words up to the furthest mapped, `when` or `const` bit
        let need = words(need, fmt.word_bytes).max(fmt.word_bytes as u64);
        if (input.len() as u64) < need {
            return Err(Error::MalformedWire);
        }
        let mut reach = 0u64;
        self.fx_decode_scope([(body.lines, body.first_kind), kind_lines], reach0, 0, 0, &mut reach, 1)?;
        // and up to the furthest bit read, the items of every group included
        if (input.len() as u64) < words(reach, fmt.word_bytes) {
            return Err(Error::MalformedWire);
        }
        Ok(())
    }

    /// Decode the fields and groups of one scope: the message (`base` 0) or
    /// one item, whose first bit is `base`. Returns where its groups end.
    fn fx_decode_scope(
        &mut self,
        parts: [(u32, u32); 2],
        static_reach: u64,
        base: u64,
        scope: u16,
        reach: &mut u64,
        depth: u8,
    ) -> Result<u64, Error> {
        if depth > MAX_DEPTH {
            return Err(Error::BadPlan);
        }
        let plan = self.plan;
        let total = self.input.len() as u64 * 8;
        // every field that is not `optional` lies inside the input
        let must = base.checked_add(static_reach).ok_or(Error::MalformedWire)?;
        if must > total {
            return Err(Error::MalformedWire);
        }
        *reach = (*reach).max(must);
        for (start, end) in parts {
            let mut i = start;
            while i < end {
                let o = plan.op(i)?;
                if o.op == OP_FIELD {
                    let at = base + o.a as u64;
                    // an `optional` field beyond the input is absent
                    if at + o.len as u64 <= total {
                        // a sentinel: the line yields no value (engine-spec 0.9)
                        if !self.is_sentinel(&o, at)? {
                            let v = self.read_field(&o, at)?;
                            self.put(scope, o.key, o.c, v)?;
                        }
                    } else if o.flags & F_OPTIONAL == 0 {
                        return Err(Error::MalformedWire);
                    }
                }
                i = plan.next(i, &o)?;
            }
        }
        let mut groups_end = 0u64;
        for (start, end) in parts {
            let mut i = start;
            while i < end {
                let o = plan.op(i)?;
                let next = plan.next(i, &o)?;
                if o.op == OP_GROUP_FIX {
                    let item_bits = plan.pool(o.b as u32)?;
                    let second = plan.pool(o.b as u32 + 1)?;
                    let n = if o.xf == 0 {
                        second
                    } else {
                        let at = base.checked_add(second).ok_or(Error::BadPlan)?;
                        *reach = (*reach).max(at + o.len as u64);
                        get_bits(self.input, at, o.len as u32, self.src_msb).ok_or(Error::MalformedWire)?
                    };
                    // the count against what the limit still allows (7d)
                    self.replacing(scope, o.key);
                    self.take_items(n)?;
                    let first = base + o.a as u64;
                    let all = n.checked_mul(item_bits).and_then(|b| b.checked_add(first));
                    match all {
                        Some(e) if e <= total => *reach = (*reach).max(e),
                        _ => return Err(Error::MalformedWire),
                    }
                    let body = self.body_info(i + 1)?;
                    let body_reach = self.extent(body.extent)?.0;
                    let discard = o.flags & 1 != 0;
                    let mut at = first;
                    let mut count: u16 = 0;
                    for _ in 0..n {
                        if at + item_bits > total {
                            return Err(Error::MalformedWire);
                        }
                        let mark = (self.nslots, self.nscopes);
                        let item = self.new_scope(scope, o.key, count)?;
                        // an item is `item <bits>` long, or ends where a nested
                        // group counted by a locator ends (ruling 4 of 0.7)
                        let nested =
                            self.fx_decode_scope([(body.lines, body.end), (0, 0)], body_reach, at, item, reach, depth + 1)?;
                        at = (at + item_bits).max(nested);
                        if discard {
                            self.drop_item(mark);
                        }
                        count = count.checked_add(1).ok_or(Error::ScratchFull)?;
                    }
                    *reach = (*reach).max(at);
                    groups_end = groups_end.max(at);
                    if !discard {
                        self.set(scope, o.key, Val::List(count))?;
                    }
                }
                i = next;
            }
        }
        Ok(groups_end)
    }

    /// Forget an item the target cannot hold, keeping only whether it failed.
    fn drop_item(&mut self, mark: (usize, usize)) {
        if let Some(s) = self.slots.get(mark.0..self.nslots) {
            if s.iter().any(|s| matches!(s.val, Val::Failed | Val::Hard)) {
                self.failed = true;
            }
        }
        self.nslots = mark.0;
        self.nscopes = mark.1;
    }

    // -- fixed layout: encode -------------------------------------------------

    /// The bits one item takes: `item <bits>`, or up to the end of a nested
    /// group counted by a locator, when that is further.
    fn fx_item_len(&self, group: u32, o: &Op, item: u16, depth: u8) -> Result<u64, Error> {
        let item_bits = self.plan.pool(o.b as u32)?;
        let body = self.body_info(group + 1)?;
        Ok(item_bits.max(self.fx_group_reach([(body.lines, body.end), (0, 0)], item, 0, depth + 1)?))
    }

    /// The furthest bit the groups of a scope write.
    fn fx_group_reach(&self, parts: [(u32, u32); 2], scope: u16, base: u64, depth: u8) -> Result<u64, Error> {
        if depth > MAX_DEPTH {
            return Err(Error::BadPlan);
        }
        let plan = self.plan;
        let mut end = 0u64;
        for (start, stop) in parts {
            let mut i = start;
            while i < stop {
                let o = plan.op(i)?;
                if o.op == OP_GROUP_FIX {
                    if o.xf != 0 {
                        end = end.max(base + plan.pool(o.b as u32 + 1)? + o.len as u64);
                    }
                    if let Some(n) = self.list_len(scope, o.key) {
                        let mut at = base + o.a as u64;
                        for k in 0..n {
                            let item = self.item(scope, o.key, k).ok_or(Error::BadPlan)?;
                            at = at.checked_add(self.fx_item_len(i, &o, item, depth)?).ok_or(Error::OutputFull)?;
                        }
                        end = end.max(at);
                    }
                }
                i = plan.next(i, &o)?;
            }
        }
        Ok(end)
    }

    fn fx_encode(&mut self, fmt: &Format, out: &mut [u8]) -> Result<usize, Error> {
        let body = self.body_info(fmt.body)?;
        let kind = self.select(&body, 0)?;
        let mut need = self.extent(body.extent)?.2;
        let mut kind_lines = (0u32, 0u32);
        if kind != NONE32 {
            let ki = self.kind_info(kind)?;
            need = need.max(self.extent(ki.extent)?.2);
            kind_lines = (ki.whens, ki.end);
        }
        let parts = [(body.lines, body.first_kind), kind_lines];
        // whole words up to the furthest bit: the lines in force, extended by the items
        let items = words(self.fx_group_reach(parts, 0, 0, 1)?, fmt.word_bytes);
        let size = words(need, fmt.word_bytes).max(fmt.word_bytes as u64).max(items);
        let size = usize::try_from(size).map_err(|_| Error::OutputFull)?;
        let msg = out.get_mut(..size).ok_or(Error::OutputFull)?;
        msg.fill(0);
        self.fx_write_scope(parts, Defs { body: fmt.body, kind }, 0, 0, msg, fmt.msb, 1)?;
        Ok(size)
    }

    fn fx_write_scope(
        &self,
        parts: [(u32, u32); 2],
        defs: Defs,
        scope: u16,
        base: u64,
        msg: &mut [u8],
        msb: bool,
        depth: u8,
    ) -> Result<(), Error> {
        if depth > MAX_DEPTH {
            return Err(Error::BadPlan);
        }
        let plan = self.plan;
        // The compiler puts the fields of a part first, one operation each.
        // (first, last) of the fields of each part, the kind's part first;
        // no indexing, so no bounds check reaches the image
        let span = |(start, end): (u32, u32)| -> Result<(u32, u32), Error> {
            let mut first = start;
            while first < end && matches!(plan.op(first)?.op, OP_WHEN | OP_REQ | OP_DEFAULT) {
                first += 1;
            }
            let mut last = first;
            while last < end && plan.op(last)?.op == OP_FIELD {
                last += 1;
            }
            Ok((first, last))
        };
        let fields = [span(parts[1])?, span(parts[0])?];
        // an absent key whose field has `absent` writes its first sentinel,
        // first: a line with a value wins over it whatever their order
        // (ruling 16 of 0.9); of two sentinels the earlier line's stays
        for (first, last) in fields {
            let mut i = last;
            while i > first {
                i -= 1;
                let o = plan.op(i)?;
                if o.nabsent != 0 && self.value_of(scope, o.key, defs)?.is_none() {
                    self.write_sentinel(&o, base + o.a as u64, msg, msb)?;
                }
            }
        }
        // later lines first: where two fields cover the same bits the earlier
        // line's value is the one left on the wire (ruling 5 of 0.5)
        for (first, last) in fields {
            let mut i = last;
            while i > first {
                i -= 1;
                let o = plan.op(i)?;
                if let Some(v) = self.value_of(scope, o.key, defs)? {
                    let wire = self.through(o.c, v, false)?.ok_or(Error::TransformEncode)?;
                    self.write_field(&o, wire, base + o.a as u64, msg, msb)?;
                }
            }
        }
        // the items of each list the entity has, back to back
        for (start, end) in parts {
            let mut i = start;
            while i < end {
                let o = plan.op(i)?;
                if o.op == OP_GROUP_FIX {
                    match self.list_len(scope, o.key) {
                        Some(n) => {
                            let body = self.body_info(i + 1)?;
                            let mut at = base + o.a as u64;
                            for k in 0..n {
                                let item = self.item(scope, o.key, k).ok_or(Error::BadPlan)?;
                                self.fx_write_scope(
                                    [(body.lines, body.end), (0, 0)],
                                    Defs { body: i + 1, kind: NONE32 },
                                    item,
                                    at,
                                    msg,
                                    msb,
                                    depth + 1,
                                )?;
                                at += self.fx_item_len(i, &o, item, depth)?;
                            }
                            // a fixed `count <n>` with a different number of items
                            if o.xf == 0 && plan.pool(o.b as u32 + 1)? != n as u64 {
                                return Err(Error::TransformEncode);
                            }
                        }
                        // an absent list under a fixed count (ruling 5 of 0.7); under a
                        // count locator it writes a count of 0 (ruling 14 of 0.7)
                        None if o.xf == 0 => return Err(Error::TransformEncode),
                        None => {}
                    }
                }
                i = plan.next(i, &o)?;
            }
        }
        // over the same bits: fields, then `const`, then `when`, then counts (ruling 15 of 0.7)
        for which in [OP_CONST, OP_WHEN] {
            for (start, end) in parts {
                let mut i = start;
                while i < end {
                    let o = plan.op(i)?;
                    if o.op == which {
                        set_bits(msg, base + o.a as u64, o.len as u32, plan.pool(o.b as u32)?, msb);
                    }
                    i = plan.next(i, &o)?;
                }
            }
        }
        for (start, end) in parts {
            let mut i = start;
            while i < end {
                let o = plan.op(i)?;
                if o.op == OP_GROUP_FIX && o.xf != 0 {
                    let n = self.list_len(scope, o.key).unwrap_or(0) as u64;
                    if o.len < 64 && n >> o.len != 0 {
                        return Err(Error::TransformEncode);
                    }
                    set_bits(msg, base + plan.pool(o.b as u32 + 1)?, o.len as u32, n, msb);
                }
                i = plan.next(i, &o)?;
            }
        }
        Ok(())
    }

    // -- sequential layout: decode --------------------------------------------

    fn need(&self, len: u64) -> Result<(), Error> {
        match self.pos.checked_add(len) {
            Some(e) if e <= self.end => Ok(()),
            _ => Err(Error::MalformedWire),
        }
    }

    /// `len` (1..=64) bits at the cursor as an unsigned value.
    fn read(&mut self, len: u32) -> Result<u64, Error> {
        if len == 0 || len > 64 {
            return Err(Error::BadPlan);
        }
        self.need(len as u64)?;
        let v = get_bits(self.input, self.pos, len, self.src_msb).unwrap_or(0);
        self.pos += len as u64;
        Ok(v)
    }

    /// The indicator bit of a `while`, `more` or `fx` group, or an `fx` bit
    /// of a chain. At or after the end of a `length` extent it reads as 0
    /// (ruling 21 of 0.8); past the end of the input it is `malformed-wire`.
    fn indicator(&mut self) -> Result<u64, Error> {
        if self.extents > 0 && self.pos >= self.end {
            return Ok(0);
        }
        self.read(1)
    }

    fn presence_slot(&mut self, id: u16) -> Result<&mut u64, Error> {
        self.presence.get_mut(id as usize).ok_or(Error::BadPlan)
    }

    /// Do the conditions of an `if` hold against the presence bits read, or written, so far?
    fn conds_hold(&self, o: &Op) -> Result<bool, Error> {
        for c in 0..o.len as u32 {
            let (id, bit, neg) = self.plan.cond(o.b as u32 + c)?;
            if bit == 0 || bit > 64 {
                return Err(Error::BadPlan);
            }
            let set = self.presence.get(id as usize).ok_or(Error::BadPlan)? >> (bit - 1) & 1 != 0;
            if set == neg {
                return Ok(false);
            }
        }
        Ok(true)
    }

    /// The common lines of a body, then the lines of the kind the wire
    /// selects. Returns the kind's number (FORMAT.md, KIND), or NONE16.
    fn sq_decode_body(&mut self, body: u32, scope: u16, depth: u8) -> Result<u16, Error> {
        let plan = self.plan;
        let b = self.body_info(body)?;
        self.sq_decode_lines(b.lines, b.first_kind, scope, depth)?;
        if b.first_kind == b.end {
            return Ok(NONE16);
        }
        let start = self.pos;
        let mut k = b.first_kind;
        while k < b.end {
            let ki = self.kind_info(k)?;
            let mut at = start;
            let mut holds = true;
            for w in ki.whens..ki.lines {
                let o = plan.op(w)?;
                if o.op != OP_WHEN {
                    continue;
                }
                // a `when` any of whose bits lies beyond the input does not hold
                let ok = at + o.len as u64 <= self.end
                    && get_bits(self.input, at, o.len as u32, self.src_msb) == Some(plan.pool(o.b as u32)?);
                at += o.len as u64;
                if !ok {
                    holds = false;
                    break;
                }
            }
            if holds {
                if ki.excluded {
                    return Err(Error::NoKind);
                }
                self.pos = at;
                self.sq_decode_lines(ki.lines, ki.end, scope, depth)?;
                return Ok(ki.ordinal);
            }
            k = ki.end;
        }
        Err(Error::NoKind)
    }

    fn sq_decode_lines(&mut self, start: u32, end: u32, scope: u16, depth: u8) -> Result<(), Error> {
        if depth > MAX_DEPTH {
            return Err(Error::BadPlan);
        }
        let plan = self.plan;
        let mut i = start;
        while i < end {
            let o = plan.op(i)?;
            let next = plan.next(i, &o)?;
            // inside a `length` block, lines beyond its extent read as absent (ruling 7 of 0.8)
            if self.extents > 0 && self.pos >= self.end {
                if o.op == OP_PRESENCE {
                    *self.presence_slot(o.key)? = 0;
                }
                i = next;
                continue;
            }
            match o.op {
                OP_FIELD => {
                    self.need(o.len as u64)?;
                    // a sentinel: neither the field's key nor an `also` key
                    // gets a value (engine-spec 0.9, ruling 24)
                    if self.is_sentinel(&o, self.pos)? {
                        self.pos += o.len as u64;
                        i = next;
                        continue;
                    }
                    let v = self.read_field(&o, self.pos)?;
                    self.pos += o.len as u64;
                    // an `also` key takes the same value through its own table
                    let mut j = i + 1;
                    while j < end {
                        let a = plan.op(j)?;
                        if a.op != OP_ALSO {
                            break;
                        }
                        self.put(scope, a.key, a.c, v)?;
                        j += 1;
                    }
                    self.put(scope, o.key, o.c, v)?;
                }
                OP_ALSO | OP_DEFAULT | OP_REQ => {}
                OP_CONST => {
                    self.read(o.len as u32)?;
                }
                OP_PAD => {
                    self.need(o.a as u64)?;
                    self.pos += o.a as u64;
                }
                OP_ALIGN => {
                    let n = o.a as u64;
                    if n == 0 {
                        return Err(Error::BadPlan);
                    }
                    // stops at the end of the input or extent without error (ruling 20 of 0.8)
                    let skip = (n - self.pos % n) % n;
                    self.pos = self.pos.saturating_add(skip).min(self.end.max(self.pos));
                }
                OP_WHEN => {
                    if self.pos + o.len as u64 > self.end || self.read(o.len as u32)? != plan.pool(o.b as u32)? {
                        return Err(Error::NoKind);
                    }
                }
                OP_PRESENCE => {
                    let named = plan.pool(o.b as u32)?;
                    let mut set = 0u64;
                    let mut stray = false;
                    let mut bit = 0u32;
                    if o.len != 0 {
                        self.need(o.len as u64)?;
                        for _ in 0..o.len {
                            if self.read(1)? == 1 {
                                if bit < 64 {
                                    set |= 1 << bit;
                                } else {
                                    stray = true;
                                }
                            }
                            bit += 1;
                        }
                    } else {
                        loop {
                            self.need(8)?;
                            for _ in 0..7 {
                                if self.read(1)? == 1 {
                                    if bit < 64 {
                                        set |= 1 << bit;
                                    } else {
                                        stray = true;
                                    }
                                }
                                bit = bit.saturating_add(1);
                            }
                            if self.read(1)? == 0 {
                                break;
                            }
                        }
                    }
                    // ruling 1 of 0.8: a bit that is 1 and that no `if` block names
                    if stray || set & !named != 0 {
                        return Err(Error::MalformedWire);
                    }
                    *self.presence_slot(o.key)? = set;
                }
                OP_IF => {
                    if self.conds_hold(&o)? {
                        self.sq_decode_lines(i + 1, next, scope, depth + 1)?;
                    }
                }
                OP_OPT => {
                    if self.read(1)? == 1 {
                        self.sq_decode_lines(i + 1, next, scope, depth + 1)?;
                    }
                }
                OP_CHAIN => {
                    let mut whole = true;
                    let mut p = i + 1;
                    while p < next {
                        let part = plan.op(p)?;
                        if part.op != OP_PART {
                            return Err(Error::BadPlan);
                        }
                        let after = plan.next(p, &part)?;
                        if p > i + 1 && self.indicator()? == 0 {
                            whole = false;
                            break;
                        }
                        self.sq_decode_lines(p + 1, after, scope, depth + 1)?;
                        p = after;
                    }
                    // ruling 3 of 0.8: the chain ends with an `fx` line and its bit is 1
                    if whole && o.flags & 1 != 0 && self.indicator()? == 1 {
                        return Err(Error::MalformedWire);
                    }
                }
                OP_LENGTH => {
                    let stated = self.stated(&o)?;
                    let unit = if o.flags & 1 != 0 { 1 } else { 8 };
                    let stop = stated
                        .checked_mul(unit)
                        .and_then(|e| self.pos.checked_add(e))
                        .filter(|s| *s <= self.end)
                        .ok_or(Error::MalformedWire)?;
                    let outer = core::mem::replace(&mut self.end, stop);
                    self.extents += 1;
                    let res = self.sq_decode_lines(i + 1, next, scope, depth + 1);
                    self.extents -= 1;
                    // content of the extent no line reads is skipped
                    self.pos = stop;
                    self.end = outer.min(self.whole);
                    res?;
                }
                OP_WHOLE => {
                    let bits = self.stated(&o)?.checked_mul(8).ok_or(Error::MalformedWire)?;
                    // ruling 8 of 0.8: a whole length is the end of the input
                    if bits > self.input.len() as u64 * 8 || bits < self.pos {
                        return Err(Error::MalformedWire);
                    }
                    self.whole = bits;
                    self.end = self.end.min(bits);
                }
                OP_GROUP_SEQ => {
                    let discard = o.flags & 1 != 0;
                    let mut count: u16 = 0;
                    self.replacing(scope, o.key);
                    match o.xf {
                        0 => {
                            let n = self.read(o.len as u32)?;
                            // the count against what the limit still allows (7d)
                            self.take_items(n)?;
                            // ruling 14 of 0.8: before any item is read
                            if n > self.end - self.pos {
                                return Err(Error::MalformedWire);
                            }
                            for _ in 0..n {
                                self.sq_decode_item(i + 1, scope, &o, &mut count, discard, depth)?;
                            }
                        }
                        1 => {
                            while self.indicator()? == 1 {
                                self.take_items(1)?;
                                self.sq_decode_item(i + 1, scope, &o, &mut count, discard, depth)?;
                            }
                        }
                        2 => loop {
                            let more = self.indicator()?;
                            self.take_items(1)?;
                            self.sq_decode_item(i + 1, scope, &o, &mut count, discard, depth)?;
                            if more == 0 {
                                break;
                            }
                        },
                        3 => loop {
                            self.take_items(1)?;
                            self.sq_decode_item(i + 1, scope, &o, &mut count, discard, depth)?;
                            if self.indicator()? == 0 {
                                break;
                            }
                        },
                        _ => return Err(Error::BadPlan),
                    }
                    if !discard {
                        self.set(scope, o.key, Val::List(count))?;
                    }
                }
                _ => return Err(Error::BadPlan),
            }
            i = next;
        }
        Ok(())
    }

    /// The value of a length field less its `plus`: never negative.
    fn stated(&mut self, o: &Op) -> Result<u64, Error> {
        let v = self.read(o.len as u32)?;
        let plus = self.plan.pool(o.b as u32)? as i64;
        // the compiler holds `plus` to 32 bits, so a value this large never fits the input
        let v = i64::try_from(v).map_err(|_| Error::MalformedWire)?;
        let stated = v.checked_sub(plus).ok_or(Error::MalformedWire)?;
        u64::try_from(stated).map_err(|_| Error::MalformedWire)
    }

    fn sq_decode_item(
        &mut self,
        body: u32,
        scope: u16,
        o: &Op,
        count: &mut u16,
        discard: bool,
        depth: u8,
    ) -> Result<(), Error> {
        let mark = (self.nslots, self.nscopes);
        let item = self.new_scope(scope, o.key, *count)?;
        let kind = self.sq_decode_body(body, item, depth + 1)?;
        if let Some(s) = self.scopes.get_mut(item as usize - 1) {
            s.kind = kind;
        }
        if discard {
            self.drop_item(mark);
        }
        *count = count.checked_add(1).ok_or(Error::ScratchFull)?;
        Ok(())
    }

    // -- sequential layout: encode --------------------------------------------

    /// The value a field writes, with its key's table: the earliest of the
    /// field's keys (its own, then its `also` keys) that the entity holds;
    /// when it holds none, the default of the earliest key that has one
    /// (rulings 13 and 16 of 0.8).
    fn field_value(&self, i: u32, end: u32, o: &Op, scope: u16, defs: Defs) -> Result<Option<(Val, u16)>, Error> {
        for held in [true, false] {
            let mut key = (o.key, o.c);
            let mut j = i + 1;
            loop {
                let v = if held { self.scalar(scope, key.0) } else { self.value_of(scope, key.0, defs)? };
                if let Some(v) = v {
                    return Ok(Some((v, key.1)));
                }
                if j >= end {
                    break;
                }
                let a = self.plan.op(j)?;
                if a.op != OP_ALSO {
                    break;
                }
                key = (a.key, a.c);
                j += 1;
            }
        }
        Ok(None)
    }

    /// Would these lines write a present key or a non-empty list? A key with
    /// a `default` in scope counts as present (ruling 2 of 0.8).
    fn content(&self, start: u32, end: u32, scope: u16, defs: Defs, depth: u8) -> Result<bool, Error> {
        if depth > MAX_DEPTH {
            return Err(Error::BadPlan);
        }
        let plan = self.plan;
        let mut i = start;
        while i < end {
            let o = plan.op(i)?;
            let next = plan.next(i, &o)?;
            let yes = match o.op {
                OP_FIELD | OP_ALSO => self.value_of(scope, o.key, defs)?.is_some(),
                OP_GROUP_SEQ => self.list_len(scope, o.key).is_some_and(|n| n > 0),
                OP_IF | OP_OPT | OP_LENGTH | OP_CHAIN | OP_PART => self.content(i + 1, next, scope, defs, depth + 1)?,
                _ => false,
            };
            if yes {
                return Ok(true);
            }
            i = next;
        }
        Ok(false)
    }

    /// The bits of presence `id`: bit i is 1 when some `if` block naming it
    /// without `!` would write a present key or a non-empty list.
    fn presence_bits(
        &self,
        start: u32,
        end: u32,
        scope: u16,
        defs: Defs,
        id: u16,
        bits: &mut u64,
        depth: u8,
    ) -> Result<(), Error> {
        if depth > MAX_DEPTH {
            return Err(Error::BadPlan);
        }
        let plan = self.plan;
        let mut i = start;
        while i < end {
            let o = plan.op(i)?;
            let next = plan.next(i, &o)?;
            match o.op {
                OP_IF => {
                    if self.content(i + 1, next, scope, defs, depth + 1)? {
                        for c in 0..o.len as u32 {
                            let (cid, bit, neg) = plan.cond(o.b as u32 + c)?;
                            if bit == 0 || bit > 64 {
                                return Err(Error::BadPlan);
                            }
                            if cid == id && !neg {
                                *bits |= 1 << (bit - 1);
                            }
                        }
                    }
                    self.presence_bits(i + 1, next, scope, defs, id, bits, depth + 1)?;
                }
                OP_OPT | OP_LENGTH | OP_CHAIN | OP_PART => {
                    self.presence_bits(i + 1, next, scope, defs, id, bits, depth + 1)?
                }
                OP_GROUP_SEQ => {
                    // a message presence may be named inside an item (ruling 12 of 0.8)
                    let body = self.body_info(i + 1)?;
                    for k in 0..self.list_len(scope, o.key).unwrap_or(0) {
                        let item = self.item(scope, o.key, k).ok_or(Error::BadPlan)?;
                        let kind = self.select(&body, item).unwrap_or(NONE32);
                        let item_defs = Defs { body: i + 1, kind };
                        self.presence_bits(body.lines, body.first_kind, item, item_defs, id, bits, depth + 1)?;
                        if kind != NONE32 {
                            let ki = self.kind_info(kind)?;
                            self.presence_bits(ki.lines, ki.end, item, item_defs, id, bits, depth + 1)?;
                        }
                    }
                }
                _ => {}
            }
            i = next;
        }
        Ok(())
    }

    fn sq_encode_body(&mut self, body: u32, scope: u16, w: &mut Wr, depth: u8) -> Result<(), Error> {
        let plan = self.plan;
        let b = self.body_info(body)?;
        let kind = self.select(&b, scope)?;
        let defs = Defs { body, kind };
        if kind == NONE32 {
            return self.sq_encode_lines(b.lines, b.first_kind, (0, 0), scope, defs, w, depth);
        }
        let ki = self.kind_info(kind)?;
        // a presence among the common lines is visible in the kind's lines
        self.sq_encode_lines(b.lines, b.first_kind, (ki.lines, ki.end), scope, defs, w, depth)?;
        for i in ki.whens..ki.lines {
            let o = plan.op(i)?;
            if o.op == OP_WHEN {
                w.put(o.len as u32, plan.pool(o.b as u32)?)?;
            }
        }
        self.sq_encode_lines(ki.lines, ki.end, (0, 0), scope, defs, w, depth)
    }

    /// Write lines. `tail`: the lines that follow them in the same scope,
    /// which may name a presence declared here.
    #[allow(clippy::too_many_arguments)]
    fn sq_encode_lines(
        &mut self,
        start: u32,
        end: u32,
        tail: (u32, u32),
        scope: u16,
        defs: Defs,
        w: &mut Wr,
        depth: u8,
    ) -> Result<(), Error> {
        if depth > MAX_DEPTH {
            return Err(Error::BadPlan);
        }
        let plan = self.plan;
        let fail = Error::TransformEncode;
        let mut i = start;
        while i < end {
            let o = plan.op(i)?;
            let next = plan.next(i, &o)?;
            match o.op {
                OP_FIELD => {
                    let value = self.field_value(i, end, &o, scope, defs)?;
                    let at = w.pos;
                    // an absent key writes zero bits
                    w.zeros(o.len as u64)?;
                    match value {
                        Some((v, table)) => {
                            let wire = self.through(table, v, false)?.ok_or(fail)?;
                            self.write_field(&o, wire, at, w.out, w.msb)?;
                        }
                        // with `absent`, the first sentinel in place of the zero bits (engine-spec 0.9)
                        None => self.write_sentinel(&o, at, w.out, w.msb)?,
                    }
                }
                OP_ALSO | OP_DEFAULT | OP_REQ => {}
                OP_CONST | OP_WHEN => w.put(o.len as u32, plan.pool(o.b as u32)?)?,
                OP_PAD => w.zeros(o.a as u64)?,
                OP_ALIGN => {
                    let n = o.a as u64;
                    if n == 0 {
                        return Err(Error::BadPlan);
                    }
                    w.zeros((n - w.pos % n) % n)?;
                }
                OP_PRESENCE => {
                    // presence is computed before it is written: the first of the two passes
                    let mut set = 0u64;
                    self.presence_bits(next, end, scope, defs, o.key, &mut set, depth + 1)?;
                    self.presence_bits(tail.0, tail.1, scope, defs, o.key, &mut set, depth + 1)?;
                    if o.len != 0 {
                        for k in 0..o.len as u32 {
                            w.put(1, if k < 64 { set >> k & 1 } else { 0 })?;
                        }
                    } else {
                        // trailing octets that are all zero are not written, and at least one octet is
                        let last = 64 - set.leading_zeros();
                        let octets = last.div_ceil(7).max(1);
                        for octet in 0..octets {
                            for k in 0..7 {
                                let bit = octet * 7 + k;
                                w.put(1, if bit < 64 { set >> bit & 1 } else { 0 })?;
                            }
                            w.put(1, (octet + 1 < octets) as u64)?;
                        }
                    }
                    *self.presence_slot(o.key)? = set;
                }
                OP_IF => {
                    if self.conds_hold(&o)? {
                        self.sq_encode_lines(i + 1, next, (0, 0), scope, defs, w, depth + 1)?;
                    }
                }
                OP_OPT => {
                    let present = self.content(i + 1, next, scope, defs, depth + 1)?;
                    w.put(1, present as u64)?;
                    if present {
                        self.sq_encode_lines(i + 1, next, (0, 0), scope, defs, w, depth + 1)?;
                    }
                }
                OP_CHAIN => {
                    let mut whole = true;
                    let mut p = i + 1;
                    while p < next {
                        let part = plan.op(p)?;
                        if part.op != OP_PART {
                            return Err(Error::BadPlan);
                        }
                        let after = plan.next(p, &part)?;
                        if p > i + 1 {
                            // 1 when any line after it in the chain would write a present key
                            let more = self.content(p, next, scope, defs, depth + 1)?;
                            w.put(1, more as u64)?;
                            if !more {
                                whole = false;
                                break;
                            }
                        }
                        self.sq_encode_lines(p + 1, after, (0, 0), scope, defs, w, depth + 1)?;
                        p = after;
                    }
                    if whole && o.flags & 1 != 0 {
                        w.put(1, 0)?;
                    }
                }
                OP_LENGTH => {
                    let at = w.pos;
                    w.zeros(o.len as u64)?;
                    let first = w.pos;
                    self.sq_encode_lines(i + 1, next, (0, 0), scope, defs, w, depth + 1)?;
                    let in_bits = o.flags & 1 != 0;
                    // a block counted in bytes is padded with zero bits to a whole byte
                    if !in_bits {
                        w.zeros((8 - (w.pos - first) % 8) % 8)?;
                    }
                    let size = (w.pos - first) / if in_bits { 1 } else { 8 };
                    let stated = (size as i64).checked_add(plan.pool(o.b as u32)? as i64).ok_or(fail)?;
                    if stated < 0 || (o.len < 64 && (stated as u64) >> o.len != 0) {
                        return Err(fail);
                    }
                    set_bits(w.out, at, o.len as u32, stated as u64, w.msb);
                }
                OP_WHOLE => {
                    let slot = w.wholes.get_mut(w.nwholes).ok_or(Error::BadPlan)?;
                    *slot = (w.pos, o.len, plan.pool(o.b as u32)? as i64);
                    w.nwholes += 1;
                    w.zeros(o.len as u64)?;
                }
                OP_GROUP_SEQ => {
                    let n = self.list_len(scope, o.key).unwrap_or(0);
                    match o.xf {
                        0 => {
                            // an absent list writes a count of 0 (ruling 14 of 0.7)
                            if o.len < 64 && (n as u64) >> o.len != 0 {
                                return Err(fail);
                            }
                            w.put(o.len as u32, n as u64)?;
                            for k in 0..n {
                                let item = self.item(scope, o.key, k).ok_or(Error::BadPlan)?;
                                self.sq_encode_body(i + 1, item, w, depth + 1)?;
                            }
                        }
                        1 => {
                            for k in 0..n {
                                let item = self.item(scope, o.key, k).ok_or(Error::BadPlan)?;
                                w.put(1, 1)?;
                                self.sq_encode_body(i + 1, item, w, depth + 1)?;
                            }
                            w.put(1, 0)?;
                        }
                        2 | 3 => {
                            // ruling 6 of 0.8
                            if n == 0 {
                                return Err(fail);
                            }
                            for k in 0..n {
                                let item = self.item(scope, o.key, k).ok_or(Error::BadPlan)?;
                                let more = (k + 1 < n) as u64;
                                if o.xf == 2 {
                                    w.put(1, more)?;
                                }
                                self.sq_encode_body(i + 1, item, w, depth + 1)?;
                                if o.xf == 3 {
                                    w.put(1, more)?;
                                }
                            }
                        }
                        _ => return Err(Error::BadPlan),
                    }
                }
                _ => return Err(Error::BadPlan),
            }
            i = next;
        }
        Ok(())
    }

    // -- derivations ----------------------------------------------------------

    fn derive(&self, d: &Derive) -> Result<Option<Val>, Error> {
        let plan = self.plan;
        let mut a = [Val::Failed; MAX_ARGS];
        let mut n = 0usize;
        if d.nargs as usize > MAX_ARGS {
            return Err(Error::BadPlan);
        }
        for i in 0..d.nargs as u32 {
            match self.scalar(0, plan.arg(d.args as u32 + i)?) {
                Some(v) => {
                    if let Some(slot) = a.get_mut(n) {
                        *slot = v;
                    }
                    n += 1;
                }
                // `any` is set when only some of its arguments are present
                None if d.func == 10 => {}
                None => return Ok(None),
            }
        }
        let a: &[Val] = a.get(..n).unwrap_or(&[]);
        let f = |i: usize| match a.get(i) {
            Some(Val::Float(x)) => *x,
            Some(Val::Int(n)) => *n as f64,
            _ => f64::NAN,
        };
        let int = |i: usize| match a.get(i) {
            Some(Val::Int(n)) => Some(*n),
            _ => None,
        };
        let pool = d.pool as u32;
        let x = match d.func {
            // copy
            0 => return Ok(a.first().copied()),
            #[cfg(feature = "sqrt")]
            1 => num::sqrt(f(0) * f(0) + f(1) * f(1)),
            #[cfg(feature = "trig")]
            2 => {
                if f(0) == 0.0 && f(1) == 0.0 {
                    return Ok(None);
                }
                // ruling 1 of 0.6: times 180/pi, the quotient computed first
                let mut deg = num::atan2(f(0), f(1)) * (180.0 / core::f64::consts::PI);
                if deg < 0.0 {
                    deg += 360.0;
                }
                if deg >= 360.0 {
                    deg = 0.0;
                }
                deg
            }
            #[cfg(feature = "trig")]
            3 | 4 => {
                let rad = f(1) * (core::f64::consts::PI / 180.0);
                match if d.func == 3 { num::sin(rad) } else { num::cos(rad) } {
                    Some(t) => f(0) * t,
                    None => return Ok(None),
                }
            }
            5 => -f(0),
            6 => {
                let (num_, den) = (f64::from_bits(plan.pool(pool)?), f64::from_bits(plan.pool(pool + 1)?));
                if den != 0.0 {
                    f(0) * num_ / den
                } else {
                    f(0) * num_
                }
            }
            7 => f(0) + f64::from_bits(plan.pool(pool)?),
            // ruling 8 of 0.6: an overflow leaves the target absent
            8 => return Ok(int(0).and_then(|k| k.checked_add(plan.pool(pool).ok()? as i64)).map(Val::Int)),
            9 => match int(0) {
                Some(ms) => return Ok(Some(Val::Float(ms.rem_euclid(86_400_000) as f64 / 1000.0))),
                None => return Ok(None),
            },
            10 => {
                if a.is_empty() {
                    return Ok(None);
                }
                return Ok(Some(Val::Int(a.iter().any(|v| !matches!(v, Val::Int(0))) as i64)));
            }
            11 => return Ok(Some(Val::Int(matches!(a.first(), Some(Val::Int(0))) as i64))),
            12 => match a.first() {
                Some(Val::Str(t)) => return Ok(self.parse_int(*t).map(Val::Int)),
                _ => return Ok(None),
            },
            // a function this build of the engine leaves out, or does not know
            _ => return Err(Error::BadPlan),
        };
        // a result that is not finite leaves the target absent
        Ok(if num::is_finite(x) { Some(Val::Float(x)) } else { None })
    }

    /// An optional `-`, then decimal digits, within 64 bits.
    fn parse_int(&self, t: TextRef) -> Option<i64> {
        let neg = t.len > 0 && self.text_at(t, 0) == b'-';
        let first = neg as u16;
        if t.len == first {
            return None;
        }
        let mut v: i64 = 0;
        for i in first..t.len {
            let c = self.text_at(t, i);
            if !c.is_ascii_digit() {
                return None;
            }
            let digit = (c - b'0') as i64;
            v = v.checked_mul(10)?;
            v = if neg { v.checked_sub(digit)? } else { v.checked_add(digit)? };
        }
        Some(v)
    }

    // -- the steps --------------------------------------------------------------

    /// Wire to model: read `input` as the plan's source format.
    pub fn decode(&mut self, input: &'a [u8]) -> Result<(), Error> {
        let fmt = self.plan.format(self.plan.src)?;
        // text values hold a 32-bit bit offset
        if input.len() > (u32::MAX / 8) as usize {
            return Err(Error::MalformedWire);
        }
        self.input = input;
        self.src_msb = fmt.msb;
        self.nslots = 0;
        self.nscopes = 0;
        self.kind = NONE16;
        self.failed = false;
        self.held = 0;
        self.presence = [0; MAX_PRESENCE];
        if fmt.sequential {
            let total = input.len() as u64 * 8;
            self.pos = 0;
            self.end = total;
            self.whole = total;
            self.extents = 0;
            self.kind = self.sq_decode_body(fmt.body, 0, 1)?;
        } else {
            self.fx_decode(&fmt)?;
        }
        // a transform failure stands unless another line gave the key its value
        let stands = |s: &Slot| matches!(s.val, Val::Failed | Val::Hard);
        if self.failed || self.slots.get(..self.nslots).is_some_and(|s| s.iter().any(stands)) {
            return Err(Error::TransformDecode);
        }
        self.decoded = true;
        Ok(())
    }

    /// Set each context key the entity lacks. Every key is checked first:
    /// one the plan was not compiled with is `UndeclaredKey`, a value of
    /// another type than the key's is `KeyTypeMismatch`.
    pub fn fill(&mut self, context: &'a [(KeyId, Value<'a>)]) -> Result<(), Error> {
        for (key, v) in context {
            let (ty, flags) = self.plan.key(key.0).ok_or(Error::UndeclaredKey)?;
            if ty == T_LIST {
                return Err(Error::KeyTypeMismatch);
            }
            if flags & K_CONTEXT == 0 {
                return Err(Error::UndeclaredKey);
            }
            let fits = matches!((ty, v), (T_INT, Value::Int(_)) | (T_FLOAT, Value::Float(_)) | (T_STR, Value::Str(_)));
            if !fits {
                return Err(Error::KeyTypeMismatch);
            }
        }
        self.context = context;
        for (i, (key, v)) in context.iter().enumerate() {
            let live = self.plan.key(key.0).is_some_and(|(_, flags)| flags & K_LIVE != 0);
            if !live || self.val(0, key.0).is_some() {
                continue;
            }
            let val = match v {
                Value::Int(n) => Val::Int(*n),
                Value::Float(x) => Val::Float(*x),
                Value::Str(t) => {
                    let len = u16::try_from(t.len()).map_err(|_| Error::ScratchFull)?;
                    Val::Str(TextRef { src: SRC_CONTEXT, len, room: 0, off: i as u32 })
                }
            };
            self.set(0, key.0, val)?;
        }
        Ok(())
    }

    /// Apply the derivations the plan holds: a line whose target is absent
    /// and whose arguments are all present sets the target. Repeats until a
    /// pass sets nothing, at most 8 times.
    pub fn complete(&mut self) -> Result<(), Error> {
        for _ in 0..8 {
            let mut any = false;
            for i in 0..self.plan.derive_count() {
                let d = self.plan.derive(i)?;
                if self.val(0, d.target).is_some() {
                    continue;
                }
                if let Some(v) = self.derive(&d)? {
                    self.set(0, d.target, v)?;
                    any = true;
                }
            }
            if !any {
                break;
            }
        }
        Ok(())
    }

    /// Model to wire: write the plan's target format into `out`. Returns the
    /// number of bytes written.
    pub fn encode(&mut self, out: &mut [u8]) -> Result<usize, Error> {
        let fmt = self.plan.format(self.plan.dst)?;
        if !fmt.sequential {
            return self.fx_encode(&fmt, out);
        }
        self.presence = [0; MAX_PRESENCE];
        let mut w = Wr { out, pos: 0, hi: 0, msb: fmt.msb, wholes: [(0, 0, 0); MAX_WHOLES], nwholes: 0 };
        self.sq_encode_body(fmt.body, 0, &mut w, 1)?;
        // a message is a whole number of bytes; the last bits are zero
        let bytes = w.hi;
        for k in 0..w.nwholes {
            let (at, len, plus) = w.wholes.get(k).copied().ok_or(Error::BadPlan)?;
            let stated = (bytes as i64).checked_add(plus).ok_or(Error::TransformEncode)?;
            if stated < 0 || (len < 64 && (stated as u64) >> len != 0) {
                return Err(Error::TransformEncode);
            }
            set_bits(w.out, at, len as u32, stated as u64, w.msb);
        }
        Ok(bytes)
    }

    // -- reading the values ---------------------------------------------------

    /// The value of a key of the message (`ROOT`) or of an item.
    pub fn get(&self, scope: Scope, key: KeyId) -> Option<Got> {
        match self.scalar(scope.0, key.0)? {
            Val::Int(n) => Some(Got::Int(n)),
            Val::Float(x) => Some(Got::Float(x)),
            Val::Str(t) => Some(Got::Text(t)),
            _ => None,
        }
    }

    /// The number of items of a list. None: the list is absent.
    pub fn list(&self, scope: Scope, list: KeyId) -> Option<u16> {
        self.list_len(scope.0, list.0)
    }

    /// Item `index` (from 0) of a list.
    pub fn list_item(&self, scope: Scope, list: KeyId, index: u16) -> Option<Scope> {
        self.item(scope.0, list.0, index).map(Scope)
    }

    /// The kind the last decode selected for the message or an item. For the
    /// message, its position in the pack, from 0; for an item, its number
    /// among the item kinds of the groups that map the item's list, one
    /// number per kind name, from 0.
    pub fn kind(&self, scope: Scope) -> Option<u16> {
        Some(self.scope_kind(scope.0)).filter(|k| *k != NONE16)
    }

    /// The name of the kind the last decode selected, when the plan was
    /// compiled with names.
    pub fn kind_name(&self, scope: Scope) -> Option<&'a str> {
        let ordinal = self.kind(scope)?;
        let fmt = self.plan.format(self.plan.src).ok()?;
        if scope.0 == 0 {
            return self.plan.kind_name_in(fmt.body, ordinal);
        }
        // an item: the body of the group that maps its list, found by walking the source format
        let rec = *self.scopes.get(scope.0 as usize - 1)?;
        let top = self.plan.op(fmt.body).ok()?;
        let end = self.plan.next(fmt.body, &top).ok()?;
        let mut i = fmt.body;
        while i < end {
            let o = self.plan.op(i).ok()?;
            if matches!(o.op, OP_GROUP_SEQ | OP_GROUP_FIX) && o.key == rec.list {
                if let Some(name) = self.plan.kind_name_in(i + 1, ordinal) {
                    return Some(name);
                }
            }
            i += 1;
        }
        None
    }

    pub fn text_len(&self, t: TextRef) -> usize {
        t.len as usize
    }

    pub fn text_byte(&self, t: TextRef, i: usize) -> u8 {
        u16::try_from(i).map_or(0, |i| self.text_at(t, i))
    }

    // -- setting the values (an encode-only plan) -------------------------------

    /// The texts `put_text` refers to by index. Call before `put_text`.
    pub fn set_texts(&mut self, texts: &'a [&'a [u8]]) {
        self.texts = texts;
    }

    pub fn put_int(&mut self, scope: Scope, key: KeyId, v: i64) -> Result<(), Error> {
        self.put_checked(scope, key, T_INT, Val::Int(v))
    }

    pub fn put_float(&mut self, scope: Scope, key: KeyId, v: f64) -> Result<(), Error> {
        if !num::is_finite(v) {
            return Err(Error::KeyTypeMismatch);
        }
        self.put_checked(scope, key, T_FLOAT, Val::Float(v))
    }

    /// Set a text key to entry `index` of the slice given to `set_texts`.
    pub fn put_text(&mut self, scope: Scope, key: KeyId, index: u16) -> Result<(), Error> {
        let len = self.texts.get(index as usize).ok_or(Error::KeyTypeMismatch)?.len();
        let len = u16::try_from(len).map_err(|_| Error::ScratchFull)?;
        self.put_checked(scope, key, T_STR, Val::Str(TextRef { src: SRC_TEXT, len, room: 0, off: index as u32 }))
    }

    fn put_checked(&mut self, scope: Scope, key: KeyId, ty: u8, v: Val) -> Result<(), Error> {
        match self.plan.key(key.0) {
            Some((t, _)) if t == ty => self.set(scope.0, key.0, v),
            Some(_) => Err(Error::KeyTypeMismatch),
            None => Err(Error::UndeclaredKey),
        }
    }

    /// Add one item to a list of the message or of an item, making the list
    /// present. Returns the new item.
    pub fn add_item(&mut self, scope: Scope, list: KeyId) -> Result<Scope, Error> {
        let n = self.put_list(scope, list)?;
        let item = self.new_scope(scope.0, list.0, n)?;
        self.set(scope.0, list.0, Val::List(n.checked_add(1).ok_or(Error::ScratchFull)?))?;
        Ok(Scope(item))
    }

    /// Make a list present, with no items when it was absent. Returns its length.
    pub fn put_list(&mut self, scope: Scope, list: KeyId) -> Result<u16, Error> {
        match self.plan.key(list.0) {
            Some((T_LIST, _)) => {}
            Some(_) => return Err(Error::KeyTypeMismatch),
            None => return Err(Error::UndeclaredKey),
        }
        match self.list_len(scope.0, list.0) {
            Some(n) => Ok(n),
            None => {
                self.set(scope.0, list.0, Val::List(0))?;
                Ok(0)
            }
        }
    }
}
