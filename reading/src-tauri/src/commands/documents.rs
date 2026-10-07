// Document commands: upload, sample, list, get, delete.
// Ported from backend/app/routers/documents.py.
use crate::db;
use crate::glossary;
use crate::markdown::strip_markdown;
use crate::splitter::split_paragraphs_and_sentences;
use rusqlite::Connection;
use serde::Serialize;

pub const SAMPLE_MOBY_DICK: &str = include_str!("../../assets/sample_moby_dick.md");
pub const SAMPLE_GATSBY: &str = include_str!("../../assets/sample_the_great_gatsby.md");

#[derive(Debug, Clone, Serialize)]
pub struct DocumentMeta {
    pub id: String,
    pub title: String,
    pub author: String,
    pub file_type: String,
    pub total_paragraphs: i64,
    pub total_sentences: i64,
    pub created_at: String,
}

/// Rejects content the frontend could not decode, before any row is written.
pub fn validate_upload(content: &str) -> Result<(), String> {
    if content.trim().is_empty() {
        return Err("文件内容为空，请导入有效的 Markdown 或 TXT 文件。".to_string());
    }
    let total = content.chars().count();
    let bad = content.chars().filter(|&c| c == '\u{FFFD}').count();
    if bad > 0 && (bad as f64) / (total as f64) > 0.005 {
        return Err(
            "文件编码异常：检测到无法解码的字符（可能不是 UTF-8），请将文件另存为 UTF-8 后重试。"
                .to_string(),
        );
    }
    Ok(())
}

/// The only input formats the reader accepts (spec §6.3). Checked on the
/// backend because the file-picker filter and `accept=` are cosmetic — a
/// drag-and-drop onto the dropzone goes through neither.
pub fn validate_extension(file_ext: &str) -> Result<(), String> {
    let ext = file_ext.trim().trim_start_matches('.').to_ascii_lowercase();
    if matches!(ext.as_str(), "md" | "markdown" | "txt") {
        Ok(())
    } else if ext.is_empty() {
        Err("无法识别文件类型：请选择 .md / .markdown / .txt 文件。".to_string())
    } else {
        Err(format!(
            "暂不支持 .{ext} 文件：本版本仅支持 .md / .markdown / .txt 纯文本原著。"
        ))
    }
}

fn now_str() -> String {
    chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string()
}

pub fn new_doc_id() -> String {
    format!("doc_{}", &uuid::Uuid::new_v4().simple().to_string()[..8])
}

/// Writes the document, its paragraphs and its sentences. Returns the number
/// of paragraphs, which is what the frontend reports back to the user.
pub fn ingest_text(
    conn: &Connection,
    doc_id: &str,
    title: &str,
    author: &str,
    file_type: &str,
    raw_content: &str,
) -> Result<usize, String> {
    let paras = split_paragraphs_and_sentences(&strip_markdown(raw_content));

    conn.execute(
        "INSERT INTO documents (id, title, author, file_type, raw_content, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        rusqlite::params![doc_id, title, author, file_type, raw_content, now_str()],
    )
    .map_err(|e| e.to_string())?;

    for p in &paras {
        let p_id = format!("{doc_id}_{}", p.paragraph_id);
        conn.execute(
            "INSERT INTO paragraphs (id, doc_id, chapter_id, order_index, raw_text)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            rusqlite::params![p_id, doc_id, "ch_1", p.order_index, p.raw_text],
        )
        .map_err(|e| e.to_string())?;
        for s in &p.sentences {
            let s_id = format!("{doc_id}_{}", s.sentence_id);
            conn.execute(
                "INSERT INTO sentences
                   (id, doc_id, paragraph_id, order_index, original, translation, deep_analysis_json)
                 VALUES (?1, ?2, ?3, ?4, ?5, NULL, NULL)",
                rusqlite::params![s_id, doc_id, p_id, s.order_index, s.original],
            )
            .map_err(|e| e.to_string())?;
        }
    }
    Ok(paras.len())
}

