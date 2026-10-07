// Vocabulary notebook storage and Anki TSV export, ported from
// backend/app/services/vocab_service.py.
use chrono::Local;
use regex::Regex;
use rusqlite::Connection;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct VocabRecord {
    pub id: i64,
    pub word: String,
    pub pos: String,
    pub translation: String,
    pub sentence_context: String,
    pub sentence_id: String,
    pub cultural_background: String,
    pub created_at: String,
}

pub fn add_vocabulary_item(
    conn: &Connection,
    word: &str,
    pos: &str,
    translation: &str,
    sentence_context: &str,
    sentence_id: &str,
    cultural_background: &str,
) -> Result<i64, String> {
    conn.execute(
        "INSERT INTO vocabulary_book
           (word, pos, translation, sentence_context, sentence_id, cultural_background, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        rusqlite::params![
            word.trim(),
            pos,
            translation.trim(),
            sentence_context,
            sentence_id,
            cultural_background,
            Local::now().format("%Y-%m-%d %H:%M:%S").to_string(),
        ],
    )
    .map_err(|e| e.to_string())?;
    Ok(conn.last_insert_rowid())
}

pub fn list_vocabulary_items(conn: &Connection) -> Result<Vec<VocabRecord>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT id, word, COALESCE(pos, ''), translation,
                    COALESCE(sentence_context, ''), COALESCE(sentence_id, ''),
                    COALESCE(cultural_background, ''), created_at
             FROM vocabulary_book ORDER BY id DESC",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |r| {
            Ok(VocabRecord {
                id: r.get(0)?,
                word: r.get(1)?,
                pos: r.get(2)?,
                translation: r.get(3)?,
                sentence_context: r.get(4)?,
                sentence_id: r.get(5)?,
                cultural_background: r.get(6)?,
                created_at: r.get(7)?,
            })
        })
        .map_err(|e| e.to_string())?;
    rows.map(|r| r.map_err(|e| e.to_string())).collect()
}

pub fn delete_vocabulary_item(conn: &Connection, vocab_id: i64) -> Result<(), String> {
    conn.execute("DELETE FROM vocabulary_book WHERE id = ?1", [vocab_id])
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Anki's TSV importer has no escape syntax: it splits a line on tabs and a file
/// on newlines, and a `"` is an ordinary character it copies through. So RFC4180
/// quoting cannot protect a field here — a quoted field containing a tab or a
/// newline still arrives as a broken row. The only portable guarantee is that no
/// field carries a tab or a newline, so every run of whitespace collapses to a
/// single space. HTML renders a run of spaces the same way, so the card looks
/// unchanged.
fn plain_field(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut pending_space = false;
    for c in s.chars() {
        if c.is_whitespace() {
            // Leading whitespace is dropped rather than turned into a space.
            pending_space = !out.is_empty();
        } else {
            if pending_space {
                out.push(' ');
                pending_space = false;
            }
            out.push(c);
        }
    }
    out
}

/// The card fields are HTML and the deck is imported with "allow HTML" on, so
/// text coming from the notebook has to be escaped before it is embedded. The
/// in-app notebook table escapes the same values for the same reason.
fn html_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#39;"),
            _ => out.push(c),
        }
    }
    out
}

fn highlight(word: &str, ctx: &str) -> String {
    if ctx.is_empty() || !ctx.to_lowercase().contains(&word.to_lowercase()) {
        return ctx.to_string();
    }
    let re = Regex::new(&format!("(?i){}", regex::escape(word))).unwrap();
    re.replace_all(
        ctx,
        format!("<b style='color:#3b82f6;'>{word}</b>").as_str(),
    )
    .to_string()
}

