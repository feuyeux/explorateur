// Markdown export of a document's translations and sentence analyses.
//
// This is the reading-oriented counterpart to the Anki deck in `vocab.rs`: the
// deck is a flashcard format, this is a document a person re-reads. Both read
// the same cached rows, so an export never triggers a model call.
use crate::llm::SentenceAnalysis;
use rusqlite::Connection;
use std::fmt::Write as _;

fn now_str() -> String {
    chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string()
}

/// Escapes only what would change the *block* structure of the output.
///
/// A novel is full of asterisks and underscores; escaping every inline
/// emphasis character would make the text unreadable, and anything that could
/// start a heading or a list already sits behind a `**n.** ` marker or inside
/// a blockquote. Backticks still have to go: the sentence text is not
/// indented, so an unescaped ``` would open a code fence mid-paragraph.
fn escape_sentence(text: &str) -> String {
    text.replace('\\', "\\\\").replace('`', "\\`")
}

/// Renders text as a blockquote, one `> ` per line.
///
/// Model output routinely arrives as multi-line text; without the per-line
/// prefix the second line would fall out of the quote and start a paragraph.
fn blockquote(text: &str) -> String {
    let mut out = String::new();
    for line in text.lines() {
        let _ = writeln!(out, "> {}", line);
    }
    out.trim_end().to_string()
}

fn write_sentence_analysis(out: &mut String, n: usize, original: &str, translation: &str, deep: Option<&str>) {
    let _ = writeln!(out, "**{n}.** {}", escape_sentence(original.trim()));
    let _ = writeln!(out);
    let _ = writeln!(out, "{}", blockquote(&escape_sentence(translation.trim())));
    let _ = writeln!(out);

    let Some(raw) = deep else { return };
    // A malformed blob must not lose the translation that was just written out.
    let Ok(a) = serde_json::from_str::<SentenceAnalysis>(raw) else {
        return;
    };

    if let Some(g) = &a.grammar_analysis {
        let _ = writeln!(out, "- **句法** {}", g.structure.trim());
        for c in &g.components {
            let _ = writeln!(
                out,
                "  - `{}` — {}",
                escape_sentence(c.element.trim()),
                c.role.trim()
            );
        }
    }

    if !a.vocabulary_and_phrases.is_empty() {
        let _ = writeln!(out, "- **词法**");
        for v in &a.vocabulary_and_phrases {
            let pos = if v.pos.trim().is_empty() {
                String::new()
            } else {
                format!("（{}）", v.pos.trim())
            };
            let _ = writeln!(
                out,
                "  - **{}**{pos} {}",
                escape_sentence(v.token.trim()),
                v.literal_meaning.trim()
            );
            if let Some(bg) = &v.cultural_background {
                if !bg.trim().is_empty() {
                    let _ = writeln!(out, "    - {}", bg.trim().replace('\n', " "));
                }
            }
        }
    }

    if !a.idioms_and_conventions.is_empty() {
        let _ = writeln!(out, "- **典故**");
        for i in &a.idioms_and_conventions {
            let _ = writeln!(
                out,
                "  - **{}** — {}",
                escape_sentence(i.expression.trim()),
                i.usage.trim().replace('\n', " ")
            );
        }
    }

    let _ = a.overall_tone.as_deref().map(|t| {
        let t = t.trim();
        if !t.is_empty() {
            let _ = writeln!(out, "- **基调** {t}");
        }
    });

    let _ = writeln!(out);
}

/// One exported sentence: its order inside the paragraph, the original, the
/// translation and the cached deep analysis. The paragraph index lives on the
/// enclosing tuple, so rows group without a second pass.
type ExportedRow = (i64, String, String, Option<String>);
/// Paragraph index paired with its sentences, in export order.
type ExportedParagraph = (i64, Vec<ExportedRow>);

