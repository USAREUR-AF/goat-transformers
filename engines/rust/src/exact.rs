//! Exact arithmetic for the integer scales of engine-spec v0.15: factors read
//! as exact fractions, offsets as exact integers, round half away from zero of
//! the exact value, and the exact decimal text of `iscale` on the text wires.
//! Standard library only: a small unsigned big integer covers what 128 bits
//! do not (a factor or a number text of any number of digits).

use std::cmp::Ordering;

/// An unsigned integer of any size: 32-bit limbs, least significant first,
/// no trailing zero limb.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Big(Vec<u32>);

impl Big {
    pub(crate) fn zero() -> Big {
        Big(Vec::new())
    }
    pub(crate) fn from_u128(mut v: u128) -> Big {
        let mut l = Vec::new();
        while v != 0 {
            l.push(v as u32);
            v >>= 32;
        }
        Big(l)
    }
    /// The value of a string of ASCII digits (the caller checked them).
    pub(crate) fn from_digits(s: &str) -> Big {
        let mut b = Big::zero();
        for chunk in s.as_bytes().chunks(9) {
            let mut m = 1u32;
            let mut a = 0u32;
            for c in chunk {
                m *= 10;
                a = a * 10 + (c - b'0') as u32;
            }
            b.mul_add_small(m, a);
        }
        b
    }
    fn trim(&mut self) {
        while self.0.last() == Some(&0) {
            self.0.pop();
        }
    }
    pub(crate) fn is_zero(&self) -> bool {
        self.0.is_empty()
    }
    /// self = self * m + a
    pub(crate) fn mul_add_small(&mut self, m: u32, a: u32) {
        let mut carry = a as u64;
        for l in self.0.iter_mut() {
            let t = *l as u64 * m as u64 + carry;
            *l = t as u32;
            carry = t >> 32;
        }
        if carry != 0 {
            self.0.push(carry as u32);
        }
        self.trim();
    }
    pub(crate) fn mul_pow10(&mut self, mut n: u64) {
        while n >= 9 {
            self.mul_add_small(1_000_000_000, 0);
            n -= 9;
        }
        if n > 0 {
            self.mul_add_small(10u32.pow(n as u32), 0);
        }
    }
    fn bits(&self) -> u64 {
        match self.0.last() {
            None => 0,
            Some(top) => (self.0.len() as u64 - 1) * 32 + (32 - top.leading_zeros() as u64),
        }
    }
    fn shl(&self, n: u64) -> Big {
        if self.is_zero() {
            return Big::zero();
        }
        let limbs = (n / 32) as usize;
        let s = (n % 32) as u32;
        let mut out = vec![0u32; limbs];
        let mut carry = 0u32;
        for l in &self.0 {
            if s == 0 {
                out.push(*l);
            } else {
                out.push((l << s) | carry);
                carry = l >> (32 - s);
            }
        }
        if carry != 0 {
            out.push(carry);
        }
        let mut b = Big(out);
        b.trim();
        b
    }
    /// self -= o, where o <= self
    fn sub_assign(&mut self, o: &Big) {
        let mut borrow = 0i64;
        for i in 0..self.0.len() {
            let t = self.0[i] as i64 - o.0.get(i).copied().unwrap_or(0) as i64 - borrow;
            if t < 0 {
                self.0[i] = (t + (1i64 << 32)) as u32;
                borrow = 1;
            } else {
                self.0[i] = t as u32;
                borrow = 0;
            }
        }
        self.trim();
    }
    fn set_bit(&mut self, i: u64) {
        let limb = (i / 32) as usize;
        if self.0.len() <= limb {
            self.0.resize(limb + 1, 0);
        }
        self.0[limb] |= 1 << (i % 32);
    }
    /// (quotient, remainder); `d` is not zero
    pub(crate) fn divmod(&self, d: &Big) -> (Big, Big) {
        let mut r = self.clone();
        let mut q = Big::zero();
        if self.cmp(d) == Ordering::Less {
            return (q, r);
        }
        let top = self.bits() - d.bits();
        for i in (0..=top).rev() {
            let s = d.shl(i);
            if r.cmp(&s) != Ordering::Less {
                r.sub_assign(&s);
                q.set_bit(i);
            }
        }
        (q, r)
    }
    pub(crate) fn to_u128(&self) -> Option<u128> {
        if self.0.len() > 4 {
            return None;
        }
        Some(self.0.iter().rev().fold(0u128, |a, l| (a << 32) | *l as u128))
    }
    fn gcd(a: &Big, b: &Big) -> Big {
        let (mut a, mut b) = (a.clone(), b.clone());
        while !b.is_zero() {
            let (_, r) = a.divmod(&b);
            a = b;
            b = r;
        }
        a
    }
}

