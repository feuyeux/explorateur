// Unsegmented Latin transliteration detector, ported from the kb repo's
// transliteration-segmentation skill (scripts/check_segmentation.py).
//
// Convention: Latin transliterations of non-Latin scripts are hyphenated at
// script-unit boundaries so each chunk maps at a glance to the original letter.
// The check flags `（*...*）` reading-aid glosses whose Latin tokens are glued:
// more than 6 characters with no hyphen, when the gloss follows hangul, kana,
// devanagari, arabic or hebrew script within the previous 30 characters.
//
// Not checked (word-level by convention): IPA transcriptions, letterwise
// scripts such as Russian/Greek (a Cyrillic gloss like `Izvinite` is not a
// violation — Cyrillic is not a target script), pinyin and jyutping. English
// language names are never transliteration targets, and known English loans
// kept in English (e.g. `zebra crossing`) are waived.
//
// The kb source also polices GFM corpus table rows (语言 column); this app has
// no corpus tables, so only the gloss rule was worth porting.
use regex::Regex;
use std::sync::OnceLock;

/// How far before a gloss the non-Latin script may sit and still count as its
/// reading aid.
const GLOSS_CONTEXT_CHARS: usize = 30;

/// English language names are never transliteration targets.
const ENGLISH_NAMES: &[&str] = &[
    "Japanese",
    "Korean",
    "Chinese",
    "Mandarin",
    "Cantonese",
    "Hindi",
    "Arabic",
    "Hebrew",
    "English",
    "German",
    "French",
    "Spanish",
    "Russian",
    "Greek",
    "Italian",
    "Turkish",
    "Vietnamese",
    "Thai",
    "Indonesian",
];

/// Glosses that are English loans kept in English, not transliterations.
const WAIVED_GLOSSES: &[&str] = &["zebra crossing"];

#[derive(Debug, serde::Serialize, PartialEq)]
pub struct TranslitFinding {
    /// The gloss text exactly as it appeared between `（*` and `*）`.
    pub gloss: String,
    /// The offending tokens, in order of appearance.
    pub tokens: Vec<String>,
}

fn gloss_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"（\*([^*]+)\*）").unwrap())
}

fn latin_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[A-Za-zÀ-ɏͰ-Ͽ\u{02B0}-\u{02FF}\u{1E00}-\u{1EFF}']+").unwrap())
}

fn link_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\[[^\]]*\]\([^)]*\)|https?://\S+").unwrap())
}

/// Hangul, kana, devanagari, arabic, hebrew — the scripts whose reading-aid
/// glosses this convention covers.
fn target_script_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[가-힯぀-ヿऀ-ॿ؀-ۿ\u{0590}-\u{05FF}]").unwrap())
}

fn unsegmented_tokens(text: &str) -> Vec<String> {
    latin_re()
        .find_iter(text)
        .map(|m| m.as_str())
        // >6 characters, no hyphen: single-syllable words and short tokens
        // (`yeop`, `dost`, `ga`, `jā`, `māf`, `hai`) are not penalised.
        .filter(|t| t.chars().count() > 6 && !t.contains('-') && !ENGLISH_NAMES.contains(t))
        .map(str::to_string)
        .collect()
}

/// The up-to-`n` characters of `text` ending at `byte_end`, by characters, not
/// bytes — the kb source slices by characters and non-Latin scripts are
/// multi-byte.
fn window_before(text: &str, byte_end: usize, n: usize) -> String {
    let head: Vec<char> = text[..byte_end].chars().collect();
    let skip = head.len().saturating_sub(n);
    head[skip..].iter().collect()
}

