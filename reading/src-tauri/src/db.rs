// Database layer.
use crate::llm::{is_deep_analysis, PLACEHOLDER_TRANSLATION_PREFIX};
use rusqlite::Connection;
use std::path::PathBuf;
use tauri::Manager;

pub fn db_path(app: &tauri::AppHandle) -> PathBuf {
    app.path()
        .app_data_dir()
        .expect("no app data dir")
        .join("ready_reader.db")
}

// Legacy project-local db, migrated on first launch (spec §3/§4) so the existing
// notebook and analyses survive the move off the Python stack. Only meaningful
// in dev, where the process cwd is src-tauri/; a packaged app has already had
// its migration happen by the time it runs from a bundle.
//
// The first entry is the real one. The old project kept its db at `<repo>/data/`,
// but that directory was removed with the Python stack and the file parked in
// `legacy-backup/`; the code kept probing only the old path, so the migration
// never fired and the notebook silently came up empty.
const LEGACY_DB_CANDIDATES: &[&str] = &[
    "../legacy-backup/data/ready_reader.db",
    "../../data/ready_reader.db",
];

fn legacy_db_path_from(base: &std::path::Path) -> Option<PathBuf> {
    LEGACY_DB_CANDIDATES
        .iter()
        .map(|rel| base.join(rel))
        .filter(|p| p.is_file())
        .find(|p| std::fs::canonicalize(p).is_ok())
}

fn legacy_db_path() -> Option<PathBuf> {
    let cwd = std::env::current_dir().ok()?;
    legacy_db_path_from(&cwd)
}

/// Clears cached rows whose "translation" is the offline demo engine's
/// `【译文】<原文>` echo, together with the heuristic analysis cached beside it.
///
/// Those rows are the residue of analysing a paragraph before any API key was
/// configured. They used to be indistinguishable from real translations, so the
/// paragraph was served from cache forever and never sent to the model — even
/// after a key was configured, the translation pane kept showing the original.
/// The write side now refuses to persist them; this purge heals databases
/// written by older builds. Idempotent, so it is safe to run on every launch.
pub fn purge_placeholder_translations(conn: &Connection) -> Result<usize, String> {
    conn.execute(
        &format!(
            "UPDATE sentences
                SET translation = NULL,
                    deep_analysis_json = NULL,
                    updated_at = datetime('now', 'localtime')
              WHERE translation LIKE '{PLACEHOLDER_TRANSLATION_PREFIX}%'"
        ),
        [],
    )
    .map_err(|e| e.to_string())
}

/// Demotes cached "deep analyses" that carry no analysis content.
///
/// An older build cached the paragraph phase's translation-only objects into
/// `deep_analysis_json`. Served from cache, those made every sentence click
/// show nothing but the translation (the inspector had no sections to
/// render), and the full-book run's deepening phase skipped the sentences as
/// "already analysed". Rows whose JSON carries no grammar/vocabulary/idiom
/// content get the column cleared — the translation stays, so nothing is
/// re-billed. Idempotent, so it runs on every launch alongside the purge.
pub fn demote_shallow_deep_analysis(conn: &Connection) -> Result<usize, String> {
    let mut shallow: Vec<String> = Vec::new();
    {
        let mut stmt = conn
            .prepare(
                "SELECT id, deep_analysis_json FROM sentences
                  WHERE deep_analysis_json IS NOT NULL AND TRIM(deep_analysis_json) <> ''",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
            .map_err(|e| e.to_string())?;
        for row in rows {
            let (id, raw) = row.map_err(|e| e.to_string())?;
            let deep = serde_json::from_str::<serde_json::Value>(&raw)
                .map(|v| is_deep_analysis(&v))
                .unwrap_or(false);
            if !deep {
                shallow.push(id);
            }
        }
    }
    for id in &shallow {
        conn.execute(
            "UPDATE sentences
                SET deep_analysis_json = NULL,
                    updated_at = datetime('now', 'localtime')
              WHERE id = ?1",
            [id],
        )
        .map_err(|e| e.to_string())?;
    }
    Ok(shallow.len())
}

/// Creates the six-table schema, the three indexes, and the default settings
/// seed. Split out of `init_db` so it can be tested against an in-memory db.
pub fn init_conn(conn: &Connection) -> Result<(), String> {
    conn.execute_batch(include_str!("schema_minimal.sql"))
        .map_err(|e| e.to_string())?;

    // Seed default settings (mirrors backend/app/database.py).
    let count: i64 = conn
        .query_row("SELECT COUNT(*) FROM settings", [], |r| r.get(0))
        .map_err(|e| e.to_string())?;
    if count == 0 {
        for (k, v) in [
            ("provider", "mock"),
            ("api_key", ""),
            ("base_url", ""),
            ("model_name", "gpt-4o-mini"),
            ("temperature", "0.2"),
            ("mock_mode", "true"),
        ] {
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
                .map_err(|e| e.to_string())?;
        }
    }

    purge_placeholder_translations(conn)?;
    demote_shallow_deep_analysis(conn)?;
    Ok(())
}

pub fn init_db(app: &tauri::AppHandle) -> Result<(), String> {
    let path = db_path(app);
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }

    // One-time migration from the legacy project-local db.
    if !path.exists() {
        if let Some(legacy) = legacy_db_path() {
            if std::fs::copy(&legacy, &path).is_ok() {
                eprintln!("migrated legacy db from {}", legacy.display());
            }
        }
    }

    let conn = Connection::open(&path).map_err(|e| e.to_string())?;
    conn.pragma_update(None, "journal_mode", "WAL").ok();
    conn.pragma_update(None, "foreign_keys", "ON").ok();
    init_conn(&conn)
}

