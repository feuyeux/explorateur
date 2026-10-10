// Contract tests between the vanilla-JS frontend and the Rust/ACL side.
//
// These guard two things a unit test inside a Rust module cannot see: that the
// frontend does not reach for a plugin API the ACL would deny, and that the
// capability file actually grants what the frontend does call.
use std::path::{Path, PathBuf};

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn frontend_js_dir() -> PathBuf {
    manifest_dir().join("../src")
}

fn read_js_files() -> Vec<(String, String)> {
    let mut out = Vec::new();
    for entry in std::fs::read_dir(frontend_js_dir()).expect("src exists") {
        let path = entry.expect("dir entry").path();
        if path.extension().and_then(|e| e.to_str()) != Some("js") {
            continue;
        }
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        let body = std::fs::read_to_string(&path).expect("js file is utf-8");
        out.push((name, body));
    }
    assert!(!out.is_empty(), "no frontend js files found");
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
}

#[test]
fn frontend_never_calls_the_fs_plugin_directly() {
    // The fs plugin's write scope cannot cover an arbitrary path chosen in a
    // save dialog, and `fs:default` would not grant it anyway. Every file write
    // therefore goes through a Rust command instead, which needs no ACL grant.
    for (name, body) in read_js_files() {
        assert!(
            !body.contains("__TAURI__.fs"),
            "{name} calls the fs plugin directly; writes must go through a Rust command"
        );
    }
}

#[test]
fn capabilities_grant_exactly_what_the_frontend_calls() {
    let caps_dir = manifest_dir().join("capabilities");
    assert!(
        caps_dir.is_dir(),
        "capabilities/ is missing: every Tauri 2 app needs at least one capability, \
         otherwise plugin commands are ACL-denied at runtime"
    );

    let mut granted: Vec<String> = Vec::new();
    let mut names: Vec<String> = Vec::new();
    for entry in std::fs::read_dir(&caps_dir).expect("capabilities dir readable") {
        let path = entry.expect("dir entry").path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        names.push(path.file_name().unwrap().to_string_lossy().to_string());
        let body = std::fs::read_to_string(&path).expect("capability json is utf-8");
        let v: serde_json::Value = serde_json::from_str(&body).expect("capability json parses");
        for p in v["permissions"].as_array().expect("permissions array") {
            granted.push(p.as_str().expect("permission is a string").to_string());
        }
    }
    assert!(!names.is_empty(), "no capability json files");

    // The frontend opens the save dialog and nothing else.
    assert!(
        granted.iter().any(|p| p == "dialog:default"),
        "capabilities must grant dialog:default, the save dialog is how the user \
         chooses the Anki export path; got {granted:?}"
    );
    assert!(
        granted.iter().any(|p| p == "core:default"),
        "capabilities must grant core:default for the invoke bridge; got {granted:?}"
    );
}

#[test]
fn every_invoke_target_is_a_registered_command() {
    // Catches a JS-side command name that has no Rust counterpart, which fails
    // only at runtime and only on that code path.
    let api = std::fs::read_to_string(frontend_js_dir().join("api.js")).expect("api.js exists");
    let lib_rs = std::fs::read_to_string(manifest_dir().join("src/lib.rs")).expect("lib.rs exists");

    let mut missing: Vec<String> = Vec::new();
    for cap in call_target_literals(&api) {
        // Entries in generate_handler! are either bare (`health,`) or fully
        // qualified (`commands::documents::list_documents,`).
        let registered =
            lib_rs.contains(&format!("::{cap},")) || lib_rs.contains(&format!(" {cap},"));
        if !registered {
            missing.push(cap);
        }
    }
    assert!(
        missing.is_empty(),
        "api.js invokes unregistered commands: {missing:?}"
    );
}

/// Pulls the snake_case command name out of each `call('name', ...)` / bare
/// `invoke('name', ...)` argument in api.js.
fn call_target_literals(api: &str) -> Vec<String> {
    let needles = ["call('", "invoke('"];
    let mut out = Vec::new();
    for needle in needles {
        let mut rest = api;
        while let Some(idx) = rest.find(needle) {
            rest = &rest[idx + needle.len()..];
            if let Some(end) = rest.find('\'') {
                out.push(rest[..end].to_string());
                rest = &rest[end + 1..];
            } else {
                break;
            }
        }
    }
    out.sort();
    out.dedup();
    out
}

#[test]
fn upload_sends_the_file_extension_so_the_backend_can_enforce_it() {
    // The file picker filter and `accept=` are cosmetic: a drag-and-drop bypasses
    // both. Only the backend, which never sees the filename today, can reject.
    let api = std::fs::read_to_string(frontend_js_dir().join("api.js")).expect("api.js exists");
    assert!(
        api.contains("fileExt"),
        "api.js must forward the file extension to upload_document"
    );
}

