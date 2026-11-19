//! The compiled plan: a read-only view of a `.gtp` blob (embedded/FORMAT.md).
//! Every read is bounds-checked; a blob that does not hold what an index
//! names gives `Error::BadPlan`, never a panic.

use crate::Error;

pub(crate) const S_FORMATS: u16 = 1;
pub(crate) const S_OPS: u16 = 2;
pub(crate) const S_POOL: u16 = 3;
pub(crate) const S_CONDS: u16 = 4;
pub(crate) const S_TABLES: u16 = 5;
pub(crate) const S_KEYS: u16 = 6;
pub(crate) const S_DERIVES: u16 = 7;
pub(crate) const S_ARGS: u16 = 8;
pub(crate) const S_PLAN: u16 = 9;
pub(crate) const S_BYTES: u16 = 10;
pub(crate) const S_CARRY: u16 = 11;
pub(crate) const S_NAMEIDX: u16 = 12;
pub(crate) const S_NAMES: u16 = 13;

pub(crate) const OP_BODY: u8 = 1;
pub(crate) const OP_KIND: u8 = 2;
pub(crate) const OP_WHEN: u8 = 3;
pub(crate) const OP_REQ: u8 = 4;
pub(crate) const OP_DEFAULT: u8 = 5;
pub(crate) const OP_FIELD: u8 = 6;
pub(crate) const OP_ALSO: u8 = 7;
pub(crate) const OP_CONST: u8 = 8;
pub(crate) const OP_PAD: u8 = 9;
pub(crate) const OP_ALIGN: u8 = 10;
pub(crate) const OP_PRESENCE: u8 = 11;
pub(crate) const OP_IF: u8 = 12;
pub(crate) const OP_OPT: u8 = 13;
pub(crate) const OP_CHAIN: u8 = 14;
pub(crate) const OP_PART: u8 = 15;
pub(crate) const OP_LENGTH: u8 = 16;
pub(crate) const OP_WHOLE: u8 = 17;
pub(crate) const OP_GROUP_SEQ: u8 = 18;
pub(crate) const OP_GROUP_FIX: u8 = 19;

pub(crate) const NONE16: u16 = 0xFFFF;
pub(crate) const NONE32: u32 = 0xFFFF_FFFF;

/// The version of the blob layout this engine reads.
pub const FORMAT_VERSION: u16 = 1;

/// One entry of the operation table.
#[derive(Clone, Copy)]
pub(crate) struct Op {
    pub op: u8,
    pub xf: u8,
    pub flags: u8,
    pub key: u16,
    pub len: u16,
    pub a: u32,
    pub b: u16,
    pub c: u16,
}

/// One compiled format.
#[derive(Clone, Copy)]
pub(crate) struct Format {
    pub msb: bool,
    pub sequential: bool,
    pub word_bytes: u16,
    pub body: u32,
}

/// One value table, specialised to the two types it converts between.
#[derive(Clone, Copy)]
pub(crate) struct Table {
    pub native_ty: u8,
    pub model_ty: u8,
    pub n: u16,
    pub first: u32,
}

#[derive(Clone, Copy)]
pub(crate) struct Derive {
    pub func: u8,
    pub nargs: u8,
    pub target: u16,
    pub args: u16,
    pub pool: u16,
}

/// One row of the conversion plan: a model key the conversion carries.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Carry {
    /// the key
    pub key: crate::KeyId,
    /// the source format reads it from the wire
    pub from_source: bool,
    /// the caller may supply it
    pub from_context: bool,
    /// a derivation may set it
    pub derived: bool,
    /// index of the first source operation that reads it
    pub source_op: Option<u32>,
    /// index of the first target operation that writes it
    pub target_op: u32,
}

#[derive(Clone, Copy)]
struct Sec<'a> {
    data: &'a [u8],
    count: u32,
}

const EMPTY: Sec<'static> = Sec { data: &[], count: 0 };

