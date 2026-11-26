//! The CPU time of the calling thread, for the tests that bound how long a
//! piece of work takes: a busy machine stretches the wall clock, not this.
//! Compiled into the library's own tests (lib.rs) and included by path into the
//! integration tests that time work (tests/run.rs, tests/fuzz.rs).

use std::time::Duration;

/// The CPU time this thread has used. On a loaded machine the wall clock
/// counts the time other processes run, and that is not this code's time.
/// The timespec below is two 64-bit fields, as on 64-bit Linux and macOS.
#[cfg(all(any(target_os = "linux", target_os = "macos"), target_pointer_width = "64"))]
pub fn thread_cpu_time() -> Duration {
    #[repr(C)]
    struct Timespec {
        sec: i64,
        nsec: i64,
    }
    extern "C" {
        fn clock_gettime(clock: i32, t: *mut Timespec) -> i32;
    }
    #[cfg(target_os = "linux")]
    const THREAD_CPU: i32 = 3;
    #[cfg(target_os = "macos")]
    const THREAD_CPU: i32 = 16;
    let mut t = Timespec { sec: 0, nsec: 0 };
    // SAFETY: clock_gettime writes one timespec into t and reads nothing else.
    let rc = unsafe { clock_gettime(THREAD_CPU, &mut t) };
    assert_eq!(rc, 0, "clock_gettime of the thread's CPU time");
    Duration::new(t.sec as u64, t.nsec as u32)
}

/// Elsewhere the wall clock stands in, measured from the first call.
#[cfg(not(all(any(target_os = "linux", target_os = "macos"), target_pointer_width = "64")))]
pub fn thread_cpu_time() -> Duration {
    use std::sync::OnceLock;
    use std::time::Instant;
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed()
}