pub fn list_documents_from(conn: &Connection) -> Result<Vec<DocumentMeta>, String> {
    // Correlated subqueries, not two joins to the same document: joining both
    // produced a paragraph x sentence intermediate (2 000 rows for a 400-
    // paragraph book) that only COUNT(DISTINCT) then had to collapse.
    let mut stmt = conn
        .prepare(
            "SELECT d.id, d.title, d.author, d.file_type,
                    (SELECT COUNT(*) FROM paragraphs p WHERE p.doc_id = d.id) AS total_paragraphs,
                    (SELECT COUNT(*) FROM sentences  s WHERE s.doc_id  = d.id) AS total_sentences,
                    d.created_at
             FROM documents d
             ORDER BY d.created_at DESC",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |r| {
            Ok(DocumentMeta {
                id: r.get(0)?,
                title: r.get(1)?,
                author: r.get(2)?,
                file_type: r.get(3)?,
                total_paragraphs: r.get(4)?,
                total_sentences: r.get(5)?,
                created_at: r.get(6)?,
            })
        })
        .map_err(|e| e.to_string())?;
    rows.map(|r| r.map_err(|e| e.to_string())).collect()
}

pub fn get_document_from(conn: &Connection, doc_id: &str) -> Result<serde_json::Value, String> {
    let doc: Option<(String, String, String, String, String)> = conn
        .query_row(
            "SELECT id, title, author, file_type, created_at FROM documents WHERE id = ?1",
            [doc_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
        )
        .ok();
    let (id, title, author, file_type, created_at) = doc.ok_or("文档未找到")?;

    let mut p_stmt = conn
        .prepare("SELECT id, order_index, raw_text FROM paragraphs WHERE doc_id = ?1 ORDER BY order_index ASC")
        .map_err(|e| e.to_string())?;
    let paras = p_stmt
        .query_map([doc_id], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, String>(2)?,
            ))
        })
        .map_err(|e| e.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;

    let mut s_stmt = conn
        .prepare(
            "SELECT id, original, translation, deep_analysis_json FROM sentences
             WHERE paragraph_id = ?1 ORDER BY order_index ASC",
        )
        .map_err(|e| e.to_string())?;
    let mut paragraphs_res = Vec::with_capacity(paras.len());
    for (p_id, order_index, raw_text) in paras {
        let sents = s_stmt
            .query_map([&p_id], |r| {
                Ok(serde_json::json!({
                    "sentence_id": r.get::<_, String>(0)?,
                    "original": r.get::<_, String>(1)?,
                    "translation": r.get::<_, Option<String>>(2)?,
                    "has_deep_analysis": r.get::<_, Option<String>>(3)?.is_some(),
                }))
            })
            .map_err(|e| e.to_string())?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())?;
        paragraphs_res.push(serde_json::json!({
            "paragraph_id": p_id,
            "order_index": order_index,
            "raw_text": raw_text,
            "sentences": sents,
        }));
    }

    Ok(serde_json::json!({
        "id": id,
        "title": title,
        "author": author,
        "file_type": file_type,
        "created_at": created_at,
        "glossary": glossary::get_document_glossary(conn, doc_id)?,
        "paragraphs": paragraphs_res,
    }))
}

