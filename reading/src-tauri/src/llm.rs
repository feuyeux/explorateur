// Analysis engine: offline curated/heuristic knowledge plus live LLM clients,
// ported from backend/app/services/llm_engine.py.
use crate::prompts::{
    build_paragraph_analysis_prompt, build_single_sentence_deep_prompt, SYSTEM_PROMPT,
};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::time::Duration;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GrammarComponent {
    pub element: String,
    pub role: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GrammarAnalysis {
    pub structure: String,
    #[serde(default)]
    pub components: Vec<GrammarComponent>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VocabItem {
    pub token: String,
    #[serde(default)]
    pub pos: String,
    pub literal_meaning: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cultural_background: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IdiomItem {
    pub expression: String,
    #[serde(default)]
    pub usage: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SentenceAnalysis {
    #[serde(default)]
    pub sentence_id: String,
    #[serde(default)]
    pub original: String,
    #[serde(default)]
    pub translation: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub overall_tone: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub grammar_analysis: Option<GrammarAnalysis>,
    #[serde(default)]
    pub vocabulary_and_phrases: Vec<VocabItem>,
    #[serde(default)]
    pub idioms_and_conventions: Vec<IdiomItem>,
}

#[derive(Clone, Debug)]
pub struct ProviderCfg {
    pub provider: String,
    pub api_key: String,
    pub base_url: String,
    pub model_name: String,
    pub temperature: f64,
    pub mock_mode: bool,
}

/// The offline demo engine echoes the original as the "translation" with this
/// prefix instead of translating it. The rest of the app treats it as a
/// sentinel: a placeholder never counts as a translated sentence and is never
/// persisted, so a demo click cannot poison the cache the way it used to — a
/// paragraph whose every sentence held one read as fully translated forever
/// and was never sent to the model again, even after a key was configured.
pub const PLACEHOLDER_TRANSLATION_PREFIX: &str = "【译文】";

/// True for the offline demo engine's `【译文】<原文>` echo of the original.
pub fn is_placeholder_translation(translation: &str) -> bool {
    translation
        .trim_start()
        .starts_with(PLACEHOLDER_TRANSLATION_PREFIX)
}

/// True when a parsed/cached analysis actually carries deep-analysis content,
/// as opposed to a translation-only object.
///
/// A translation-only response is legitimate from the paragraph phase (or from
/// a model that skipped the analysis fields), but it must never be treated as
/// a finished deep analysis: cached as one, it makes every later sentence
/// click serve it from cache, and the inspector shows nothing but the
/// translation — exactly what happened once a real LLM replaced the offline
/// engine, whose heuristic always included an S-V-O slice.
pub fn is_deep_analysis(v: &serde_json::Value) -> bool {
    let grammar = v.get("grammar_analysis").is_some_and(|g| {
        g.get("structure")
            .and_then(|s| s.as_str())
            .is_some_and(|s| !s.trim().is_empty())
            || g.get("components")
                .and_then(|c| c.as_array())
                .is_some_and(|c| !c.is_empty())
    });
    let vocab = v
        .get("vocabulary_and_phrases")
        .and_then(|a| a.as_array())
        .is_some_and(|a| !a.is_empty());
    let idioms = v
        .get("idioms_and_conventions")
        .and_then(|a| a.as_array())
        .is_some_and(|a| !a.is_empty());
    grammar || vocab || idioms
}

/// Which engine actually produced an analysis and — when it was not the live
/// model — why. A silent fallback used to be indistinguishable from success,
/// which is exactly how a paragraph could "finish" showing its own original.
#[derive(Debug, Clone)]
pub struct EngineProvenance {
    /// "llm", "offline-demo" (no key / mock mode) or "offline-fallback"
    /// (a live call was attempted and failed).
    pub engine: &'static str,
    /// The live-call error behind an `offline-fallback`.
    pub fallback_reason: Option<String>,
}

fn offline_demo() -> EngineProvenance {
    EngineProvenance {
        engine: "offline-demo",
        fallback_reason: None,
    }
}

/// The offline engine runs when the user explicitly asked for mock mode, or
/// when there is no key to spend. A `provider` of "mock" is handled separately
/// at the call sites, mirroring the Python version.
pub fn is_mock(cfg: &ProviderCfg) -> bool {
    cfg.mock_mode || cfg.api_key.trim().is_empty()
}

fn curated(sentence_id: &str, original: &str) -> Option<SentenceAnalysis> {
    let data = match original.trim() {
        "Call me Ishmael." => serde_json::json!({
            "translation": "叫我以实玛利吧。",
            "overall_tone": "简洁而带有叙事宿命感的开篇第一人称独白",
            "grammar_analysis": {
                "structure": "祈使句 (Imperative sentence)",
                "components": [
                    {"element": "Call", "role": "谓语动词 (V)"},
                    {"element": "me", "role": "宾语 (O)"},
                    {"element": "Ishmael", "role": "宾语补足语 (OC)"}
                ]
            },
            "vocabulary_and_phrases": [{
                "token": "Ishmael",
                "pos": "专有名词",
                "literal_meaning": "人名（以实玛利）",
                "cultural_background": "《圣经·创世记》中亚伯拉罕之子，后常引申指代被放逐者、孤立于世的流浪汉。"
            }],
            "idioms_and_conventions": [{
                "expression": "Call me [Name]",
                "usage": "常用于非正式的自我介绍，此处开篇弱化了说话者的身份界限，拉近与读者的距离，带有哲理反讽与神秘感。"
            }]
        }),
        "Some years ago—never mind how long precisely—having little or no money in my purse, and nothing particular to interest me on shore, I thought I would sail about a little and see the watery part of the world." => serde_json::json!({
            "translation": "几年前——具体多久不必深究——钱包里空空如也，岸上也实在没有什么叫我留恋的，我便寻思着出海转转，瞧瞧这个世界上汪洋浩瀚的那一部分。",
            "overall_tone": "豁达、略带自嘲的漫游者心态，典型的麦尔维尔式海洋哲学",
            "grammar_analysis": {
                "structure": "复合长句 (主句 + 插入语 + 分词伴随状语 + 宾语从句)",
                "components": [
                    {"element": "Some years ago", "role": "时间状语 (Time Adv)"},
                    {"element": "—never mind how long precisely—", "role": "插入语 (Parenthetical)"},
                    {"element": "having little or no money in my purse, and nothing particular to interest me on shore", "role": "现在分词短语作伴随/原因状语 (Participle Clause)"},
                    {"element": "I", "role": "主语 (S)"},
                    {"element": "thought", "role": "谓语动词 (V)"},
                    {"element": "I would sail about a little and see the watery part of the world", "role": "宾语从句 (Object Clause)"}
                ]
            },
            "vocabulary_and_phrases": [
                {
                    "token": "watery part of the world",
                    "pos": "名词短语",
                    "literal_meaning": "世界的海洋部分 / 汪洋大海",
                    "cultural_background": "作者以此将地球分为陆地平庸生活与海洋未知广袤两大领域，暗含对文明社会的精神逃离。"
                },
                {
                    "token": "sail about",
                    "pos": "动词短语",
                    "literal_meaning": "到处航行、漫游出海",
                    "cultural_background": "19世纪捕鲸时代的探险航海文化，代表漂泊与未知的命运。"
                }
            ],
            "idioms_and_conventions": [{
                "expression": "never mind",
                "usage": "意为'没关系、不用介意'，在此打破严肃纪年法，营造如同在炉火旁与听众促膝长谈的口吻。"
            }]
        }),
        "In my younger and more vulnerable years my father gave me some advice that I’ve been turning over in my mind ever since." => serde_json::json!({
            "translation": "在我年纪还轻、心智还不够成熟的岁月里，父亲曾给过我一句告诫，这些年来我一直在心头反复咀嚼回想。",
            "overall_tone": "怀旧、沉静而富有哲思的倒叙叙事基调",
            "grammar_analysis": {
                "structure": "复合句 (时间状语从句 + 主句 + 定语从句)",
                "components": [
                    {"element": "In my younger and more vulnerable years", "role": "时间状语 (Time Adv)"},
                    {"element": "my father", "role": "主语 (S)"},
                    {"element": "gave", "role": "谓语动词 (V)"},
                    {"element": "me", "role": "间接宾语 (IO)"},
                    {"element": "some advice", "role": "直接宾语 (DO)"},
                    {"element": "that I've been turning over in my mind ever since", "role": "定语从句修饰 advice (Relative Clause)"}
                ]
            },
            "vocabulary_and_phrases": [{
                "token": "vulnerable",
                "pos": "形容词",
                "literal_meaning": "脆弱的、易受伤害或影响的",
                "cultural_background": "形容青年时期价值观未成形、极易被外部繁华与世俗观念动摇的状态。"
            }],
            "idioms_and_conventions": [{
                "expression": "turn over in one's mind",
                "usage": "固定成语搭配，比喻反复琢磨、反刍沉思某事，生动展现叙述者内省的性格。"
            }]
        }),
        _ => return None,
    };

    let mut out: SentenceAnalysis = serde_json::from_value(data).expect("curated entry is valid");
    out.sentence_id = sentence_id.to_string();
    out.original = original.to_string();
    Some(out)
}

/// Offline fallback for arbitrary sentences: S-V-O slicing plus a transliterated
/// translation. Never fails, so the UI always has something to render.
pub fn heuristic_sentence_analysis(sentence_id: &str, original: &str) -> SentenceAnalysis {
    if let Some(c) = curated(sentence_id, original) {
        return c;
    }
    let orig_clean = original.trim();
    let word_re = Regex::new(r"[a-zA-Z']+").unwrap();
    let words: Vec<String> = word_re
        .find_iter(orig_clean)
        .map(|m| m.as_str().to_string())
        .collect();
    let n = words.len();

    let mut structure = String::new();
    let mut components: Vec<GrammarComponent> = Vec::new();
    if n > 0 {
        let first = &words[0];
        let lower = first.to_lowercase();
        if ["if", "when", "although", "because", "while", "as"].contains(&lower.as_str()) {
            structure = "复合从句 (Adverbial Clause + Main Clause)".to_string();
            components.push(GrammarComponent {
                element: format!("{first} ..."),
                role: "状语从句 (Adv Clause)".to_string(),
            });
        } else if first
            .chars()
            .next()
            .map(|c| c.is_uppercase())
            .unwrap_or(false)
            && ["call", "look", "see", "listen", "be", "do"].contains(&lower.as_str())
        {
            structure = "祈使句 (Imperative Sentence)".to_string();
            components.push(GrammarComponent {
                element: first.clone(),
                role: "谓语动词 (V)".to_string(),
            });
            if n > 1 {
                components.push(GrammarComponent {
                    element: words[1..].join(" "),
                    role: "宾语与补足语 (O / OC)".to_string(),
                });
            }
        } else {
            structure = "陈述句 (Declarative Sentence)".to_string();
            let mid = 3.min((n / 3).max(1));
            components.push(GrammarComponent {
                element: words[..mid].join(" "),
                role: "主语主干 (S)".to_string(),
            });
            if n > mid {
                let v_end = (mid + 2).min(n);
                components.push(GrammarComponent {
                    element: words[mid..v_end].join(" "),
                    role: "核心谓语 (V)".to_string(),
                });
            }
            if n > mid + 2 {
                components.push(GrammarComponent {
                    element: words[mid + 2..].join(" "),
                    role: "宾语及状语修饰 (O / Adv)".to_string(),
                });
            }
        }
    }

    let skip = ["because", "through", "without", "between"];
    let long_words: Vec<&String> = words
        .iter()
        .filter(|w| w.len() >= 6 && !skip.contains(&w.to_lowercase().as_str()))
        .take(2)
        .collect();
    let vocabulary_and_phrases = long_words
        .into_iter()
        .map(|w| VocabItem {
            token: capitalize(w),
            pos: "名词/形容词".to_string(),
            literal_meaning: format!("原著特定语境释义：[{w}]"),
            cultural_background: Some(
                "西文原著经典用词，在此处强化了句子的文学层次与语感。".to_string(),
            ),
        })
        .collect();

    SentenceAnalysis {
        sentence_id: sentence_id.to_string(),
        original: original.to_string(),
        translation: format!("{PLACEHOLDER_TRANSLATION_PREFIX}{original}"),
        overall_tone: Some("严谨庄重，具有典型文学叙事色彩".to_string()),
        grammar_analysis: Some(GrammarAnalysis {
            structure,
            components,
        }),
        vocabulary_and_phrases,
        idioms_and_conventions: vec![IdiomItem {
            expression: if n > 0 {
                format!("{} ...", words[0])
            } else {
                "Literary style".to_string()
            },
            usage: "原著叙事修辞手法，通过特定的句法结构增强表达张力。".to_string(),
        }],
    }
}

fn capitalize(w: &str) -> String {
    let mut chars = w.chars();
    match chars.next() {
        Some(c) => c.to_uppercase().collect::<String>() + chars.as_str(),
        None => String::new(),
    }
}

/// Parses the LLM's JSON envelope, keeping only sentences whose id the caller
/// actually asked for. An id the model invented is discarded, never stored.
pub fn parse_llm_sentences(
    parsed: &serde_json::Value,
    expected_ids: &[String],
) -> Vec<SentenceAnalysis> {
    let arr = match parsed.get("sentences").and_then(|s| s.as_array()) {
        Some(a) => a,
        None => return vec![],
    };
    arr.iter()
        .filter_map(|v| serde_json::from_value::<SentenceAnalysis>(v.clone()).ok())
        .filter(|s| expected_ids.contains(&s.sentence_id))
        .collect()
}

fn strip_json_fence(raw: &str) -> String {
    let mut cleaned = raw.trim().to_string();
    if cleaned.starts_with("```") {
        let open = Regex::new(r"^```(?:json)?\s*").unwrap();
        let close = Regex::new(r"\s*```$").unwrap();
        cleaned = close.replace(&open.replace(&cleaned, ""), "").to_string();
    }
    cleaned
}

/// Resolves the endpoint and model for a provider, filling in defaults when
/// the user left the base URL or the model box blank.
///
/// The bool is "speaks the Anthropic message format". It is not the same thing
/// as "is Claude": MiniMax also exposes an Anthropic-compatible surface, and
/// posting its `/anthropic` path with OpenAI's bearer-auth + `chat/completions`
/// body gets a 404 that used to vanish into the silent offline fallback.
pub fn resolve_endpoint(cfg: &ProviderCfg) -> (String, String, bool) {
    let is_anthropic = matches!(cfg.provider.as_str(), "claude" | "minimax");
    let model = cfg.model_name.trim();
    // One default table for both branches. Pointing a provider at a proxy is
    // still pointing it at that provider's API, so the model it defaults to
    // must not change just because a base URL was typed in — that used to send
    // gpt-4o-mini to an Anthropic or DeepSeek host, which 404s and drops the
    // request into the offline engine with no visible error.
    let default_model = match cfg.provider.as_str() {
        "deepseek" => "deepseek-chat",
        "gemini" => "gemini-1.5-flash",
        "claude" => "claude-3-5-sonnet",
        "minimax" => "MiniMax-M3",
        _ => "gpt-4o-mini",
    };
    let model = if model.is_empty() {
        default_model
    } else {
        model
    };

    let base = cfg.base_url.trim();
    if base.is_empty() {
        let b = match cfg.provider.as_str() {
            "deepseek" => "https://api.deepseek.com/v1",
            "gemini" => "https://generativelanguage.googleapis.com/v1beta/openai",
            "claude" => "https://api.anthropic.com/v1",
            // MiniMax's Anthropic surface is namespaced: the messages path is
            // /anthropic/v1/messages, not /anthropic/messages.
            "minimax" => "https://api.minimaxi.com/anthropic/v1",
            _ => "https://api.openai.com/v1",
        };
        (b.to_string(), model.to_string(), is_anthropic)
    } else {
        (
            base.trim_end_matches('/').to_string(),
            model.to_string(),
            is_anthropic,
        )
    }
}

async fn call_llm(
    cfg: &ProviderCfg,
    system_prompt: &str,
    user_prompt: &str,
    json_mode: bool,
) -> Result<String, String> {
    let (base, model, is_anthropic) = resolve_endpoint(cfg);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|e| e.to_string())?;

    // Anthropic has its own message shape: system is a top-level field, auth
    // is a header rather than a bearer token, and the reply is a content array.
    if is_anthropic {
        let url = format!("{base}/messages");
        let payload = serde_json::json!({
            "model": model,
            // 4096 truncated a full paragraph analysis mid-JSON, and the
            // offline fallback then replaced every real translation in it
            // with a demo echo.
            "max_tokens": 8192,
            "temperature": cfg.temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}]
        });
        let resp = client
            .post(&url)
            .header("x-api-key", &cfg.api_key)
            .header("anthropic-version", "2023-06-01")
            .json(&payload)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !resp.status().is_success() {
            // Surface the body, not just the status: MiniMax answers
            // `insufficient_balance_error` and Claude answers a model-not-found
            // with the actionable text, while the bare code says neither.
            let status = resp.status();
            let detail = resp.text().await.unwrap_or_default();
            return Err(format!("anthropic api error {status}: {detail}"));
        }
        let data: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
        return data
            .get("content")
            .and_then(|c| c.get(0))
            .and_then(|c| c.get("text"))
            .and_then(|t| t.as_str())
            .map(|s| s.to_string())
            .ok_or_else(|| "anthropic response had no content[0].text".to_string());
    }

    let url = format!("{base}/chat/completions");
    let mut payload = serde_json::json!({
        "model": model,
        "temperature": cfg.temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    });
    if json_mode {
        payload["response_format"] = serde_json::json!({"type": "json_object"});
    }
    let resp = client
        .post(&url)
        .bearer_auth(&cfg.api_key)
        .json(&payload)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("llm api error: {}", resp.status()));
    }
    let data: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
    data.get("choices")
        .and_then(|c| c.get(0))
        .and_then(|c| c.get("message"))
        .and_then(|m| m.get("content"))
        .and_then(|c| c.as_str())
        .map(|s| s.to_string())
        .ok_or_else(|| "llm response had no choices[0].message.content".to_string())
}

