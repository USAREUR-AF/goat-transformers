//! WebAssembly module of the goat-transformers reference engine, for
//! `wasm32-unknown-unknown`. No imports, no global state.
//!
//! For shipping only: a host embeds this module instead of carrying a native
//! engine. It is never a voice in the vector cross-check
//! (`spec/interop-and-sharing.md`).
//!
//! The interface, as `goat_transformers.mjs` drives it:
//! - the host writes each text argument into linear memory it got from
//!   `gt_alloc`, passes pointer + byte length, and releases it with `gt_free`;
//! - an engine is a handle from `gt_engine_new`;
//! - a load, a convert and a formats call return a result handle; the host
//!   reads `gt_result_ok`, `gt_result_ptr`, `gt_result_len`, copies the bytes
//!   out of linear memory, and calls `gt_result_free`.
//!
//! A panic is a trap on this target (it does not unwind), and a trap leaves
//! the instance's stack pointer where it was. The host must drop the instance
//! after a trap; `goat_transformers.mjs` does.

use goat_transformers::Engine;

/// The outcome of one call: `ok` and the result text, or the error text.
pub struct GtResult {
    ok: bool,
    bytes: Vec<u8>,
}

fn result(r: Result<String, String>) -> *mut GtResult {
    let (ok, s) = match r {
        Ok(s) => (true, s),
        Err(s) => (false, s),
    };
    Box::into_raw(Box::new(GtResult { ok, bytes: s.into_bytes() }))
}

unsafe fn text<'a>(ptr: *const u8, len: usize, what: &str) -> Result<&'a str, String> {
    if len == 0 {
        return Ok("");
    }
    if ptr.is_null() {
        return Err(format!("bad-argument: {} is a null pointer", what));
    }
    std::str::from_utf8(std::slice::from_raw_parts(ptr, len)).map_err(|_| format!("bad-argument: {} is not UTF-8", what))
}

/// Context text: one `key=value` per line, lines end with `\n`, the key ends
/// at the first `=`. Empty lines are skipped.
fn parse_context(text: &str) -> Result<Vec<(String, String)>, String> {
    let mut pairs = Vec::new();
    for line in text.split('\n') {
        if line.is_empty() {
            continue;
        }
        match line.split_once('=') {
            Some((k, v)) => pairs.push((k.to_string(), v.to_string())),
            None => return Err(format!("bad-argument: context line `{}` is not key=value", line)),
        }
    }
    Ok(pairs)
}

/// `len` bytes of linear memory for the host to write an argument into.
#[no_mangle]
pub extern "C" fn gt_alloc(len: usize) -> *mut u8 {
    let mut v: Vec<u8> = Vec::with_capacity(len);
    let p = v.as_mut_ptr();
    std::mem::forget(v);
    p
}

/// Release memory from `gt_alloc`, with the same length.
///
/// # Safety
/// `ptr` came from `gt_alloc(len)` and is not used again.
#[no_mangle]
pub unsafe extern "C" fn gt_free(ptr: *mut u8, len: usize) {
    drop(Vec::from_raw_parts(ptr, 0, len));
}

/// A new, empty engine.
#[no_mangle]
pub extern "C" fn gt_engine_new() -> *mut Engine {
    Box::into_raw(Box::new(Engine::new()))
}

/// Release an engine.
///
/// # Safety
/// `engine` came from `gt_engine_new` and is not used again.
#[no_mangle]
pub unsafe extern "C" fn gt_engine_free(engine: *mut Engine) {
    if !engine.is_null() {
        drop(Box::from_raw(engine));
    }
}

/// Load one model module from the text of a `model/<module>.def`.
///
/// # Safety
/// `engine` came from `gt_engine_new`; `ptr` is valid for `len` bytes.
#[no_mangle]
pub unsafe extern "C" fn gt_load_model(engine: *mut Engine, ptr: *const u8, len: usize) -> *mut GtResult {
    result((|| {
        let t = text(ptr, len, "model text")?;
        (*engine).load_model(t).map_err(|e| e.msg)?;
        Ok(String::new())
    })())
}

/// Load one pack from the text of a `packs/<format>/pack.def`.
///
/// # Safety
/// As `gt_load_model`.
#[no_mangle]
pub unsafe extern "C" fn gt_load_pack(engine: *mut Engine, ptr: *const u8, len: usize) -> *mut GtResult {
    result((|| {
        let t = text(ptr, len, "pack text")?;
        (*engine).load_def(t).map_err(|e| e.msg)?;
        Ok(String::new())
    })())
}

/// Convert `input` from format `from` to format `to`. `has_context` 0: no
/// context; otherwise the context is `key=value\n` text (length 0: an empty
/// context, which still counts as a context given).
///
/// # Safety
/// `engine` came from `gt_engine_new`; each pointer is valid for its length.
#[no_mangle]
pub unsafe extern "C" fn gt_convert(
    engine: *const Engine,
    from: *const u8,
    from_len: usize,
    to: *const u8,
    to_len: usize,
    input: *const u8,
    input_len: usize,
    has_context: i32,
    context: *const u8,
    context_len: usize,
) -> *mut GtResult {
    result((|| {
        let from = text(from, from_len, "from")?;
        let to = text(to, to_len, "to")?;
        let input = text(input, input_len, "input")?;
        let pairs = if has_context == 0 { None } else { Some(parse_context(text(context, context_len, "context")?)?) };
        (*engine).convert_text(from, to, input, pairs.as_deref()).map_err(|e| e.msg)
    })())
}

/// The loaded format names, sorted, one per line (each ends with `\n`).
///
/// # Safety
/// `engine` came from `gt_engine_new`.
#[no_mangle]
pub unsafe extern "C" fn gt_formats(engine: *const Engine) -> *mut GtResult {
    result(Ok((*engine).formats().iter().map(|f| format!("{}\n", f)).collect()))
}

/// 1 when the call succeeded, 0 when the result holds an error text.
///
/// # Safety
/// `r` is a live result handle (also for the three calls below).
#[no_mangle]
pub unsafe extern "C" fn gt_result_ok(r: *const GtResult) -> i32 {
    (*r).ok as i32
}

/// Where the result's bytes are in linear memory.
#[no_mangle]
pub unsafe extern "C" fn gt_result_ptr(r: *const GtResult) -> *const u8 {
    (*r).bytes.as_ptr()
}

/// How many bytes the result holds.
#[no_mangle]
pub unsafe extern "C" fn gt_result_len(r: *const GtResult) -> usize {
    (*r).bytes.len()
}

/// Release a result handle.
#[no_mangle]
pub unsafe extern "C" fn gt_result_free(r: *mut GtResult) {
    if !r.is_null() {
        drop(Box::from_raw(r));
    }
}