/// A compiled plan, borrowed from the blob. Cheap to copy.
#[derive(Clone, Copy)]
pub struct Plan<'a> {
    formats: Sec<'a>,
    ops: Sec<'a>,
    pool: Sec<'a>,
    conds: Sec<'a>,
    tables: Sec<'a>,
    keys: Sec<'a>,
    derives: Sec<'a>,
    args: Sec<'a>,
    bytes: Sec<'a>,
    carry: Sec<'a>,
    nameidx: Sec<'a>,
    names: Sec<'a>,
    pub(crate) src: u16,
    pub(crate) dst: u16,
    pub(crate) same: bool,
}

fn rd<const N: usize>(b: &[u8], off: u64) -> Option<[u8; N]> {
    let off = usize::try_from(off).ok()?;
    let s = b.get(off..)?.get(..N)?;
    let mut out = [0u8; N];
    out.copy_from_slice(s);
    Some(out)
}
fn u16_at(b: &[u8], off: u64) -> Option<u16> {
    rd::<2>(b, off).map(u16::from_le_bytes)
}
fn u32_at(b: &[u8], off: u64) -> Option<u32> {
    rd::<4>(b, off).map(u32::from_le_bytes)
}
fn u64_at(b: &[u8], off: u64) -> Option<u64> {
    rd::<8>(b, off).map(u64::from_le_bytes)
}