pub async fn analyze_paragraph_structured(
    cfg: &ProviderCfg,
    paragraph_id: &str,
    paragraph_text: &str,
    sentences_meta: &[(String, String)],
    glossary_context: &str,
) -> (Vec<SentenceAnalysis>, EngineProvenance) {
    if is_mock(cfg) || cfg.provider == "mock" {
        return (
            sentences_meta
                .iter()
                .map(|(id, orig)| heuristic_sentence_analysis(id, orig))
                .collect(),
            offline_demo(),
        );
    }

    let user_prompt = build_paragraph_analysis_prompt(
        paragraph_id,
        paragraph_text,
        sentences_meta,
        glossary_context,
    );
    let expected: Vec<String> = sentences_meta.iter().map(|(id, _)| id.clone()).collect();

    let fallback = |reason: String| -> (Vec<SentenceAnalysis>, EngineProvenance) {
        (
            sentences_meta
                .iter()
                .map(|(id, orig)| heuristic_sentence_analysis(id, orig))
                .collect(),
            EngineProvenance {
                engine: "offline-fallback",
                fallback_reason: Some(reason),
            },
        )
    };

    match call_llm(cfg, SYSTEM_PROMPT, &user_prompt, true).await {
        Ok(raw) => match serde_json::from_str::<serde_json::Value>(&strip_json_fence(&raw)) {
            Ok(parsed) => {
                let sents = parse_llm_sentences(&parsed, &expected);
                if sents.is_empty() {
                    eprintln!("LLM returned no matching sentence ids; using offline engine.");
                    fallback("模型返回的句子 id 与请求不一致".to_string())
                } else {
                    (
                        sents,
                        EngineProvenance {
                            engine: "llm",
                            fallback_reason: None,
                        },
                    )
                }
            }
            Err(e) => {
                eprintln!("LLM JSON parse failed: {e}. Falling back to offline engine.");
                fallback(format!("模型输出不是合法 JSON: {e}"))
            }
        },
        Err(e) => {
            eprintln!("LLM call failed: {e}. Falling back to offline engine.");
            fallback(e)
        }
    }
}

