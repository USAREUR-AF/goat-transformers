//! C ABI of the goat-transformers reference engine (`goat_transformers.h`).
//!
//! For shipping only: a host in another language embeds this library instead
//! of carrying a native engine. It is never a voice in the vector cross-check
//! (`spec/interop-and-sharing.md`).
//!
//! Rules of the boundary:
//! - no global state: everything hangs off a `gt_engine` handle;
//! - no panic crosses it: every entry point runs under `catch_unwind`;
//! - every text argument is a pointer and a byte length, UTF-8, no NUL needed;
//! - every result is a status code and an owned `gt_buf` the caller frees.

use goat_transformers::Engine;
use std::panic::{catch_unwind, AssertUnwindSafe};

/// The call succeeded; the buffer holds the result (empty for a load).
pub const GT_OK: i32 = 0;
/// The engine refused; the buffer holds its named error (`<kind>: <text>`).
pub const GT_ERR_ENGINE: i32 = 1;
/// An argument was unusable (null, not UTF-8, a context line with no `=`);
/// the buffer holds `bad-argument: <text>`.
pub const GT_ERR_ARGUMENT: i32 = 2;
/// The engine panicked; the buffer holds `panic: <text>`. A panic inside a
/// load leaves the engine refusing every later call.
pub const GT_ERR_PANIC: i32 = 3;