/// Single entry point for every command's database access.
pub fn with_conn<T>(
    app: &tauri::AppHandle,
    f: impl FnOnce(&Connection) -> Result<T, String>,
) -> Result<T, String> {
    let conn = Connection::open(db_path(app)).map_err(|e| e.to_string())?;
    conn.pragma_update(None, "foreign_keys", "ON").ok();
    f(&conn)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn init_conn_creates_all_six_tables() {
        let conn = Connection::open_in_memory().unwrap();
        init_conn(&conn).unwrap();
        let mut stmt = conn
            .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            .unwrap();
        let names: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(0))
            .unwrap()
            .map(|x| x.unwrap())
            .collect();
        for t in [
            "documents",
            "glossary",
            "paragraphs",
            "sentences",
            "settings",
            "vocabulary_book",
        ] {
            assert!(
                names.contains(&t.to_string()),
                "missing table {t}, got {names:?}"
            );
        }
    }

    #[test]
    fn init_conn_creates_the_three_indexes() {
        let conn = Connection::open_in_memory().unwrap();
        init_conn(&conn).unwrap();
        let mut stmt = conn
            .prepare("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%' ORDER BY name")
            .unwrap();
        let names: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(0))
            .unwrap()
            .map(|x| x.unwrap())
            .collect();
        assert_eq!(
            names,
            vec![
                "idx_paragraphs_doc",
                "idx_sentences_doc",
                "idx_sentences_para"
            ]
        );
    }

    #[test]
    fn init_conn_seeds_six_default_settings() {
        let conn = Connection::open_in_memory().unwrap();
        init_conn(&conn).unwrap();
        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM settings", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 6);
    }

    #[test]
    fn init_conn_seeds_mock_defaults() {
        let conn = Connection::open_in_memory().unwrap();
        init_conn(&conn).unwrap();
        let get = |k: &str| -> String {
            conn.query_row("SELECT value FROM settings WHERE key = ?1", [k], |r| {
                r.get(0)
            })
            .unwrap()
        };
        assert_eq!(get("provider"), "mock");
        assert_eq!(get("model_name"), "gpt-4o-mini");
        assert_eq!(get("temperature"), "0.2");
        assert_eq!(get("mock_mode"), "true");
    }

    #[test]
    fn init_conn_does_not_reseed_existing_settings() {
        let conn = Connection::open_in_memory().unwrap();
        init_conn(&conn).unwrap();
        conn.execute(
            "UPDATE settings SET value='deepseek' WHERE key='provider'",
            [],
        )
        .unwrap();
        init_conn(&conn).unwrap();
        let provider: String = conn
            .query_row("SELECT value FROM settings WHERE key='provider'", [], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(provider, "deepseek");
    }

    /// Seeds one paragraph with a placeholder-only sentence, a fully analysed
    /// one, and one whose cached "analysis" is a translation-only object.
    fn seed_purge_fixture(conn: &Connection) {
        conn.execute(
            "INSERT INTO documents (id,title,author,file_type,raw_content,created_at)
             VALUES ('d1','T','A','md','x','2026')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'raw')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO sentences (id,doc_id,paragraph_id,order_index,original,translation,deep_analysis_json)
             VALUES ('s_ph','d1','p1',0,'One.',?1,'{\"sentence_id\":\"s_ph\"}')",
            [format!("{PLACEHOLDER_TRANSLATION_PREFIX}One.")],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO sentences (id,doc_id,paragraph_id,order_index,original,translation,deep_analysis_json)
             VALUES ('s_real','d1','p1',1,'Two.','真实译文',?1)",
            [r#"{"sentence_id":"s_real","translation":"真实译文","grammar_analysis":{"structure":"陈述句","components":[{"element":"Two","role":"主语 (S)"}]}}"#],
        )
        .unwrap();
        // What the paragraph phase cached before the deep/shallow split: a
        // real translation with a "deep" column holding no analysis at all.
        conn.execute(
            "INSERT INTO sentences (id,doc_id,paragraph_id,order_index,original,translation,deep_analysis_json)
             VALUES ('s_shallow','d1','p1',2,'Three.','第三句',?1)",
            [r#"{"sentence_id":"s_shallow","translation":"第三句","vocabulary_and_phrases":[],"idioms_and_conventions":[]}"#],
        )
        .unwrap();
    }

    fn translation_of(conn: &Connection, id: &str) -> Option<String> {
        conn.query_row(
            "SELECT translation FROM sentences WHERE id = ?1",
            [id],
            |r| r.get(0),
        )
        .unwrap()
    }

    #[test]
    fn init_conn_purges_offline_placeholder_rows_and_keeps_real_ones() {
        // A database written by an older build holds `【译文】` echoes that look
        // exactly like translations to every read path; the startup purge is
        // what heals it, so those paragraphs go back to the model.
        let conn = Connection::open_in_memory().unwrap();
        init_conn(&conn).unwrap();
        seed_purge_fixture(&conn);

        init_conn(&conn).unwrap(); // second launch: idempotent

        let (ph_trans, ph_deep): (Option<String>, Option<String>) = conn
            .query_row(
                "SELECT translation, deep_analysis_json FROM sentences WHERE id='s_ph'",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert!(ph_trans.is_none(), "the placeholder must be cleared");
        assert!(ph_deep.is_none(), "its heuristic analysis must go with it");

        let real = translation_of(&conn, "s_real");
        assert_eq!(real.as_deref(), Some("真实译文"));
        let deep: String = conn
            .query_row(
                "SELECT deep_analysis_json FROM sentences WHERE id='s_real'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert!(deep.contains("陈述句"), "a real analysis must survive");

        // The shallow entry: analysis column cleared, translation kept — the
        // sentence reads as "translated but not deep-analysed", so the next
        // click deepens it instead of serving the empty object forever.
        let (sh_trans, sh_deep): (Option<String>, Option<String>) = conn
            .query_row(
                "SELECT translation, deep_analysis_json FROM sentences WHERE id='s_shallow'",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(sh_trans.as_deref(), Some("第三句"), "no re-billing");
        assert!(sh_deep.is_none(), "the shallow analysis must be demoted");
    }

    #[test]
    fn purge_reports_how_many_rows_it_healed() {
        let conn = Connection::open_in_memory().unwrap();
        init_conn(&conn).unwrap();
        seed_purge_fixture(&conn);
        // Two more placeholder rows to make the count observable.
        conn.execute(
            "INSERT INTO paragraphs VALUES ('p2','d1','ch_1',1,'raw')",
            [],
        )
        .unwrap();
        for i in 0..2 {
            conn.execute(
                "INSERT INTO sentences (id,doc_id,paragraph_id,order_index,original,translation)
                 VALUES (?1,'d1','p2',?2,'X.',?3)",
                rusqlite::params![
                    format!("s_x{i}"),
                    i,
                    format!("{PLACEHOLDER_TRANSLATION_PREFIX}X.")
                ],
            )
            .unwrap();
        }

        assert_eq!(purge_placeholder_translations(&conn).unwrap(), 3);
        assert_eq!(purge_placeholder_translations(&conn).unwrap(), 0);
    }

    #[test]
    fn demote_reports_how_many_rows_it_healed() {
        let conn = Connection::open_in_memory().unwrap();
        init_conn(&conn).unwrap();
        seed_purge_fixture(&conn);
        // s_ph's heuristic stub and s_shallow's translation-only object are
        // both shallow; s_real's real analysis is not.
        assert_eq!(demote_shallow_deep_analysis(&conn).unwrap(), 2);
        assert_eq!(
            demote_shallow_deep_analysis(&conn).unwrap(),
            0,
            "idempotent"
        );
    }

    #[test]
    fn documents_table_matches_legacy_columns() {
        let conn = Connection::open_in_memory().unwrap();
        init_conn(&conn).unwrap();
        conn.execute(
            "INSERT INTO documents (id,title,author,file_type,raw_content,created_at)
             VALUES ('d1','T','A','md','raw','2020')",
            [],
        )
        .unwrap();
        let (t, a, f): (String, String, String) = conn
            .query_row(
                "SELECT title,author,file_type FROM documents WHERE id='d1'",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .unwrap();
        assert_eq!((t.as_str(), a.as_str(), f.as_str()), ("T", "A", "md"));
    }

    #[test]
    fn foreign_keys_cascade_paragraph_delete() {
        let conn = Connection::open_in_memory().unwrap();
        init_conn(&conn).unwrap();
        conn.pragma_update(None, "foreign_keys", "ON").unwrap();
        conn.execute(
            "INSERT INTO documents VALUES ('d1','T','A','md','c','x')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'raw')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO sentences VALUES ('s1','d1','p1',0,'o','t',NULL,NULL)",
            [],
        )
        .unwrap();
        conn.execute("DELETE FROM documents WHERE id='d1'", [])
            .unwrap();
        let n: i64 = conn
            .query_row("SELECT COUNT(*) FROM sentences", [], |r| r.get(0))
            .unwrap();
        assert_eq!(n, 0, "sentences must cascade with the document");
    }

    /// Builds a fake dev cwd plus a legacy db sitting where `rel` lands from
    /// that cwd, and returns `(cwd, sandbox_root)`.
    ///
    /// The cwd is nested three deep — `<sandbox>/workspace/ready/src-tauri` —
    /// so that both real candidates, `../…` and `../../…`, resolve to paths
    /// *inside* the sandbox. With a shallower root, `../../data/…` escapes into
    /// the shared temp directory and the test writes outside its own sandbox.
    /// Cleanup must therefore always target `sandbox_root` and nothing above it.
    fn make_legacy_layout(tag: &str, rel: &str) -> (std::path::PathBuf, std::path::PathBuf) {
        let sandbox = std::env::temp_dir().join(format!("rr_mig_{tag}"));
        let _ = std::fs::remove_dir_all(&sandbox);
        let cwd = sandbox.join("workspace").join("ready").join("src-tauri");
        std::fs::create_dir_all(&cwd).unwrap();
        let file = cwd.join(rel);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(&file, b"legacy").unwrap();
        (cwd, sandbox)
    }

    #[test]
    fn legacy_db_is_found_where_it_actually_lives_now() {
        // The regression: the candidate list probed only `<repo>/data/`, which
        // was deleted along with the Python stack, so the copy never happened
        // and an existing notebook came up empty on first launch.
        let (cwd, sandbox) = make_legacy_layout("parked", "../legacy-backup/data/ready_reader.db");
        let found = legacy_db_path_from(&cwd).expect("the parked legacy db must be found");
        assert!(
            found.ends_with("ready_reader.db"),
            "got {}",
            found.display()
        );
        std::fs::remove_dir_all(sandbox).ok();
    }

    #[test]
    fn legacy_db_still_resolves_from_its_original_project_local_path() {
        let (cwd, sandbox) = make_legacy_layout("oldpath", "../../data/ready_reader.db");
        let found = legacy_db_path_from(&cwd).expect("the pre-Tauri path must keep working");
        assert!(
            found.ends_with("ready_reader.db"),
            "got {}",
            found.display()
        );
        std::fs::remove_dir_all(sandbox).ok();
    }

    #[test]
    fn the_parked_backup_wins_when_both_copies_exist() {
        // Both are the same notebook; preferring the one inside the repo keeps
        // the result independent of whatever sits above the project directory.
        let (cwd, sandbox) = make_legacy_layout("both", "../legacy-backup/data/ready_reader.db");
        let old = cwd.join("../../data");
        std::fs::create_dir_all(&old).unwrap();
        std::fs::write(old.join("ready_reader.db"), b"old").unwrap();

        let found = legacy_db_path_from(&cwd).expect("one of them must be found");
        assert!(
            found.to_string_lossy().contains("legacy-backup"),
            "expected the in-repo backup, got {}",
            found.display()
        );
        std::fs::remove_dir_all(sandbox).ok();
    }

    #[test]
    fn no_legacy_db_is_reported_when_nothing_is_there() {
        let sandbox = std::env::temp_dir().join("rr_mig_none");
        let _ = std::fs::remove_dir_all(&sandbox);
        let cwd = sandbox.join("workspace").join("ready").join("src-tauri");
        std::fs::create_dir_all(&cwd).unwrap();
        assert!(
            legacy_db_path_from(&cwd).is_none(),
            "a missing legacy db must not be reported as found"
        );
        std::fs::remove_dir_all(sandbox).ok();
    }
}
