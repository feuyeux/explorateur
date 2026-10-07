// Precision sentence boundary detection, ported from
// backend/app/parsers/sentence_splitter.py.
use fancy_regex::Regex as FancyRegex;
use regex::Regex;
use std::collections::HashMap;
use std::sync::OnceLock;

const TITLES: &[&str] = &[
    "mr", "mrs", "ms", "dr", "prof", "rev", "gen", "col", "maj", "capt", "lt", "cmdr", "sgt", "st",
    "jr", "sr", "esq", "hon", "messrs", "mme", "mlle",
];

const GENERAL_ABBREVIATIONS: &[&str] = &[
    "e.g", "i.e", "etc", "vs", "v", "viz", "al", "ca", "cf", "ibid", "id", "inc", "ltd", "corp",
    "co", "assn", "dept", "univ", "fig", "figs", "no", "nos", "vol", "vols", "p", "pp", "ch",
    "sec", "ed", "eds", "trans", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec", "ave", "blvd", "rd", "sq", "apt",
];

/// Every pattern `protect_tokens` needs, compiled once for the process.
///
/// These are constant patterns, so there is nothing to gain from rebuilding them
/// per paragraph and a great deal to lose: the full set is 72 fancy_regex
/// compiles, and importing a full-length novel runs this once per paragraph.
fn protector_patterns() -> &'static Vec<FancyRegex> {
    static PATTERNS: OnceLock<Vec<FancyRegex>> = OnceLock::new();
    PATTERNS.get_or_init(|| {
        let mut out: Vec<FancyRegex> = Vec::new();
        // 1. Decimals: 3.14, 8.30, $10.50
        out.push(FancyRegex::new(r"\b\d+\.\d+\b").unwrap());
        // 2. Acronym chains and single capital initials: D.C., U.S.A., a.m., J. K.
        out.push(FancyRegex::new(r"\b(?:[A-Za-z]\.){2,}").unwrap());
        out.push(FancyRegex::new(r"\b[A-Z]\.(?=\s+[A-Z])").unwrap());
        // 3. Titles: Mr., Dr., Prof. — even when followed by a capitalised name.
        for title in TITLES {
            out.push(
                FancyRegex::new(&format!(
                    r#"(?i)\b({})\.(?=\s+["'“‘]?[a-zA-Z0-9])"#,
                    regex::escape(title)
                ))
                .unwrap(),
            );
        }
        // 4. General abbreviations: e.g., i.e., etc., al.
        for abbr in GENERAL_ABBREVIATIONS {
            out.push(
                FancyRegex::new(&format!(
                    r#"(?i)\b({})\.(?=\s*[,;:]|\s+["'“‘]?[a-z0-9]|\s+[A-Z][a-z])"#,
                    regex::escape(abbr)
                ))
                .unwrap(),
            );
        }
        out
    })
}

fn constant_regex(cell: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(pattern).unwrap())
}

fn ellipsis_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    constant_regex(&RE, r"\.{3,}")
}