/// The curated seeds that ship with each built-in sample.
fn seed_sample_glossary(conn: &Connection, sample_name: &str) -> Result<(), String> {
    let seeds: &[(&str, &str, &str, &str)] = match sample_name {
        "the_great_gatsby" => &[
            (
                "Gatsby",
                "盖茨比",
                "核心主角",
                "杰·盖茨比，象征美国梦的华美与虚幻幻灭",
            ),
            (
                "Daisy",
                "黛西",
                "主角人物",
                "盖茨比终生痴恋与追求的绿灯彼岸",
            ),
        ],
        _ => &[
            (
                "Ishmael",
                "以实玛利",
                "核心主角/叙述者",
                "希伯来语意为'神垂听'，代表被放逐与流浪之人",
            ),
            (
                "Manhattoes",
                "曼哈托斯（曼哈顿旧称）",
                "地名",
                "纽约曼哈顿印第安语古名，强调其四面环海的岛屿本色",
            ),
            (
                "Cato",
                "加图",
                "历史/典故人物",
                "古罗马政治家小加图，以在兵败后拔剑自刎保持自由尊严闻名",
            ),
        ],
    };
    let doc_id = format!("sample_{sample_name}");
    for (term, translation, category, notes) in seeds {
        glossary::add_glossary_item(conn, &doc_id, term, translation, category, notes)?;
    }
    Ok(())
}

fn sample_source(name: &str) -> Option<(&'static str, &'static str, &'static str)> {
    match name {
        "moby_dick" => Some((SAMPLE_MOBY_DICK, "白鲸记 (Moby-Dick)", "Herman Melville")),
        "the_great_gatsby" => Some((
            SAMPLE_GATSBY,
            "了不起的盖茨比 (The Great Gatsby)",
            "F. Scott Fitzgerald",
        )),
        _ => None,
    }
}

fn load_sample_conn(conn: &Connection, sample_name: &str) -> Result<serde_json::Value, String> {
    let name = if sample_source(sample_name).is_some() {
        sample_name
    } else {
        "moby_dick"
    };
    let (raw_text, title, author) = sample_source(name).expect("sample resolved above");
    let doc_id = format!("sample_{name}");

    let exists: Option<String> = conn
        .query_row("SELECT id FROM documents WHERE id = ?1", [&doc_id], |r| {
            r.get(0)
        })
        .ok();
    if exists.is_some() {
        return Ok(serde_json::json!({
            "status": "already_loaded",
            "doc_id": doc_id,
            "title": title,
        }));
    }

    let total = ingest_text(conn, &doc_id, title, author, "md", raw_text)?;
    seed_sample_glossary(conn, name)?;

    Ok(serde_json::json!({
        "status": "success",
        "doc_id": doc_id,
        "title": title,
        "total_paragraphs": total,
    }))
}

fn delete_document_conn(conn: &Connection, doc_id: &str) -> Result<serde_json::Value, String> {
    // `documents` is keyed by id; the three child tables carry doc_id.
    conn.execute("DELETE FROM documents WHERE id = ?1", [doc_id])
        .map_err(|e| e.to_string())?;
    for table in ["paragraphs", "sentences", "glossary"] {
        conn.execute(&format!("DELETE FROM {table} WHERE doc_id = ?1"), [doc_id])
            .map_err(|e| e.to_string())?;
    }
    Ok(serde_json::json!({"status": "deleted", "doc_id": doc_id}))
}

fn ingest_upload_conn(
    conn: &Connection,
    title: &str,
    content: &str,
    file_ext: &str,
) -> Result<serde_json::Value, String> {
    validate_extension(file_ext)?;
    validate_upload(content)?;
    let doc_id = new_doc_id();
    let total = ingest_text(conn, &doc_id, title, "未知作者", file_ext, content)?;
    Ok(serde_json::json!({
        "status": "success",
        "doc_id": doc_id,
        "title": title,
        "total_paragraphs": total,
    }))
}

#[tauri::command]
pub fn list_documents(app: tauri::AppHandle) -> Result<Vec<DocumentMeta>, String> {
    db::with_conn(&app, list_documents_from)
}

#[tauri::command]
pub fn get_document(app: tauri::AppHandle, doc_id: String) -> Result<serde_json::Value, String> {
    db::with_conn(&app, |conn| get_document_from(conn, &doc_id))
}

#[tauri::command]
pub fn delete_document(app: tauri::AppHandle, doc_id: String) -> Result<serde_json::Value, String> {
    db::with_conn(&app, |conn| delete_document_conn(conn, &doc_id))
}

