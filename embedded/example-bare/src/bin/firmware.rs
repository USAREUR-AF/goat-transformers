//! A linkable image for size measurement: a reset entry that calls the
//! conversion on buffers the optimiser cannot see through. Not a working
//! firmware; `embedded/measure.sh` links it and reads the section sizes.
#![no_std]
#![no_main]

use core::ptr::{read_volatile, write_volatile};
use example_bare::{gt_rid_location_to_cat062, GtCat062Context};

static mut INPUT: [u8; 25] = [0; 25];
static mut OUTPUT: [u8; 32] = [0; 32];
static mut CONTEXT: GtCat062Context = GtCat062Context { time_of_day_s: 0.0, track_number: 0, sac: 0, sic: 0, confirmed: 0 };
static mut RESULT: i32 = 0;

#[no_mangle]
pub unsafe extern "C" fn _start() -> ! {
    loop {
        let input = &raw mut INPUT;
        let out = &raw mut OUTPUT;
        let ctx = &raw mut CONTEXT;
        let len = read_volatile(&raw const RESULT) as usize;
        let n = gt_rid_location_to_cat062(input as *const u8, len, out as *mut u8, 32, ctx);
        write_volatile(&raw mut RESULT, n);
    }
}
