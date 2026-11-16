//! C ABI of the goat-transformers reference engine (`goat_transformers.h`).
//!
//! For shipping only: a host in another language embeds this library instead
//! of carrying a native engine. It is never a voice in the vector cross-check
//! (`spec/interop-and-sharing.md`).
//!
//! Rules of the boundary, stated for the caller in the header:
//! - no global state: everything hangs off a `gt_engine` handle;
//! - no panic crosses it: every entry point runs under `catch_unwind`;
//! - every text argument is a pointer and a byte length, UTF-8, no NUL needed;
//! - every result is a status code and an owned `gt_buf` the caller frees.

#![deny(unsafe_op_in_unsafe_fn)]

#[path = "../../shared/glue.rs"]
mod glue;

use goat_transformers::Engine;
use std::any::Any;
use std::panic::{catch_unwind, AssertUnwindSafe};

/// The call succeeded; the buffer holds the result (empty for a load).
pub const GT_OK: i32 = 0;
/// The engine refused; the buffer holds its named error (`<kind>: <text>`).
pub const GT_ERR_ENGINE: i32 = 1;
/// An argument was unusable (null, not UTF-8, a context line with no `=`);
/// the buffer holds `bad-argument: <text>`.
pub const GT_ERR_ARGUMENT: i32 = 2;
/// The engine panicked; the buffer holds `panic: <text>`. A panic inside a
/// call that changes the engine leaves it refusing every later call.
pub const GT_ERR_PANIC: i32 = 3;

/// The distribution limit `public` for `gt_engine_set_max_distribution`.
pub const GT_DISTRIBUTION_PUBLIC: i32 = glue::DISTRIBUTION_PUBLIC;
/// The distribution limit `controlled`, the default.
pub const GT_DISTRIBUTION_CONTROLLED: i32 = glue::DISTRIBUTION_CONTROLLED;

/// Opaque engine handle.
pub struct GtEngine {
    inner: Engine,
    /// set when a call that changes the engine panicked: the loaded set may
    /// be half-changed
    poisoned: bool,
}

/// An owned byte buffer. `data` holds `len` bytes followed by one NUL, so a
/// text result is also a C string. Released with `gt_buf_free`.
#[repr(C)]
pub struct GtBuf {
    pub data: *mut u8,
    pub len: usize,
}

// An engine may move between threads, and `gt_convert` / `gt_formats` may run
// on several threads at once: this fails to compile if the engine ever stops
// allowing that.
const _: fn() = || {
    fn send_sync<T: Send + Sync>() {}
    send_sync::<Engine>();
};

/// Why a call did not succeed: the status to return and the text for `out`.
struct Failure {
    status: i32,
    text: String,
}

type Outcome = Result<String, Failure>;

fn bad_argument(text: String) -> Failure {
    Failure {
        status: GT_ERR_ARGUMENT,
        text: format!("bad-argument: {text}"),
    }
}

fn engine_error(error: goat_transformers::Error) -> Failure {
    Failure {
        status: GT_ERR_ENGINE,
        text: error.msg,
    }
}

fn poisoned() -> Failure {
    Failure {
        status: GT_ERR_PANIC,
        text: "panic: an earlier call on this engine panicked; free this engine".to_string(),
    }
}

/// The text of a caught panic, as the caller reads it.
fn panic_text(payload: Box<dyn Any + Send>) -> String {
    let message = if let Some(text) = payload.downcast_ref::<&str>() {
        text
    } else if let Some(text) = payload.downcast_ref::<String>() {
        text.as_str()
    } else {
        "no message"
    };
    format!("panic: {message}")
}

/// Move a text into a buffer the caller owns: its bytes, then one NUL.
fn into_buf(text: String) -> GtBuf {
    let mut bytes = text.into_bytes();
    let len = bytes.len();
    bytes.push(0);
    GtBuf {
        data: Box::into_raw(bytes.into_boxed_slice()).cast::<u8>(),
        len,
    }
}

