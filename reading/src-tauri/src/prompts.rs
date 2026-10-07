// Prompt templates, ported verbatim from
// backend/app/services/prompt_templates.py.

pub const SYSTEM_PROMPT: &str = r#"你是一位世界级的外语文学原著精读导师、资深翻译家与语言学教授。
你的核心任务是将外语原著文本进行段落级上下文理解，并对其包含的每一个句子进行透彻、严谨、优雅的结构化拆解与解析。

解析准则与核心原则：
1. 【段落级宏观语境】：切勿将句子孤立看待。必须结合所在段落前后的叙事逻辑、代词指代、叙述者心理与文体基调进行解读。
2. 【严格多义词语境锁定】：严禁罗列词典中泛泛的全部义项！重点生词的释义必须严格锁定在当前句子的语境含义上。
3. 【全书术语一致性】：严格遵守提供的专有名词与术语表（Glossary），确保人名、地名、核心概念全书完全统一。
4. 【句法主干结构化切片】：将句子切分为清晰的主干与修饰成分（如 主语S、谓语V、宾语O、表语P、宾补OC、状语Adv、定语Attr 等），便于前端可视化渲染。
5. 【文化典故与约定俗成深度挖掘】：对圣经典故、古典神话、历史事件、特定时代的隐喻或俚语必须提供画龙点睛的背景解读。
6. 【纯粹 JSON 输出】：必须严格按照指定的 JSON Schema 返回结果，严禁输出任何多余的开场白、Markdown 标记或总结语。"#;

/// The exact JSON shape `llm::SentenceAnalysis` deserializes from.
///
/// The prompts used to describe the analysis in prose and never name the
/// fields, so every model invented its own key names; serde silently dropped
/// the unknown keys, the optional analysis fields defaulted to empty, and
/// every real response came back "translation only". The schema below is the
/// contract — the field names are what the deserializer actually reads.
const SENTENCE_JSON_SCHEMA: &str = r#"{
  "sentence_id": "原样返回给定的 ID，不得改动",
  "original": "原句原文",
  "translation": "精准、流畅、符合文学语感的中文译文",
  "overall_tone": "用一句话概括该句的叙事基调或情感色彩",
  "grammar_analysis": {
    "structure": "句型结构概括（如：复合长句 / 祈使句 / 主从复合句）",
    "components": [
      {"element": "句中原文片段", "role": "成分角色，如：主语 (S) / 谓语 (V) / 宾语 (O) / 宾语补足语 (OC) / 状语 (Adv) / 定语 (Attr)"}
    ]
  },
  "vocabulary_and_phrases": [
    {"token": "重点词或短语（保留原词）", "pos": "词性（如：名词 / 动词 / 习语短语）", "literal_meaning": "严格锁定当前语境的释义，不是词典泛义", "cultural_background": "可选：典故、隐喻或时代背景，确无则省略此键"}
  ],
  "idioms_and_conventions": [
    {"expression": "习语 / 典故 / 固定搭配 / 修辞手法", "usage": "它在此句语境中的确切含义与修辞作用"}
  ]
}"#;

/// `sentences_meta` is a list of `(sentence_id, original)` pairs.
pub fn build_paragraph_analysis_prompt(
    paragraph_id: &str,
    paragraph_text: &str,
    sentences_meta: &[(String, String)],
    glossary_context: &str,
) -> String {
    let sents_formatted = sentences_meta
        .iter()
        .map(|(id, orig)| format!("- ID: {id} | 原文: {orig}"))
        .collect::<Vec<_>>()
        .join("\n");

    format!(
        r#"请对以下段落进行深入拆解与语法透视分析。

{glossary_context}

【段落整体内容 (Paragraph ID: {paragraph_id})】：
"""{paragraph_text}"""

【已预先断句的句子列表（请务必按此顺序和 ID 逐句输出严格的结构化解析）】：
{sents_formatted}

请输出严格符合以下约定的 JSON 对象，严禁输出任何多余的开场白、Markdown 代码围栏或总结语：

1. 根对象形如 {{"sentences": [ … ]}}，数组内每个元素对应一个句子对象，结构与字段名严格如下（字段名必须一字不差）：
{SENTENCE_JSON_SCHEMA}
2. 句子列表中的每一个句子都必须出现，按给出顺序排列，sentence_id 原样返回，严禁遗漏、增添或改动任何句子。
3. grammar_analysis、vocabulary_and_phrases、idioms_and_conventions 三个分析字段必须逐句认真给出；确无内容时，数组给 []，grammar_analysis 可整体省略。"#
    )
}

