//! The arithmetic gt-core carries because `core` has none of it, against the
//! standard library on the host.
//!
//! `round` and `sqrt` must be bit for bit the host's. `sin`, `cos` and
//! `atan2` are not required to be: platform libraries differ among
//! themselves in the last bit, and the specification compares a derived
//! float within 1e-9 relative. The bound checked here is 4e-16 relative,
//! about two units in the last place.

use gt_core::num;
use gt_proof::Rng;

fn doubles(rng: &mut Rng, n: usize) -> Vec<f64> {
    let mut v: Vec<f64> = vec![0.0, -0.0, 0.5, -0.5, 1.5, 2.5, -2.5, 0.49999999999999994, 4503599627370495.5, 1e300, -1e300, 5e-324];
    for _ in 0..n {
        // any bit pattern, and values of ordinary size
        v.push(f64::from_bits(rng.next()));
        v.push((rng.next() as i64 as f64) / 4294967296.0 / 1024.0);
    }
    v
}

#[test]
fn round_is_the_standard_round() {
    let mut rng = Rng(11);
    for x in doubles(&mut rng, 200_000) {
        let (got, want) = (num::round(x), x.round());
        assert!(got.to_bits() == want.to_bits() || (got.is_nan() && want.is_nan()) || got == want, "round({:e})", x);
    }
}

#[test]
fn sqrt_is_correctly_rounded() {
    let mut rng = Rng(12);
    for x in doubles(&mut rng, 200_000) {
        let (got, want) = (num::sqrt(x), x.sqrt());
        assert!(got.to_bits() == want.to_bits() || (got.is_nan() && want.is_nan()), "sqrt({:e}): {:e} want {:e}", x, got, want);
    }
}

fn close(got: f64, want: f64) -> bool {
    got == want || (got - want).abs() <= 4e-16 * want.abs().max(1e-300)
}

#[test]
fn sine_and_cosine_within_two_units_in_the_last_place() {
    let mut rng = Rng(13);
    let mut worst = 0.0f64;
    for i in 0..400_000 {
        // degrees a course can take, and radians across the reduction's whole range
        let x = if i % 2 == 0 {
            (rng.next() % 72_000_000) as f64 / 100_000.0 * (std::f64::consts::PI / 180.0)
        } else {
            (rng.next() as i64 as f64) / 9.3e12
        };
        for (got, want) in [(num::sin(x), x.sin()), (num::cos(x), x.cos())] {
            let got = got.unwrap_or_else(|| panic!("{} is inside the range", x));
            // near a zero of the function the result is tiny and its relative error is the reduction's
            assert!(close(got, want) || (got - want).abs() < 1e-17, "x = {:e}: {:e} want {:e}", x, got, want);
            if want != 0.0 {
                worst = worst.max(((got - want) / want).abs());
            }
        }
    }
    eprintln!("sin, cos: largest relative difference from the host library {:e}", worst);
    assert!(num::sin(1e9).is_none() && num::cos(-1e9).is_none());
}

#[test]
fn atan2_within_two_units_in_the_last_place() {
    let mut rng = Rng(14);
    let mut worst = 0.0f64;
    let mut pairs: Vec<(f64, f64)> = vec![(0.0, 1.0), (0.0, -1.0), (1.0, 0.0), (-1.0, 0.0), (3.0, 4.0), (-12.5, 4.25), (1.0, 1.0)];
    for _ in 0..300_000 {
        let scale = |r: u64| (r as i64 as f64) / 9.2e15 * 10f64.powi((r % 9) as i32 - 3);
        pairs.push((scale(rng.next()), scale(rng.next())));
    }
    for (y, x) in pairs {
        let (got, want) = (num::atan2(y, x), y.atan2(x));
        assert!(close(got, want), "atan2({:e}, {:e}): {:e} want {:e}", y, x, got, want);
        if want != 0.0 {
            worst = worst.max(((got - want) / want).abs());
        }
    }
    eprintln!("atan2: largest relative difference from the host library {:e}", worst);
}
