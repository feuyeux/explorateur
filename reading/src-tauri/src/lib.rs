pub mod commands;
pub mod batch;
pub mod db;
pub mod export;
pub mod glossary;
pub mod llm;
pub mod markdown;
pub mod prompts;
pub mod splitter;
pub mod vocab;

/// Runs a blocking job on the blocking pool and awaits its result.
///
/// Tauri executes an `async fn` command body as a *task on the tokio runtime*.
/// Calling `tauri::async_runtime::block_on` from inside one therefore panics
/// ("Cannot start a runtime from within a runtime"), the task dies before it can
/// resolve the invoke promise, and the UI waits forever on a button that never
/// comes back. Handing the job to `spawn_blocking` puts it on a blocking-pool
/// thread, where `block_on` — and the synchronous SQLite work — are legal, and
/// the runtime stays free to serve the rest of the UI.
pub async fn run_blocking<T, F>(job: F) -> Result<T, String>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, String> + Send + 'static,
{
    tauri::async_runtime::spawn_blocking(job)
        .await
        .map_err(|e| format!("后台任务失败：{e}"))?
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            db::init_db(app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::documents::list_documents,
            commands::documents::get_document,
            commands::documents::upload_document,
            commands::documents::load_sample,
            commands::documents::delete_document,
            commands::documents::export_markdown_to,
            commands::analysis::analyze_paragraph,
            commands::analysis::get_sentence_analysis,
            commands::analysis::start_batch_analysis,
            commands::analysis::batch_progress,
            commands::analysis::cancel_batch_analysis,
            commands::vocabulary::get_vocabulary,
            commands::vocabulary::add_vocabulary,
            commands::vocabulary::delete_vocabulary,
            commands::vocabulary::export_anki_to,
            commands::settings::get_settings,
            commands::settings::update_settings,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