/// Run `call` with no panic leaving it, write its result or its error text
/// to `out`, and return its status.
///
/// # Safety
/// `out` is null or points to a `GtBuf` that may be overwritten.
unsafe fn respond(out: *mut GtBuf, call: impl FnOnce() -> Outcome) -> i32 {
    let (status, text) = match catch_unwind(AssertUnwindSafe(call)) {
        Ok(Ok(text)) => (GT_OK, text),
        Ok(Err(failure)) => (failure.status, failure.text),
        Err(payload) => (GT_ERR_PANIC, panic_text(payload)),
    };
    if !out.is_null() {
        // The buffer is built outside `call`: an allocation failure here
        // aborts the process, as any allocation failure in Rust does.
        // SAFETY: `out` is not null, so by contract it points to a `GtBuf`
        // this call may overwrite. `write` does not read the old value.
        unsafe { out.write(into_buf(text)) };
    }
    status
}

/// The engine behind a handle, for a call that only reads it.
///
/// # Safety
/// `engine` is null or a live handle from `gt_engine_new`, and no call that
/// changes the engine runs during `'a`.
unsafe fn shared<'a>(engine: *const GtEngine) -> Result<&'a Engine, Failure> {
    // SAFETY: by contract the handle is null or live and not being changed.
    match unsafe { engine.as_ref() } {
        None => Err(bad_argument("engine is a null pointer".to_string())),
        Some(handle) if handle.poisoned => Err(poisoned()),
        Some(handle) => Ok(&handle.inner),
    }
}

/// Run `apply` on the engine behind a handle and answer through `out`. A
/// panic inside `apply` may leave the engine half-changed, so it marks the
/// engine and every later call is refused.
///
/// # Safety
/// `engine` is null or a live handle from `gt_engine_new` that no other call
/// uses during this one; `out` is null or points to a `GtBuf` that may be
/// overwritten.
unsafe fn change(
    engine: *mut GtEngine,
    out: *mut GtBuf,
    apply: impl FnOnce(&mut Engine) -> Result<(), Failure>,
) -> i32 {
    // SAFETY: by contract the handle is null or live, and this call has it
    // to itself, so a unique reference may be made.
    let Some(handle) = (unsafe { engine.as_mut() }) else {
        // SAFETY: `out` is passed on under this function's own contract.
        return unsafe {
            respond(out, || {
                Err(bad_argument("engine is a null pointer".to_string()))
            })
        };
    };
    if handle.poisoned {
        // SAFETY: as above.
        return unsafe { respond(out, || Err(poisoned())) };
    }
    let inner = &mut handle.inner;
    // SAFETY: as above.
    let status = unsafe { respond(out, || apply(inner).map(|()| String::new())) };
    if status == GT_ERR_PANIC {
        handle.poisoned = true;
    }
    status
}

/// Read one text argument of a call.
///
/// # Safety
/// As `glue::text`.
unsafe fn text<'a>(ptr: *const u8, len: usize, what: &str) -> Result<&'a str, Failure> {
    // SAFETY: passed on under this function's own contract.
    unsafe { glue::text(ptr, len, what) }.map_err(bad_argument)
}

/// A new, empty engine. Null only if creating it panicked.
#[no_mangle]
pub extern "C" fn gt_engine_new() -> *mut GtEngine {
    let created = catch_unwind(|| {
        Box::new(GtEngine {
            inner: Engine::new(),
            poisoned: false,
        })
    });
    match created {
        Ok(engine) => Box::into_raw(engine),
        Err(_) => std::ptr::null_mut(),
    }
}

/// Release an engine. Null is accepted.
///
/// # Safety
/// `engine` is null, or came from `gt_engine_new`, has not been freed, and is
/// not used by any call during or after this one.
#[no_mangle]
pub unsafe extern "C" fn gt_engine_free(engine: *mut GtEngine) {
    if engine.is_null() {
        return;
    }
    // SAFETY: by contract `engine` came from `Box::into_raw` in
    // `gt_engine_new` and this is the only release of it.
    let owned = unsafe { Box::from_raw(engine) };
    let _ = catch_unwind(AssertUnwindSafe(|| drop(owned)));
}

/// Limit what the engine loads: `GT_DISTRIBUTION_PUBLIC` makes every later
/// load of a `controlled` model module or pack fail with
/// `distribution-refused`. Refused on an engine that has loaded anything.
///
/// # Safety
/// `engine` is null or a live handle from `gt_engine_new` that no other call
/// uses during this one; `out` is null or points to a `gt_buf` this call may
/// overwrite.
#[no_mangle]
pub unsafe extern "C" fn gt_engine_set_max_distribution(
    engine: *mut GtEngine,
    limit: i32,
    out: *mut GtBuf,
) -> i32 {
    // SAFETY: passed on under this function's own contract.
    unsafe {
        change(engine, out, |engine| {
            glue::set_max_distribution(engine, limit).map_err(bad_argument)
        })
    }
}

