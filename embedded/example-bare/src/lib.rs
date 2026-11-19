//! gt-core and one compiled plan, callable from C firmware.
//!
//! The plan turns an ASTM F3411 Remote ID Location message (25 bytes) into
//! an ASTERIX CAT062 data block holding one track record. Latitude,
//! longitude and geodetic altitude are carried from the message. The five
//! values CAT062 requires and a Remote ID Location message does not hold
//! come from the caller: the data source identifier (SAC, SIC), the time of
//! day, the track number and the confirmed flag.
//!
//! `build.rs` compiles the plan with `tools/gen/packc.py`; see
//! `include/gt_example.h` for the C side.
#![no_std]

use gt_core::{KeyId, Plan, Scratch, Value};

include!(concat!(env!("OUT_DIR"), "/plan.rs"));

/// What the caller supplies for each record.
#[repr(C)]
pub struct GtCat062Context {
    /// I062/070: seconds since the last UTC midnight
    pub time_of_day_s: f64,
    /// I062/040: track number, 0 to 65535
    pub track_number: u16,
    /// I062/010: system area code
    pub sac: u8,
    /// I062/010: system identification code
    pub sic: u8,
    /// 1: the track is confirmed, 0: tentative
    pub confirmed: u8,
}

/// Convert one Remote ID Location message to one CAT062 data block.
///
/// Returns the number of bytes written to `out`, or a negative error code:
/// -1 no-kind (not a Location message), -2 malformed-wire, -3
/// transform-decode, -4 transform-encode, -5 undeclared-key, -6
/// key-type-mismatch, -7 `out` too short, -8 scratch too small, -9 bad plan,
/// -10 a null pointer.
///
/// # Safety
///
/// `input` points to `input_len` readable bytes, `out` to `out_cap` writable
/// bytes that do not overlap the input, and `ctx` to one `GtCat062Context`.
#[no_mangle]
pub unsafe extern "C" fn gt_rid_location_to_cat062(
    input: *const u8,
    input_len: usize,
    out: *mut u8,
    out_cap: usize,
    ctx: *const GtCat062Context,
) -> i32 {
    if input.is_null() || out.is_null() || ctx.is_null() {
        return -10;
    }
    // SAFETY: the caller's contract, stated above.
    let (input, out, ctx) = unsafe {
        (core::slice::from_raw_parts(input, input_len), core::slice::from_raw_parts_mut(out, out_cap), &*ctx)
    };
    match convert(input, out, ctx) {
        Ok(n) => n as i32,
        Err(e) => -(e as i32 + 1),
    }
}

/// The same conversion for Rust callers.
pub fn convert(input: &[u8], out: &mut [u8], ctx: &GtCat062Context) -> Result<usize, gt_core::Error> {
    let plan = Plan::parse(&PLAN)?;
    // three carried values and five from the context
    let mut scratch = Scratch::<12>::new();
    let context = [
        (KeyId(KEY_CAT062_SAC), Value::Int(ctx.sac as i64)),
        (KeyId(KEY_CAT062_SIC), Value::Int(ctx.sic as i64)),
        (KeyId(KEY_CAT062_TIME_OF_DAY_S), Value::Float(ctx.time_of_day_s)),
        (KeyId(KEY_CAT062_TRACK_NUMBER), Value::Int(ctx.track_number as i64)),
        (KeyId(KEY_TRACK_CONFIRMED), Value::Int(ctx.confirmed as i64)),
    ];
    gt_core::convert(&plan, input, out, &mut scratch, &context)
}

#[cfg(all(not(test), target_os = "none"))]
#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! {
    loop {}
}
