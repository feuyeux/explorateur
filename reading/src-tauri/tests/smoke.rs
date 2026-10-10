// Full-pipeline smoke test: ingest a sample book, analyse a paragraph in mock
// mode, cache the result, add vocabulary, and export an Anki TSV.
use ready_reader_lib::commands::analysis::{
    analyze_paragraph_conn, get_sentence_analysis_conn, load_provider_cfg,
};
use ready_reader_lib::commands::documents::{get_document_from, ingest_text, SAMPLE_MOBY_DICK};
use ready_reader_lib::llm::analyze_paragraph_structured;
use ready_reader_lib::vocab::{add_vocabulary_item, export_vocabulary_anki_tsv};
use rusqlite::Connection;

fn temp_conn(tag: &str) -> (std::path::PathBuf, Connection) {
    let dir = std::env::temp_dir().join(format!("rr_smoke_{tag}_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let file = dir.join("smoke.db");
    let conn = Connection::open(&file).unwrap();
    conn.execute_batch(include_str!("../src/schema_minimal.sql"))
        .unwrap();
    (dir, conn)
}

#[test]
fn full_pipeline_mock_mode() {
    let (dir, conn) = temp_conn("pipeline");

    // 1. Ingest the built-in sample book.
    let total = ingest_text(
        &conn,
        "sample_moby_dick",
        "白鲸记 (Moby-Dick)",
        "Herman Melville",
        "md",
        SAMPLE_MOBY_DICK,
        "en-US",
    )
    .unwrap();
    // 2 title lines + the prose paragraphs; the same shape the TXT produced.
    assert!(
        (4..=8).contains(&total),
        "expected a multi-paragraph book, got {total}"
    );

    // 2. Analyse the paragraph holding the famous opening line. The book's
    //    first paragraphs are title lines, so the prose is not paragraph 0.
    let doc = get_document_from(&conn, "sample_moby_dick").unwrap();
    let p0 = doc["paragraphs"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["raw_text"].as_str().unwrap().contains("Call me Ishmael."))
        .expect("the sample must contain the opening line")
        .clone();
    let p0_id = p0["paragraph_id"].as_str().unwrap().to_string();
    let sents_meta: Vec<(String, String)> = p0["sentences"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| {
            (
                s["sentence_id"].as_str().unwrap().to_string(),
                s["original"].as_str().unwrap().to_string(),
            )
        })
        .collect();
    assert!(!sents_meta.is_empty());

    let cfg = load_provider_cfg(&conn);
    let (analysed, provenance) = tauri::async_runtime::block_on(analyze_paragraph_structured(
        &cfg,
        &p0_id,
        p0["raw_text"].as_str().unwrap(),
        &sents_meta,
        "",
    ));
    assert_eq!(provenance.engine, "offline-demo");
    assert_eq!(analysed.len(), sents_meta.len());
    assert!(analysed
        .iter()
        .all(|a| sents_meta.iter().any(|(id, _)| id == &a.sentence_id)));

    // 3. The curated entry really is curated, not heuristic boilerplate.
    let ishmael = analysed
        .iter()
        .find(|a| a.original.contains("Call me Ishmael."))
        .expect("the opening line must be present");
    assert_eq!(ishmael.translation, "叫我以实玛利吧。");
    let sentence_id = ishmael.sentence_id.clone();

    // 4. Cache write through the command path: the curated sentence keeps its
    //    real translation in the database, while the demo engine's echo for
    //    the non-curated ones is not persisted — the paragraph stays retryable
    //    instead of reading as translated forever while showing the original.
    let first = tauri::async_runtime::block_on(analyze_paragraph_conn(&conn, &p0_id)).unwrap();
    assert_eq!(first["source"], "generated");
    let stored: Option<String> = conn
        .query_row(
            "SELECT translation FROM sentences WHERE id = ?1",
            [&sentence_id],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(stored.as_deref(), Some("叫我以实玛利吧。"));
    let second = tauri::async_runtime::block_on(analyze_paragraph_conn(&conn, &p0_id)).unwrap();
    assert_eq!(
        second["source"], "generated",
        "a paragraph whose non-curated sentences only got demo echoes must stay retryable"
    );

    // 5. Deep analysis for a single sentence.
    let deep =
        tauri::async_runtime::block_on(get_sentence_analysis_conn(&conn, &sentence_id)).unwrap();
    assert_eq!(deep["sentence_id"], sentence_id.as_str());

    // 6. Vocabulary notebook + Anki export.
    add_vocabulary_item(
        &conn,
        "Ishmael",
        "专有名词",
        "以实玛利",
        "Call me Ishmael.",
        &sentence_id,
        "《圣经》亚伯拉罕之子",
    )
    .unwrap();
    let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
    assert!(tsv.starts_with("#separator:tab\n#html:true\n#tags column:5\n"));
    assert!(tsv.contains("Ishmael"));
    assert!(tsv.contains("ReadyReader ForeignLiterature"));

    // 7. Nothing was written under an id the caller never asked for.
    let stored_ids: Vec<String> = {
        let mut stmt = conn
            .prepare("SELECT id FROM sentences WHERE doc_id='sample_moby_dick'")
            .unwrap();
        let ids = stmt
            .query_map([], |r| r.get::<_, String>(0))
            .unwrap()
            .map(|r| r.unwrap())
            .collect();
        ids
    };
    assert!(stored_ids
        .iter()
        .all(|id| id.starts_with("sample_moby_dick_")));

    drop(conn);
    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn full_pipeline_rejects_empty_upload_without_side_effects() {
    let (dir, conn) = temp_conn("reject");
    let before: i64 = conn
        .query_row("SELECT COUNT(*) FROM documents", [], |r| r.get(0))
        .unwrap();
    assert_eq!(before, 0);
    let err = ready_reader_lib::commands::documents::validate_upload("   \n\t ").unwrap_err();
    assert!(err.contains("为空"), "got {err}");
    let after: i64 = conn
        .query_row("SELECT COUNT(*) FROM documents", [], |r| r.get(0))
        .unwrap();
    assert_eq!(after, 0, "a rejected upload must not create rows");
    drop(conn);
    std::fs::remove_dir_all(&dir).ok();
}
