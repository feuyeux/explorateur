// Vocabulary notebook commands.
use crate::db;
use crate::vocab::{
    add_vocabulary_item, delete_vocabulary_item, export_vocabulary_anki_tsv, list_vocabulary_items,
    VocabRecord,
};
use rusqlite::Connection;

/// Ids reach us from the DOM (`dataset.id`), which is always a string. Parsing
/// here rather than taking `i64` in the command signature is what makes the
/// round trip work: Tauri hands a command argument straight to serde, and serde
/// will not coerce `"5"` into an i64.
pub fn parse_vocab_id(raw: &str) -> Result<i64, String> {
    raw.trim()
        .parse::<i64>()
        .map_err(|_| format!("生词本条目标识无效：{raw:?}"))
}

pub fn validate_vocab_fields(word: &str, translation: &str) -> Result<(), String> {
    if word.trim().is_empty() || translation.trim().is_empty() {
        return Err("生词与释义不能为空".to_string());
    }
    Ok(())
}

pub fn add_vocabulary_conn(
    conn: &Connection,
    word: &str,
    translation: &str,
    pos: &str,
    sentence_context: &str,
    sentence_id: &str,
    cultural_background: &str,
) -> Result<serde_json::Value, String> {
    validate_vocab_fields(word, translation)?;
    let id = add_vocabulary_item(
        conn,
        word,
        pos,
        translation,
        sentence_context,
        sentence_id,
        cultural_background,
    )?;
    Ok(serde_json::json!({
        "status": "success",
        "id": id,
        "word": word.trim(),
    }))
}

pub fn delete_vocabulary_conn(
    conn: &Connection,
    raw_id: &str,
) -> Result<serde_json::Value, String> {
    let id = parse_vocab_id(raw_id)?;
    delete_vocabulary_item(conn, id)?;
    Ok(serde_json::json!({"status": "deleted", "id": id}))
}

/// Renders the Anki deck and writes it where the user chose in the save
/// dialog. The write happens in Rust rather than through the fs plugin because
/// no fs scope can cover an arbitrary user-chosen path, and a capability that
/// tried would be far broader than this one call needs.
pub fn write_anki_deck_to(conn: &Connection, path: &str) -> Result<usize, String> {
    if path.trim().is_empty() {
        return Err("未选择保存路径。".to_string());
    }
    let tsv = export_vocabulary_anki_tsv(conn)?;
    std::fs::write(path, tsv.as_bytes()).map_err(|e| format!("写入 {path} 失败：{e}"))?;
    Ok(tsv.len())
}

#[tauri::command]
pub fn get_vocabulary(app: tauri::AppHandle) -> Result<Vec<VocabRecord>, String> {
    db::with_conn(&app, list_vocabulary_items)
}

#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub fn add_vocabulary(
    app: tauri::AppHandle,
    word: String,
    translation: String,
    pos: Option<String>,
    sentence_context: Option<String>,
    sentence_id: Option<String>,
    cultural_background: Option<String>,
) -> Result<serde_json::Value, String> {
    db::with_conn(&app, |conn| {
        add_vocabulary_conn(
            conn,
            &word,
            &translation,
            pos.as_deref().unwrap_or(""),
            sentence_context.as_deref().unwrap_or(""),
            sentence_id.as_deref().unwrap_or(""),
            cultural_background.as_deref().unwrap_or(""),
        )
    })
}

#[tauri::command]
pub fn delete_vocabulary(
    app: tauri::AppHandle,
    vocab_id: String,
) -> Result<serde_json::Value, String> {
    db::with_conn(&app, |conn| delete_vocabulary_conn(conn, &vocab_id))
}

#[tauri::command]
pub fn export_anki_to(app: tauri::AppHandle, path: String) -> Result<serde_json::Value, String> {
    let path_for_result = path.clone();
    let written = db::with_conn(&app, |conn| write_anki_deck_to(conn, &path))?;
    Ok(serde_json::json!({
        "status": "written",
        "path": path_for_result,
        "bytes": written,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mem_db() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        crate::db::init_conn(&conn).unwrap();
        conn
    }

    #[test]
    fn test_add_vocabulary_rejects_blank_word_or_translation() {
        let conn = mem_db();
        let err = add_vocabulary_conn(&conn, "", "释义", "", "", "", "").unwrap_err();
        assert_eq!(err, "生词与释义不能为空");
        let err = add_vocabulary_conn(&conn, "Ishmael", "  ", "", "", "", "").unwrap_err();
        assert_eq!(err, "生词与释义不能为空");
        // A rejection must not have created a row.
        let n: i64 = conn
            .query_row("SELECT COUNT(*) FROM vocabulary_book", [], |r| r.get(0))
            .unwrap();
        assert_eq!(n, 0);
    }

    #[test]
    fn test_add_vocabulary_then_delete_by_the_string_the_dom_hands_us() {
        // Regression: the command used to take i64 while the frontend sends the
        // string from `dataset.id`, so every delete failed to deserialize.
        let conn = mem_db();
        let added = add_vocabulary_conn(&conn, "Ishmael", "以实玛利", "人名", "", "", "").unwrap();
        let id = added["id"].as_i64().unwrap();
        let from_dom = id.to_string(); // what `String(btn.dataset.id)` gives us

        let deleted = delete_vocabulary_conn(&conn, &from_dom).unwrap();
        assert_eq!(deleted["id"].as_i64().unwrap(), id);
        let n: i64 = conn
            .query_row("SELECT COUNT(*) FROM vocabulary_book", [], |r| r.get(0))
            .unwrap();
        assert_eq!(n, 0);
    }

    #[test]
    fn test_delete_rejects_an_id_that_is_not_a_number() {
        let conn = mem_db();
        let err = delete_vocabulary_conn(&conn, "abc").unwrap_err();
        assert!(err.contains("无效"), "got {err}");
    }

    #[test]
    fn test_write_anki_deck_lands_the_tsv_at_the_chosen_path() {
        let conn = mem_db();
        add_vocabulary_conn(&conn, "Ishmael", "以实玛利", "人名", "", "", "").unwrap();
        let dir = std::env::temp_dir().join(format!("rr_anki_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("deck.txt");
        let path_str = path.to_string_lossy().to_string();

        let bytes = write_anki_deck_to(&conn, &path_str).unwrap();
        let written = std::fs::read_to_string(&path).unwrap();
        assert_eq!(bytes, written.len());
        assert!(written.starts_with("#separator:tab"));
        assert!(written.contains("Ishmael"));

        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn test_write_anki_deck_refuses_an_empty_path() {
        let conn = mem_db();
        assert!(write_anki_deck_to(&conn, "  ").is_err());
    }
}