impl PartialOrd for Big {
    fn partial_cmp(&self, o: &Big) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for Big {
    fn cmp(&self, o: &Big) -> Ordering {
        self.0.len().cmp(&o.0.len()).then_with(|| self.0.iter().rev().cmp(o.0.iter().rev()))
    }
}

fn all_digits(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())
}

/// An exact factor in lowest terms, `num / den` (`den` > 0, each at most
/// 2^32, `num` not 0), and an exact offset with absolute value below 2^63.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Exact {
    pub num: i64,
    pub den: i64,
    pub offset: i64,
}

impl Exact {
    /// `<factor>[:<offset>]` as the integer scales read it (Exact factors).
    pub(crate) fn parse(args: &str) -> Option<Exact> {
        let mut parts = args.split(':');
        let factor = parts.next()?;
        let offset = match parts.next() {
            Some(o) => parse_offset(o)?,
            None => 0,
        };
        if parts.next().is_some() {
            return None;
        }
        let (neg, body) = match factor.strip_prefix('-') {
            Some(rest) => (true, rest),
            None => (false, factor),
        };
        let (n, d) = match body.split_once('/') {
            Some((n, d)) => {
                if !all_digits(n) || !all_digits(d) {
                    return None;
                }
                (Big::from_digits(n), Big::from_digits(d))
            }
            None => {
                let (ip, fp) = match body.split_once('.') {
                    Some((i, f)) => {
                        if !all_digits(f) {
                            return None;
                        }
                        (i, f)
                    }
                    None => (body, ""),
                };
                if !all_digits(ip) {
                    return None;
                }
                let mut n = Big::from_digits(ip);
                n.mul_pow10(fp.len() as u64);
                let f = Big::from_digits(fp);
                let n = add(&n, &f);
                let mut d = Big::from_u128(1);
                d.mul_pow10(fp.len() as u64);
                (n, d)
            }
        };
        if n.is_zero() || d.is_zero() {
            return None;
        }
        let g = Big::gcd(&n, &d);
        let (n, _) = n.divmod(&g);
        let (d, _) = d.divmod(&g);
        let limit = 1u128 << 32;
        let n = n.to_u128().filter(|v| *v <= limit)? as i64;
        let d = d.to_u128().filter(|v| *v <= limit)? as i64;
        Some(Exact { num: if neg { -n } else { n }, den: d, offset })
    }

    /// `round(v × factor) + offset`, None outside the signed 64-bit range.
    #[cfg(any(feature = "bits", feature = "tlv"))]
    pub(crate) fn decode(&self, v: i128) -> Option<i64> {
        let r = div_round(v * self.num as i128, self.den as i128) + self.offset as i128;
        i64::try_from(r).ok()
    }

    /// `round((x − offset) / factor)`
    #[cfg(any(feature = "bits", feature = "tlv"))]
    pub(crate) fn encode(&self, x: i64) -> i128 {
        div_round((x as i128 - self.offset as i128) * self.den as i128, self.num as i128)
    }

    /// `(x − offset) / factor` exactly, in plain decimal notation; None when
    /// it does not terminate within 18 fraction digits.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json"))]
    pub(crate) fn encode_decimal(&self, x: i64) -> Option<String> {
        let mut n = (x as i128 - self.offset as i128) * self.den as i128;
        let mut d = self.num as i128;
        if d < 0 {
            n = -n;
            d = -d;
        }
        let neg = n < 0;
        let n = n.unsigned_abs();
        let d = d as u128;
        let mut out = String::new();
        if neg {
            out.push('-');
        }
        out.push_str(&(n / d).to_string());
        let mut rem = n % d;
        if rem != 0 {
            out.push('.');
            let mut digits = 0;
            while rem != 0 {
                if digits == 18 {
                    return None;
                }
                rem *= 10;
                out.push((b'0' + (rem / d) as u8) as char);
                rem %= d;
                digits += 1;
            }
        }
        Some(out)
    }

