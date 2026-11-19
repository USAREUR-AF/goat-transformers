//! What the C library and the WebAssembly module do the same way: read an
//! argument, read a context, set the distribution limit, write the format
//! list. Each binding includes this file (`#[path]`), so the two cannot drift.
//!
//! Every function here returns the text of a refusal without a kind; the
//! binding puts `bad-argument: ` before it.

use goat_transformers::{Distribution, Engine};

/// The distribution limit `public`, as the bindings pass it.
pub const DISTRIBUTION_PUBLIC: i32 = 0;
/// The distribution limit `controlled` (the engine's default), as the
/// bindings pass it.
pub const DISTRIBUTION_CONTROLLED: i32 = 1;

/// Read a pointer and a byte length as text. A length of 0 is the empty text
/// whatever the pointer is; a null pointer with any other length is refused,
/// as is text that is not UTF-8. `what` names the argument in the refusal.
///
/// # Safety
/// When `len` is not 0 and `ptr` is not null, `ptr` points to `len` bytes
/// that stay readable and unchanged for `'a`.
pub unsafe fn text<'a>(ptr: *const u8, len: usize, what: &str) -> Result<&'a str, String> {
    if len == 0 {
        return Ok("");
    }
    if ptr.is_null() {
        return Err(format!("{what} is a null pointer with length {len}"));
    }
    if len > isize::MAX as usize {
        return Err(format!("{what} has an impossible length {len}"));
    }
    // SAFETY: `ptr` is not null and, by this function's contract, points to
    // `len` readable bytes that outlive `'a`; `len` fits in `isize`.
    let bytes = unsafe { std::slice::from_raw_parts(ptr, len) };
    std::str::from_utf8(bytes).map_err(|_| format!("{what} is not UTF-8"))
}

/// Read a context text: one `key=value` per line, each line ended by `\n`.
/// The key ends at the first `=`, so a value may hold `=` and may be empty.
/// Empty lines are skipped. A line with no `=` is refused.
pub fn parse_context(text: &str) -> Result<Vec<(String, String)>, String> {
    text.split('\n')
        .filter(|line| !line.is_empty())
        .map(|line| {
            line.split_once('=')
                .map(|(key, value)| (key.to_string(), value.to_string()))
                .ok_or_else(|| format!("context line `{line}` is not key=value"))
        })
        .collect()
}

/// Set the engine's distribution limit from `DISTRIBUTION_PUBLIC` or
/// `DISTRIBUTION_CONTROLLED`. The limit is checked when a module or a pack is
/// loaded, so it is refused on an engine that already holds one: a limit set
/// afterwards would leave what is loaded in place and say otherwise.
pub fn set_max_distribution(engine: &mut Engine, limit: i32) -> Result<(), String> {
    let distribution = match limit {
        DISTRIBUTION_PUBLIC => Distribution::Public,
        DISTRIBUTION_CONTROLLED => Distribution::Controlled,
        other => {
            return Err(format!(
                "distribution limit {other} is neither {DISTRIBUTION_PUBLIC} (public) nor {DISTRIBUTION_CONTROLLED} (controlled)"
            ))
        }
    };
    if !engine.modules().is_empty() || !engine.formats().is_empty() {
        return Err(
            "the distribution limit is set before the first model module or pack is loaded"
                .to_string(),
        );
    }
    engine.set_max_distribution(distribution);
    Ok(())
}

/// Set the limit on list items one decode holds (engine-spec ruling 7 of
/// 0.11). 0 refuses any item; a value beyond the platform's `usize` is no
/// limit. It may be set at any time, also after loading.
pub fn set_max_items(engine: &mut Engine, max_items: u64) {
    engine.set_max_items(usize::try_from(max_items).unwrap_or(usize::MAX));
}

