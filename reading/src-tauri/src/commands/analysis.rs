// Analysis commands: paragraph-level and sentence-level, with a SQLite cache
// and a background prefetch of the next paragraph.
// Ported from backend/app/routers/analysis.py.
use crate::db;
use crate::glossary::format_glossary_for_prompt;
use crate::llm::{
    analyze_paragraph_structured, analyze_single_sentence_deep, is_deep_analysis,
    is_placeholder_translation, ProviderCfg, PLACEHOLDER_TRANSLATION_PREFIX,
};
use chrono::Local;
use rusqlite::Connection;
use std::collections::HashMap;

fn now_str() -> String {
    Local::now().format("%Y-%m-%d %H:%M:%S").to_string()
}

pub fn load_provider_cfg(conn: &Connection) -> ProviderCfg {
    let mut stmt = conn
        .prepare("SELECT key, value FROM settings")
        .expect("settings table exists");
    let rows: HashMap<String, String> = stmt
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
        .expect("settings query")
        .map(|r| r.expect("settings row"))
        .collect();
    let get = |k: &str| rows.get(k).cloned().unwrap_or_default();
    ProviderCfg {
        provider: {
            let p = get("provider");
            if p.is_empty() {
                "mock".to_string()
            } else {
                p
            }
        },
        api_key: get("api_key"),
        base_url: get("base_url"),
        // Left empty on purpose: `llm::resolve_endpoint` picks the per-provider
        // default model. Substituting gpt-4o-mini here sent a claude or
        // deepseek request to the right host with an OpenAI model name.
        model_name: get("model_name"),
        temperature: get("temperature").parse::<f64>().unwrap_or(0.2),
        mock_mode: get("mock_mode") == "true",
    }
}

type SentRow = (String, String, Option<String>, Option<String>);

fn load_sentences(conn: &Connection, paragraph_id: &str) -> Result<Vec<SentRow>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT id, original, translation, deep_analysis_json FROM sentences
             WHERE paragraph_id = ?1 ORDER BY order_index ASC",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([paragraph_id], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, Option<String>>(2)?,
                r.get::<_, Option<String>>(3)?,
            ))
        })
        .map_err(|e| e.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    Ok(rows)
}