/// Load one model module from the text of a `model/<module>.def`. Load `core`
/// first, and every module before the packs that use it.
///
/// # Safety
/// `engine` is null or a live handle from `gt_engine_new` that no other call
/// uses during this one; `text` is null with `text_len` 0 or points to
/// `text_len` readable bytes; `out` is null or points to a `gt_buf` this call
/// may overwrite.
#[no_mangle]
pub unsafe extern "C" fn gt_load_model(
    engine: *mut GtEngine,
    text: *const u8,
    text_len: usize,
    out: *mut GtBuf,
) -> i32 {
    // SAFETY: passed on under this function's own contract.
    unsafe {
        change(engine, out, |engine| {
            let text = self::text(text, text_len, "model text")?;
            engine.load_model(text).map_err(engine_error)
        })
    }
}

/// Load one pack from the text of a `packs/<format>/pack.def`.
///
/// # Safety
/// As `gt_load_model`.
#[no_mangle]
pub unsafe extern "C" fn gt_load_pack(
    engine: *mut GtEngine,
    text: *const u8,
    text_len: usize,
    out: *mut GtBuf,
) -> i32 {
    // SAFETY: passed on under this function's own contract.
    unsafe {
        change(engine, out, |engine| {
            let text = self::text(text, text_len, "pack text")?;
            engine.load_def(text).map_err(engine_error)
        })
    }
}

/// Convert `input` from format `from` to format `to`. `context` is null for
/// "no context", or `key=value\n` text (length 0: an empty context, which
/// still counts as a context given).
///
/// # Safety
/// `engine` is null or a live handle from `gt_engine_new` that no load, no
/// `gt_engine_set_max_distribution` and no `gt_engine_free` uses during this
/// call; each text pointer is null with length 0 or points to that many
/// readable bytes; `out` is null or points to a `gt_buf` this call may
/// overwrite.
#[no_mangle]
pub unsafe extern "C" fn gt_convert(
    engine: *const GtEngine,
    from: *const u8,
    from_len: usize,
    to: *const u8,
    to_len: usize,
    input: *const u8,
    input_len: usize,
    context: *const u8,
    context_len: usize,
    out: *mut GtBuf,
) -> i32 {
    let call = || {
        // SAFETY: the handle and each text are passed on under this
        // function's own contract.
        let engine = unsafe { shared(engine) }?;
        // SAFETY: as above.
        let from = unsafe { text(from, from_len, "from") }?;
        // SAFETY: as above.
        let to = unsafe { text(to, to_len, "to") }?;
        // SAFETY: as above.
        let input = unsafe { text(input, input_len, "input") }?;
        let pairs = if context.is_null() {
            None
        } else {
            // SAFETY: as above.
            let context = unsafe { text(context, context_len, "context") }?;
            Some(glue::parse_context(context).map_err(bad_argument)?)
        };
        engine
            .convert_text(from, to, input, pairs.as_deref())
            .map_err(engine_error)
    };
    // SAFETY: `out` is passed on under this function's own contract.
    unsafe { respond(out, call) }
}

/// The loaded format names, sorted, one per line (each ends with `\n`).
///
/// # Safety
/// `engine` is as for `gt_convert`; `out` is null or points to a `gt_buf`
/// this call may overwrite.
#[no_mangle]
pub unsafe extern "C" fn gt_formats(engine: *const GtEngine, out: *mut GtBuf) -> i32 {
    // SAFETY: the handle and `out` are passed on under this function's own
    // contract.
    unsafe { respond(out, || Ok(glue::formats_text(shared(engine)?))) }
}

/// Release a buffer a call filled, and clear it. Null and an already cleared
/// buffer are accepted.
///
/// # Safety
/// `buf` is null or points to a `gt_buf` that is zeroed, or that a call of
/// this library filled and that has not been freed since, through this
/// `gt_buf` or through a copy of it.
#[no_mangle]
pub unsafe extern "C" fn gt_buf_free(buf: *mut GtBuf) {
    // SAFETY: by contract `buf` is null or points to a `gt_buf`.
    let Some(buf) = (unsafe { buf.as_mut() }) else {
        return;
    };
    if buf.data.is_null() {
        return;
    }
    let bytes = std::ptr::slice_from_raw_parts_mut(buf.data, buf.len + 1);
    buf.data = std::ptr::null_mut();
    buf.len = 0;
    // SAFETY: by contract `data` and `len` are as `into_buf` left them: a
    // boxed slice of `len` bytes and one NUL, released here and only here.
    drop(unsafe { Box::from_raw(bytes) });
}