/// Renders one document as Markdown: YAML front matter, then every paragraph
/// that has at least one translated sentence.
///
/// Un-parsed paragraphs are omitted rather than stubbed — the export is meant
/// to be the reading copy of what has actually been translated. The header
/// still reports `已解析 N/M 段`, so a partial export is visibly partial.
pub fn export_document_markdown(conn: &Connection, doc_id: &str) -> Result<String, String> {
    let (title, author): (String, String) = conn
        .query_row(
            "SELECT title, author FROM documents WHERE id = ?1",
            [doc_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .map_err(|e| format!("未找到该原著: {e}"))?;

    let paragraphs_total: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM paragraphs WHERE doc_id = ?1",
            [doc_id],
            |r| r.get(0),
        )
        .map_err(|e| e.to_string())?;

    let mut stmt = conn
        .prepare(
            "SELECT p.order_index, s.order_index, s.original, s.translation, s.deep_analysis_json
             FROM paragraphs p
             JOIN sentences s ON s.paragraph_id = p.id
             WHERE p.doc_id = ?1
               AND s.translation IS NOT NULL AND TRIM(s.translation) <> ''
             ORDER BY p.order_index, s.order_index",
        )
        .map_err(|e| e.to_string())?;

    // One pass to count, one to render: rusqlite borrows the connection for the
    // statement's lifetime, so the body is buffered rather than streamed.
    let mut paragraphs: Vec<ExportedParagraph> = Vec::new();
    let mut sentences_exported = 0usize;
    let rows = stmt
        .query_map([doc_id], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, Option<String>>(4)?,
            ))
        })
        .map_err(|e| e.to_string())?;

    for row in rows {
        let (p_idx, s_idx, original, translation, deep) = row.map_err(|e| e.to_string())?;
        sentences_exported += 1;
        match paragraphs.last_mut() {
            Some(last) if last.0 == p_idx => last.1.push((s_idx, original, translation, deep)),
            _ => paragraphs.push((p_idx, vec![(s_idx, original, translation, deep)])),
        }
    }

    let now = now_str();
    let mut out = String::new();
    let _ = writeln!(out, "---");
    let _ = writeln!(out, "title: \"{}\"", title.replace('"', "'"));
    let _ = writeln!(out, "author: \"{}\"", author.replace('"', "'"));
    let _ = writeln!(out, "exported_at: \"{now}\"");
    let _ = writeln!(out, "paragraphs_exported: {}", paragraphs.len());
    let _ = writeln!(out, "paragraphs_total: {paragraphs_total}");
    let _ = writeln!(out, "sentences_exported: {sentences_exported}");
    let _ = writeln!(out, "---");
    let _ = writeln!(out);
    let _ = writeln!(out, "# {}", title.trim());
    let _ = writeln!(out);
    let _ = writeln!(
        out,
        "> 作者：{} · 导出于 {now} · 已解析 {}/{} 段 · {sentences_exported} 句译文",
        if author.trim().is_empty() { "未知" } else { author.trim() },
        paragraphs.len(),
        paragraphs_total
    );
    let _ = writeln!(out);

    if paragraphs.is_empty() {
        let _ = writeln!(out, "> 尚无已解析的段落。请先在应用中点「一键解析本段」，再重新导出。");
        return Ok(out);
    }

    for (p_idx, sentences) in &paragraphs {
        let _ = writeln!(out, "---");
        let _ = writeln!(out);
        let _ = writeln!(out, "## 第 {} 段", p_idx + 1);
        let _ = writeln!(out);
        for (i, (_, original, translation, deep)) in sentences.iter().enumerate() {
            write_sentence_analysis(&mut out, i + 1, original, translation, deep.as_deref());
        }
    }

    Ok(out)
}

