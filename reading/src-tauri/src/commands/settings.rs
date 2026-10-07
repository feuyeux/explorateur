// Settings commands, ported from backend/app/routers/settings.py and
// database.get_all_settings.
use crate::db;
use rusqlite::Connection;
use std::collections::HashMap;

/// Read-back helper for the tests below; production code goes through
/// `all_settings`, which coerces every value in one pass.
#[cfg(test)]
fn get_setting(conn: &Connection, key: &str) -> Option<String> {
    conn.query_row("SELECT value FROM settings WHERE key = ?1", [key], |r| {
        r.get::<_, String>(0)
    })
    .ok()
}

fn set_setting(conn: &Connection, key: &str, value: &str) -> Result<(), String> {
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?1, ?2)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        rusqlite::params![key, value],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

/// Settings are stored as text; the frontend expects booleans and numbers.
fn coerce(value: &str) -> serde_json::Value {
    if value.eq_ignore_ascii_case("true") {
        return serde_json::Value::Bool(true);
    }
    if value.eq_ignore_ascii_case("false") {
        return serde_json::Value::Bool(false);
    }
    if value.contains('.') {
        if let Ok(f) = value.parse::<f64>() {
            return serde_json::json!(f);
        }
    } else if let Ok(i) = value.parse::<i64>() {
        return serde_json::json!(i);
    }
    serde_json::Value::String(value.to_string())
}

pub fn all_settings(conn: &Connection) -> Result<serde_json::Value, String> {
    let mut stmt = conn
        .prepare("SELECT key, value FROM settings")
        .map_err(|e| e.to_string())?;
    let rows: Vec<(String, String)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .map_err(|e| e.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    let map: HashMap<String, serde_json::Value> =
        rows.into_iter().map(|(k, v)| (k, coerce(&v))).collect();
    serde_json::to_value(map).map_err(|e| e.to_string())
}

pub fn write_settings(
    conn: &Connection,
    provider: &str,
    api_key: Option<&str>,
    base_url: Option<&str>,
    model_name: Option<&str>,
    temperature: f64,
    mock_mode: bool,
) -> Result<serde_json::Value, String> {
    set_setting(conn, "provider", provider)?;
    if let Some(v) = api_key {
        set_setting(conn, "api_key", v)?;
    }
    if let Some(v) = base_url {
        set_setting(conn, "base_url", v)?;
    }
    if let Some(v) = model_name {
        set_setting(conn, "model_name", v)?;
    }
    set_setting(conn, "temperature", &temperature.to_string())?;
    set_setting(conn, "mock_mode", if mock_mode { "true" } else { "false" })?;
    Ok(serde_json::json!({
        "status": "success",
        "settings": all_settings(conn)?,
    }))
}

#[tauri::command]
pub fn get_settings(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    db::with_conn(&app, all_settings)
}

#[tauri::command]
pub fn update_settings(
    app: tauri::AppHandle,
    provider: String,
    api_key: Option<String>,
    base_url: Option<String>,
    model_name: Option<String>,
    temperature: f64,
    mock_mode: bool,
) -> Result<serde_json::Value, String> {
    db::with_conn(&app, |conn| {
        write_settings(
            conn,
            &provider,
            api_key.as_deref(),
            base_url.as_deref(),
            model_name.as_deref(),
            temperature,
            mock_mode,
        )
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

    #[test]
    fn test_coerce_types() {
        assert_eq!(coerce("true"), serde_json::json!(true));
        assert_eq!(coerce("TRUE"), serde_json::json!(true));
        assert_eq!(coerce("false"), serde_json::json!(false));
        assert_eq!(coerce("0.2"), serde_json::json!(0.2));
        assert_eq!(coerce("42"), serde_json::json!(42));
        assert_eq!(coerce("gpt-4o-mini"), serde_json::json!("gpt-4o-mini"));
    }

    #[test]
    fn test_get_settings_returns_typed_defaults() {
        let conn = mem_db();
        let s = all_settings(&conn).unwrap();
        assert_eq!(s["provider"], "mock");
        assert_eq!(s["mock_mode"], true);
        assert_eq!(s["temperature"], 0.2);
        assert_eq!(s["api_key"], "");
    }

    #[test]
    fn test_update_settings_writes_and_returns_new_state() {
        let conn = mem_db();
        let out = write_settings(
            &conn,
            "deepseek",
            Some("sk-1"),
            Some("https://x/v1"),
            Some("deepseek-chat"),
            0.7,
            false,
        )
        .unwrap();
        assert_eq!(out["status"], "success");
        assert_eq!(out["settings"]["provider"], "deepseek");
        assert_eq!(out["settings"]["mock_mode"], false);
        assert_eq!(out["settings"]["temperature"], 0.7);
        let stored = get_setting(&conn, "api_key").unwrap();
        assert_eq!(stored, "sk-1");
    }

    #[test]
    fn test_update_settings_leaves_omitted_optionals_alone() {
        let conn = mem_db();
        set_setting(&conn, "api_key", "keep-me").unwrap();
        write_settings(&conn, "openai", None, None, None, 0.3, true).unwrap();
        assert_eq!(get_setting(&conn, "api_key").unwrap(), "keep-me");
    }

    #[test]
    fn test_update_settings_overwrites_previous_key() {
        let conn = mem_db();
        write_settings(&conn, "openai", Some("a"), None, None, 0.2, true).unwrap();
        write_settings(&conn, "deepseek", Some("b"), None, None, 0.2, true).unwrap();
        let s = all_settings(&conn).unwrap();
        assert_eq!(s["provider"], "deepseek");
        assert_eq!(s["api_key"], "b");
    }
}