#[tauri::command]
pub fn upload_document(
    app: tauri::AppHandle,
    title: String,
    content: String,
    file_ext: String,
) -> Result<serde_json::Value, String> {
    db::with_conn(&app, |conn| {
        ingest_upload_conn(conn, &title, &content, &file_ext)
    })
}

#[tauri::command]
pub fn load_sample(
    app: tauri::AppHandle,
    sample_name: String,
) -> Result<serde_json::Value, String> {
    db::with_conn(&app, |conn| load_sample_conn(conn, &sample_name))
}

/// Writes a document's translations and sentence analyses to `path` as Markdown.
///
/// Mirrors `export_anki_to`: the frontend owns the save dialog and passes the
/// chosen path, so this command never opens UI of its own. Reads cached rows
/// only — exporting never spends a model call.
#[tauri::command]
pub fn export_markdown_to(
    app: tauri::AppHandle,
    doc_id: String,
    path: String,
) -> Result<serde_json::Value, String> {
    let path_for_result = path.clone();
    let bytes = db::with_conn(&app, |conn| {
        crate::export::write_document_markdown_to(conn, &doc_id, &path)
    })?;
    let (title, sentences): (String, i64) = db::with_conn(&app, |conn| {
        let title: String = conn
            .query_row("SELECT title FROM documents WHERE id = ?1", [&doc_id], |r| r.get(0))
            .unwrap_or_default();
        let n: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM sentences
                 WHERE doc_id = ?1 AND translation IS NOT NULL AND TRIM(translation) <> ''",
                [&doc_id],
                |r| r.get(0),
            )
            .unwrap_or(0);
        Ok((title, n))
    })?;
    Ok(serde_json::json!({
        "status": "written",
        "path": path_for_result,
        "bytes": bytes,
        "title": title,
        "sentences": sentences,
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
    fn test_validate_upload_rejects_empty() {
        assert!(validate_upload("").is_err());
        assert!(validate_upload("   \n\n  \n").is_err());
    }

    #[test]
    fn test_validate_upload_rejects_garbled_utf8() {
        // Review Focus #1: GBK bytes mis-decoded by FileReader -> U+FFFD soup.
        let garbled = "\u{FFFD}\u{FFFD}\u{FFFD}\u{FFFD}一些乱码\u{FFFD}";
        let err = validate_upload(garbled).unwrap_err();
        assert!(err.contains("编码"), "got: {err}");
        assert!(validate_upload("Call me Ishmael. Some years ago.").is_ok());
    }

    #[test]
    fn test_validate_upload_tolerates_one_stray_replacement_char() {
        let s = format!(
            "Call me Ishmael.{}\u{FFFD} Some years ago.",
            " ".repeat(4000)
        );
        assert!(validate_upload(&s).is_ok());
    }

    #[test]
    fn test_ingest_text_creates_rows() {
        let conn = mem_db();
        let total = ingest_text(
            &conn,
            "doc_x",
            "Test Book",
            "Author",
            "md",
            "Call me Ishmael.\n\nSome years ago, I went to sea.",
        )
        .unwrap();
        assert_eq!(total, 2);
        let n_docs: i64 = conn
            .query_row("SELECT COUNT(*) FROM documents", [], |r| r.get(0))
            .unwrap();
        let n_paras: i64 = conn
            .query_row("SELECT COUNT(*) FROM paragraphs", [], |r| r.get(0))
            .unwrap();
        let n_sents: i64 = conn
            .query_row("SELECT COUNT(*) FROM sentences", [], |r| r.get(0))
            .unwrap();
        assert_eq!((n_docs, n_paras, n_sents), (1, 2, 2));
        let sid: String = conn
            .query_row("SELECT id FROM sentences LIMIT 1", [], |r| r.get(0))
            .unwrap();
        assert_eq!(sid, "doc_x_p1_s1");
    }

    #[test]
    fn test_get_document_shape() {
        let conn = mem_db();
        ingest_text(&conn, "doc_x", "T", "A", "md", "Call me Ishmael.").unwrap();
        let v = get_document_from(&conn, "doc_x").unwrap();
        assert_eq!(v["id"], "doc_x");
        assert_eq!(v["title"], "T");
        assert_eq!(v["paragraphs"].as_array().unwrap().len(), 1);
        let s0 = &v["paragraphs"][0]["sentences"][0];
        assert_eq!(s0["sentence_id"], "doc_x_p1_s1");
        assert_eq!(s0["has_deep_analysis"], false);
        assert!(v["glossary"].is_array());
    }

    #[test]
    fn test_get_document_missing_is_chinese_error() {
        let conn = mem_db();
        assert_eq!(get_document_from(&conn, "nope").unwrap_err(), "文档未找到");
    }

    #[test]
    fn test_load_sample_seeds_glossary_and_is_idempotent() {
        let conn = mem_db();
        let first = load_sample_conn(&conn, "moby_dick").unwrap();
        assert_eq!(first["status"], "success");
        assert_eq!(first["doc_id"], "sample_moby_dick");
        assert!(first["total_paragraphs"].as_u64().unwrap() > 0);
        assert_eq!(
            glossary::get_document_glossary(&conn, "sample_moby_dick")
                .unwrap()
                .len(),
            3
        );

        let second = load_sample_conn(&conn, "moby_dick").unwrap();
        assert_eq!(second["status"], "already_loaded");
    }

    #[test]
    fn test_load_sample_unknown_name_falls_back_to_moby_dick() {
        let conn = mem_db();
        let v = load_sample_conn(&conn, "not_a_book").unwrap();
        assert_eq!(v["doc_id"], "sample_moby_dick");
    }

    #[test]
    fn test_delete_document_removes_all_four_tables() {
        let conn = mem_db();
        load_sample_conn(&conn, "moby_dick").unwrap();
        let out = delete_document_conn(&conn, "sample_moby_dick").unwrap();
        assert_eq!(out["status"], "deleted");
        for table in ["documents", "paragraphs", "sentences", "glossary"] {
            let n: i64 = conn
                .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r.get(0))
                .unwrap();
            assert_eq!(n, 0, "{table} not emptied");
        }
    }

    #[test]
    fn test_upload_rejects_empty_without_writing_a_row() {
        let conn = mem_db();
        assert!(ingest_upload_conn(&conn, "T", "   \n ", "md").is_err());
        assert_documents_empty(&conn, "empty upload");
    }

    #[test]
    fn test_upload_rejects_a_misencoded_file_without_writing_a_row() {
        // Review Focus #1, the side-effect half: validate_upload is called before
        // new_doc_id/ingest_text, so a rejected encoding leaves the db untouched.
        // Reordering those two lines would still pass every other test here.
        let conn = mem_db();
        let garbled = "\u{FFFD}\u{FFFD}\u{FFFD}无法解码\u{FFFD}\u{FFFD}";
        assert!(ingest_upload_conn(&conn, "老舍", garbled, "txt").is_err());
        assert_documents_empty(&conn, "misencoded upload");
    }

    #[test]
    fn test_upload_accepts_only_the_three_supported_extensions() {
        for ext in ["md", "markdown", "txt", ".MD", "  Txt "] {
            assert!(validate_extension(ext).is_ok(), "{ext} should be accepted");
        }
        for ext in ["pdf", "epub", "docx", "html"] {
            let err = validate_extension(ext).unwrap_err();
            assert!(err.contains(ext), "the message should name the type: {err}");
            assert!(
                err.contains(".md"),
                "the message should say what is supported: {err}"
            );
        }
        assert!(validate_extension("").is_err());
        assert!(validate_extension("no-extension").is_err());
    }

    #[test]
    fn test_upload_rejects_an_unsupported_extension_without_writing_a_row() {
        let conn = mem_db();
        let err = ingest_upload_conn(&conn, "book", "Call me Ishmael.", "pdf").unwrap_err();
        assert!(err.contains("pdf"), "got {err}");
        assert_documents_empty(&conn, "unsupported extension");
    }

    fn assert_documents_empty(conn: &Connection, what: &str) {
        let n: i64 = conn
            .query_row("SELECT COUNT(*) FROM documents", [], |r| r.get(0))
            .unwrap();
        assert_eq!(n, 0, "{what} must not create a document row");
        let p: i64 = conn
            .query_row("SELECT COUNT(*) FROM paragraphs", [], |r| r.get(0))
            .unwrap();
        assert_eq!(p, 0, "{what} must not create a paragraph row");
    }

    #[test]
    fn test_list_documents_returns_every_field_in_the_right_slot() {
        // The SELECT listed d.created_at at index 4 while the row mapper read an
        // integer there, so this command failed on every call and the dropdown was
        // silently left empty. It had no test at all until now.
        let conn = Connection::open_in_memory().unwrap();
        crate::db::init_conn(&conn).unwrap();
        conn.execute(
            "INSERT INTO documents (id,title,author,file_type,raw_content,created_at)
         VALUES ('d1','白鲸记 (Moby-Dick)','Herman Melville','md','x','2020-01-01 00:00:00')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO documents (id,title,author,file_type,raw_content,created_at)
         VALUES ('d2','Empty','A','txt','x','2021-01-01 00:00:00')",
            [],
        )
        .unwrap();

        let docs = list_documents_from(&conn).unwrap();
        assert_eq!(docs.len(), 2);
        // newest first
        assert_eq!(docs[0].id, "d2");
        let moby = &docs[1];
        assert_eq!(moby.id, "d1");
        assert_eq!(moby.title, "白鲸记 (Moby-Dick)");
        assert_eq!(moby.author, "Herman Melville");
        assert_eq!(moby.file_type, "md");
        assert_eq!(moby.created_at, "2020-01-01 00:00:00");
        // a document with no paragraphs yet must report zero, not a join artifact
        assert_eq!(docs[0].total_paragraphs, 0);
        assert_eq!(docs[0].total_sentences, 0);
    }

    /// A document long enough for the old query's cost to show. 400 paragraphs x 5
    /// sentences is a short novella; the cross join turned that into 2 000 rows per
    /// document before aggregating.
    #[test]
    fn test_list_documents_stays_fast_on_a_full_length_book() {
        let conn = Connection::open_in_memory().unwrap();
        crate::db::init_conn(&conn).unwrap();
        conn.execute(
            "INSERT INTO documents (id,title,author,file_type,raw_content,created_at)
         VALUES ('d1','Moby-Dick','Melville','md','x','2020')",
            [],
        )
        .unwrap();
        for i in 0..400 {
            let p_id = format!("d1_p{i}");
            conn.execute(
                "INSERT INTO paragraphs (id,doc_id,chapter_id,order_index,raw_text)
             VALUES (?1,'d1','ch_1',?2,'para')",
                rusqlite::params![p_id, i],
            )
            .unwrap();
            for j in 0..5 {
                conn.execute(
                    "INSERT INTO sentences (id,doc_id,paragraph_id,order_index,original)
                 VALUES (?1,'d1',?2,?3,'Call me Ishmael.')",
                    rusqlite::params![format!("{p_id}_s{j}"), p_id, j],
                )
                .unwrap();
            }
        }

        let started = std::time::Instant::now();
        let docs = list_documents_from(&conn).unwrap();
        let elapsed = started.elapsed();

        assert_eq!(docs.len(), 1);
        assert_eq!(docs[0].total_paragraphs, 400, "counts must stay correct");
        assert_eq!(docs[0].total_sentences, 2000, "counts must stay correct");
        assert!(
            elapsed.as_millis() < 300,
            "listing a 400-paragraph book took {elapsed:?}; the paragraph x sentence \
         cross join is back"
        );
    }
}