/// The loaded format names, sorted, one per line, each ended by `\n`.
pub fn formats_text(engine: &Engine) -> String {
    engine
        .formats()
        .iter()
        .flat_map(|name| [name.as_str(), "\n"])
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    const CORE: &str =
        "module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\n";
    const CONTROLLED_PACK: &str = "format probe\nversion 0.4.0\ndistribution controlled\nsource \"probe\"\nwire xml\nroot item\nfield uid @id string\n";

    fn read(bytes: &[u8]) -> Result<&str, String> {
        // SAFETY: the pointer and the length are those of a live slice.
        unsafe { text(bytes.as_ptr(), bytes.len(), "input") }
    }

    #[test]
    fn text_reads_utf8_and_keeps_an_embedded_nul() {
        assert_eq!(read("a\0é".as_bytes()), Ok("a\0é"));
    }

    #[test]
    fn text_of_length_zero_is_empty_whatever_the_pointer() {
        // SAFETY: with a length of 0 the pointer is not read.
        unsafe {
            assert_eq!(text(std::ptr::null(), 0, "input"), Ok(""));
            assert_eq!(
                text(std::ptr::NonNull::dangling().as_ptr(), 0, "input"),
                Ok("")
            );
        }
    }

    #[test]
    fn text_refuses_a_null_pointer_with_a_length() {
        // SAFETY: a null pointer is refused before it is read.
        let refused = unsafe { text(std::ptr::null(), 3, "input") };
        assert_eq!(
            refused,
            Err("input is a null pointer with length 3".to_string())
        );
    }

    #[test]
    fn text_refuses_a_length_no_allocation_can_have() {
        let byte = 0u8;
        // SAFETY: the length is refused before the pointer is read.
        let refused = unsafe { text(&byte, usize::MAX, "input") };
        assert!(refused.unwrap_err().contains("impossible length"));
    }

    #[test]
    fn text_refuses_bytes_that_are_not_utf8() {
        assert_eq!(read(b"\xff\xfe"), Err("input is not UTF-8".to_string()));
        // a sequence cut short at the end of the argument
        assert_eq!(
            read(&"é".as_bytes()[..1]),
            Err("input is not UTF-8".to_string())
        );
    }

    #[test]
    fn context_key_ends_at_the_first_equals_sign() {
        let pairs = parse_context("a=b=c\nempty=\n\nname=Zoë\n").unwrap();
        let want = [("a", "b=c"), ("empty", ""), ("name", "Zoë")];
        assert_eq!(pairs.len(), want.len());
        for ((key, value), (want_key, want_value)) in pairs.iter().zip(want) {
            assert_eq!((key.as_str(), value.as_str()), (want_key, want_value));
        }
    }

    #[test]
    fn context_without_a_final_line_break_is_read() {
        assert_eq!(
            parse_context("a=1").unwrap(),
            [("a".to_string(), "1".to_string())]
        );
    }

    #[test]
    fn empty_context_text_is_an_empty_context() {
        assert_eq!(parse_context("").unwrap(), []);
    }

    #[test]
    fn context_line_without_equals_sign_is_refused() {
        assert_eq!(
            parse_context("a=1\nnot a pair\n"),
            Err("context line `not a pair` is not key=value".to_string())
        );
    }

    #[test]
    fn public_limit_refuses_a_controlled_pack() {
        let mut engine = Engine::new();
        set_max_distribution(&mut engine, DISTRIBUTION_PUBLIC).unwrap();
        engine.load_model(CORE).unwrap();
        let refused = engine.load_def(CONTROLLED_PACK).unwrap_err();
        assert!(
            refused.msg.starts_with("distribution-refused:"),
            "{}",
            refused.msg
        );
        assert_eq!(formats_text(&engine), "");
    }

    #[test]
    fn controlled_limit_is_the_default_and_loads_a_controlled_pack() {
        for set_it in [false, true] {
            let mut engine = Engine::new();
            if set_it {
                set_max_distribution(&mut engine, DISTRIBUTION_CONTROLLED).unwrap();
            }
            engine.load_model(CORE).unwrap();
            engine.load_def(CONTROLLED_PACK).unwrap();
            assert_eq!(formats_text(&engine), "probe\n");
        }
    }

    #[test]
    fn unknown_limit_is_refused_and_changes_nothing() {
        let mut engine = Engine::new();
        assert!(set_max_distribution(&mut engine, 2).is_err());
        assert!(set_max_distribution(&mut engine, -1).is_err());
        engine.load_model(CORE).unwrap();
        engine.load_def(CONTROLLED_PACK).unwrap();
    }

    #[test]
    fn limit_is_refused_once_anything_is_loaded() {
        let mut engine = Engine::new();
        engine.load_model(CORE).unwrap();
        let refused = set_max_distribution(&mut engine, DISTRIBUTION_PUBLIC).unwrap_err();
        assert!(refused.contains("before the first"), "{refused}");
    }

    #[test]
    fn formats_are_one_per_line() {
        assert_eq!(formats_text(&Engine::new()), "");
    }
}
