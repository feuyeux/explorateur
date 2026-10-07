// Guards the shape of Tauri command dispatch.
//
// Tauri runs an `async fn` command body as a *task on the tokio runtime*.
// Calling `tauri::async_runtime::block_on` from inside one therefore panics
// with "Cannot start a runtime from within a runtime", the task dies before it
// resolves the invoke promise, and the UI waits forever on a button that never
// comes back. Every unit test calls the `*_conn` functions directly from a
// plain test thread, where `block_on` is legal — which is exactly why this
// class of bug survived 64 green tests.
//
// These tests drive the real inner job through Tauri's real dispatch shape.
use ready_reader_lib::commands::documents::{ingest_text, SAMPLE_MOBY_DICK};
use ready_reader_lib::llm::analyze_paragraph_structured;
use ready_reader_lib::run_blocking;
use rusqlite::Connection;

/// Builds a throwaway database holding the sample book and returns the id of
/// the paragraph carrying the opening line.
fn seeded_doc() -> (std::path::PathBuf, Connection, String) {
    let dir = std::env::temp_dir().join(format!("rr_dispatch_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let file = dir.join("dispatch.db");
    let conn = Connection::open(&file).unwrap();
    conn.execute_batch(include_str!("../src/schema_minimal.sql"))
        .unwrap();
    ingest_text(
        &conn,
        "doc_dispatch",
        "白鲸记",
        "Herman Melville",
        "md",
        SAMPLE_MOBY_DICK,
    )
    .unwrap();
    let para_id: String = conn
        .query_row(
            "SELECT id FROM paragraphs WHERE raw_text LIKE '%Call me Ishmael.%' LIMIT 1",
            [],
            |r| r.get(0),
        )
        .unwrap();
    (dir, conn, para_id)
}

#[test]
fn block_on_inside_a_spawned_task_panics_which_is_why_commands_use_run_blocking() {
    // This test is the RED demonstration for the C1 fix, kept as a standing
    // record of the trap: `analyze_paragraph` and `get_sentence_analysis` used
    // to call `block_on` from inside a spawned task, and this is what that did.
    let dir = std::env::temp_dir().join(format!("rr_dispatch_red_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let red_db = dir.join("red.db");

    let task = tauri::async_runtime::spawn(async move {
        tauri::async_runtime::block_on(async {
            let conn = Connection::open(&red_db).unwrap();
            conn.execute_batch(include_str!("../src/schema_minimal.sql"))
                .unwrap();
            ingest_text(
                &conn,
                "doc_red",
                "白鲸记",
                "Herman Melville",
                "md",
                SAMPLE_MOBY_DICK,
            )
            .unwrap();
            let para_id: String = conn
                .query_row(
                    "SELECT id FROM paragraphs WHERE raw_text LIKE '%Call me Ishmael.%' LIMIT 1",
                    [],
                    |r| r.get(0),
                )
                .unwrap();
            let cfg = ready_reader_lib::commands::analysis::load_provider_cfg(&conn);
            let meta = vec![("p_s1".to_string(), "Call me Ishmael.".to_string())];
            let out = tauri::async_runtime::block_on(analyze_paragraph_structured(
                &cfg,
                &para_id,
                "Call me Ishmael.",
                &meta,
                "",
            ));
            out.len()
        })
    });

    let joined = tauri::async_runtime::block_on(task);
    let err = joined.expect_err("block_on inside a runtime task is expected to panic");
    let msg = err.to_string();
    assert!(
        msg.contains("Cannot start a runtime from within a runtime"),
        "unexpected failure mode: {msg}"
    );
    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn run_blocking_carries_a_real_analysis_through_that_same_dispatch_shape() {
    let (dir, _conn, para_id) = seeded_doc();
    let file = dir.join("dispatch.db");

    let task = tauri::async_runtime::spawn(async move {
        run_blocking(move || -> Result<usize, String> {
            let conn = Connection::open(&file).map_err(|e| e.to_string())?;
            let cfg = ready_reader_lib::commands::analysis::load_provider_cfg(&conn);
            let meta = vec![("p_s1".to_string(), "Call me Ishmael.".to_string())];
            let out = tauri::async_runtime::block_on(analyze_paragraph_structured(
                &cfg,
                &para_id,
                "Call me Ishmael.",
                &meta,
                "",
            ));
            Ok(out.len())
        })
        .await
    });

    let joined = tauri::async_runtime::block_on(task);
    let n = joined
        .expect("the blocking job must not panic when run off the runtime")
        .expect("the job itself");
    assert_eq!(
        n, 1,
        "mock mode should still return the one analysed sentence"
    );

    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn run_blocking_surfaces_a_job_error_instead_of_panicking() {
    let task = tauri::async_runtime::spawn(async {
        run_blocking(|| -> Result<(), String> { Err("生词与释义不能为空".to_string()) }).await
    });
    let joined = tauri::async_runtime::block_on(task);
    assert_eq!(joined.unwrap().unwrap_err(), "生词与释义不能为空");
}

/// The structural invariant behind the tests above: no `async fn` command body
/// may call `block_on` directly. It cannot be reached from a test without
/// booting a real Wry app, so it is asserted on the source instead.
#[test]
fn no_async_command_body_calls_block_on_directly() {
    let src_dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut offenders: Vec<String> = Vec::new();

    fn walk(dir: &std::path::Path, offenders: &mut Vec<String>) {
        for entry in std::fs::read_dir(dir).expect("src dir readable") {
            let path = entry.expect("dir entry").path();
            if path.is_dir() {
                walk(&path, offenders);
                continue;
            }
            if path.extension().and_then(|e| e.to_str()) != Some("rs") {
                continue;
            }
            let src = std::fs::read_to_string(&path).expect("rs file is utf-8");
            let lines: Vec<&str> = src.lines().collect();
            for (i, line) in lines.iter().enumerate() {
                let is_command = line.trim() == "#[tauri::command]";
                if !is_command {
                    continue;
                }
                let sig = lines.get(i + 1).copied().unwrap_or_default();
                if !sig.trim_start().starts_with("pub async fn") {
                    continue; // a sync command's block_on runs on the IPC thread: legal
                }
                // The signature can wrap over several lines before its opening
                // brace, so collect lines until one contains it, then
                // brace-match to the end of the function.
                let mut depth = 0usize;
                let mut body = String::new();
                let mut started = false;
                let mut cursor = i + 1;
                while let Some(l) = lines.get(cursor) {
                    let piece = if !started {
                        match l.find('{') {
                            Some(at) => {
                                started = true;
                                &l[at..]
                            }
                            None => {
                                body.push_str(l);
                                body.push('\n');
                                cursor += 1;
                                continue;
                            }
                        }
                    } else {
                        l
                    };
                    body.push_str(piece);
                    body.push('\n');
                    for ch in piece.chars() {
                        if ch == '{' {
                            depth += 1;
                        } else if ch == '}' {
                            depth -= 1;
                        }
                    }
                    if depth == 0 {
                        break;
                    }
                    cursor += 1;
                }
                if !started {
                    continue;
                }
                // A `block_on` is safe exactly when it sits inside the closure
                // handed to `run_blocking`: that closure runs on a blocking-pool
                // thread. Track paren nesting so a bare `block_on` in the
                // command's own body is still caught.
                if let Some(at) = unsafe_block_on(&body) {
                    offenders.push(format!(
                        "{}:{} {} (offset {at})",
                        path.display(),
                        i + 2,
                        sig.trim()
                    ));
                }
            }
        }
    }

    walk(&src_dir, &mut offenders);
    assert!(
        offenders.is_empty(),
        "an async tauri command calls block_on directly, which panics under Tauri's \
         dispatch: {offenders:?}"
    );
}

/// Returns the byte offset of the first `async_runtime::block_on` in `body`
/// that is NOT inside the closure passed to `run_blocking`.
fn unsafe_block_on(body: &str) -> Option<usize> {
    // Stack of open parentheses: `true` when the paren belongs to `run_blocking(`.
    let mut open: Vec<bool> = Vec::new();
    let bytes: Vec<char> = body.chars().collect();
    let mut i = 0usize;
    while i < bytes.len() {
        let rest: String = bytes[i..].iter().collect();
        if rest.starts_with("run_blocking(") {
            open.push(true);
            i += "run_blocking(".len();
            continue;
        }
        if rest.starts_with("async_runtime::block_on") {
            if !open.iter().any(|&is_run| is_run) {
                return Some(bytes[..i].iter().map(|c| c.len_utf8()).sum());
            }
            i += "async_runtime::block_on".len();
            continue;
        }
        match bytes[i] {
            '(' => open.push(false),
            ')' => {
                open.pop();
            }
            _ => {}
        }
        i += 1;
    }
    None
}