pub fn export_vocabulary_anki_tsv(conn: &Connection) -> Result<String, String> {
    let items = list_vocabulary_items(conn)?;
    let mut out = String::from("#separator:tab\n#html:true\n#tags column:5\n");
    for item in items {
        // Two views of the same value: the plain text goes into the plain-text
        // columns Anki's list shows, the escaped text into the HTML card face.
        // Both are whitespace-collapsed first so neither can carry a delimiter.
        let word = plain_field(&item.word);
        let word_html = html_escape(&word);
        let meaning = plain_field(&item.translation);
        let meaning_html = html_escape(&meaning);
        let ctx = plain_field(&item.sentence_context);
        let ctx_html = html_escape(&ctx);
        let pos_html = html_escape(&plain_field(&item.pos));
        let notes_html = html_escape(&plain_field(&item.cultural_background));

        // Highlight the escaped context against the escaped word, so a word
        // containing `&` or `<` is still matched and still renders correctly.
        let ctx_highlighted = highlight(&word_html, &ctx_html);

        let mut front =
            format!("<div style='font-size: 20px; font-weight: bold;'>{word_html}</div>");
        if !ctx_highlighted.is_empty() {
            front.push_str(&format!(
                "<div style='margin-top: 8px; color: #6b7280; font-style: italic;'>“{ctx_highlighted}”</div>"
            ));
        }

        let mut back = format!("<div style='font-size: 16px;'><span style='background:#e0e7ff; color:#3730a3; padding: 2px 6px; border-radius: 4px; font-size: 12px; margin-right: 6px;'>{pos_html}</span>{meaning_html}</div>");
        if !notes_html.is_empty() {
            back.push_str(&format!(
                "<div style='margin-top: 10px; font-size: 13px; color: #4b5563; border-left: 3px solid #6366f1; padding-left: 8px;'>{notes_html}</div>"
            ));
        }

        let tags = "ReadyReader ForeignLiterature";
        let cols = [front, back, word.clone(), meaning, tags.to_string()];
        // Belt and braces: whatever the card faces above are built from, a column
        // can never reach the file carrying a delimiter.
        let row: Vec<String> = cols.iter().map(|c| plain_field(c)).collect();
        out.push_str(&row.join("\t"));
        out.push('\n');
    }
    Ok(out)
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
    fn test_add_list_delete_roundtrip() {
        let conn = mem_db();
        let id = add_vocabulary_item(
            &conn,
            "Ishmael",
            "专有名词",
            "以实玛利（人名）",
            "Call me Ishmael.",
            "p1_s1",
            "《圣经》亚伯拉罕之子",
        )
        .unwrap();
        let items = list_vocabulary_items(&conn).unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].word, "Ishmael");
        assert_eq!(items[0].pos, "专有名词");
        assert!(!items[0].created_at.is_empty());
        delete_vocabulary_item(&conn, id).unwrap();
        assert!(list_vocabulary_items(&conn).unwrap().is_empty());
    }

    #[test]
    fn test_anki_tsv_structure_and_highlight() {
        let conn = mem_db();
        add_vocabulary_item(
            &conn,
            "Ishmael",
            "专有名词",
            "以实玛利（人名）",
            "Call me Ishmael.",
            "p1_s1",
            "《圣经》亚伯拉罕之子",
        )
        .unwrap();
        let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
        assert!(tsv.starts_with("#separator:tab\n#html:true\n#tags column:5\n"));
        let lines: Vec<&str> = tsv.lines().collect();
        assert_eq!(lines.len(), 4); // 3 header + 1 row
        let cols: Vec<&str> = lines[3].split('\t').collect();
        assert_eq!(cols.len(), 5);
        assert!(cols[0].contains("Ishmael"));
        assert!(cols[0].contains("<b style='color:#3b82f6;'>Ishmael</b>"));
        assert!(cols[1].contains("以实玛利"));
        assert_eq!(cols[3], "以实玛利（人名）");
        assert_eq!(cols[4], "ReadyReader ForeignLiterature");
    }

    #[test]
    fn test_anki_tsv_keeps_every_row_at_five_columns_for_anki() {
        // Anki's TSV importer has no quote handling at all: it splits a line on
        // tabs and a file on newlines, and takes everything between literally.
        // So RFC4180 quoting does not protect a field here — it only hides the
        // problem from a test written against a quote-aware parser. A meaning
        // containing a tab or newline used to arrive at Anki as a second row, or
        // as a row whose columns (including the `#tags column:5` one) had shifted.
        let conn = mem_db();
        add_vocabulary_item(
            &conn,
            "Ishmael",
            "人名",
            "以实玛利\n《白鲸记》叙述者，\t全书统一译名",
            "Call me Ishmael.\nSome years ago—never mind.",
            "",
            "",
        )
        .unwrap();
        let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
        let rows = parse_tsv_as_anki_does(&tsv);
        let data: Vec<&Vec<String>> = rows.iter().skip(3).collect();
        assert_eq!(
            data.len(),
            1,
            "a newline in a field must not become a second card: {tsv:?}"
        );
        let cols = data[0];
        assert_eq!(cols.len(), 5, "every card must have all five columns");
        assert_eq!(cols[2], "Ishmael");
        assert_eq!(
            cols[3], "以实玛利 《白鲸记》叙述者， 全书统一译名",
            "tabs and newlines must collapse to a space, not vanish or shift columns"
        );
        assert_eq!(
            cols[4], "ReadyReader ForeignLiterature",
            "tags column must survive"
        );
    }

    #[test]
    fn test_anki_tsv_quotes_are_not_doubled_as_rfc4180_escaping() {
        // A quote carries no meaning to Anki's importer, so it must not be
        // doubled the way RFC4180 would. It does get HTML-encoded, because the
        // card face is HTML rendered with "allow HTML" on.
        let conn = mem_db();
        add_vocabulary_item(
            &conn,
            "ahab",
            "名",
            "亚哈",
            "The mate said \"Starbuck\" twice.",
            "",
            "",
        )
        .unwrap();
        let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
        let rows = parse_tsv_as_anki_does(&tsv);
        let cols = &rows[3];
        assert_eq!(cols.len(), 5);
        assert_eq!(cols[3], "亚哈");
        assert!(cols[0].contains("&quot;Starbuck&quot;"), "got {cols:?}");
        assert!(
            !cols[0].contains("\"\""),
            "quotes must not be RFC4180-doubled"
        );
    }

    #[test]
    fn test_anki_card_faces_escape_text_but_plain_columns_do_not() {
        // The notebook stores whatever the model or the user typed, and the deck
        // is imported with "allow HTML" switched on, so a meaning containing
        // `&` or a tag used to render as broken markup (or inject a tag) inside
        // the card. The HTML faces escape; the plain Anki columns keep the real
        // characters so the field list in Anki still reads correctly.
        let conn = mem_db();
        add_vocabulary_item(
            &conn,
            "AT&T",
            "名",
            "AT&T 是<b>公司</b>名",
            "The AT&T line & the <b>other</b> one.",
            "",
            "AT&T 全称 <i>American Telephone & Telegraph</i>",
        )
        .unwrap();
        let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
        let rows = parse_tsv_as_anki_does(&tsv);
        let cols = &rows[3];
        assert_eq!(cols.len(), 5);
        assert_eq!(cols[2], "AT&T", "plain word column stays literal");
        assert_eq!(
            cols[3], "AT&T 是<b>公司</b>名",
            "plain meaning column stays literal"
        );
        // Front face: the word plus the sentence context.
        assert!(
            !cols[0].contains("<b>other</b>"),
            "the context must not inject a tag"
        );
        assert!(cols[0].contains("AT&amp;T"), "got {}", cols[0]);
        assert!(
            cols[0].contains("&lt;b&gt;other&lt;/b&gt;"),
            "got {}",
            cols[0]
        );
        // Back face: pos, meaning and notes.
        assert!(
            !cols[1].contains("<b>公司</b>"),
            "the meaning must not inject a tag"
        );
        assert!(
            cols[1].contains("&lt;b&gt;公司&lt;/b&gt;"),
            "got {}",
            cols[1]
        );
        assert!(cols[1].contains("&lt;i&gt;American Telephone &amp; Telegraph&lt;/i&gt;"));
        // The word is still highlighted even though both sides are escaped.
        assert!(
            cols[0].contains("<b style='color:#3b82f6;'>AT&amp;T</b>"),
            "got {}",
            cols[0]
        );
    }

    #[test]
    fn test_highlight_case_insensitive() {
        let conn = mem_db();
        add_vocabulary_item(&conn, "ishmael", "名", "释", "Call me ISHMAEL now.", "", "").unwrap();
        let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
        assert!(tsv.contains("<b style='color:#3b82f6;'>ishmael</b>"));
    }

    #[test]
    fn test_empty_notebook_yields_headers_only() {
        let conn = mem_db();
        let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
        assert_eq!(tsv, "#separator:tab\n#html:true\n#tags column:5\n");
    }

    #[test]
    fn test_word_absent_from_context_leaves_context_untouched() {
        let conn = mem_db();
        add_vocabulary_item(&conn, "Ahab", "名", "亚哈", "Call me Ishmael.", "", "").unwrap();
        let tsv = export_vocabulary_anki_tsv(&conn).unwrap();
        assert!(tsv.contains("“Call me Ishmael.”"));
        assert!(
            !tsv.contains("<b style"),
            "no highlight when the word is absent"
        );
    }

    /// TSV reader that behaves the way Anki's importer does: a newline ends a
    /// row, a tab ends a field, and a quote is just a character. Deliberately
    /// *not* RFC4180 — a quote-aware parser here would have hidden the very bug
    /// these tests exist to catch.
    fn parse_tsv_as_anki_does(input: &str) -> Vec<Vec<String>> {
        input
            .lines()
            .map(|line| line.split('\t').map(|f| f.to_string()).collect())
            .filter(|row: &Vec<String>| !(row.len() == 1 && row[0].is_empty()))
            .collect()
    }
}
