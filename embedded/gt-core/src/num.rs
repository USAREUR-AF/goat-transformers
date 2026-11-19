//! Arithmetic the engine needs and `core` does not provide: rounding, and the
//! functions behind the derive lines `hypot`, `bearing`, `east_of` and
//! `north_of`. No floating-point formatting and no parsing of decimal text.

/// Round half away from zero, as the reference engine's `f64::round`.
pub fn round(x: f64) -> f64 {
    // every double of magnitude 2^52 or more is an integer; NaN is returned as it is
    if !(x > -4503599627370496.0 && x < 4503599627370496.0) {
        return x;
    }
    let t = x as i64 as f64;
    let d = x - t;
    if d >= 0.5 {
        t + 1.0
    } else if d <= -0.5 {
        t - 1.0
    } else {
        t
    }
}

/// 2 to the power `n`, exact, for `n` in 0..=1023.
pub fn two_pow(n: u32) -> f64 {
    f64::from_bits(((1023 + n.min(1023)) as u64) << 52)
}

pub fn is_finite(x: f64) -> bool {
    (x.to_bits() >> 52) & 0x7ff != 0x7ff
}

/// The square root, correctly rounded, in integer arithmetic.
#[cfg(feature = "sqrt")]
pub fn sqrt(x: f64) -> f64 {
    if x == 0.0 || x != x {
        return x;
    }
    if x < 0.0 {
        return f64::NAN;
    }
    if !is_finite(x) {
        return x;
    }
    let bits = x.to_bits();
    let mut e = ((bits >> 52) & 0x7ff) as i32;
    let mut m = bits & 0x000f_ffff_ffff_ffff;
    if e == 0 {
        // subnormal: bring the top bit to bit 52
        let shift = m.leading_zeros() as i32 - 11;
        m <<= shift;
        e = 1 - shift;
    } else {
        m |= 1 << 52;
    }
    // x = (m / 2^52) * 2^exp, m in [2^52, 2^53)
    let mut exp = e - 1023;
    if exp & 1 != 0 {
        m <<= 1;
        exp -= 1;
    }
    // r = floor(sqrt(m * 2^54)), 54 bits: the 53-bit result and one rounding bit
    let n = (m as u128) << 54;
    let mut r: u128 = 0;
    let mut bit: u128 = 1 << 53;
    while bit != 0 {
        let t = r | bit;
        if t * t <= n {
            r = t;
        }
        bit >>= 1;
    }
    let r = r as u64;
    // a square root is never exactly half way between two doubles
    let q = (r >> 1) + (r & 1);
    let biased = (exp / 2 + 1023) as u64;
    f64::from_bits((biased << 52) + (q - (1 << 52)))
}

#[cfg(feature = "trig")]
mod trig {
    use super::round;

    const S1: f64 = -1.66666666666666324348e-01;
    const S2: f64 = 8.33333333332248946124e-03;
    const S3: f64 = -1.98412698298579493134e-04;
    const S4: f64 = 2.75573137070700676789e-06;
    const S5: f64 = -2.50507602534068634195e-08;
    const S6: f64 = 1.58969099521155010221e-10;

    const C1: f64 = 4.16666666666666019037e-02;
    const C2: f64 = -1.38888888888741095749e-03;
    const C3: f64 = 2.48015872894767294178e-05;
    const C4: f64 = -2.75573143513906633035e-07;
    const C5: f64 = 2.08757232129817482790e-09;
    const C6: f64 = -1.13596475577881948265e-11;

    const INVPIO2: f64 = 6.36619772367581382433e-01;
    const PIO2_1: f64 = 1.57079632673412561417e+00;
    const PIO2_1T: f64 = 6.07710050650619224932e-11;
    const PIO2_2: f64 = 6.07710050630396597660e-11;
    const PIO2_2T: f64 = 2.02226624879595063154e-21;
    const PIO2_3: f64 = 2.02226624871116645580e-21;
    const PIO2_3T: f64 = 8.47842766036889956997e-32;

    /// sine on [-pi/4, pi/4]; `y` is the tail of `x`
    fn k_sin(x: f64, y: f64, tail: bool) -> f64 {
        let z = x * x;
        let w = z * z;
        let r = S2 + z * (S3 + z * S4) + z * w * (S5 + z * S6);
        let v = z * x;
        if tail {
            x - ((z * (0.5 * y - v * r) - y) - v * S1)
        } else {
            x + v * (S1 + z * r)
        }
    }

    /// cosine on [-pi/4, pi/4]; `y` is the tail of `x`
    fn k_cos(x: f64, y: f64) -> f64 {
        let z = x * x;
        let w = z * z;
        let r = z * (C1 + z * (C2 + z * C3)) + w * w * (C4 + z * (C5 + z * C6));
        let hz = 0.5 * z;
        let w = 1.0 - hz;
        w + (((1.0 - w) - hz) + (z * r - x * y))
    }

    fn exponent(x: f64) -> i32 {
        ((x.to_bits() >> 52) & 0x7ff) as i32
    }