/// Writes the rendered Markdown to `path`, returning the byte count.
pub fn write_document_markdown_to(conn: &Connection, doc_id: &str, path: &str) -> Result<usize, String> {
    let md = export_document_markdown(conn, doc_id)?;
    if let Some(parent) = std::path::Path::new(path).parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent).map_err(|e| format!("无法创建目录: {e}"))?;
        }
    }
    std::fs::write(path, md.as_bytes()).map_err(|e| format!("写入文件失败: {e}"))?;
    Ok(md.len())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mem_db() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        crate::db::init_conn(&conn).unwrap();
        conn
    }

    fn seed_doc(conn: &Connection, doc_id: &str, title: &str, author: &str) {
        conn.execute(
            "INSERT INTO documents (id,title,author,file_type,raw_content,created_at)
             VALUES (?1,?2,?3,'md','x','2026-01-01 00:00:00')",
            rusqlite::params![doc_id, title, author],
        )
        .unwrap();
    }

    #[allow(clippy::too_many_arguments)] // a seed helper; grouping these would obscure the fixtures
    fn seed_sentence(
        conn: &Connection,
        sid: &str,
        doc_id: &str,
        pid: &str,
        s_idx: i64,
        original: &str,
        translation: Option<&str>,
        deep: Option<&str>,
    ) {
        conn.execute(
            "INSERT INTO sentences (id,doc_id,paragraph_id,order_index,original,translation,deep_analysis_json)
             VALUES (?1,?2,?3,?4,?5,?6,?7)",
            rusqlite::params![sid, doc_id, pid, s_idx, original, translation, deep],
        )
        .unwrap();
    }

    fn analysis_json() -> &'static str {
        r#"{
            "sentence_id":"s1","original":"Call me Ishmael.","translation":"叫我以实玛利吧。",
            "overall_tone":"简洁的叙事开篇",
            "grammar_analysis":{"structure":"祈使句 (Imperative sentence)","components":[
                {"element":"Call","role":"谓语动词 (V)"},
                {"element":"me","role":"宾语 (O)"}]},
            "vocabulary_and_phrases":[{"token":"Ishmael","pos":"专有名词","literal_meaning":"人名（以实玛利）",
                "cultural_background":"《圣经·创世记》中亚伯拉罕之子。"}],
            "idioms_and_conventions":[{"expression":"Call me [Name]","usage":"非正式的自我介绍。"}]
        }"#
    }

    #[test]
    fn renders_front_matter_and_both_languages() {
        let conn = mem_db();
        seed_doc(&conn, "d1", "白鲸记", "赫尔曼·麦尔维尔");
        conn.execute(
            "INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'raw')",
            [],
        )
        .unwrap();
        seed_sentence(&conn, "s1", "d1", "p1", 0, "Call me Ishmael.", Some("叫我以实玛利吧。"), None);

        let md = export_document_markdown(&conn, "d1").unwrap();
        assert!(md.starts_with("---\n"), "must open with YAML front matter: {md}");
        assert!(md.contains("title: \"白鲸记\""));
        assert!(md.contains("paragraphs_exported: 1"));
        assert!(md.contains("paragraphs_total: 1"));
        assert!(md.contains("sentences_exported: 1"));
        assert!(md.contains("# 白鲸记"));
        assert!(md.contains("**1.** Call me Ishmael."));
        assert!(md.contains("> 叫我以实玛利吧。"));
    }

    #[test]
    fn renders_the_full_analysis_when_it_is_cached() {
        let conn = mem_db();
        seed_doc(&conn, "d1", "白鲸记", "麦尔维尔");
        conn.execute("INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'raw')", []).unwrap();
        seed_sentence(
            &conn, "s1", "d1", "p1", 0, "Call me Ishmael.", Some("叫我以实玛利吧。"),
            Some(analysis_json()),
        );

        let md = export_document_markdown(&conn, "d1").unwrap();
        assert!(md.contains("- **句法** 祈使句 (Imperative sentence)"));
        assert!(md.contains("  - `Call` — 谓语动词 (V)"));
        assert!(md.contains("- **词法**"));
        assert!(md.contains("**Ishmael**（专有名词） 人名（以实玛利）"), "got:\n{md}");
        assert!(md.contains("《圣经·创世记》中亚伯拉罕之子。"));
        assert!(md.contains("- **典故**"));
        assert!(md.contains("**Call me [Name]** — 非正式的自我介绍。"));
        assert!(md.contains("- **基调** 简洁的叙事开篇"));
    }

    #[test]
    fn skips_untranslated_paragraphs_but_still_reports_progress() {
        // The Anki export has no document notion; this one does. A paragraph
        // nobody translated must not appear, or the file claims to be the book
        // when it is a fragment of it.
        let conn = mem_db();
        seed_doc(&conn, "d1", "白鲸记", "麦尔维尔");
        conn.execute("INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'a')", []).unwrap();
        conn.execute("INSERT INTO paragraphs VALUES ('p2','d1','ch_1',1,'b')", []).unwrap();
        conn.execute("INSERT INTO paragraphs VALUES ('p3','d1','ch_1',2,'c')", []).unwrap();
        seed_sentence(&conn, "s1", "d1", "p2", 0, "Call me Ishmael.", Some("叫我以实玛利吧。"), None);
        seed_sentence(&conn, "s2", "d1", "p3", 0, "Untranslated.", None, None);

        let md = export_document_markdown(&conn, "d1").unwrap();
        assert!(md.contains("## 第 2 段"), "exported paragraph keeps its real index");
        assert!(!md.contains("## 第 1 段"));
        assert!(!md.contains("## 第 3 段"));
        assert!(md.contains("paragraphs_exported: 1"));
        assert!(md.contains("paragraphs_total: 3"));
        assert!(md.contains("已解析 1/3 段"));
    }

    #[test]
    fn a_blank_translation_counts_as_unparsed() {
        let conn = mem_db();
        seed_doc(&conn, "d1", "T", "A");
        conn.execute("INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'a')", []).unwrap();
        seed_sentence(&conn, "s1", "d1", "p1", 0, "Hi.", Some("   "), None);

        let md = export_document_markdown(&conn, "d1").unwrap();
        assert!(md.contains("尚无已解析的段落"), "whitespace is not a translation");
        assert!(!md.contains("**1.**"));
    }

    #[test]
    fn a_document_with_nothing_parsed_explains_itself_instead_of_being_empty() {
        let conn = mem_db();
        seed_doc(&conn, "d1", "白鲸记", "麦尔维尔");
        conn.execute("INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'a')", []).unwrap();
        seed_sentence(&conn, "s1", "d1", "p1", 0, "Call me Ishmael.", None, None);

        let md = export_document_markdown(&conn, "d1").unwrap();
        assert!(md.contains("sentences_exported: 0"));
        assert!(md.contains("尚无已解析的段落"));
    }

    #[test]
    fn keeps_the_translation_when_the_cached_analysis_is_corrupt() {
        let conn = mem_db();
        seed_doc(&conn, "d1", "T", "A");
        conn.execute("INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'a')", []).unwrap();
        seed_sentence(
            &conn, "s1", "d1", "p1", 0, "Call me Ishmael.", Some("叫我以实玛利吧。"),
            Some("{not json at all"),
        );

        let md = export_document_markdown(&conn, "d1").unwrap();
        assert!(md.contains("> 叫我以实玛利吧。"), "translation must survive");
        assert!(!md.contains("- **句法**"));
    }

    #[test]
    fn a_multiline_translation_stays_inside_its_blockquote() {
        // Model output arrives with hard line breaks. Without a per-line "> "
        // the second line escapes the quote and starts a stray paragraph.
        let conn = mem_db();
        seed_doc(&conn, "d1", "T", "A");
        conn.execute("INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'a')", []).unwrap();
        seed_sentence(
            &conn, "s1", "d1", "p1", 0, "One two.", Some("第一行\n第二行"), None,
        );

        let md = export_document_markdown(&conn, "d1").unwrap();
        assert!(md.contains("> 第一行\n> 第二行"), "got: {md}");
    }

    #[test]
    fn escapes_backticks_that_would_open_a_code_fence() {
        let conn = mem_db();
        seed_doc(&conn, "d1", "T", "A");
        conn.execute("INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'a')", []).unwrap();
        seed_sentence(&conn, "s1", "d1", "p1", 0, "He said ```hi```.", Some("他说```你好```。"), None);

        let md = export_document_markdown(&conn, "d1").unwrap();
        assert!(md.contains("He said \\`\\`\\`hi\\`\\`\\`."), "got: {md}");
        assert!(md.contains("他说\\`\\`\\`你好\\`\\`\\`。"));
    }

    #[test]
    fn orders_sentences_within_a_paragraph_by_their_own_index() {
        let conn = mem_db();
        seed_doc(&conn, "d1", "T", "A");
        conn.execute("INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'a')", []).unwrap();
        // inserted out of order on purpose
        seed_sentence(&conn, "s2", "d1", "p1", 1, "Second.", Some("第二句。"), None);
        seed_sentence(&conn, "s1", "d1", "p1", 0, "First.", Some("第一句。"), None);

        let md = export_document_markdown(&conn, "d1").unwrap();
        let first = md.find("第一句。").unwrap();
        let second = md.find("第二句。").unwrap();
        assert!(first < second, "sentences must follow order_index");
        assert!(md.contains("sentences_exported: 2"));
    }

    #[test]
    fn refuses_an_unknown_document() {
        let conn = mem_db();
        assert!(export_document_markdown(&conn, "nope").is_err());
    }

    #[test]
    fn writes_the_file_and_reports_its_size() {
        let conn = mem_db();
        seed_doc(&conn, "d1", "白鲸记", "麦尔维尔");
        conn.execute("INSERT INTO paragraphs VALUES ('p1','d1','ch_1',0,'a')", []).unwrap();
        seed_sentence(&conn, "s1", "d1", "p1", 0, "Call me Ishmael.", Some("叫我以实玛利吧。"), None);

        let dir = std::env::temp_dir().join("ready-md-export-test");
        let path = dir.join("nested").join("out.md");
        let n = write_document_markdown_to(&conn, "d1", path.to_str().unwrap()).unwrap();
        let body = std::fs::read_to_string(&path).unwrap();
        assert_eq!(n, body.len());
        assert!(body.contains("叫我以实玛利吧。"));
        let _ = std::fs::remove_dir_all(&dir);
    }
}