#[test]
fn toasts_are_built_from_text_nodes_not_inner_html() {
    // A toast message is assembled from a vocabulary token (straight from the
    // model's JSON), the uploaded file name, and backend error strings. Every
    // other renderer in the app escapes its input; showToast interpolated the
    // message into innerHTML, so a token containing markup ran in the webview.
    let app = std::fs::read_to_string(frontend_js_dir().join("main.js")).expect("main.js exists");
    let body = app
        .split("showToast(message, type = 'info') {")
        .nth(1)
        .expect("showToast is defined in main.js")
        .split("\n  }")
        .next()
        .expect("showToast body has an end");
    assert!(
        !body.contains("innerHTML"),
        "showToast must create nodes and set textContent instead:\n{body}"
    );
}

#[test]
fn the_inspector_is_never_handed_a_raw_sentence_id() {
    // `selectSentence` used to re-trigger the inspector with the *id* when the
    // clicked sentence was already active (a second click, or the re-select
    // after its paragraph was re-analysed). The inspector read `.sentence_id`
    // off the string, got `undefined`, and invoke dropped the key: every such
    // click died with "command get_sentence_analysis missing required key
    // sentenceId".
    let reader = std::fs::read_to_string(frontend_js_dir().join("dual_reader.js"))
        .expect("dual_reader.js exists");
    assert!(
        !reader.contains("this.onSentenceSelected(sentenceId)"),
        "selectSentence must resolve the id to a sentence object before \
         re-triggering the inspector:\n{reader}"
    );
    assert!(
        reader.contains("this.findSentence(sentenceId)"),
        "selectSentence should resolve ids through the loaded sentence objects"
    );
}

#[test]
fn tts_ranking_sorts_but_never_filters() {
    // voiceRank is a ranking, never a filter: a language whose only installed
    // voice is a penalised one (macOS novelty, Eloquence robot, super-compact)
    // must still speak. A `.filter(` inside the rank would silently mute those
    // languages, and no amount of unit tests in the app would catch it.
    let tts = std::fs::read_to_string(frontend_js_dir().join("tts.js")).expect("tts.js exists");
    let rank = tts
        .split("export function voiceRank(v) {")
        .nth(1)
        .expect("voiceRank is defined in tts.js")
        .split("\n}")
        .next()
        .expect("voiceRank body has an end");
    assert!(
        !rank.contains(".filter("),
        "voiceRank must sort, never filter — a penalised voice is still a \
         speakable voice:\n{rank}"
    );
}

#[test]
fn tts_keeps_its_chromium_defenses() {
    // Three runtime invariants ported from the kb corpus pipeline, kept as
    // source-level asserts because the webview has no JS test harness:
    // 1. cancel() wedges Chromium's queue unless a settle tick precedes speak()
    // 2. long utterances get silently paused without a heartbeat
    // 3. engines reuse the previous utterance's rate/pitch unless pinned
    let tts = std::fs::read_to_string(frontend_js_dir().join("tts.js")).expect("tts.js exists");
    assert!(
        tts.contains("const CANCEL_SETTLE_MS = 60;"),
        "tts.js lost CANCEL_SETTLE_MS: a speak() issued in the same tick as a \
         cancel() is silently swallowed on Chromium"
    );
    assert!(
        tts.contains("const KEEPALIVE_MS = 10000;"),
        "tts.js lost KEEPALIVE_MS: Chromium pauses long utterances on its own"
    );
    assert!(
        tts.contains("u.rate = 1.0;") && tts.contains("u.pitch = 1.0;"),
        "every utterance must pin rate/pitch, or engines replay the previous \
         utterance's parameters"
    );
}

#[test]
fn window_label_in_config_is_covered_by_the_capability() {
    let conf: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(manifest_dir().join("tauri.conf.json")).expect("tauri.conf.json"),
    )
    .expect("tauri.conf.json parses");
    let window = &conf["app"]["windows"][0];
    let label = window["label"].as_str().unwrap_or("main");

    let caps_dir = manifest_dir().join("capabilities");
    let mut covered = false;
    for entry in std::fs::read_dir(&caps_dir).expect("capabilities dir readable") {
        let path = entry.expect("dir entry").path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        let v: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
        if let Some(windows) = v["windows"].as_array() {
            covered |= windows.iter().any(|w| w.as_str() == Some(label));
        }
    }
    assert!(
        covered,
        "no capability targets the window labelled {label:?}; the app window would be ACL-denied"
    );
    let _: &Path = caps_dir.as_path();
}