impl<'a> Plan<'a> {
    /// Read the header and the section directory of a blob. The tables are
    /// not copied.
    pub fn parse(blob: &'a [u8]) -> Result<Plan<'a>, Error> {
        let bad = Error::BadPlan;
        if blob.get(..4) != Some(b"GTP1") || u16_at(blob, 4) != Some(FORMAT_VERSION) {
            return Err(bad);
        }
        let total = u32_at(blob, 8).ok_or(bad)? as usize;
        let blob = blob.get(..total).ok_or(bad)?;
        let nsec = u16_at(blob, 12).ok_or(bad)?;
        let mut p = Plan {
            formats: EMPTY,
            ops: EMPTY,
            pool: EMPTY,
            conds: EMPTY,
            tables: EMPTY,
            keys: EMPTY,
            derives: EMPTY,
            args: EMPTY,
            bytes: EMPTY,
            carry: EMPTY,
            nameidx: EMPTY,
            names: EMPTY,
            src: NONE16,
            dst: NONE16,
            same: false,
        };
        let mut plan_sec = EMPTY;
        for i in 0..nsec as u64 {
            let at = 16 + 12 * i;
            let id = u16_at(blob, at).ok_or(bad)?;
            let entry = u16_at(blob, at + 2).ok_or(bad)? as u64;
            let off = u32_at(blob, at + 4).ok_or(bad)? as usize;
            let count = u32_at(blob, at + 8).ok_or(bad)?;
            let size = usize::try_from(entry * count as u64).map_err(|_| bad)?;
            let data = blob.get(off..).and_then(|s| s.get(..size)).ok_or(bad)?;
            let want = match id {
                S_FORMATS | S_OPS => 16,
                S_POOL | S_TABLES | S_DERIVES => 8,
                S_CONDS | S_KEYS | S_NAMEIDX => 4,
                S_ARGS => 2,
                S_PLAN | S_CARRY => 12,
                S_BYTES | S_NAMES => 1,
                // a section this engine does not know is skipped
                _ => continue,
            };
            if entry != want {
                return Err(bad);
            }
            let sec = Sec { data, count };
            match id {
                S_FORMATS => p.formats = sec,
                S_OPS => p.ops = sec,
                S_POOL => p.pool = sec,
                S_CONDS => p.conds = sec,
                S_TABLES => p.tables = sec,
                S_KEYS => p.keys = sec,
                S_DERIVES => p.derives = sec,
                S_ARGS => p.args = sec,
                S_PLAN => plan_sec = sec,
                S_BYTES => p.bytes = sec,
                S_CARRY => p.carry = sec,
                S_NAMEIDX => p.nameidx = sec,
                _ => p.names = sec,
            }
        }
        if plan_sec.count != 1 {
            return Err(bad);
        }
        p.src = u16_at(plan_sec.data, 0).ok_or(bad)?;
        p.dst = u16_at(plan_sec.data, 2).ok_or(bad)?;
        p.same = plan_sec.data.get(4).ok_or(bad)? & 1 != 0;
        Ok(p)
    }

    pub(crate) fn op(&self, i: u32) -> Result<Op, Error> {
        let b = rd::<16>(self.ops.data, i as u64 * 16).ok_or(Error::BadPlan)?;
        Ok(Op {
            op: b[0],
            xf: b[1],
            flags: b[2],
            key: u16::from_le_bytes([b[4], b[5]]),
            len: u16::from_le_bytes([b[6], b[7]]),
            a: u32::from_le_bytes([b[8], b[9], b[10], b[11]]),
            b: u16::from_le_bytes([b[12], b[13]]),
            c: u16::from_le_bytes([b[14], b[15]]),
        })
    }

    /// The index of the operation after `o` and everything nested in it.
    pub(crate) fn next(&self, i: u32, o: &Op) -> Result<u32, Error> {
        let n = match o.op {
            OP_BODY | OP_KIND | OP_IF | OP_OPT | OP_CHAIN | OP_PART | OP_LENGTH => o.a as u64 + 1,
            OP_GROUP_SEQ | OP_GROUP_FIX => {
                let body = self.op(i.checked_add(1).ok_or(Error::BadPlan)?)?;
                if body.op != OP_BODY {
                    return Err(Error::BadPlan);
                }
                body.a as u64 + 2
            }
            _ => 1,
        };
        let next = i as u64 + n;
        if next > self.ops.count as u64 {
            return Err(Error::BadPlan);
        }
        Ok(next as u32)
    }

    pub(crate) fn pool(&self, i: u32) -> Result<u64, Error> {
        u64_at(self.pool.data, i as u64 * 8).ok_or(Error::BadPlan)
    }

    pub(crate) fn format(&self, i: u16) -> Result<Format, Error> {
        let b = rd::<16>(self.formats.data, i as u64 * 16).ok_or(Error::BadPlan)?;
        Ok(Format {
            msb: b[0] & 1 != 0,
            sequential: b[0] & 2 != 0,
            word_bytes: u16::from_le_bytes([b[2], b[3]]),
            body: u32::from_le_bytes([b[4], b[5], b[6], b[7]]),
        })
    }

    /// (presence id, bit from 1, negated)
    pub(crate) fn cond(&self, i: u32) -> Result<(u16, u8, bool), Error> {
        let b = rd::<4>(self.conds.data, i as u64 * 4).ok_or(Error::BadPlan)?;
        Ok((u16::from_le_bytes([b[0], b[1]]), b[2], b[3] != 0))
    }

    pub(crate) fn table(&self, i: u16) -> Result<Table, Error> {
        let b = rd::<8>(self.tables.data, i as u64 * 8).ok_or(Error::BadPlan)?;
        Ok(Table {
            native_ty: b[0],
            model_ty: b[1],
            n: u16::from_le_bytes([b[2], b[3]]),
            first: u32::from_le_bytes([b[4], b[5], b[6], b[7]]),
        })
    }

    /// (type, flags) of a key
    pub(crate) fn key(&self, k: u16) -> Option<(u8, u8)> {
        let b = rd::<4>(self.keys.data, k as u64 * 4)?;
        Some((b[0], b[1]))
    }

    pub(crate) fn derive_count(&self) -> u32 {
        self.derives.count
    }

    pub(crate) fn derive(&self, i: u32) -> Result<Derive, Error> {
        let b = rd::<8>(self.derives.data, i as u64 * 8).ok_or(Error::BadPlan)?;
        Ok(Derive {
            func: b[0],
            nargs: b[1],
            target: u16::from_le_bytes([b[2], b[3]]),
            args: u16::from_le_bytes([b[4], b[5]]),
            pool: u16::from_le_bytes([b[6], b[7]]),
        })
    }

    pub(crate) fn arg(&self, i: u32) -> Result<u16, Error> {
        u16_at(self.args.data, i as u64 * 2).ok_or(Error::BadPlan)
    }

    pub(crate) fn byte(&self, i: u64) -> Option<u8> {
        self.bytes.data.get(usize::try_from(i).ok()?).copied()
    }

    /// The number of model keys the plan names.
    pub fn key_count(&self) -> u16 {
        self.keys.count.min(NONE16 as u32 - 1) as u16
    }

    /// True when source and target are one format: `convert` keeps the kind
    /// of the message and, with no context, does not derive.
    pub fn is_same_format(&self) -> bool {
        self.same
    }

    /// True when the plan holds a source format: `decode` and `convert` work.
    pub fn has_source(&self) -> bool {
        self.src != NONE16
    }

    /// True when the plan holds a target format: `encode` and `convert` work.
    pub fn has_target(&self) -> bool {
        self.dst != NONE16
    }

    /// The number of rows of the conversion plan.
    pub fn carry_count(&self) -> u32 {
        self.carry.count
    }

    /// Row `i` of the conversion plan: a key the conversion carries, with the
    /// first source operation that reads it and the first target operation
    /// that writes it.
    pub fn carry(&self, i: u32) -> Option<Carry> {
        let b = rd::<12>(self.carry.data, i as u64 * 12)?;
        let how = u16::from_le_bytes([b[2], b[3]]);
        let s = u32::from_le_bytes([b[4], b[5], b[6], b[7]]);
        Some(Carry {
            key: crate::KeyId(u16::from_le_bytes([b[0], b[1]])),
            from_source: how & 1 != 0,
            from_context: how & 2 != 0,
            derived: how & 4 != 0,
            source_op: if s == NONE32 { None } else { Some(s) },
            target_op: u32::from_le_bytes([b[8], b[9], b[10], b[11]]),
        })
    }

    fn name(&self, id: u16) -> Option<&'a str> {
        let off = u32_at(self.nameidx.data, id as u64 * 4)? as usize;
        let len = *self.names.data.get(off)? as usize;
        let s = self.names.data.get(off + 1..)?.get(..len)?;
        core::str::from_utf8(s).ok()
    }

