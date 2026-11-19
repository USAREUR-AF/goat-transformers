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
//! - a load, a convert, a formats call and a change of the distribution limit
//!   return a result handle; the host reads `gt_result_ok`, `gt_result_ptr`,
//!   `gt_result_len`, copies the bytes out of linear memory, and calls
//!   `gt_result_free`.
//!
//! A handle of 0 is refused with an error (`bad-argument`), never read:
//! address 0 is ordinary memory in WebAssembly, so nothing else would stop it.
//!
//! A panic is a trap on this target (it does not unwind), and a trap leaves
//! the instance's stack pointer where it was. The host must drop the instance
//! after a trap; `goat_transformers.mjs` does.

#![deny(unsafe_op_in_unsafe_fn)]

#[path = "../../shared/glue.rs"]
mod glue;

use goat_transformers::Engine;

/// The outcome of one call: `ok` and the result text, or the error text.
pub struct GtResult {
    ok: bool,
    bytes: Vec<u8>,
}

/// Move the outcome of a call to the heap and give the host its handle.
fn into_result(outcome: Result<String, String>) -> *mut GtResult {
    let (ok, text) = match outcome {
        Ok(text) => (true, text),
        Err(text) => (false, text),
    };
    Box::into_raw(Box::new(GtResult {
        ok,
        bytes: text.into_bytes(),
    }))
}

fn bad_argument(text: String) -> String {
    format!("bad-argument: {text}")
}

/// Read one text argument of a call.
///
/// # Safety
/// As `glue::text`.
unsafe fn text<'a>(ptr: *const u8, len: usize, what: &str) -> Result<&'a str, String> {
    // SAFETY: passed on under this function's own contract.
    unsafe { glue::text(ptr, len, what) }.map_err(bad_argument)
}

/// The engine behind a handle, for a call that only reads it.
///
/// # Safety
/// `engine` is 0 or a live handle from `gt_engine_new`.
unsafe fn shared<'a>(engine: *const Engine) -> Result<&'a Engine, String> {
    // SAFETY: by contract the handle is 0 or live; a module instance runs one
    // call at a time, so nothing changes the engine meanwhile.
    unsafe { engine.as_ref() }.ok_or_else(|| bad_argument("engine is 0".to_string()))
}

/// The engine behind a handle, for a call that changes it.
///
/// # Safety
/// `engine` is 0 or a live handle from `gt_engine_new`.
unsafe fn exclusive<'a>(engine: *mut Engine) -> Result<&'a mut Engine, String> {
    // SAFETY: by contract the handle is 0 or live; a module instance runs one
    // call at a time, so this is the only reference.
    unsafe { engine.as_mut() }.ok_or_else(|| bad_argument("engine is 0".to_string()))
}

/// `len` bytes of linear memory for the host to write an argument into.
#[no_mangle]
pub extern "C" fn gt_alloc(len: usize) -> *mut u8 {
    let mut bytes: Vec<u8> = Vec::with_capacity(len);
    let ptr = bytes.as_mut_ptr();
    std::mem::forget(bytes);
    ptr
}

/// Release memory from `gt_alloc`, with the same length.
///
/// # Safety
/// `ptr` came from `gt_alloc(len)`, has not been released, and is not used
/// again.
#[no_mangle]
pub unsafe extern "C" fn gt_free(ptr: *mut u8, len: usize) {
    // SAFETY: by contract `ptr` is the pointer of a `Vec<u8>` of capacity
    // `len` that `gt_alloc` forgot; taking it back with length 0 drops no
    // element and releases the allocation once.
    drop(unsafe { Vec::from_raw_parts(ptr, 0, len) });
}

/// A new, empty engine.
#[no_mangle]
pub extern "C" fn gt_engine_new() -> *mut Engine {
    Box::into_raw(Box::new(Engine::new()))
}

/// Release an engine. 0 is accepted.
///
/// # Safety
/// `engine` is 0, or came from `gt_engine_new`, has not been released, and
/// is not used again.
#[no_mangle]
pub unsafe extern "C" fn gt_engine_free(engine: *mut Engine) {
    if !engine.is_null() {
        // SAFETY: by contract `engine` came from `Box::into_raw` in
        // `gt_engine_new` and this is the only release of it.
        drop(unsafe { Box::from_raw(engine) });
    }
}