    /// `round(r × factor) + offset` for a number text `r` of the form
    /// `-?digits(.digits)?([eE][+-]?digits)?`, the exponent at most 400 in
    /// absolute value. None for other text or a result outside the signed
    /// 64-bit range.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json"))]
    pub(crate) fn decode_text(&self, text: &str) -> Option<i64> {
        let (neg, rest) = match text.strip_prefix('-') {
            Some(r) => (true, r),
            None => (false, text),
        };
        let (mant, exp) = match rest.find(|c| c == 'e' || c == 'E') {
            Some(i) => (&rest[..i], Some(&rest[i + 1..])),
            None => (rest, None),
        };
        let (ip, fp) = match mant.split_once('.') {
            Some((i, f)) => {
                if !all_digits(f) {
                    return None;
                }
                (i, f)
            }
            None => (mant, ""),
        };
        if !all_digits(ip) {
            return None;
        }
        let e: i64 = match exp {
            None => 0,
            Some(x) => {
                let (eneg, digits) = match x.as_bytes().first() {
                    Some(b'-') => (true, &x[1..]),
                    Some(b'+') => (false, &x[1..]),
                    _ => (false, x),
                };
                if !all_digits(digits) {
                    return None;
                }
                let digits = digits.trim_start_matches('0');
                if digits.len() > 3 {
                    return None;
                }
                let v: i64 = if digits.is_empty() { 0 } else { digits.parse().ok()? };
                if v > 400 {
                    return None;
                }
                if eneg {
                    -v
                } else {
                    v
                }
            }
        };
        // the significant digits M and the exponent k: r = M × 10^k
        let all: String = format!("{}{}", ip, fp);
        let lead = all.trim_start_matches('0');
        let sig = lead.trim_end_matches('0');
        let k = e - fp.len() as i64 + (lead.len() - sig.len()) as i64;
        let scaled = if sig.is_empty() {
            0i128
        } else {
            let l = sig.len() as i64;
            // |r| >= 10^(l+k-1) and |factor| >= 2^-32: from l+k >= 31 the
            // product exceeds 2^64, beyond any offset's reach
            if l + k >= 31 {
                return None;
            }
            // |r| < 10^(l+k) and |factor| <= 2^32: from l+k <= -10 the product
            // is below 1/2 and rounds to 0
            if l + k <= -10 {
                0
            } else {
                // linear in the number of digits: r = I + F, I the integer
                // part (at most 30 digits), F the fraction digits
                let m = self.num.unsigned_abs() as u128;
                let d = self.den as u128;
                let l = sig.len();
                let (int_digits, frac): (&str, Vec<u8>) = if k >= 0 {
                    (sig, Vec::new())
                } else {
                    let s = (-k) as usize;
                    if s >= l {
                        let mut f = vec![0u8; s - l];
                        f.extend(sig.bytes().map(|b| b - b'0'));
                        ("", f)
                    } else {
                        (&sig[..l - s], sig[l - s..].bytes().map(|b| b - b'0').collect())
                    }
                };
                let mut int: u128 = int_digits.bytes().fold(0u128, |a, b| a * 10 + (b - b'0') as u128);
                for _ in 0..k.max(0) {
                    int *= 10;
                }
                // a product beyond 128 bits is beyond any result in range
                let im = int.checked_mul(m)?;
                let (q1, r1) = (im / d, im % d);
                // F × m, right to left: g its integer part, p1 its first fraction digit
                let mut carry: u128 = 0;
                let mut p1: u128 = 0;
                for digit in frac.iter().rev() {
                    let v = *digit as u128 * m + carry;
                    p1 = v % 10;
                    carry = v / 10;
                }
                let sum = r1 + carry;
                let mut q = q1.checked_add(sum / d)?;
                let t = sum % d;
                // remainder t + frac(F × m) against d / 2
                if 2 * t >= d || (2 * t + 1 == d && p1 >= 5) {
                    q += 1;
                }
                if q >= 1u128 << 66 {
                    return None;
                }
                let q = q as i128;
                if neg != (self.num < 0) {
                    -q
                } else {
                    q
                }
            }
        };
        i64::try_from(scaled + self.offset as i128).ok()
    }
}