fn split_re() -> &'static FancyRegex {
    static RE: OnceLock<FancyRegex> = OnceLock::new();
    RE.get_or_init(|| FancyRegex::new(r#"([.?!…]+["'”’)\]]*)\s+(?=["'“‘A-Z0-9—]|$)"#).unwrap())
}

fn tail_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    constant_regex(&RE, r#"^[.?!…]+["'”’)\]]*$"#)
}

fn lowercase_start_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    constant_regex(&RE, r"^[a-z]")
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct SentenceUnit {
    pub sentence_id: String,
    pub order_index: i64,
    pub original: String,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Paragraph {
    pub paragraph_id: String,
    pub order_index: i64,
    pub raw_text: String,
    pub sentences: Vec<SentenceUnit>,
}

/// Swaps every match of `re` for a `__TOK_N__` placeholder, recording the
/// original text for restoration.
fn sub_placeholder(
    text: &str,
    re: &FancyRegex,
    counter: &mut usize,
    placeholders: &mut HashMap<String, String>,
) -> String {
    let mut next = String::with_capacity(text.len());
    let mut last = 0usize;
    if let Ok(matches) = re.find_iter(text).collect::<Result<Vec<_>, _>>() {
        for m in matches {
            next.push_str(&text[last..m.start()]);
            let token = format!("__TOK_{counter}__");
            *counter += 1;
            placeholders.insert(token.clone(), m.as_str().to_string());
            next.push_str(&token);
            last = m.end();
        }
    }
    next.push_str(&text[last..]);
    next
}

/// Protects decimals, acronym chains, single initials, titles and general
/// abbreviations so the split pattern never breaks inside them.
fn protect_tokens(text: &str) -> (String, HashMap<String, String>) {
    let mut placeholders: HashMap<String, String> = HashMap::new();
    let mut counter = 0usize;
    let mut out = text.to_string();
    for re in protector_patterns() {
        out = sub_placeholder(&out, re, &mut counter, &mut placeholders);
    }
    (out, placeholders)
}

fn restore_tokens(text: &str, placeholders: &HashMap<String, String>) -> String {
    let mut out = text.to_string();
    for (token, orig) in placeholders {
        out = out.replace(token, orig);
    }
    out
}

pub fn split_sentences_western(paragraph_text: &str) -> Vec<String> {
    let cleaned = paragraph_text.trim();
    if cleaned.is_empty() {
        return vec![];
    }

    let (protected_text, placeholders) = protect_tokens(cleaned);

    // Fold runs of three or more dots into a single ellipsis character so the
    // split pattern treats "..." as one terminator.
    let protected_text = ellipsis_re().replace_all(&protected_text, "…").to_string();

    // Sentence-ending punctuation, optional closing quotes/brackets, then
    // whitespace followed by a capital/quote/dash or end of text.
    let split_re = split_re();
    // fancy_regex's `split` drops capture groups, which would eat the terminal
    // punctuation. Walk the matches instead and interleave the captured
    // separator, matching Python's `re.split` semantics.
    let mut parts: Vec<String> = Vec::new();
    let mut last = 0usize;
    for caps in split_re.captures_iter(&protected_text).flatten() {
        let whole = caps.get(0).expect("group 0 always exists");
        parts.push(protected_text[last..whole.start()].to_string());
        parts.push(
            caps.get(1)
                .map(|c| c.as_str().to_string())
                .unwrap_or_default(),
        );
        last = whole.end();
    }
    parts.push(protected_text[last..].to_string());

    let tail_re = tail_re();
    let mut raw_sentences: Vec<String> = Vec::new();
    let mut i = 0usize;
    while i < parts.len() {
        let chunk = parts[i].trim().to_string();
        if chunk.is_empty() {
            i += 1;
            continue;
        }
        if i + 1 < parts.len() && tail_re.is_match(parts[i + 1].trim()) {
            raw_sentences.push(format!("{chunk}{}", parts[i + 1]).trim().to_string());
            i += 2;
        } else {
            raw_sentences.push(chunk);
            i += 1;
        }
    }

    // Re-merge dialogue attributions: '"Call me Ishmael!"' + 'he said.'
    let lower_re = lowercase_start_re();
    let mut merged: Vec<String> = Vec::new();
    let mut idx = 0usize;
    while idx < raw_sentences.len() {
        let curr = &raw_sentences[idx];
        if idx + 1 < raw_sentences.len() && lower_re.is_match(raw_sentences[idx + 1].trim()) {
            merged.push(format!("{curr} {}", raw_sentences[idx + 1]));
            idx += 2;
            continue;
        }
        merged.push(curr.clone());
        idx += 1;
    }

    let final_sentences: Vec<String> = merged
        .iter()
        .map(|s| restore_tokens(s, &placeholders).trim().replace('…', "..."))
        .filter(|s| !s.is_empty())
        .collect();

    if final_sentences.is_empty() {
        vec![cleaned.to_string()]
    } else {
        final_sentences
    }
}

pub fn split_paragraphs_and_sentences(text: &str) -> Vec<Paragraph> {
    let normalized = text.replace("\r\n", "\n").replace('\r', "\n");
    let para_re = Regex::new(r"\n\s*\n").unwrap();
    let mut raw_paras: Vec<String> = para_re
        .split(&normalized)
        .map(|p| p.trim().to_string())
        .filter(|p| !p.is_empty())
        .collect();
    if raw_paras.is_empty() {
        raw_paras = normalized
            .split('\n')
            .map(|p| p.trim().to_string())
            .filter(|p| !p.is_empty())
            .collect();
    }

    raw_paras
        .into_iter()
        .enumerate()
        .map(|(p_idx, p_text)| {
            let paragraph_id = format!("p{}", p_idx + 1);
            let sentences = split_sentences_western(&p_text)
                .into_iter()
                .enumerate()
                .map(|(s_idx, sent_text)| SentenceUnit {
                    sentence_id: format!("{paragraph_id}_s{}", s_idx + 1),
                    order_index: s_idx as i64 + 1,
                    original: sent_text,
                })
                .collect();
            Paragraph {
                paragraph_id,
                order_index: p_idx as i64 + 1,
                raw_text: p_text,
                sentences,
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Instant;

    #[test]
    fn test_the_protection_patterns_are_compiled_once_not_per_paragraph() {
        // Importing a full novel calls split_paragraphs_and_sentences once per
        // paragraph, and protect_tokens used to build 72 fancy_regex patterns
        // every time — over ten seconds of pure compilation for a real book.
        let a = protector_patterns();
        let b = protector_patterns();
        assert!(
            std::ptr::eq(a, b),
            "the compiled patterns must be a single shared set, rebuilt per call"
        );
    }

    #[test]
    fn test_splitting_a_chapter_worth_of_prose_stays_responsive() {
        let para = "Call me Ishmael. Some years ago—never mind how long precisely—having \
                    little or no money in my purse, and nothing particular to interest me on \
                    shore, I thought I would sail about a little and see the watery part of the \
                    world. Mr. Smith went to Washington, D.C. at 8.30 a.m. e.g. to see the U.S.A. \
                    Is this not curious? Absolutely!";
        let started = Instant::now();
        for _ in 0..200 {
            let n = split_sentences_western(para).len();
            assert!(n > 1, "sanity: the sample paragraph really does split");
        }
        let elapsed = started.elapsed();
        // Measured on this machine, unoptimised (the profile cargo test uses):
        // 20.9s before, 1.4s after. Release: 1.24s before, 0.11s after — which
        // is the ~12s a full-length novel used to spend here, against ~1.1s now.
        assert!(
            elapsed.as_millis() < 5000,
            "200 paragraphs took {elapsed:?}; per-call regex compilation is back"
        );
    }

    #[test]
    fn test_precision_sentence_splitting() {
        let sample = "Mr. Smith and Dr. Watson arrived at 8.30 a.m. in Washington, D.C. \
They met Prof. Moriarty near St. Jude's hospital (e.g., on 5th Ave.). \
\"Call me Ishmael!\" he said. \
Is this not curious? Absolutely.";
        let sents = split_sentences_western(sample);
        assert!(
            sents
                .iter()
                .any(|s| s.contains("Mr. Smith and Dr. Watson arrived")),
            "got {sents:?}"
        );
        assert!(
            sents.iter().any(|s| s.contains("Washington, D.C.")),
            "got {sents:?}"
        );
        assert!(
            sents.iter().any(|s| s.contains("Prof. Moriarty")),
            "got {sents:?}"
        );
        assert!(
            sents.iter().any(|s| s.contains("Call me Ishmael!")),
            "got {sents:?}"
        );
        assert_eq!(sents.len(), 4, "got {sents:?}");
    }

    #[test]
    fn test_structured_paragraph_decomposition() {
        let text = "Call me Ishmael.\n\nSome years ago, I went to sea.";
        let paras = split_paragraphs_and_sentences(text);
        assert_eq!(paras.len(), 2);
        assert_eq!(paras[0].paragraph_id, "p1");
        assert_eq!(paras[0].sentences[0].sentence_id, "p1_s1");
        assert_eq!(paras[0].sentences[0].original, "Call me Ishmael.");
        assert_eq!(paras[1].paragraph_id, "p2");
        assert_eq!(paras[1].sentences[0].sentence_id, "p2_s1");
    }

    #[test]
    fn test_terminal_punctuation_is_preserved() {
        // Regression: fancy_regex's split() drops capture groups, which silently
        // stripped the "." / "!" / "?" off every sentence.
        let sents = split_sentences_western("Call me Ishmael. Some years ago, I went to sea.");
        assert_eq!(
            sents,
            vec!["Call me Ishmael.", "Some years ago, I went to sea."]
        );
        assert!(sents.iter().all(|s| s.ends_with('.')));

        let q = split_sentences_western("Is this not curious? Absolutely!");
        assert_eq!(q, vec!["Is this not curious?", "Absolutely!"]);
    }

    #[test]
    fn test_split_on_the_real_sample_prose() {
        let sents = split_sentences_western(
            "Call me Ishmael. Some years ago—never mind how long precisely—having little or no money in my purse, and nothing particular to interest me on shore, I thought I would sail about a little and see the watery part of the world.",
        );
        assert_eq!(sents[0], "Call me Ishmael.");
        assert!(sents[1].starts_with("Some years ago—never mind"));
        assert!(sents[1].ends_with('.'));
    }

    #[test]
    fn test_ellipsis_and_multiple_punct() {
        let sents = split_sentences_western("What the devil is the matter?\" asked he...");
        assert_eq!(sents.len(), 1, "got {sents:?}");
        assert!(sents[0].contains("..."));
    }
}