pub fn build_single_sentence_deep_prompt(
    sentence_id: &str,
    target_sentence: &str,
    paragraph_context: &str,
    glossary_context: &str,
) -> String {
    format!(
        r#"请对段落中的特定句子进行高深度的【语法透视镜】结构化拆解。

{glossary_context}

【所在完整段落语境】：
"""{paragraph_context}"""

【待深度解析的目标句子】：
- sentence_id: {sentence_id}
- original: """{target_sentence}"""

请严格输出根结构为 {{"sentences": [ … ]}} 的 JSON（数组内只包含该句的一个对象），对象结构与字段名严格如下（字段名必须一字不差）：

{SENTENCE_JSON_SCHEMA}

sentence_id 必须原样为 {sentence_id}。必须包含精准翻译、风格语调、句法成分切片、语境词汇释义及文化典故解析，严禁输出 JSON 以外的任何文字。"#
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_paragraph_prompt_contains_parts() {
        let p = build_paragraph_analysis_prompt(
            "p1",
            "Call me Ishmael.",
            &[("p1_s1".to_string(), "Call me Ishmael.".to_string())],
            "【全书统一专有名词与术语表（必须严格遵循一致译名）】：\n- Ishmael [主角]: 以实玛利",
        );
        assert!(p.contains("Paragraph ID: p1"));
        assert!(p.contains("- ID: p1_s1 | 原文: Call me Ishmael."));
        assert!(p.contains("以实玛利"));
        assert!(
            p.contains(r#""sentences""#),
            "must ask for a sentences array"
        );
    }

    #[test]
    fn test_single_sentence_prompt_contains_json_root_hint() {
        let p = build_single_sentence_deep_prompt(
            "p1_s1",
            "Call me Ishmael.",
            "Call me Ishmael. Some years ago--never mind how long precisely--",
            "glossary",
        );
        assert!(p.contains("- sentence_id: p1_s1"));
        assert!(
            p.contains(r#""sentences""#),
            "must ask for a sentences array"
        );
    }

    #[test]
    fn test_system_prompt_lists_six_rules() {
        for n in 1..=6 {
            assert!(
                SYSTEM_PROMPT.contains(&format!("{n}. 【")),
                "missing rule {n}"
            );
        }
    }

    /// The prompts must NAME the exact fields `SentenceAnalysis` reads.
    /// They used to describe the analysis only in prose; the model invented
    /// its own key names, serde dropped them, and every real response came
    /// back "translation only" with empty analysis sections.
    #[test]
    fn both_prompts_name_the_exact_schema_fields() {
        for field in [
            "sentence_id",
            "original",
            "translation",
            "overall_tone",
            "grammar_analysis",
            "structure",
            "components",
            "element",
            "role",
            "vocabulary_and_phrases",
            "literal_meaning",
            "cultural_background",
            "idioms_and_conventions",
            "expression",
            "usage",
        ] {
            assert!(
                SENTENCE_JSON_SCHEMA.contains(&format!("\"{field}\"")),
                "schema must name the field {field}"
            );
        }

        let para = build_paragraph_analysis_prompt(
            "p1",
            "Text.",
            &[("p1_s1".to_string(), "Text.".to_string())],
            "",
        );
        let deep = build_single_sentence_deep_prompt("p1_s1", "Text.", "Text.", "");
        for (name, prompt) in [("paragraph", &para), ("deep", &deep)] {
            for field in [
                "\"sentence_id\"",
                "\"translation\"",
                "\"grammar_analysis\"",
                "\"vocabulary_and_phrases\"",
                "\"idioms_and_conventions\"",
            ] {
                assert!(
                    prompt.contains(field),
                    "{name} prompt must name the schema field {field}"
                );
            }
        }
    }
}