fn add(a: &Big, b: &Big) -> Big {
    let mut out = Vec::new();
    let mut carry = 0u64;
    for i in 0..a.0.len().max(b.0.len()) {
        let t = a.0.get(i).copied().unwrap_or(0) as u64 + b.0.get(i).copied().unwrap_or(0) as u64 + carry;
        out.push(t as u32);
        carry = t >> 32;
    }
    if carry != 0 {
        out.push(carry as u32);
    }
    let mut r = Big(out);
    r.trim();
    r
}

/// `[-]digits` with absolute value below 2^63.
fn parse_offset(s: &str) -> Option<i64> {
    let (neg, digits) = match s.strip_prefix('-') {
        Some(d) => (true, d),
        None => (false, s),
    };
    if !all_digits(digits) {
        return None;
    }
    let d = digits.trim_start_matches('0');
    if d.len() > 19 {
        return None;
    }
    let v: u64 = if d.is_empty() { 0 } else { d.parse().ok()? };
    if v >= 1u64 << 63 {
        return None;
    }
    Some(if neg { -(v as i64) } else { v as i64 })
}

/// `n / d` rounded half away from zero; `d` is not zero.
#[cfg(any(feature = "bits", feature = "tlv"))]
pub(crate) fn div_round(n: i128, d: i128) -> i128 {
    let (n, d) = if d < 0 { (-n, -d) } else { (n, d) };
    let q = n / d;
    let r = n % d;
    if 2 * r.abs() >= d {
        q + n.signum()
    } else {
        q
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn factors() {
        assert_eq!(Exact::parse("0.001"), Some(Exact { num: 1, den: 1000, offset: 0 }));
        assert_eq!(Exact::parse("-2/4:-5"), Some(Exact { num: -1, den: 2, offset: -5 }));
        assert!(Exact::parse("4294967296").is_some());
        assert!(Exact::parse("4294967297").is_none());
        assert!(Exact::parse("1:-9223372036854775807").is_some());
        assert!(Exact::parse("1:-9223372036854775808").is_none());
        assert!(Exact::parse("-0").is_none());
        assert!(Exact::parse("+1").is_none());
        assert!(Exact::parse("1/-2").is_none());
        assert!(Exact::parse("1:+2").is_none());
        assert!(Exact::parse("1.").is_none());
        assert!(Exact::parse(".5").is_none());
        assert!(Exact::parse("1e3").is_none());
        assert!(Exact::parse("1/0").is_none());
        assert!(Exact::parse("100000000000000000000000000000/100000000000000000000000000000").is_some());
    }

    #[test]
    fn rounding() {
        assert_eq!(div_round(-5, 2), -3);
        assert_eq!(div_round(5, 2), 3);
        assert_eq!(div_round(5, -2), -3);
        assert_eq!(div_round(-4, 3), -1);
    }

    #[test]
    fn texts() {
        let one = Exact { num: 1, den: 1, offset: 0 };
        assert_eq!(one.decode_text("9007199254740993"), Some(9007199254740993));
        assert_eq!(one.decode_text("1e-400"), Some(0));
        assert_eq!(one.decode_text("0e400"), Some(0));
        assert_eq!(one.decode_text("0e401"), None);
        assert_eq!(one.decode_text("-2.5"), Some(-3));
        assert_eq!(one.decode_text("2.5"), Some(3));
        assert_eq!(one.decode_text("2.4999999999999999999999"), Some(2));
        assert_eq!(one.decode_text("1.5e2"), Some(150));
        assert_eq!(one.decode_text("9223372036854775807"), Some(i64::MAX));
        assert_eq!(one.decode_text("9223372036854775808"), None);
        assert_eq!(one.decode_text(" 1"), None);
        assert_eq!(one.decode_text("1."), None);
        let e7 = Exact { num: 10_000_000, den: 1, offset: 0 };
        assert_eq!(e7.decode_text("-12.34567895"), Some(-123456790));
        let big = Exact { num: 1 << 32, den: 1, offset: 0 };
        assert_eq!(big.decode_text("2"), Some(1 << 33));
        assert_eq!(Exact { num: 1, den: 10, offset: 0 }.encode_decimal(125), Some("1250".into()));
        assert_eq!(Exact { num: 10, den: 1, offset: 0 }.encode_decimal(-125), Some("-12.5".into()));
        assert_eq!(Exact { num: 10, den: 1, offset: 0 }.encode_decimal(-5), Some("-0.5".into()));
        assert_eq!(Exact { num: 3, den: 1, offset: 0 }.encode_decimal(1), None);
    }

    /// The exact value through big integers, for comparison.
    fn reference(ex: &Exact, mant: &str, e: i64) -> Option<i64> {
        let (neg, digits) = match mant.strip_prefix('-') {
            Some(d) => (true, d),
            None => (false, mant),
        };
        let (ip, fp) = digits.split_once('.').unwrap_or((digits, ""));
        let mut nn = Big::from_digits(&format!("{}{}", ip, fp));
        let m = ex.num.unsigned_abs();
        if m == 1 << 32 {
            nn = nn.shl(32);
        } else {
            nn.mul_add_small(m as u32, 0);
        }
        let mut d = Big::from_u128(ex.den as u128);
        let k = e - fp.len() as i64;
        if k >= 0 {
            nn.mul_pow10(k as u64);
        } else {
            d.mul_pow10((-k) as u64);
        }
        let (q, r) = nn.divmod(&d);
        let mut q = q.to_u128()? as i128;
        if r.shl(1) >= d {
            q += 1;
        }
        let q = if neg != (ex.num < 0) { -q } else { q };
        i64::try_from(q + ex.offset as i128).ok()
    }

    #[test]
    fn texts_against_big_integers() {
        let mut seed: u64 = 0x9e3779b97f4a7c15;
        let mut next = move || {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            seed
        };
        let factors = ["1", "3", "1/3", "2/7", "-5/2", "4294967296", "1/4294967296", "0.001", "1000", "7/4294967295", "1/2"];
        for _ in 0..20000 {
            let f = factors[(next() % factors.len() as u64) as usize];
            let ex = Exact::parse(&format!("{}:{}", f, (next() % 2001) as i64 - 1000)).unwrap();
            let il = (next() % 22) as usize;
            let fl = (next() % 25) as usize;
            let dig = |n: usize, next: &mut dyn FnMut() -> u64| -> String {
                (0..n).map(|_| match next() % 4 { 0 => '0', 1 => '5', 2 => '9', _ => (b'0' + (next() % 10) as u8) as char }).collect()
            };
            let mut ip = dig(il, &mut next);
            if ip.is_empty() {
                ip = "0".into();
            }
            let fp = dig(fl, &mut next);
            let e = (next() % 41) as i64 - 20;
            let neg = next() % 2 == 0;
            let mant = format!("{}{}{}{}", if neg { "-" } else { "" }, ip, if fp.is_empty() { "" } else { "." }, fp);
            let text = if e == 0 { mant.clone() } else { format!("{}e{}", mant, e) };
            assert_eq!(ex.decode_text(&text), reference(&ex, &mant, e), "{} with {:?}", text, ex);
        }
    }

    #[test]
    fn long_texts_are_linear() {
        let one = Exact { num: 1, den: 1, offset: 0 };
        let text = format!("0.{}5", "4".repeat(2_000_000));
        let t = std::time::Instant::now();
        assert_eq!(one.decode_text(&text), Some(0));
        let text = format!("2.{}1", "0".repeat(2_000_000));
        assert_eq!(Exact { num: 1, den: 4, offset: 0 }.decode_text(&text), Some(1));
        assert!(t.elapsed().as_secs() < 2);
    }
}