    /// `x` reduced to (quadrant, y0, y1) with `y0 + y1` in [-pi/4, pi/4].
    /// None beyond the range the three-part reduction covers.
    fn rem_pio2(x: f64) -> Option<(i32, f64, f64)> {
        // 2^20 * pi/2
        if !(x > -1647099.0 && x < 1647099.0) {
            return None;
        }
        let f = round(x * INVPIO2);
        let n = f as i32;
        let mut r = x - f * PIO2_1;
        let mut w = f * PIO2_1T;
        let mut y0 = r - w;
        let ex = exponent(x);
        if ex - exponent(y0) > 16 {
            let t = r;
            w = f * PIO2_2;
            r = t - w;
            w = f * PIO2_2T - ((t - r) - w);
            y0 = r - w;
            if ex - exponent(y0) > 49 {
                let t = r;
                w = f * PIO2_3;
                r = t - w;
                w = f * PIO2_3T - ((t - r) - w);
                y0 = r - w;
            }
        }
        let y1 = (r - y0) - w;
        Some((n, y0, y1))
    }

    /// The sine of `x` radians. None when `x` is outside +-1647099.
    pub fn sin(x: f64) -> Option<f64> {
        if x > -0.7853981633974483 && x < 0.7853981633974483 {
            if x > -1.4901161193847656e-08 && x < 1.4901161193847656e-08 {
                return Some(x);
            }
            return Some(k_sin(x, 0.0, false));
        }
        let (n, y0, y1) = rem_pio2(x)?;
        Some(match n & 3 {
            0 => k_sin(y0, y1, true),
            1 => k_cos(y0, y1),
            2 => -k_sin(y0, y1, true),
            _ => -k_cos(y0, y1),
        })
    }

    /// The cosine of `x` radians. None when `x` is outside +-1647099.
    pub fn cos(x: f64) -> Option<f64> {
        if x > -0.7853981633974483 && x < 0.7853981633974483 {
            return Some(k_cos(x, 0.0));
        }
        let (n, y0, y1) = rem_pio2(x)?;
        Some(match n & 3 {
            0 => k_cos(y0, y1),
            1 => -k_sin(y0, y1, true),
            2 => -k_cos(y0, y1),
            _ => k_sin(y0, y1, true),
        })
    }

    const ATANHI: [f64; 4] = [
        4.63647609000806093515e-01,
        7.85398163397448278999e-01,
        9.82793723247329054082e-01,
        1.57079632679489655800e+00,
    ];
    const ATANLO: [f64; 4] = [
        2.26987774529616870924e-17,
        3.06161699786838301793e-17,
        1.39033110312309984516e-17,
        6.12323399573676603587e-17,
    ];
    const AT: [f64; 11] = [
        3.33333333333329318027e-01,
        -1.99999999998764832476e-01,
        1.42857142725034663711e-01,
        -1.11111104054623557880e-01,
        9.09088713343650656196e-02,
        -7.69187620504482999495e-02,
        6.66107313738753120669e-02,
        -5.83357013379057348645e-02,
        4.97687799461593236017e-02,
        -3.65315727442169155270e-02,
        1.62858201153657823623e-02,
    ];

    fn atan(x: f64) -> f64 {
        let neg = x < 0.0;
        let ax = if neg { -x } else { x };
        if ax >= 7.378697629483821e19 {
            // 2^66 and beyond
            let z = ATANHI[3] + ATANLO[3];
            return if neg { -z } else { z };
        }
        let (id, x) = if ax < 0.4375 {
            if ax < 7.450580596923828e-09 {
                return x;
            }
            (usize::MAX, x)
        } else if ax < 1.1875 {
            if ax < 0.6875 {
                (0, (2.0 * ax - 1.0) / (2.0 + ax))
            } else {
                (1, (ax - 1.0) / (ax + 1.0))
            }
        } else if ax < 2.4375 {
            (2, (ax - 1.5) / (1.0 + 1.5 * ax))
        } else {
            (3, -1.0 / ax)
        };
        let z = x * x;
        let w = z * z;
        let s1 = z * (AT[0] + w * (AT[2] + w * (AT[4] + w * (AT[6] + w * (AT[8] + w * AT[10])))));
        let s2 = w * (AT[1] + w * (AT[3] + w * (AT[5] + w * (AT[7] + w * AT[9]))));
        if id == usize::MAX {
            return x - x * (s1 + s2);
        }
        let z = ATANHI[id] - ((x * (s1 + s2) - ATANLO[id]) - x);
        if neg {
            -z
        } else {
            z
        }
    }

    const PI: f64 = 3.1415926535897931160e+00;
    const PI_LO: f64 = 1.2246467991473531772e-16;

    /// The angle of the point (x, y) in radians, for finite arguments.
    pub fn atan2(y: f64, x: f64) -> f64 {
        let y_neg = y.to_bits() >> 63 != 0;
        let x_neg = x.to_bits() >> 63 != 0;
        if y == 0.0 {
            return match (x_neg, y_neg) {
                (false, _) => y,
                (true, false) => PI,
                (true, true) => -PI,
            };
        }
        if x == 0.0 {
            return if y_neg { -PI / 2.0 } else { PI / 2.0 };
        }
        let k = exponent(y) - exponent(x);
        let z = if k > 64 {
            PI / 2.0
        } else if x_neg && k < -64 {
            0.0
        } else {
            let q = y / x;
            atan(if q < 0.0 { -q } else { q })
        };
        match (x_neg, y_neg) {
            (false, false) => z,
            (false, true) => -z,
            (true, false) => PI - (z - PI_LO),
            (true, true) => (z - PI_LO) - PI,
        }
    }
}

#[cfg(feature = "trig")]
pub use trig::{atan2, cos, sin};
