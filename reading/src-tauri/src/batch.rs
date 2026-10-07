// Whole-document analysis: translate every paragraph, then deepen every
// sentence, as one cancellable background job.
//
// Two things shaped this design:
//
//   * Every paragraph and sentence is cached individually, so the job is
//     naturally resumable — re-running only picks up what is still missing.
//     That matters because a full book is hundreds of model calls.
//   * The app had no progress channel at all (`prefetch_next_paragraph` runs
//     silently), which is fine for a speculative warm-up and useless for a
//     job the user is waiting on. Progress is therefore *pulled*: the
//     frontend polls `progress()`. That avoids introducing an event bus for
//     one screen, and cannot lose a listener or leak one across windows.
use crate::commands::analysis::{analyze_paragraph_conn, get_sentence_analysis_conn, load_provider_cfg};
use crate::db;
use crate::llm::is_mock;
use rusqlite::Connection;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Mutex, MutexGuard, OnceLock};
use tauri::AppHandle;

/// Requested worker count. Kept modest on purpose: three parallel calls is
/// already enough to hide latency, and a higher number walks straight into
/// provider rate limits — which turn a slow run into a failed one.
pub const DEFAULT_CONCURRENCY: usize = 3;

#[derive(Debug, Default, Clone)]
pub struct BatchState {
    pub running: bool,
    pub doc_id: String,
    /// "paragraphs" | "sentences" | "idle"
    pub phase: String,
    pub done: usize,
    pub total: usize,
    pub failed: usize,
    pub current: String,
    pub last_error: Option<String>,
    pub cancel: bool,
}

static STATE: OnceLock<Mutex<BatchState>> = OnceLock::new();

fn state() -> MutexGuard<'static, BatchState> {
    STATE
        .get_or_init(|| Mutex::new(BatchState::default()))
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// The work a run still has to do.
///
/// Only unfinished items are listed. A paragraph counts as translated once any
/// of its sentences carries a translation; a sentence counts as analysed once
/// it has a cached `deep_analysis_json`.
#[derive(Debug, Default, PartialEq)]
pub struct Plan {
    pub paragraphs: Vec<String>,
    pub sentences: Vec<String>,
    pub paragraphs_skipped: usize,
    pub sentences_skipped: usize,
}

impl Plan {
    pub fn total(&self) -> usize {
        self.paragraphs.len() + self.sentences.len()
    }
    pub fn is_empty(&self) -> bool {
        self.total() == 0
    }
}