/// Limit what the engine loads: 0 (`public`) makes every later load of a
/// `controlled` model module or pack fail with `distribution-refused`; 1
/// (`controlled`) is the default. Refused on an engine that has loaded
/// anything, and for any other value.
///
/// # Safety
/// `engine` is 0 or a live handle from `gt_engine_new`.
#[no_mangle]
pub unsafe extern "C" fn gt_engine_set_max_distribution(
    engine: *mut Engine,
    limit: i32,
) -> *mut GtResult {
    // SAFETY: the handle is passed on under this function's own contract.
    let outcome = unsafe { exclusive(engine) }.and_then(|engine| {
        glue::set_max_distribution(engine, limit).map_err(bad_argument)?;
        Ok(String::new())
    });
    into_result(outcome)
}

/// Set the limit on list items one decode holds (engine-spec ruling 7 of
/// 0.11; the default is 100000). A conversion whose decode would hold one
/// item more fails with `malformed-wire`; 0 refuses any item.
///
/// # Safety
/// `engine` is 0 or a live handle from `gt_engine_new`.
#[no_mangle]
pub unsafe extern "C" fn gt_engine_set_max_items(
    engine: *mut Engine,
    max_items: u32,
) -> *mut GtResult {
    // SAFETY: the handle is passed on under this function's own contract.
    let outcome = unsafe { exclusive(engine) }.map(|engine| {
        glue::set_max_items(engine, u64::from(max_items));
        String::new()
    });
    into_result(outcome)
}

/// Load one model module from the text of a `model/<module>.def`.
///
/// # Safety
/// `engine` is 0 or a live handle from `gt_engine_new`; `ptr` is valid for
/// `len` bytes.
#[no_mangle]
pub unsafe extern "C" fn gt_load_model(
    engine: *mut Engine,
    ptr: *const u8,
    len: usize,
) -> *mut GtResult {
    let load = || {
        // SAFETY: the handle and the text are passed on under this
        // function's own contract.
        let (engine, text) = unsafe { (exclusive(engine)?, text(ptr, len, "model text")?) };
        engine.load_model(text).map_err(|error| error.msg)?;
        Ok(String::new())
    };
    into_result(load())
}

/// Load one pack from the text of a `packs/<format>/pack.def`.
///
/// # Safety
/// As `gt_load_model`.
#[no_mangle]
pub unsafe extern "C" fn gt_load_pack(
    engine: *mut Engine,
    ptr: *const u8,
    len: usize,
) -> *mut GtResult {
    let load = || {
        // SAFETY: the handle and the text are passed on under this
        // function's own contract.
        let (engine, text) = unsafe { (exclusive(engine)?, text(ptr, len, "pack text")?) };
        engine.load_def(text).map_err(|error| error.msg)?;
        Ok(String::new())
    };
    into_result(load())
}

/// Convert `input` from format `from` to format `to`. `has_context` 0: no
/// context; otherwise the context is `key=value\n` text (length 0: an empty
/// context, which still counts as a context given).
///
/// # Safety
/// `engine` is 0 or a live handle from `gt_engine_new`; each pointer is valid
/// for its length.
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
    let convert = || {
        // SAFETY: the handle and each text are passed on under this
        // function's own contract.
        let (engine, from, to, input) = unsafe {
            (
                shared(engine)?,
                text(from, from_len, "from")?,
                text(to, to_len, "to")?,
                text(input, input_len, "input")?,
            )
        };
        let pairs = if has_context == 0 {
            None
        } else {
            // SAFETY: as above.
            let context = unsafe { text(context, context_len, "context") }?;
            Some(glue::parse_context(context).map_err(bad_argument)?)
        };
        engine
            .convert_text(from, to, input, pairs.as_deref())
            .map_err(|error| error.msg)
    };
    into_result(convert())
}

/// The loaded format names, sorted, one per line (each ends with `\n`).
///
/// # Safety
/// `engine` is 0 or a live handle from `gt_engine_new`.
#[no_mangle]
pub unsafe extern "C" fn gt_formats(engine: *const Engine) -> *mut GtResult {
    // SAFETY: the handle is passed on under this function's own contract.
    into_result(unsafe { shared(engine) }.map(glue::formats_text))
}

/// 1 when the call succeeded, 0 when the result holds an error text.
///
/// # Safety
/// `result` is 0 or a live handle a call returned.
#[no_mangle]
pub unsafe extern "C" fn gt_result_ok(result: *const GtResult) -> i32 {
    // SAFETY: by contract the handle is 0 or live.
    unsafe { result.as_ref() }.map_or(0, |result| i32::from(result.ok))
}

/// Where the result's bytes are in linear memory. Meaningful only together
/// with `gt_result_len`, and only until the next call that allocates.
///
/// # Safety
/// `result` is 0 or a live handle a call returned.
#[no_mangle]
pub unsafe extern "C" fn gt_result_ptr(result: *const GtResult) -> *const u8 {
    // SAFETY: by contract the handle is 0 or live.
    unsafe { result.as_ref() }.map_or(std::ptr::null(), |result| result.bytes.as_ptr())
}