    /// The name of a key, when the plan was compiled with names.
    pub fn key_name(&self, k: crate::KeyId) -> Option<&'a str> {
        let b = rd::<4>(self.keys.data, k.0 as u64 * 4)?;
        self.name(u16::from_le_bytes([b[2], b[3]]))
    }

    /// The id of a key by name, when the plan was compiled with names.
    pub fn find_key(&self, name: &str) -> Option<crate::KeyId> {
        (0..self.key_count()).map(crate::KeyId).find(|k| self.key_name(*k) == Some(name))
    }

    /// The name of kind number `ordinal` of the message body of the source
    /// (`source` true) or target format, when the plan was compiled with
    /// names. `ordinal` is the position of the kind in its pack, from 0.
    pub fn kind_name(&self, source: bool, ordinal: u16) -> Option<&'a str> {
        let f = self.format(if source { self.src } else { self.dst }).ok()?;
        self.kind_name_in(f.body, ordinal)
    }

    /// The name of kind `ordinal` of the body at operation `body`.
    pub(crate) fn kind_name_in(&self, body: u32, ordinal: u16) -> Option<&'a str> {
        let b = self.op(body).ok()?;
        let end = body as u64 + 1 + b.a as u64;
        let mut i = body + 1;
        while (i as u64) < end {
            let o = self.op(i).ok()?;
            if o.op == OP_KIND && o.key == ordinal {
                return self.name(o.c);
            }
            i = self.next(i, &o).ok()?;
        }
        None
    }
}