/// Opaque engine handle.
pub struct GtEngine {
    inner: Engine,
    /// set when a load panicked: the loaded set may be half-changed
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

type Outcome = Result<String, (i32, String)>;

fn bad<T>(msg: impl Into<String>) -> Result<T, (i32, String)> {
    Err((GT_ERR_ARGUMENT, format!("bad-argument: {}", msg.into())))
}

fn engine_err(e: goat_transformers::Error) -> (i32, String) {
    (GT_ERR_ENGINE, e.msg)
}

/// Read a pointer + length argument as text. A null pointer with length 0 is
/// the empty text.
unsafe fn text<'a>(ptr: *const u8, len: usize, what: &str) -> Result<&'a str, (i32, String)> {
    if ptr.is_null() {
        if len == 0 {
            return Ok("");
        }
        return bad(format!("{} is a null pointer", what));
    }
    let bytes = std::slice::from_raw_parts(ptr, len);
    match std::str::from_utf8(bytes) {
        Ok(s) => Ok(s),
        Err(_) => bad(format!("{} is not UTF-8", what)),
    }
}

/// Context text: one `key=value` per line, lines end with `\n`, the key ends
/// at the first `=`. Empty lines are skipped.
fn parse_context(text: &str) -> Result<Vec<(String, String)>, (i32, String)> {
    let mut pairs = Vec::new();
    for line in text.split('\n') {
        if line.is_empty() {
            continue;
        }
        match line.split_once('=') {
            Some((k, v)) => pairs.push((k.to_string(), v.to_string())),
            None => return bad(format!("context line `{}` is not key=value", line)),
        }
    }
    Ok(pairs)
}

fn into_buf(s: String) -> GtBuf {
    let mut v = s.into_bytes();
    let len = v.len();
    v.push(0);
    let b = v.into_boxed_slice();
    GtBuf { data: Box::into_raw(b) as *mut u8, len }
}

fn panic_text(p: Box<dyn std::any::Any + Send>) -> String {
    let what = if let Some(s) = p.downcast_ref::<&str>() {
        (*s).to_string()
    } else if let Some(s) = p.downcast_ref::<String>() {
        s.clone()
    } else {
        "no message".to_string()
    };
    format!("panic: {}", what)
}

/// Run `f` with no panic leaving it, and hand its outcome to the caller.
unsafe fn finish(out: *mut GtBuf, f: impl FnOnce() -> Outcome) -> i32 {
    let (code, textual) = match catch_unwind(AssertUnwindSafe(f)) {
        Ok(Ok(s)) => (GT_OK, s),
        Ok(Err((code, msg))) => (code, msg),
        Err(p) => (GT_ERR_PANIC, panic_text(p)),
    };
    if !out.is_null() {
        // the buffer itself is built outside `f`; an allocation failure aborts
        out.write(into_buf(textual));
    }
    code
}

unsafe fn engine_ref<'a>(e: *const GtEngine) -> Result<&'a GtEngine, (i32, String)> {
    match e.as_ref() {
        None => bad("engine is a null pointer"),
        Some(e) if e.poisoned => Err((GT_ERR_PANIC, "panic: a load panicked earlier; free this engine".to_string())),
        Some(e) => Ok(e),
    }
}

unsafe fn load(
    e: *mut GtEngine,
    ptr: *const u8,
    len: usize,
    out: *mut GtBuf,
    what: &str,
    f: fn(&mut Engine, &str) -> Result<(), goat_transformers::Error>,
) -> i32 {
    let code = finish(out, || {
        engine_ref(e)?;
        let t = text(ptr, len, what)?;
        f(&mut (*e).inner, t).map_err(engine_err)?;
        Ok(String::new())
    });
    if code == GT_ERR_PANIC && !e.is_null() {
        (*e).poisoned = true;
    }
    code
}

/// A new, empty engine. Never null.
#[no_mangle]
pub extern "C" fn gt_engine_new() -> *mut GtEngine {
    match catch_unwind(|| Box::new(GtEngine { inner: Engine::new(), poisoned: false })) {
        Ok(b) => Box::into_raw(b),
        Err(_) => std::ptr::null_mut(),
    }
}

/// Release an engine. Null is accepted.
///
/// # Safety
/// `engine` is null or came from `gt_engine_new` and is not used again.
#[no_mangle]
pub unsafe extern "C" fn gt_engine_free(engine: *mut GtEngine) {
    if !engine.is_null() {
        let _ = catch_unwind(AssertUnwindSafe(|| drop(Box::from_raw(engine))));
    }
}

/// Load one model module from the text of a `model/<module>.def`. Load `core`
/// first, and every module before the packs that use it.
///
/// # Safety
/// `engine` came from `gt_engine_new`; `text` points to `text_len` bytes;
/// `out` is null or points to a `gt_buf` this call may overwrite.
#[no_mangle]
pub unsafe extern "C" fn gt_load_model(engine: *mut GtEngine, text: *const u8, text_len: usize, out: *mut GtBuf) -> i32 {
    load(engine, text, text_len, out, "model text", Engine::load_model)
}

/// Load one pack from the text of a `packs/<format>/pack.def`.
///
/// # Safety
/// As `gt_load_model`.
#[no_mangle]
pub unsafe extern "C" fn gt_load_pack(engine: *mut GtEngine, text: *const u8, text_len: usize, out: *mut GtBuf) -> i32 {
    load(engine, text, text_len, out, "pack text", Engine::load_def)
}

/// Convert `input` from format `from` to format `to`. `context` is null for
/// "no context", or `key=value\n` text (length 0: an empty context, which
/// still counts as a context given).
///
/// # Safety
/// `engine` came from `gt_engine_new`; each pointer is valid for its length;
/// `out` is null or points to a `gt_buf` this call may overwrite.
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
    finish(out, || {
        let e = engine_ref(engine)?;
        let from = text(from, from_len, "from")?;
        let to = text(to, to_len, "to")?;
        let input = text(input, input_len, "input")?;
        let pairs = if context.is_null() { None } else { Some(parse_context(text(context, context_len, "context")?)?) };
        e.inner.convert_text(from, to, input, pairs.as_deref()).map_err(engine_err)
    })
}

/// The loaded format names, sorted, one per line (each ends with `\n`).
///
/// # Safety
/// `engine` came from `gt_engine_new`; `out` is null or points to a `gt_buf`.
#[no_mangle]
pub unsafe extern "C" fn gt_formats(engine: *const GtEngine, out: *mut GtBuf) -> i32 {
    finish(out, || {
        let e = engine_ref(engine)?;
        Ok(e.inner.formats().iter().map(|f| format!("{}\n", f)).collect())
    })
}

/// Release a buffer a call filled, and clear it. Null and an already cleared
/// buffer are accepted.
///
/// # Safety
/// `buf` is null or points to a `gt_buf` that is zeroed or was filled by this
/// library and not freed since.
#[no_mangle]
pub unsafe extern "C" fn gt_buf_free(buf: *mut GtBuf) {
    if buf.is_null() || (*buf).data.is_null() {
        return;
    }
    let slice = std::ptr::slice_from_raw_parts_mut((*buf).data, (*buf).len + 1);
    (*buf).data = std::ptr::null_mut();
    (*buf).len = 0;
    let _ = catch_unwind(AssertUnwindSafe(|| drop(Box::from_raw(slice))));
}