pub async fn analyze_single_sentence_deep(
    cfg: &ProviderCfg,
    sentence_id: &str,
    target_sentence: &str,
    paragraph_context: &str,
    glossary_context: &str,
) -> (SentenceAnalysis, EngineProvenance) {
    if is_mock(cfg) || cfg.provider == "mock" {
        return (
            heuristic_sentence_analysis(sentence_id, target_sentence),
            offline_demo(),
        );
    }

    let user_prompt = build_single_sentence_deep_prompt(
        sentence_id,
        target_sentence,
        paragraph_context,
        glossary_context,
    );

    let fallback = |reason: String| -> (SentenceAnalysis, EngineProvenance) {
        (
            heuristic_sentence_analysis(sentence_id, target_sentence),
            EngineProvenance {
                engine: "offline-fallback",
                fallback_reason: Some(reason),
            },
        )
    };

    match call_llm(cfg, SYSTEM_PROMPT, &user_prompt, true).await {
        Ok(raw) => match serde_json::from_str::<serde_json::Value>(&strip_json_fence(&raw)) {
            Ok(parsed) => {
                let expected = vec![sentence_id.to_string()];
                match parse_llm_sentences(&parsed, &expected).into_iter().next() {
                    Some(a) => (
                        a,
                        EngineProvenance {
                            engine: "llm",
                            fallback_reason: None,
                        },
                    ),
                    None => {
                        eprintln!("LLM returned no matching sentence; using offline engine.");
                        fallback("模型返回的句子 id 与请求不一致".to_string())
                    }
                }
            }
            Err(e) => {
                eprintln!("Single sentence JSON parse failed: {e}");
                fallback(format!("模型输出不是合法 JSON: {e}"))
            }
        },
        Err(e) => {
            eprintln!("Single sentence LLM error: {e}");
            fallback(e)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn block_on<F: std::future::Future>(f: F) -> F::Output {
        tauri::async_runtime::block_on(f)
    }

    fn mock_cfg() -> ProviderCfg {
        ProviderCfg {
            provider: "mock".into(),
            api_key: String::new(),
            base_url: String::new(),
            model_name: "gpt-4o-mini".into(),
            temperature: 0.2,
            mock_mode: true,
        }
    }

    #[test]
    fn test_is_mock_rules() {
        let mut c = mock_cfg();
        assert!(is_mock(&c));
        c.mock_mode = false;
        assert!(is_mock(&c), "empty api_key still mock");
        c.api_key = "sk-x".into();
        assert!(!is_mock(&c));
        c.mock_mode = true;
        assert!(is_mock(&c), "mock_mode wins");
    }

    #[test]
    fn test_curated_ishmael_exact_match() {
        let cfg = mock_cfg();
        let (out, prov) = block_on(analyze_paragraph_structured(
            &cfg,
            "p1",
            "Call me Ishmael.",
            &[("p1_s1".into(), "Call me Ishmael.".into())],
            "",
        ));
        assert_eq!(prov.engine, "offline-demo");
        assert_eq!(out.len(), 1);
        let a = &out[0];
        assert_eq!(a.sentence_id, "p1_s1");
        assert_eq!(a.translation, "叫我以实玛利吧。");
        let comps = &a.grammar_analysis.as_ref().unwrap().components;
        assert!(comps.iter().any(|c| c.role.contains("谓语")));
        assert!(comps.iter().any(|c| c.role.contains("宾语")));
        assert_eq!(a.vocabulary_and_phrases[0].token, "Ishmael");
        assert!(!a.vocabulary_and_phrases[0].literal_meaning.is_empty());
        assert!(!a.idioms_and_conventions[0].expression.is_empty());
    }

    #[test]
    fn test_heuristic_fallback_svo() {
        let cfg = mock_cfg();
        let orig = "The old man carefully navigated the treacherous strait near the harbor.";
        let (out, prov) = block_on(analyze_paragraph_structured(
            &cfg,
            "p2",
            orig,
            &[("p2_s1".into(), orig.into())],
            "",
        ));
        assert_eq!(prov.engine, "offline-demo");
        let a = &out[0];
        assert_eq!(a.translation, format!("【译文】{orig}"));
        assert!(!a.grammar_analysis.as_ref().unwrap().components.is_empty());
        assert!(a
            .vocabulary_and_phrases
            .iter()
            .any(|v| v.token == "Treacherous" || v.token == "Navigated" || v.token == "Harbor"));
    }

    #[test]
    fn test_unreachable_endpoint_falls_back_to_heuristic() {
        // Review Focus #3: unreachable endpoint + non-mock cfg -> heuristic result.
        let cfg = ProviderCfg {
            provider: "custom".into(),
            api_key: "sk-test".into(),
            base_url: "http://127.0.0.1:1".into(),
            model_name: "test".into(),
            temperature: 0.2,
            mock_mode: false,
        };
        let (out, prov) = block_on(analyze_paragraph_structured(
            &cfg,
            "p3",
            "A simple sentence.",
            &[("p3_s1".into(), "A simple sentence.".into())],
            "",
        ));
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].sentence_id, "p3_s1");
        assert!(out[0]
            .translation
            .starts_with(PLACEHOLDER_TRANSLATION_PREFIX));
        // The fallback must not be silent: the caller surfaces the reason so
        // "finished" and "the call failed" are distinguishable in the UI.
        assert_eq!(prov.engine, "offline-fallback");
        assert!(
            prov.fallback_reason
                .as_deref()
                .is_some_and(|r| !r.is_empty()),
            "a failed live call must carry its error out"
        );
    }

    #[test]
    fn test_placeholder_translation_recognition() {
        assert!(is_placeholder_translation("【译文】Call me Ishmael."));
        assert!(is_placeholder_translation("  【译文】X"));
        assert!(!is_placeholder_translation("叫我以实玛利吧。"));
        assert!(!is_placeholder_translation(""));
        // A real translation quoting the marker must not be misread as one.
        assert!(!is_placeholder_translation(
            "原文中出现了「【译文】」的说法，翻译如下"
        ));
    }

    #[test]
    fn test_deep_analysis_detection() {
        // A full analysis counts, on any of the three content fields.
        let full = serde_json::json!({
            "sentence_id": "s1", "translation": "甲",
            "grammar_analysis": {"structure": "复合句", "components": [{"element": "I", "role": "S"}]},
            "vocabulary_and_phrases": [], "idioms_and_conventions": []
        });
        assert!(is_deep_analysis(&full));

        let vocab_only = serde_json::json!({
            "sentence_id": "s1", "translation": "甲",
            "vocabulary_and_phrases": [{"token": "x", "literal_meaning": "y"}]
        });
        assert!(is_deep_analysis(&vocab_only));

        let idiom_only = serde_json::json!({
            "sentence_id": "s1", "translation": "甲",
            "idioms_and_conventions": [{"expression": "x", "usage": "y"}]
        });
        assert!(is_deep_analysis(&idiom_only));

        // Translation-only — what a model actually returns when the prompt
        // never named the schema fields — is NOT deep, or the inspector shows
        // nothing but the translation forever.
        let shallow = serde_json::json!({
            "sentence_id": "s1", "translation": "甲",
            "vocabulary_and_phrases": [], "idioms_and_conventions": []
        });
        assert!(!is_deep_analysis(&shallow));

        // An empty grammar object is a model giving up, not an analysis.
        let empty_grammar = serde_json::json!({
            "sentence_id": "s1", "translation": "甲",
            "grammar_analysis": {"structure": "", "components": []}
        });
        assert!(!is_deep_analysis(&empty_grammar));

        assert!(!is_deep_analysis(&serde_json::json!({})));
    }

    #[test]
    fn test_llm_response_with_wrong_sentence_id_is_dropped() {
        // Review Focus #5: a hallucinated id must not be written to the db.
        let raw = r#"{"sentences":[{"sentence_id":"p9_s99","original":"A simple sentence.","translation":"幻觉译文","overall_tone":"x","grammar_analysis":{"structure":"陈述句","components":[]},"vocabulary_and_phrases":[],"idioms_and_conventions":[]}]}"#;
        let parsed: serde_json::Value = serde_json::from_str(raw).unwrap();
        let sents = parse_llm_sentences(&parsed, &["p3_s1".to_string()]);
        assert!(sents.is_empty(), "hallucinated id must not map to p3_s1");
    }

    #[test]
    fn test_parse_llm_keeps_matching_ids() {
        let raw = r#"{"sentences":[
            {"sentence_id":"p3_s1","original":"A.","translation":"甲"},
            {"sentence_id":"p9_s99","original":"B.","translation":"乙"}
        ]}"#;
        let parsed: serde_json::Value = serde_json::from_str(raw).unwrap();
        let sents = parse_llm_sentences(&parsed, &["p3_s1".to_string()]);
        assert_eq!(sents.len(), 1);
        assert_eq!(sents[0].translation, "甲");
    }

    #[test]
    fn test_parse_llm_tolerates_missing_optional_fields() {
        let raw = r#"{"sentences":[{"sentence_id":"p3_s1","translation":"甲"}]}"#;
        let parsed: serde_json::Value = serde_json::from_str(raw).unwrap();
        let sents = parse_llm_sentences(&parsed, &["p3_s1".to_string()]);
        assert_eq!(sents.len(), 1);
        assert!(sents[0].overall_tone.is_none());
        assert!(sents[0].grammar_analysis.is_none());
        assert!(sents[0].vocabulary_and_phrases.is_empty());
    }

    #[test]
    fn test_claude_uses_its_own_endpoint_shape() {
        let cfg = ProviderCfg {
            provider: "claude".into(),
            api_key: "k".into(),
            base_url: "".into(),
            model_name: "".into(),
            temperature: 0.2,
            mock_mode: false,
        };
        let (base, model, is_claude) = resolve_endpoint(&cfg);
        assert!(is_claude);
        assert_eq!(base, "https://api.anthropic.com/v1");
        assert_eq!(model, "claude-3-5-sonnet");
    }

    #[test]
    fn test_openai_compatible_default_endpoint() {
        let cfg = ProviderCfg {
            provider: "openai".into(),
            api_key: "k".into(),
            base_url: "".into(),
            model_name: "".into(),
            temperature: 0.2,
            mock_mode: false,
        };
        let (base, model, is_claude) = resolve_endpoint(&cfg);
        assert!(!is_claude);
        assert_eq!(base, "https://api.openai.com/v1");
        assert_eq!(model, "gpt-4o-mini");
    }

    #[test]
    fn test_minimax_uses_the_anthropic_surface() {
        // MiniMax exposes an Anthropic-compatible API, but the messages path is
        // /anthropic/v1/messages — /anthropic/messages 404s. It must therefore
        // speak the Anthropic wire format (x-api-key + content[] reply) and
        // default to a base that already carries the version segment, because
        // call_llm appends "/messages" verbatim.
        let cfg = ProviderCfg {
            provider: "minimax".into(),
            api_key: "k".into(),
            base_url: "".into(),
            model_name: "".into(),
            temperature: 0.2,
            mock_mode: false,
        };
        let (base, model, is_anthropic) = resolve_endpoint(&cfg);
        assert!(
            is_anthropic,
            "minimax must not fall back to the OpenAI wire format"
        );
        assert_eq!(base, "https://api.minimaxi.com/anthropic/v1");
        assert_eq!(
            format!("{base}/messages"),
            "https://api.minimaxi.com/anthropic/v1/messages"
        );
        // The model box is filled from MiniMax's own /v1/models list; the
        // OpenRouter-style "minimax/" prefix 404s here.
        assert_eq!(model, "MiniMax-M3");
        assert!(
            !is_mock(&cfg),
            "a key without mock mode must not be treated as offline"
        );
    }

    #[test]
    fn test_strip_json_fence() {
        assert_eq!(strip_json_fence("```json\n{\"a\":1}\n```"), "{\"a\":1}");
        assert_eq!(strip_json_fence("{\"a\":1}"), "{\"a\":1}");
    }

    #[test]
    fn test_a_custom_base_url_keeps_the_providers_own_default_model() {
        // The default-model table used to live only in the blank-base-URL
        // branch, so routing a provider through a proxy with a blank model box
        // sent an OpenAI model name to that host. Same failure as the one above,
        // one branch over.
        for (provider, want_model) in [
            ("claude", "claude-3-5-sonnet"),
            ("minimax", "MiniMax-M3"),
            ("deepseek", "deepseek-chat"),
            ("gemini", "gemini-1.5-flash"),
            ("openai", "gpt-4o-mini"),
        ] {
            let cfg = ProviderCfg {
                provider: provider.into(),
                api_key: "k".into(),
                base_url: "https://proxy.internal/v1/".into(),
                model_name: "".into(),
                temperature: 0.2,
                mock_mode: false,
            };
            let (base, model, is_anthropic) = resolve_endpoint(&cfg);
            assert_eq!(base, "https://proxy.internal/v1", "trailing slash trimmed");
            assert_eq!(model, want_model, "{provider} default model over a proxy");
            assert_eq!(
                is_anthropic,
                matches!(provider, "claude" | "minimax"),
                "{provider} protocol"
            );
        }
    }

    #[test]
    fn test_an_explicit_model_still_wins_over_a_custom_base_url() {
        let cfg = ProviderCfg {
            provider: "claude".into(),
            api_key: "k".into(),
            base_url: "https://proxy.internal/v1".into(),
            model_name: "  claude-3-7-sonnet  ".into(),
            temperature: 0.2,
            mock_mode: false,
        };
        let (_, model, _) = resolve_endpoint(&cfg);
        assert_eq!(model, "claude-3-7-sonnet", "surrounding space is trimmed");
    }
}