/// Flags reading-aid glosses whose Latin transliteration is glued together
/// instead of hyphenated at script-unit boundaries.
pub fn check_transliteration(text: &str) -> Vec<TranslitFinding> {
    let mut out = Vec::new();
    for caps in gloss_re().captures_iter(text) {
        let whole = caps.get(0).unwrap();
        let gloss = caps.get(1).unwrap().as_str();
        if WAIVED_GLOSSES.contains(&gloss) {
            continue;
        }
        let before = window_before(text, whole.start(), GLOSS_CONTEXT_CHARS);
        if !target_script_re().is_match(&before) {
            continue;
        }
        let tokens = unsegmented_tokens(&link_re().replace_all(gloss, " "));
        if !tokens.is_empty() {
            out.push(TranslitFinding {
                gloss: gloss.to_string(),
                tokens,
            });
        }
    }
    out
}

/// Checks a text for unsegmented transliterations. Pure and synchronous: no
/// database, no async runtime, so it avoids the block_on trap entirely.
#[tauri::command]
pub fn check_transliterations(text: String) -> Vec<TranslitFinding> {
    check_transliteration(&text)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn findings(text: &str) -> Vec<TranslitFinding> {
        check_transliteration(text)
    }

    #[test]
    fn korean_glossed_glued_tokens_are_caught() {
        // kb 实测样例：환영합니다 的分段转写是 hwan-nyeong-ham-ni-da；粘连形必须被抓。
        let out = findings("환영합니다（*hwannyeong hamnida*）");
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].gloss, "hwannyeong hamnida");
        assert_eq!(out[0].tokens, vec!["hwannyeong", "hamnida"]);
    }

    #[test]
    fn hyphenated_korean_passes() {
        assert!(findings("환영합니다（*hwan-nyeong-ham-ni-da*）").is_empty());
    }

    #[test]
    fn japanese_sokuon_double_consonant_passes() {
        assert!(findings("まっすぐ（*ma-s-su-gu*）").is_empty());
    }

    #[test]
    fn short_tokens_are_not_penalised() {
        // 않았어요 → a-na-sseo-yo：写成空格分隔的短 token 也不罚（>6 才罚）。
        assert!(findings("않았어요（*a na sseo yo*）").is_empty());
    }

    #[test]
    fn russian_letterwise_script_is_not_a_target() {
        // 字母对应文字（俄语/希腊语）不分段：西里尔不在目标文字集里。
        assert!(findings("Извините（*Izvinite*）").is_empty());
    }

    #[test]
    fn arabic_glued_gloss_is_caught() {
        let out = findings("تتخلى（*takhalla*）");
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].tokens, vec!["takhalla"]);
    }

    #[test]
    fn hebrew_and_devanagari_context_counts() {
        assert_eq!(findings("स्वागत है（*svaagat hai*）").len(), 1);
        assert!(findings("שלום（*shalom*）").is_empty()); // exactly 6 chars: not >6
    }

    #[test]
    fn latin_only_text_has_no_findings() {
        assert!(findings("Call me Ishmael. Some years ago, I went to sea.").is_empty());
        assert!(findings("Welcome（*hwannyeonghamnida*）").is_empty());
    }

    #[test]
    fn english_language_names_are_never_targets() {
        assert!(findings("日本語（*Japanese*）").is_empty());
    }

    #[test]
    fn english_loan_glosses_are_waived() {
        assert!(findings("सिग्नल（*zebra crossing*）").is_empty());
    }

    #[test]
    fn links_inside_the_gloss_are_masked() {
        // Markdown 链接和 URL 不是转写，先屏蔽再量 token。
        assert!(
            findings("한국어（*see [wiki](https://example.com/wiki/KoreanTranslit)*）").is_empty()
        );
    }

    #[test]
    fn script_farther_than_30_chars_back_does_not_count() {
        // 谚文离注音超过 30 字符：注音不判。
        let filler = "a".repeat(31);
        assert!(findings(&format!("한국어 {filler}（*hwannyeonghamnida*）")).is_empty());
    }

    #[test]
    fn script_within_30_chars_back_counts_even_across_punctuation() {
        assert_eq!(
            findings("환영합니다, 친구들!（*hwannyeonghamnida*）").len(),
            1
        );
    }
}