#[cfg(test)]
mod tests {
    //! What the C test cannot reach: a panic inside the library. The C ABI
    //! itself is tested from C (`test/`).
    use super::*;

    fn read(buf: &mut GtBuf) -> String {
        assert!(!buf.data.is_null());
        // SAFETY: `buf` was filled by `respond`, which wrote `len` bytes.
        let text = unsafe { std::slice::from_raw_parts(buf.data, buf.len) }.to_vec();
        // SAFETY: `buf` was filled by this library and is freed once.
        unsafe { gt_buf_free(buf) };
        String::from_utf8(text).unwrap()
    }

    fn empty_buf() -> GtBuf {
        GtBuf {
            data: std::ptr::null_mut(),
            len: 0,
        }
    }

    #[test]
    fn a_panic_becomes_a_status_and_a_text() {
        let mut out = empty_buf();
        // SAFETY: `out` is a live `GtBuf`.
        let status = unsafe { respond(&mut out, || panic!("the cause")) };
        assert_eq!(status, GT_ERR_PANIC);
        assert_eq!(read(&mut out), "panic: the cause");
    }

    #[test]
    fn a_panic_with_a_formatted_message_keeps_it() {
        let mut out = empty_buf();
        let n = 7;
        // SAFETY: `out` is a live `GtBuf`.
        let status = unsafe { respond(&mut out, || panic!("value {n}")) };
        assert_eq!(status, GT_ERR_PANIC);
        assert_eq!(read(&mut out), "panic: value 7");
    }

    #[test]
    fn a_panic_with_another_payload_is_still_a_text() {
        let mut out = empty_buf();
        // SAFETY: `out` is a live `GtBuf`.
        let status = unsafe { respond(&mut out, || std::panic::panic_any(42_u8)) };
        assert_eq!(status, GT_ERR_PANIC);
        assert_eq!(read(&mut out), "panic: no message");
    }

    #[test]
    fn a_panic_with_no_out_is_still_only_a_status() {
        // SAFETY: a null `out` is allowed.
        let status = unsafe { respond(std::ptr::null_mut(), || panic!("unseen")) };
        assert_eq!(status, GT_ERR_PANIC);
    }

    #[test]
    fn a_panic_while_changing_the_engine_stops_the_engine() {
        let engine = gt_engine_new();
        let mut out = empty_buf();
        // SAFETY: `engine` is live and used by this thread only; `out` is a
        // live `GtBuf`, freed by `read` after every call.
        unsafe {
            assert_eq!(
                change(engine, &mut out, |_| panic!("half loaded")),
                GT_ERR_PANIC
            );
            assert_eq!(read(&mut out), "panic: half loaded");

            assert_eq!(gt_formats(engine, &mut out), GT_ERR_PANIC);
            assert!(read(&mut out).starts_with("panic: an earlier call"));
            assert_eq!(
                gt_load_model(engine, std::ptr::null(), 0, &mut out),
                GT_ERR_PANIC
            );
            assert!(read(&mut out).starts_with("panic: an earlier call"));
            let status = gt_convert(
                engine,
                std::ptr::null(),
                0,
                std::ptr::null(),
                0,
                std::ptr::null(),
                0,
                std::ptr::null(),
                0,
                &mut out,
            );
            assert_eq!(status, GT_ERR_PANIC);
            assert!(read(&mut out).starts_with("panic: an earlier call"));

            gt_engine_free(engine);
        }
    }

    #[test]
    fn a_refusal_does_not_stop_the_engine() {
        let engine = gt_engine_new();
        let mut out = empty_buf();
        // SAFETY: as in the test above.
        unsafe {
            let status = change(engine, &mut out, |_| Err(bad_argument("no".to_string())));
            assert_eq!(status, GT_ERR_ARGUMENT);
            assert_eq!(read(&mut out), "bad-argument: no");
            assert_eq!(gt_formats(engine, &mut out), GT_OK);
            assert_eq!(read(&mut out), "");
            gt_engine_free(engine);
        }
    }
}
