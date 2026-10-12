// Small shared helpers: things that used to be copy-pasted (or inlined) in
// each command module, where drift between the copies was only a matter of
// time.
use crate::llm::PLACEHOLDER_TRANSLATION_PREFIX;

/// "Now" as the app's canonical timestamp format. Every table that carries a
/// written-at column goes through this one function, so the format cannot
// diverge between the writer and the reader of a column.
pub fn now_str() -> String {
    chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string()
}

/// The LIKE pattern (prefix + `%`) that matches the offline demo engine's
/// `【译文】<原文>` placeholder. Bound as a parameter everywhere it is used, so
/// the prefix never has to be spliced into the SQL string itself.
pub fn placeholder_like_pattern() -> String {
    format!("{PLACEHOLDER_TRANSLATION_PREFIX}%")
}

/// SQL condition that keeps only real translations of `col` — present, not
/// blank, and not the offline demo engine's placeholder echo. `?` is the
/// parameter slot for [`placeholder_like_pattern`]; in SQLite a bare `?` takes
/// the next index after any `?N` that precedes it, so the pattern is always the
/// last bound value of the statement.
pub fn real_translation_filter(col: &str) -> String {
    format!("{col} IS NOT NULL AND TRIM({col}) <> '' AND {col} NOT LIKE ?")
}

/// Minimal sanity check on a caller-supplied save path.
///
/// The path is expected to come from the native save dialog
/// (tauri-plugin-dialog); this only rejects obviously broken input (blank, or
/// pointing at a directory instead of a file) rather than trying to encode a
/// filesystem policy the dialog already enforces.
pub fn validate_save_path(path: &str) -> Result<(), String> {
    let trimmed = path.trim();
    if trimmed.is_empty() {
        return Err("未选择保存路径。".to_string());
    }
    // `Path::file_name` normalizes a trailing separator away ("/tmp/" reads as
    // a file named "tmp"), so a path that ends in one is checked explicitly.
    if trimmed.ends_with('/') || trimmed.ends_with('\\') {
        return Err(format!("保存路径无效：{trimmed}（指向目录而非文件）"));
    }
    if std::path::Path::new(trimmed).file_name().is_none() {
        return Err(format!("保存路径无效：{trimmed}"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn now_str_matches_the_canonical_format() {
        // The format is load-bearing: rows written with one format and read
        // (or ordered) with another silently mis-sort.
        assert!(regex_like_match(&now_str()));
    }

    fn regex_like_match(s: &str) -> bool {
        let bytes = s.as_bytes();
        s.len() == 19
            && bytes[4] == b'-'
            && bytes[7] == b'-'
            && bytes[10] == b' '
            && bytes[13] == b':'
            && bytes[16] == b':'
            && s.chars().all(|c| c.is_ascii_digit() || "-: ".contains(c))
    }

    #[test]
    fn placeholder_pattern_is_the_prefix_plus_wildcard() {
        assert_eq!(placeholder_like_pattern(), format!("{PLACEHOLDER_TRANSLATION_PREFIX}%"));
    }

    #[test]
    fn the_filter_splices_the_column_but_not_the_pattern() {
        let sql = real_translation_filter("s.translation");
        assert!(sql.contains("s.translation IS NOT NULL"));
        assert!(sql.ends_with("NOT LIKE ?"));
        assert!(!sql.contains(PLACEHOLDER_TRANSLATION_PREFIX));
    }

    #[test]
    fn save_paths_from_a_dialog_pass_and_obviously_broken_ones_do_not() {
        assert!(validate_save_path("/home/u/Documents/deck.txt").is_ok());
        assert!(validate_save_path("  /tmp/out.md  ").is_ok());
        assert!(validate_save_path("").is_err());
        assert!(validate_save_path("   ").is_err());
        // A bare directory has no file name to write to.
        assert!(validate_save_path("/tmp/").is_err());
    }
}