fn cache_sentence(
    conn: &Connection,
    sentence_id: &str,
    translation: &str,
    deep_json: &str,
) -> Result<(), String> {
    // A model that returns no translation for one sentence must not replace a
    // good one with an empty string: the paragraph would then look translated
    // forever while showing nothing. A blank result is simply not cached, so
    // the next click retries it.
    if translation.trim().is_empty() {
        return Ok(());
    }
    // The offline demo engine's `【译文】<原文>` echo is not a translation
    // either. Persisting it made a demo click (no key configured yet) mark
    // the paragraph as fully translated forever — from then on it was served
    // from cache and never sent to the model again, even after a key was
    // configured. Refuse to store it, and clear one left behind by an older
    // run so the paragraph reads as untranslated again. A real translation
    // is never touched.
    if is_placeholder_translation(translation) {
        conn.execute(
            "UPDATE sentences
                SET translation = NULL,
                    deep_analysis_json = NULL,
                    updated_at = ?2
              WHERE id = ?1 AND translation LIKE ?3",
            rusqlite::params![
                sentence_id,
                now_str(),
                format!("{PLACEHOLDER_TRANSLATION_PREFIX}%")
            ],
        )
        .map_err(|e| e.to_string())?;
        return Ok(());
    }
    // A deep analysis is cached only when the payload actually is one. A
    // translation-only object — the paragraph phase's normal output before
    // the deepening click, or a model that skipped the analysis fields —
    // must not squat in `deep_analysis_json`: served from cache, it made the
    // inspector show nothing but the translation forever, and the batch's
    // deepening phase skipped the sentence as "already analysed". An
    // existing deep analysis is never clobbered by a shallow payload.
    let deep_to_store: Option<&str> = serde_json::from_str::<serde_json::Value>(deep_json)
        .ok()
        .filter(is_deep_analysis)
        .map(|_| deep_json);
    conn.execute(
        "UPDATE sentences
            SET translation = ?1,
                deep_analysis_json = CASE WHEN ?2 IS NOT NULL THEN ?2
                                          ELSE deep_analysis_json END,
                updated_at = ?3
          WHERE id = ?4",
        rusqlite::params![translation, deep_to_store, now_str(), sentence_id],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

/// A sentence counts as translated only with a real translation in hand: the
/// offline demo engine's `【译文】` echo of the original is explicitly not one,
/// or a paragraph analysed before a key was configured would be served from
/// cache forever while showing its own original.
fn is_translated(translation: &Option<String>) -> bool {
    translation
        .as_deref()
        .is_some_and(|t| !t.trim().is_empty() && !is_placeholder_translation(t))
}

fn parse_deep(raw: &Option<String>) -> serde_json::Value {
    match raw {
        Some(s) => serde_json::from_str(s).unwrap_or(serde_json::Value::Null),
        None => serde_json::Value::Null,
    }
}

pub async fn analyze_paragraph_conn(
    conn: &Connection,
    paragraph_id: &str,
) -> Result<serde_json::Value, String> {
    let (doc_id, raw_text): (String, String) = conn
        .query_row(
            "SELECT doc_id, raw_text FROM paragraphs WHERE id = ?1",
            [paragraph_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .map_err(|_| "段落未找到".to_string())?;

    let s_rows = load_sentences(conn, paragraph_id)?;

    // Every sentence already translated -> serve from cache.
    if s_rows.iter().all(|(_, _, t, _)| is_translated(t)) {
        let sentences: Vec<serde_json::Value> = s_rows
            .iter()
            .map(|(id, orig, trans, deep)| {
                let deep_obj = parse_deep(deep);
                serde_json::json!({
                    "sentence_id": id,
                    "original": orig,
                    "translation": trans,
                    // Content, not mere presence: a shallow object here would
                    // badge the sentence as analysed with nothing to show.
                    "has_deep_analysis": is_deep_analysis(&deep_obj),
                    "deep_analysis": deep_obj,
                })
            })
            .collect();
        return Ok(serde_json::json!({
            "paragraph_id": paragraph_id,
            "sentences": sentences,
            "source": "cache",
            "engine": "cache",
        }));
    }

    let cfg = load_provider_cfg(conn);
    let glossary_context = format_glossary_for_prompt(conn, &doc_id)?;
    let meta: Vec<(String, String)> = s_rows
        .iter()
        .map(|(id, o, _, _)| (id.clone(), o.clone()))
        .collect();

    let (analyzed, provenance) =
        analyze_paragraph_structured(&cfg, paragraph_id, &raw_text, &meta, &glossary_context).await;
    let analyzed_map: HashMap<String, serde_json::Value> = analyzed
        .into_iter()
        .map(|a| {
            let v = serde_json::to_value(&a).unwrap_or(serde_json::Value::Null);
            (a.sentence_id.clone(), v)
        })
        .collect();

    let mut final_sentences = Vec::with_capacity(s_rows.len());
    for (s_id, original, old_translation, _) in &s_rows {
        match analyzed_map.get(s_id) {
            Some(parsed) => {
                let generated = parsed
                    .get("translation")
                    .and_then(|t| t.as_str())
                    .unwrap_or_default()
                    .trim()
                    .to_string();
                // Only a sentence that actually came back translated is marked
                // done; otherwise keep whatever we had and let the next click
                // try again rather than serving a permanent blank.
                let usable = !generated.is_empty();
                // The badge tells the truth about deep-ness: a translation
                // without analysis content is not "has_deep_analysis".
                let deep = is_deep_analysis(parsed);
                let trans = if usable {
                    generated
                } else {
                    old_translation.clone().unwrap_or_default()
                };
                if usable {
                    let deep_json = serde_json::to_string(parsed).map_err(|e| e.to_string())?;
                    cache_sentence(conn, s_id, &trans, &deep_json)?;
                }
                final_sentences.push(serde_json::json!({
                    "sentence_id": s_id,
                    "original": original,
                    "translation": if trans.is_empty() { "【解析中】".to_string() } else { trans },
                    "has_deep_analysis": deep,
                    "deep_analysis": if deep { parsed.clone() } else { serde_json::Value::Null },
                }));
            }
            None => final_sentences.push(serde_json::json!({
                "sentence_id": s_id,
                "original": original,
                "translation": old_translation.clone().unwrap_or_else(|| "【解析中】".to_string()),
                "has_deep_analysis": false,
                "deep_analysis": serde_json::Value::Null,
            })),
        }
    }

    Ok(serde_json::json!({
        "paragraph_id": paragraph_id,
        "sentences": final_sentences,
        "source": "generated",
        // Which engine produced the sentences, and the live-call error behind
        // an offline fallback. Without this, a failed call looked exactly like
        // a finished one: the toast said success while the right pane showed
        // the original.
        "engine": provenance.engine,
        "fallback_reason": provenance.fallback_reason,
    }))
}

pub async fn get_sentence_analysis_conn(
    conn: &Connection,
    sentence_id: &str,
) -> Result<serde_json::Value, String> {
    let (paragraph_id, original, translation, deep_json, doc_id_fallback): (
        String,
        String,
        Option<String>,
        Option<String>,
        String,
    ) = conn
        .query_row(
            "SELECT paragraph_id, original, translation, deep_analysis_json, doc_id
             FROM sentences WHERE id = ?1",
            [sentence_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
        )
        .map_err(|_| "句子未找到".to_string())?;

    if let Some(raw) = &deep_json {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(raw) {
            // Only a real deep analysis short-circuits. A translation-only
            // entry squatting in this column (written by an older build that
            // cached the paragraph phase's shallow output) must fall through
            // and be deepened, not be served forever.
            if is_deep_analysis(&v) {
                return Ok(v);
            }
        }
    }

    let para: Option<(String, String)> = conn
        .query_row(
            "SELECT raw_text, doc_id FROM paragraphs WHERE id = ?1",
            [&paragraph_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .ok();
    let (para_text, doc_id) = match para {
        Some(p) => p,
        None => (original.clone(), doc_id_fallback),
    };

    let cfg = load_provider_cfg(conn);
    let glossary_context = format_glossary_for_prompt(conn, &doc_id)?;
    let (result, provenance) =
        analyze_single_sentence_deep(&cfg, sentence_id, &original, &para_text, &glossary_context)
            .await;

    let mut value = serde_json::to_value(&result).map_err(|e| e.to_string())?;
    // Surface which engine produced this so the caller (the inspector and the
    // batch counters) can tell a real analysis from a demo echo or a silent
    // fallback, which used to be indistinguishable from success.
    if let Some(obj) = value.as_object_mut() {
        obj.insert("engine".into(), serde_json::json!(provenance.engine));
        obj.insert(
            "fallback_reason".into(),
            serde_json::json!(provenance.fallback_reason),
        );
    }
    let trans = if result.translation.trim().is_empty() {
        translation.unwrap_or_default()
    } else {
        result.translation.clone()
    };
    let deep_str = serde_json::to_string(&result).map_err(|e| e.to_string())?;
    cache_sentence(conn, sentence_id, &trans, &deep_str)?;
    Ok(value)
}

/// Warms the cache for the following paragraph so the next click feels instant.
/// Best-effort: any failure only costs the user a repeat of the analysis.
pub async fn prefetch_next_paragraph(app: tauri::AppHandle, doc_id: String, next_order_index: i64) {
    let res = db::with_conn(&app, |conn| {
        let next_p: Option<(String, String)> = conn
            .query_row(
                "SELECT id, raw_text FROM paragraphs WHERE doc_id = ?1 AND order_index = ?2",
                rusqlite::params![doc_id, next_order_index],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .ok();
        let Some((p_id, raw_text)) = next_p else {
            return Ok(None);
        };
        let cached: i64 = conn
            .query_row(
                &format!(
                    "SELECT COUNT(*) FROM sentences
                      WHERE paragraph_id = ?1
                        AND translation IS NOT NULL
                        AND TRIM(translation) <> ''
                        AND translation NOT LIKE '{PLACEHOLDER_TRANSLATION_PREFIX}%'"
                ),
                [&p_id],
                |r| r.get(0),
            )
            .map_err(|e| e.to_string())?;
        if cached > 0 {
            return Ok(None);
        }
        Ok(Some((p_id, raw_text)))
    });

    let Ok(Some((p_id, raw_text))) = res else {
        return;
    };

    let result = db::with_conn(&app, |conn| {
        let s_rows = load_sentences(conn, &p_id)?;
        let cfg = load_provider_cfg(conn);
        let glossary_context = format_glossary_for_prompt(conn, &doc_id)?;
        let meta: Vec<(String, String)> = s_rows
            .iter()
            .map(|(id, o, _, _)| (id.clone(), o.clone()))
            .collect();
        Ok::<_, String>((s_rows, cfg, glossary_context, meta, raw_text))
    });
    let Ok((_s_rows, cfg, glossary_context, meta, raw_text)) = result else {
        return;
    };

    let (analyzed, _provenance) =
        analyze_paragraph_structured(&cfg, &p_id, &raw_text, &meta, &glossary_context).await;
    let _ = db::with_conn(&app, |conn| {
        for a in analyzed {
            let value = serde_json::to_value(&a).map_err(|e| e.to_string())?;
            let deep_str = serde_json::to_string(&a).map_err(|e| e.to_string())?;
            cache_sentence(conn, &a.sentence_id, &a.translation, &deep_str)?;
            let _ = value;
        }
        Ok(())
    });
}

#[tauri::command]
pub async fn analyze_paragraph(
    app: tauri::AppHandle,
    paragraph_id: String,
) -> Result<serde_json::Value, String> {
    // The job is moved onto the blocking pool: `block_on` inside this async body
    // would run as a tokio task and panic. See `run_blocking`.
    let job_app = app.clone();
    let job_paragraph_id = paragraph_id.clone();
    let out = crate::run_blocking(move || -> Result<serde_json::Value, String> {
        db::with_conn(&job_app, |conn| {
            tauri::async_runtime::block_on(analyze_paragraph_conn(conn, &job_paragraph_id))
        })
    })
    .await?;

    // Warm the next paragraph without blocking the response.
    let next = db::with_conn(&app, |conn| {
        conn.query_row(
            "SELECT doc_id, order_index + 1 FROM paragraphs WHERE id = ?1",
            [&paragraph_id],
            |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)),
        )
        .map_err(|e| e.to_string())
    });
    if let Ok((doc_id, next_idx)) = next {
        tauri::async_runtime::spawn(async move {
            prefetch_next_paragraph(app, doc_id, next_idx).await;
        });
    }

    Ok(out)
}

#[tauri::command]
pub async fn get_sentence_analysis(
    app: tauri::AppHandle,
    sentence_id: String,
) -> Result<serde_json::Value, String> {
    let job_app = app.clone();
    crate::run_blocking(move || -> Result<serde_json::Value, String> {
        db::with_conn(&job_app, |conn| {
            tauri::async_runtime::block_on(get_sentence_analysis_conn(conn, &sentence_id))
        })
    })
    .await
}

/// Starts a whole-document run: translate every untranslated paragraph, then
/// deepen every un-analysed sentence.
///
/// Returns as soon as the job is queued; the frontend polls
/// [`batch_progress`] for counters. Refuses to start in the offline demo mode —
/// see [`crate::batch::guard_against_offline`].
#[tauri::command]
pub fn start_batch_analysis(
    app: tauri::AppHandle,
    doc_id: String,
    concurrency: Option<usize>,
) -> Result<serde_json::Value, String> {
    crate::batch::start(app, doc_id, concurrency)
}

#[tauri::command]
pub fn batch_progress() -> serde_json::Value {
    crate::batch::progress()
}

#[tauri::command]
pub fn cancel_batch_analysis() -> serde_json::Value {
    crate::batch::cancel()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::documents::ingest_text;
    use rusqlite::Connection;

    fn block_on<F: std::future::Future>(f: F) -> F::Output {
        tauri::async_runtime::block_on(f)
    }

    fn mem_db() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        crate::db::init_conn(&conn).unwrap();
        conn
    }

    fn seeded() -> Connection {
        let conn = mem_db();
        ingest_text(
            &conn,
            "doc_x",
            "T",
            "A",
            "md",
            "Call me Ishmael.\n\nSome years ago, I went to sea.",
            "en-US",
        )
        .unwrap();
        conn
    }

    #[test]
    fn test_load_provider_cfg_reads_settings() {
        let conn = mem_db();
        let cfg = load_provider_cfg(&conn);
        assert_eq!(cfg.provider, "mock");
        assert_eq!(cfg.model_name, "gpt-4o-mini");
        assert!((cfg.temperature - 0.2).abs() < f64::EPSILON);
        assert!(cfg.mock_mode);
    }

    #[test]
    fn test_load_provider_cfg_parses_temperature_and_bool() {
        let conn = mem_db();
        conn.execute(
            "UPDATE settings SET value='0.9' WHERE key='temperature'",
            [],
        )
        .unwrap();
        conn.execute(
            "UPDATE settings SET value='false' WHERE key='mock_mode'",
            [],
        )
        .unwrap();
        let cfg = load_provider_cfg(&conn);
        assert!((cfg.temperature - 0.9).abs() < 1e-9);
        assert!(!cfg.mock_mode);
    }

    #[test]
    fn test_load_provider_cfg_temperature_falls_back_on_garbage() {
        let conn = mem_db();
        conn.execute(
            "UPDATE settings SET value='not-a-number' WHERE key='temperature'",
            [],
        )
        .unwrap();
        let cfg = load_provider_cfg(&conn);
        assert!((cfg.temperature - 0.2).abs() < f64::EPSILON);
    }

    #[test]
    fn test_analyze_paragraph_missing_is_chinese_error() {
        let conn = mem_db();
        let err = block_on(analyze_paragraph_conn(&conn, "nope")).unwrap_err();
        assert_eq!(err, "段落未找到");
    }

    #[test]
    fn test_analyze_paragraph_generates_and_caches() {
        let conn = seeded();
        let out = block_on(analyze_paragraph_conn(&conn, "doc_x_p1")).unwrap();
        assert_eq!(out["source"], "generated");
        assert_eq!(out["paragraph_id"], "doc_x_p1");
        let s0 = &out["sentences"][0];
        assert_eq!(s0["sentence_id"], "doc_x_p1_s1");
        assert_eq!(s0["has_deep_analysis"], true);
        assert_eq!(s0["translation"], "叫我以实玛利吧。");

        // Cached to sqlite, so the second call short-circuits.
        let cached: Option<String> = conn
            .query_row(
                "SELECT translation FROM sentences WHERE id='doc_x_p1_s1'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(cached.as_deref(), Some("叫我以实玛利吧。"));
    }

    #[test]
    fn test_analyze_paragraph_second_call_hits_cache() {
        let conn = seeded();
        block_on(analyze_paragraph_conn(&conn, "doc_x_p1")).unwrap();
        let out = block_on(analyze_paragraph_conn(&conn, "doc_x_p1")).unwrap();
        assert_eq!(out["source"], "cache");
        assert_eq!(out["sentences"][0]["has_deep_analysis"], true);
        assert!(out["sentences"][0]["deep_analysis"].is_object());
    }

    #[test]
    fn test_get_sentence_analysis_missing_is_chinese_error() {
        let conn = mem_db();
        let err = block_on(get_sentence_analysis_conn(&conn, "nope")).unwrap_err();
        assert_eq!(err, "句子未找到");
    }

    #[test]
    fn test_get_sentence_analysis_generates_then_caches() {
        let conn = seeded();
        let out = block_on(get_sentence_analysis_conn(&conn, "doc_x_p1_s1")).unwrap();
        assert_eq!(out["sentence_id"], "doc_x_p1_s1");
        assert_eq!(out["translation"], "叫我以实玛利吧。");

        let again = block_on(get_sentence_analysis_conn(&conn, "doc_x_p1_s1")).unwrap();
        assert_eq!(again["sentence_id"], "doc_x_p1_s1");
        assert_eq!(again["translation"], "叫我以实玛利吧。");
    }

    #[test]
    fn test_deep_analysis_json_is_aligned_to_the_db_sentence_id() {
        // Review Focus #5 again, at the write side: a hallucinated id from the
        // model must never be written under the caller's sentence id.
        let conn = seeded();
        block_on(analyze_paragraph_conn(&conn, "doc_x_p1")).unwrap();
        let stored: String = conn
            .query_row(
                "SELECT deep_analysis_json FROM sentences WHERE id='doc_x_p1_s1'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        let v: serde_json::Value = serde_json::from_str(&stored).unwrap();
        assert_eq!(v["sentence_id"], "doc_x_p1_s1");
    }

    #[test]
    fn test_an_empty_model_setting_resolves_to_that_providers_own_default() {
        // I2: clearing the model box to "accept the default" used to load
        // gpt-4o-mini for every provider, so a claude request 404'd and fell
        // back to the offline engine with no visible error.
        for (provider, want_model, want_host) in [
            ("claude", "claude-3-5-sonnet", "api.anthropic.com"),
            ("deepseek", "deepseek-chat", "api.deepseek.com"),
            (
                "gemini",
                "gemini-1.5-flash",
                "generativelanguage.googleapis.com",
            ),
            ("openai", "gpt-4o-mini", "api.openai.com"),
        ] {
            let conn = seeded();
            conn.execute(
                "UPDATE settings SET value=?1 WHERE key='provider'",
                [provider],
            )
            .unwrap();
            conn.execute("UPDATE settings SET value='' WHERE key='model_name'", [])
                .unwrap();

            let cfg = load_provider_cfg(&conn);
            assert_eq!(
                cfg.model_name, "",
                "{provider}: the setting must stay empty"
            );
            let (url, model, _) = crate::llm::resolve_endpoint(&cfg);
            assert_eq!(model, want_model, "{provider} default model");
            assert!(url.contains(want_host), "{provider} endpoint was {url}");
        }
    }

    #[test]
    fn test_an_explicit_model_setting_still_wins_over_the_default() {
        let conn = seeded();
        conn.execute(
            "UPDATE settings SET value='claude' WHERE key='provider'",
            [],
        )
        .unwrap();
        conn.execute(
            "UPDATE settings SET value='claude-3-7-sonnet' WHERE key='model_name'",
            [],
        )
        .unwrap();
        let cfg = load_provider_cfg(&conn);
        let (_, model, _) = crate::llm::resolve_endpoint(&cfg);
        assert_eq!(model, "claude-3-7-sonnet");
    }

    #[test]
    fn test_a_blank_cached_translation_is_not_treated_as_done() {
        // I1: a model that omits `translation` on one sentence used to cache an
        // empty string, and `t.is_some()` counted that as translated — from then
        // on the paragraph served `source: "cache"` forever with no translation
        // and no way to retry short of deleting the document.
        let conn = seeded();
        conn.execute(
            "UPDATE sentences SET translation = '', deep_analysis_json = NULL WHERE id='doc_x_p1_s1'",
            [],
        )
        .unwrap();
        let out = block_on(analyze_paragraph_conn(&conn, "doc_x_p1")).unwrap();
        assert_eq!(
            out["source"], "generated",
            "a blank translation must be regenerated, not served as cached"
        );
        assert_eq!(
            out["sentences"][0]["translation"], "叫我以实玛利吧。",
            "the regenerated translation should be a real one"
        );
    }

    #[test]
    fn test_a_whitespace_translation_is_not_treated_as_done() {
        let conn = seeded();
        conn.execute(
            "UPDATE sentences SET translation = '   ' WHERE id='doc_x_p1_s1'",
            [],
        )
        .unwrap();
        let out = block_on(analyze_paragraph_conn(&conn, "doc_x_p1")).unwrap();
        assert_eq!(out["source"], "generated");
    }

    #[test]
    fn test_a_real_translation_is_still_cached() {
        // The other half of the gate: a genuine translation must keep hitting the
        // cache, or every click would re-bill the user.
        let conn = seeded();
        block_on(analyze_paragraph_conn(&conn, "doc_x_p1")).unwrap();
        let again = block_on(analyze_paragraph_conn(&conn, "doc_x_p1")).unwrap();
        assert_eq!(again["source"], "cache");
    }

    #[test]
    fn test_cache_sentence_refuses_to_overwrite_a_good_translation_with_nothing() {
        // The write side of the same defect.
        let conn = seeded();
        cache_sentence(&conn, "doc_x_p1_s1", "叫我以实玛利吧。", "{}").unwrap();
        cache_sentence(&conn, "doc_x_p1_s1", "", "{}").unwrap();
        let stored: String = conn
            .query_row(
                "SELECT translation FROM sentences WHERE id='doc_x_p1_s1'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(stored, "叫我以实玛利吧。");
    }

    #[test]
    fn test_a_placeholder_translation_is_not_treated_as_done() {
        // The regression this file fixes: the offline demo engine's `【译文】`
        // echo used to count as a real translation, so a paragraph analysed
        // before a key was configured was served from cache forever and never
        // sent to the model — the right pane kept showing the original.
        let conn = seeded();
        conn.execute(
            "UPDATE sentences SET translation = ?1, deep_analysis_json = '{}'
              WHERE id = 'doc_x_p2_s1'",
            [format!(
                "{PLACEHOLDER_TRANSLATION_PREFIX}Some years ago, I went to sea."
            )],
        )
        .unwrap();

        let out = block_on(analyze_paragraph_conn(&conn, "doc_x_p2")).unwrap();
        assert_eq!(
            out["source"], "generated",
            "a placeholder row must be regenerated, not served as cached"
        );
        assert_eq!(out["engine"], "offline-demo");
        // Still a demo in mock mode — but the placeholder must not be
        // persisted again, so the paragraph stays retryable.
        let stored: Option<String> = conn
            .query_row(
                "SELECT translation FROM sentences WHERE id='doc_x_p2_s1'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert!(stored.is_none(), "a demo echo must never reach the cache");
    }

    #[test]
    fn test_cache_sentence_refuses_to_persist_a_placeholder() {
        // The write side of the same defect: persisting the demo echo is what
        // made the paragraph read as translated in the first place.
        let conn = seeded();
        cache_sentence(
            &conn,
            "doc_x_p1_s1",
            &format!("{PLACEHOLDER_TRANSLATION_PREFIX}Call me Ishmael."),
            "{}",
        )
        .unwrap();
        let stored: Option<String> = conn
            .query_row(
                "SELECT translation FROM sentences WHERE id='doc_x_p1_s1'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert!(stored.is_none(), "the placeholder must not be written");
    }

    #[test]
    fn test_cache_sentence_stores_translation_but_not_a_shallow_analysis() {
        // A translation-only object is the paragraph phase's legitimate
        // output; cached into `deep_analysis_json` it made the inspector show
        // nothing but the translation forever, and the batch's deepening
        // phase skip the sentence as "already analysed".
        let conn = seeded();
        let shallow = r#"{"sentence_id":"doc_x_p1_s1","original":"Call me Ishmael.","translation":"叫我以实玛利吧。","vocabulary_and_phrases":[],"idioms_and_conventions":[]}"#;
        cache_sentence(&conn, "doc_x_p1_s1", "叫我以实玛利吧。", shallow).unwrap();
        let (trans, deep): (Option<String>, Option<String>) = conn
            .query_row(
                "SELECT translation, deep_analysis_json FROM sentences WHERE id='doc_x_p1_s1'",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(trans.as_deref(), Some("叫我以实玛利吧。"));
        assert!(deep.is_none(), "a shallow payload must not squat as deep");
    }

    #[test]
    fn test_cache_sentence_never_clobbers_a_deep_analysis_with_a_shallow_one() {
        let conn = seeded();
        let deep_json = r#"{"sentence_id":"doc_x_p1_s1","translation":"甲","grammar_analysis":{"structure":"祈使句","components":[{"element":"Call","role":"谓语动词 (V)"}]}}"#;
        cache_sentence(&conn, "doc_x_p1_s1", "叫我以实玛利吧。", deep_json).unwrap();
        let shallow = r#"{"sentence_id":"doc_x_p1_s1","translation":"叫我以实玛利吧。","vocabulary_and_phrases":[]}"#;
        cache_sentence(&conn, "doc_x_p1_s1", "叫我以实玛利吧。", shallow).unwrap();
        let deep: String = conn
            .query_row(
                "SELECT deep_analysis_json FROM sentences WHERE id='doc_x_p1_s1'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert!(deep.contains("祈使句"), "the deep analysis must survive");
    }

    #[test]
    fn test_get_sentence_analysis_deepens_a_shallow_cached_entry() {
        // The cache invariant is "deep_analysis_json set ⇒ real deep analysis";
        // a shallow entry written by an older build must not be served from
        // cache but deepened — here by the mock engine, whose output carries
        // grammar slices.
        let conn = seeded();
        conn.execute(
            "UPDATE sentences SET translation = ?1, deep_analysis_json = ?2
              WHERE id = 'doc_x_p1_s1'",
            rusqlite::params![
                "叫我以实玛利吧。",
                r#"{"sentence_id":"doc_x_p1_s1","translation":"叫我以实玛利吧。","vocabulary_and_phrases":[]}"#
            ],
        )
        .unwrap();

        let out = block_on(get_sentence_analysis_conn(&conn, "doc_x_p1_s1")).unwrap();
        assert!(
            out["grammar_analysis"].is_object(),
            "must be deepened, not served shallow"
        );
        let deep: String = conn
            .query_row(
                "SELECT deep_analysis_json FROM sentences WHERE id='doc_x_p1_s1'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        let v: serde_json::Value = serde_json::from_str(&deep).unwrap();
        assert!(is_deep_analysis(&v), "the deepened analysis is cached");
    }
}
