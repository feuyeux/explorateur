// Per-document glossary storage and prompt formatting, ported from
// backend/app/parsers/glossary.py.

use rusqlite::Connection;

#[derive(Debug, Clone, serde::Serialize)]
pub struct GlossaryItem {
    pub term: String,
    pub category: String,
    pub canonical_translation: String,
    pub notes: String,
}

pub fn add_glossary_item(
    conn: &Connection,
    doc_id: &str,
    term: &str,
    canonical_translation: &str,
    category: &str,
    notes: &str,
) -> Result<(), String> {
    conn.execute(
        "INSERT INTO glossary (doc_id, term, category, canonical_translation, notes)
         VALUES (?1, ?2, ?3, ?4, ?5)",
        rusqlite::params![
            doc_id,
            term.trim(),
            category,
            canonical_translation.trim(),
            notes
        ],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

pub fn get_document_glossary(conn: &Connection, doc_id: &str) -> Result<Vec<GlossaryItem>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT term, COALESCE(category, '专有名词'), canonical_translation, COALESCE(notes, '')
             FROM glossary WHERE doc_id = ?1 ORDER BY id ASC",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([doc_id], |r| {
            Ok(GlossaryItem {
                term: r.get(0)?,
                category: r.get(1)?,
                canonical_translation: r.get(2)?,
                notes: r.get(3)?,
            })
        })
        .map_err(|e| e.to_string())?;
    rows.map(|r| r.map_err(|e| e.to_string())).collect()
}

pub fn format_glossary_for_prompt(conn: &Connection, doc_id: &str) -> Result<String, String> {
    let items = get_document_glossary(conn, doc_id)?;
    if items.is_empty() {
        return Ok("暂无预设术语表（请遵循通用经典翻译规范）。".to_string());
    }
    let mut out = String::from("【全书统一专有名词与术语表（必须严格遵循一致译名）】：");
    for it in items {
        let notes_str = if it.notes.is_empty() {
            String::new()
        } else {
            format!(" ({})", it.notes)
        };
        out.push_str(&format!(
            "\n- {} [{}]: {}{}",
            it.term, it.category, it.canonical_translation, notes_str
        ));
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mem_db() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "CREATE TABLE glossary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL, term TEXT NOT NULL,
                category TEXT DEFAULT '专有名词',
                canonical_translation TEXT NOT NULL, notes TEXT);",
        )
        .unwrap();
        conn
    }

    #[test]
    fn test_glossary_add_and_format() {
        let conn = mem_db();
        add_glossary_item(&conn, "d1", "Ishmael", "以实玛利", "主角", "圣经典例").unwrap();
        add_glossary_item(&conn, "d1", "Cato", "加图", "典故人物", "").unwrap();
        let items = get_document_glossary(&conn, "d1").unwrap();
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].term, "Ishmael");
        let snippet = format_glossary_for_prompt(&conn, "d1").unwrap();
        assert!(snippet.contains("以实玛利"));
        assert!(snippet.contains("Ishmael [主角]: 以实玛利 (圣经典例)"));
        let empty = format_glossary_for_prompt(&conn, "nope").unwrap();
        assert!(empty.contains("暂无预设术语表"));
    }

    #[test]
    fn test_glossary_note_is_omitted_when_empty() {
        let conn = mem_db();
        add_glossary_item(&conn, "d1", "Cato", "加图", "典故人物", "").unwrap();
        let snippet = format_glossary_for_prompt(&conn, "d1").unwrap();
        assert!(snippet.contains("- Cato [典故人物]: 加图"), "got {snippet}");
        assert!(!snippet.contains("加图 ("), "got {snippet}");
    }

    #[test]
    fn test_glossary_is_scoped_to_document() {
        let conn = mem_db();
        add_glossary_item(&conn, "d1", "Ahab", "亚哈", "人物", "").unwrap();
        add_glossary_item(&conn, "d2", "Gatsby", "盖茨比", "人物", "").unwrap();
        assert_eq!(get_document_glossary(&conn, "d1").unwrap().len(), 1);
        assert_eq!(get_document_glossary(&conn, "d2").unwrap().len(), 1);
        assert!(get_document_glossary(&conn, "d3").unwrap().is_empty());
    }
}