pub fn plan_batch(conn: &Connection, doc_id: &str) -> Result<Plan, String> {
    let mut paragraphs = Vec::new();
    {
        let mut stmt = conn
            .prepare(
                "SELECT p.id FROM paragraphs p
                 WHERE p.doc_id = ?1
                   AND NOT EXISTS (
                     SELECT 1 FROM sentences s
                     WHERE s.paragraph_id = p.id
                       AND s.translation IS NOT NULL AND TRIM(s.translation) <> ''
                   )
                 ORDER BY p.order_index",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([doc_id], |r| r.get::<_, String>(0))
            .map_err(|e| e.to_string())?;
        for row in rows {
            paragraphs.push(row.map_err(|e| e.to_string())?);
        }
    }
    let paragraphs_skipped = {
        let mut stmt = conn
            .prepare("SELECT COUNT(*) FROM paragraphs WHERE doc_id = ?1")
            .map_err(|e| e.to_string())?;
        stmt.query_row([doc_id], |r| r.get::<_, i64>(0))
            .map_err(|e| e.to_string())? as usize
            - paragraphs.len()
    };

    let mut sentences = Vec::new();
    {
        let mut stmt = conn
            .prepare(
                "SELECT id FROM sentences
                 WHERE doc_id = ?1
                   AND (deep_analysis_json IS NULL OR TRIM(deep_analysis_json) = '')
                 ORDER BY paragraph_id, order_index",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([doc_id], |r| r.get::<_, String>(0))
            .map_err(|e| e.to_string())?;
        for row in rows {
            sentences.push(row.map_err(|e| e.to_string())?);
        }
    }
    let sentences_skipped = {
        let mut stmt = conn
            .prepare("SELECT COUNT(*) FROM sentences WHERE doc_id = ?1")
            .map_err(|e| e.to_string())?;
        stmt.query_row([doc_id], |r| r.get::<_, i64>(0))
            .map_err(|e| e.to_string())? as usize
            - sentences.len()
    };

    Ok(Plan {
        paragraphs,
        sentences,
        paragraphs_skipped,
        sentences_skipped,
    })
}

fn cancelled() -> bool {
    state().cancel
}

/// Reports a refusal to run the batch at all.
///
/// This guard is the whole point of the feature existing safely. The offline
/// engine answers instantly with `【译文】<原文>`; a whole-book run would spend
/// minutes "working" and then leave hundreds of placeholder rows in the cache,
/// which look exactly like real translations in every later read and export.
pub fn guard_against_offline(conn: &Connection) -> Result<(), String> {
    let cfg = load_provider_cfg(conn);
    if is_mock(&cfg) {
        return Err(
            "当前是内置离线演示模式，批量跑只会把「【译文】+原文」占位符写满全书缓存。\
             请先在「⚙️ 设置」里选择模型提供商、填入 API Key，并取消勾选「优先离线演示模式」。"
                .to_string(),
        );
    }
    Ok(())
}

fn bump_done(label: &str, ok: bool, err: Option<String>) {
    let mut st = state();
    st.current = label.to_string();
    st.done += 1;
    if !ok {
        st.failed += 1;
        if let Some(e) = err {
            st.last_error = Some(e);
        }
    }
}

/// Runs one phase with `concurrency` workers pulling from a shared index, and
/// returns once every worker has drained the queue.
///
/// Workers pull from an atomic counter instead of taking a semaphore: the
/// queue is already in order, so a work-stealing runtime buys nothing here and
/// an atomic keeps the worker bodies trivial.
async fn run_phase(app: &AppHandle, items: Vec<String>, sentence_mode: bool, concurrency: usize) {
    let total = items.len();
    if total == 0 {
        return;
    }
    {
        // `total` is fixed for the whole run, not per phase: growing it as each
        // phase starts would walk the progress bar backwards from 100%.
        let mut st = state();
        st.phase = if sentence_mode { "sentences" } else { "paragraphs" }.into();
    }
    let next = std::sync::Arc::new(AtomicUsize::new(0));

    let mut handles = Vec::with_capacity(concurrency.max(1));
    for _ in 0..concurrency.max(1) {
        let app = app.clone();
        let next = next.clone();
        let items = items.clone();
        handles.push(tauri::async_runtime::spawn(async move {
            loop {
                if cancelled() {
                    return;
                }
                let i = next.fetch_add(1, Ordering::SeqCst);
                if i >= items.len() {
                    return;
                }
                let id = items[i].clone();
                let label = if sentence_mode {
                    format!("{} · 句子 {}/{}", if items.is_empty() { "" } else { "深度解析" }, i + 1, total)
                } else {
                    format!("翻译段落 {}/{}", i + 1, total)
                };

                // `run_blocking` puts the synchronous SQLite work on the
                // blocking pool, where `block_on` is legal. See `run_blocking`.
                let job_app = app.clone();
                let job_id = id.clone();
                let res = crate::run_blocking(move || -> Result<serde_json::Value, String> {
                    db::with_conn(&job_app, |conn| {
                        tauri::async_runtime::block_on(async {
                            if sentence_mode {
                                get_sentence_analysis_conn(conn, &job_id).await
                            } else {
                                analyze_paragraph_conn(conn, &job_id).await
                            }
                        })
                    })
                })
                .await;

                match res {
                    Ok(_) => bump_done(&label, true, None),
                    Err(e) => bump_done(&label, false, Some(e)),
                }
            }
        }));
    }

    for h in handles {
        let _ = h.await;
    }
}

/// Kicks off a whole-document run. Returns immediately; progress comes from
/// [`progress`].
pub fn start(app: AppHandle, doc_id: String, concurrency: Option<usize>) -> Result<serde_json::Value, String> {
    {
        let st = state();
        if st.running {
            return Err("已有一个全文翻译任务在运行中".to_string());
        }
    }

    let plan = db::with_conn(&app, |conn| {
        guard_against_offline(conn)?;
        plan_batch(conn, &doc_id)
    })?;

    if plan.is_empty() {
        return Ok(serde_json::json!({
            "started": false,
            "reason": "nothing_to_do",
            "total": 0,
        }));
    }

    let total = plan.total();
    let paragraphs_left = plan.paragraphs.len();
    let sentences_left = plan.sentences.len();
    {
        let mut st = state();
        *st = BatchState {
            running: true,
            doc_id: doc_id.clone(),
            phase: "paragraphs".into(),
            done: 0,
            total,
            failed: 0,
            current: String::new(),
            last_error: None,
            cancel: false,
        };
    }

    // One orchestrator task owns both phases. Sentences wait for the paragraph
    // phase to drain: deep analysis reads its paragraph, and firing them
    // together would have a worker analyse a sentence whose paragraph
    // translation has not landed yet.
    let conc = concurrency.unwrap_or(DEFAULT_CONCURRENCY).clamp(1, 8);
    let paragraphs = plan.paragraphs.clone();
    let sentences = plan.sentences.clone();
    tauri::async_runtime::spawn(async move {
        run_phase(&app, paragraphs, false, conc).await;
        if !cancelled() {
            run_phase(&app, sentences, true, conc).await;
        }
        let mut st = state();
        st.running = false;
        st.phase = "idle".into();
        st.current.clear();
    });

    Ok(serde_json::json!({
        "started": true,
        "total": total,
        "paragraphs": paragraphs_left,
        "sentences": sentences_left,
        "paragraphs_already_done": plan.paragraphs_skipped,
        "sentences_already_done": plan.sentences_skipped,
    }))
}

pub fn cancel() -> serde_json::Value {
    let mut st = state();
    if st.running {
        st.cancel = true;
    }
    serde_json::json!({ "cancelling": st.running })
}

pub fn progress() -> serde_json::Value {
    let st = state();
    serde_json::json!({
        "running": st.running,
        "cancelling": st.cancel,
        "doc_id": st.doc_id,
        "phase": st.phase,
        "done": st.done,
        "total": st.total,
        "failed": st.failed,
        "current": st.current,
        "last_error": st.last_error,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mem_db() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        crate::db::init_conn(&conn).unwrap();
        conn
    }

    fn seed(conn: &Connection) {
        conn.execute(
            "INSERT INTO documents (id,title,author,file_type,raw_content,created_at)
             VALUES ('d1','白鲸记','Melville','md','x','2026')",
            [],
        )
        .unwrap();
        conn.execute("INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'a')", []).unwrap();
        conn.execute("INSERT INTO paragraphs VALUES ('p2','d1','ch_1',1,'b')", []).unwrap();
        conn.execute(
            "INSERT INTO sentences (id,doc_id,paragraph_id,order_index,original,translation,deep_analysis_json)
             VALUES ('s1','d1','p1',0,'One.','','')", [],
        ).unwrap();
        conn.execute(
            "INSERT INTO sentences (id,doc_id,paragraph_id,order_index,original,translation,deep_analysis_json)
             VALUES ('s2','d1','p1',1,'Two.',NULL,NULL)", [],
        ).unwrap();
        conn.execute(
            "INSERT INTO sentences (id,doc_id,paragraph_id,order_index,original,translation,deep_analysis_json)
             VALUES ('s3','d1','p2',0,'Three.',NULL,NULL)", [],
        ).unwrap();
    }

    #[test]
    fn plans_every_untranslated_paragraph_and_unanalysed_sentence() {
        let conn = mem_db();
        seed(&conn);
        let plan = plan_batch(&conn, "d1").unwrap();
        assert_eq!(plan.paragraphs, vec!["p1".to_string(), "p2".to_string()]);
        assert_eq!(plan.sentences, vec!["s1".to_string(), "s2".to_string(), "s3".to_string()]);
        assert_eq!(plan.total(), 5);
    }

    #[test]
    fn a_translated_paragraph_is_left_out_so_a_rerun_resumes() {
        let conn = mem_db();
        seed(&conn);
        conn.execute("UPDATE sentences SET translation='一句。' WHERE id='s1'", []).unwrap();

        let plan = plan_batch(&conn, "d1").unwrap();
        assert_eq!(plan.paragraphs, vec!["p2".to_string()], "p1 is done");
        assert_eq!(plan.paragraphs_skipped, 1);
        assert_eq!(plan.sentences.len(), 3, "a translated sentence can still need deep analysis");
    }

    #[test]
    fn an_analysed_sentence_is_left_out() {
        let conn = mem_db();
        seed(&conn);
        conn.execute("UPDATE sentences SET translation='一句。' WHERE id='s1'", []).unwrap();
        conn.execute("UPDATE sentences SET deep_analysis_json='{}' WHERE id='s2'", []).unwrap();

        let plan = plan_batch(&conn, "d1").unwrap();
        assert_eq!(plan.paragraphs, vec!["p2".to_string()]);
        assert!(!plan.sentences.contains(&"s2".to_string()));
        assert_eq!(plan.sentences_skipped, 1);
    }

    #[test]
    fn a_finished_document_plans_nothing() {
        let conn = mem_db();
        seed(&conn);
        conn.execute("UPDATE sentences SET translation='x', deep_analysis_json='{}'", []).unwrap();
        let plan = plan_batch(&conn, "d1").unwrap();
        assert!(plan.is_empty());
        assert_eq!(plan.total(), 0);
    }

    #[test]
    fn whitespace_is_not_a_translation() {
        let conn = mem_db();
        seed(&conn);
        conn.execute("UPDATE sentences SET translation='   ' WHERE id='s1'", []).unwrap();
        let plan = plan_batch(&conn, "d1").unwrap();
        assert!(plan.paragraphs.contains(&"p1".to_string()));
    }

    #[test]
    fn other_documents_are_never_touched() {
        let conn = mem_db();
        seed(&conn);
        conn.execute(
            "INSERT INTO documents (id,title,author,file_type,raw_content,created_at)
             VALUES ('d2','Other','A','md','x','2026')", [],
        ).unwrap();
        conn.execute("INSERT INTO paragraphs VALUES ('q1','d2','ch_1',0,'a')", []).unwrap();
        conn.execute(
            "INSERT INTO sentences (id,doc_id,paragraph_id,order_index,original,translation,deep_analysis_json)
             VALUES ('z1','d2','q1',0,'X.',NULL,NULL)", [],
        ).unwrap();

        let plan = plan_batch(&conn, "d1").unwrap();
        assert!(!plan.paragraphs.contains(&"q1".to_string()));
        assert!(!plan.sentences.contains(&"z1".to_string()));
    }

    #[test]
    fn the_offline_engine_is_refused() {
        // Otherwise a whole-book run spends minutes producing hundreds of rows
        // of 【译文】+原文 that later read and export as if they were real.
        let conn = mem_db();
        seed(&conn);
        let err = guard_against_offline(&conn).unwrap_err();
        assert!(err.contains("离线演示模式"), "got: {err}");

        conn.execute(
            "INSERT OR REPLACE INTO settings (key,value) VALUES ('mock_mode','false')", [],
        ).unwrap();
        conn.execute(
            "INSERT OR REPLACE INTO settings (key,value) VALUES ('api_key','sk-test')", [],
        ).unwrap();
        assert!(guard_against_offline(&conn).is_ok());
    }

    #[test]
    fn a_key_with_mock_mode_still_on_is_refused() {
        let conn = mem_db();
        seed(&conn);
        conn.execute(
            "INSERT OR REPLACE INTO settings (key,value) VALUES ('api_key','sk-test')", [],
        ).unwrap();
        // mock_mode defaults to true, so a filled-in key alone is not enough —
        // exactly the trap the settings UI has to make the user clear.
        assert!(guard_against_offline(&conn).is_err());
    }
}