/// How many bytes the result holds.
///
/// # Safety
/// `result` is 0 or a live handle a call returned.
#[no_mangle]
pub unsafe extern "C" fn gt_result_len(result: *const GtResult) -> usize {
    // SAFETY: by contract the handle is 0 or live.
    unsafe { result.as_ref() }.map_or(0, |result| result.bytes.len())
}

/// Release a result handle. 0 is accepted.
///
/// # Safety
/// `result` is 0, or a handle a call returned that has not been released and
/// is not used again.
#[no_mangle]
pub unsafe extern "C" fn gt_result_free(result: *mut GtResult) {
    if !result.is_null() {
        // SAFETY: by contract `result` came from `Box::into_raw` in
        // `into_result` and this is the only release of it.
        drop(unsafe { Box::from_raw(result) });
    }
}

#[cfg(test)]
mod tests {
    //! The raw interface, driven on the build machine as a host drives it in
    //! linear memory. The module itself is tested from Node (`test/`).
    use super::*;

    /// Copy a text into memory from `gt_alloc`, as a host does.
    fn pass(text: &str) -> (*mut u8, usize) {
        let ptr = gt_alloc(text.len());
        // SAFETY: `ptr` has room for `text.len()` bytes and overlaps nothing.
        unsafe { std::ptr::copy_nonoverlapping(text.as_ptr(), ptr, text.len()) };
        (ptr, text.len())
    }

    /// Read a result handle and release it, as a host does.
    fn take(result: *mut GtResult) -> Result<String, String> {
        // SAFETY: `result` is a live handle, read and then released once.
        unsafe {
            let bytes = std::slice::from_raw_parts(gt_result_ptr(result), gt_result_len(result));
            let text = String::from_utf8(bytes.to_vec()).unwrap();
            let ok = gt_result_ok(result) == 1;
            gt_result_free(result);
            if ok {
                Ok(text)
            } else {
                Err(text)
            }
        }
    }

    const CORE: &str =
        "module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\n";
    const PACK: &str = "format probe\nversion 0.4.0\ndistribution public\nsource \"probe\"\nwire xml\nroot item\nfield uid @id string\n";

    #[test]
    fn a_host_loads_and_converts_through_the_raw_interface() {
        let engine = gt_engine_new();
        let (core, core_len) = pass(CORE);
        let (pack, pack_len) = pass(PACK);
        let (name, name_len) = pass("probe");
        let (input, input_len) = pass("<item id=\"u1\"/>");
        // SAFETY: every handle and pointer is live and passed with its length.
        unsafe {
            assert_eq!(
                take(gt_load_model(engine, core, core_len)),
                Ok(String::new())
            );
            assert_eq!(
                take(gt_load_pack(engine, pack, pack_len)),
                Ok(String::new())
            );
            assert_eq!(take(gt_formats(engine)), Ok("probe\n".to_string()));
            let converted = gt_convert(
                engine,
                name,
                name_len,
                name,
                name_len,
                input,
                input_len,
                0,
                std::ptr::null(),
                0,
            );
            assert_eq!(take(converted), Ok("<item id=\"u1\"/>".to_string()));
            gt_free(core, core_len);
            gt_free(pack, pack_len);
            gt_free(name, name_len);
            gt_free(input, input_len);
            gt_engine_free(engine);
        }
    }

    #[test]
    fn a_handle_of_zero_is_refused_not_read() {
        let none = std::ptr::null_mut::<Engine>();
        // SAFETY: 0 is a handle every call accepts.
        unsafe {
            for result in [
                gt_formats(none),
                gt_load_model(none, std::ptr::null(), 0),
                gt_load_pack(none, std::ptr::null(), 0),
                gt_engine_set_max_distribution(none, 0),
                gt_convert(
                    none,
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    0,
                    std::ptr::null(),
                    0,
                    0,
                    std::ptr::null(),
                    0,
                ),
            ] {
                assert_eq!(take(result), Err("bad-argument: engine is 0".to_string()));
            }
            gt_engine_free(none);

            let no_result = std::ptr::null_mut::<GtResult>();
            assert_eq!(gt_result_ok(no_result), 0);
            assert_eq!(gt_result_len(no_result), 0);
            assert!(gt_result_ptr(no_result).is_null());
            gt_result_free(no_result);
        }
    }

    #[test]
    fn an_allocation_of_no_bytes_is_released_like_any_other() {
        let ptr = gt_alloc(0);
        // SAFETY: `ptr` came from `gt_alloc(0)`.
        unsafe { gt_free(ptr, 0) };
    }
}
