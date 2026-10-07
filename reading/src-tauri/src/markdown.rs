// Markdown / plain-text cleaning, used before sentence splitting.
use regex::Regex;

/// Strips inline and block markup while preserving blank-line paragraph
/// structure, so the downstream splitter still sees paragraph breaks.
pub fn strip_markdown(input: &str) -> String {
    let normalized = input.replace("\r\n", "\n").replace('\r', "\n");

    // 1. Drop fenced code blocks wholesale — novels have no use for them and
    //    their contents would otherwise pollute the prose.
    let fenced = Regex::new(r"(?s)```[^\n]*\n.*?```").unwrap();
    let no_fences = fenced.replace_all(&normalized, "").to_string();

    let hdr = Regex::new(r"^\s{0,3}#{1,6}\s+").unwrap();
    let bq = Regex::new(r"^\s{0,3}>\s?").unwrap();
    let img = Regex::new(r"!\[([^\]]*)\]\([^)]*\)").unwrap();
    let link = Regex::new(r"\[([^\]]+)\]\([^)]*\)").unwrap();

    let mut out_lines: Vec<String> = Vec::new();
    for line in no_fences.lines() {
        let mut l = line.to_string();
        l = hdr.replace(&l, "").to_string(); // 2. header hashes
        l = bq.replace(&l, "").to_string(); // 3. blockquote marker
        l = img.replace_all(&l, "${1}").to_string(); // 4. images, before links
        l = link.replace_all(&l, "${1}").to_string(); // 5. links
        out_lines.push(l);
    }
    let joined = out_lines.join("\n");

    // 6. Inline emphasis. The underscore-italic rule avoids lookbehind so the
    //    plain `regex` crate suffices (Rust regex has no lookaround at all).
    let bold1 = Regex::new(r"\*\*([^*]+)\*\*").unwrap();
    let bold2 = Regex::new(r"__([^_]+)__").unwrap();
    let ital1 = Regex::new(r"\*([^*\n]+)\*").unwrap();
    let ital2 = Regex::new(r"(^|[^A-Za-z0-9_])_([^_\n]+)_([^A-Za-z0-9_]|$)").unwrap();
    let code = Regex::new(r"`([^`\n]+)`").unwrap();

    let mut out = joined;
    for re in [bold1, bold2, ital1] {
        out = re.replace_all(&out, "${1}").to_string();
    }
    out = ital2.replace_all(&out, "${1}${2}${3}").to_string();
    out = code.replace_all(&out, "${1}").to_string();

    // 7. Collapse runs of 3+ newlines back to a single paragraph break.
    let multi = Regex::new(r"\n{3,}").unwrap();
    multi.replace_all(&out, "\n\n").trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_strips_headers_emphasis_links() {
        let md = "# Chapter 1\n\nIt was a **dark** and *stormy* night — see [the wiki](https://example.com) for more.\n\n> A quote line\n\n```\ncode fence\n```\n\nPlain tail.";
        let out = strip_markdown(md);
        assert!(out.contains("Chapter 1"));
        assert!(out.contains("It was a dark and stormy night — see the wiki for more."));
        assert!(!out.contains("**"));
        assert!(!out.contains("](http"));
        assert!(!out.contains("```"));
        assert!(!out.contains("> A quote"));
        let blocks: Vec<&str> = out.split("\n\n").collect();
        assert!(blocks.len() >= 3, "got {blocks:?}");
        assert!(out.contains("Plain tail."));
    }

    #[test]
    fn test_plain_text_passthrough() {
        let txt = "Call me Ishmael.\n\nSome years ago.";
        assert_eq!(strip_markdown(txt), txt);
    }

    #[test]
    fn test_inline_code_and_images() {
        let out = strip_markdown("Use `foo.py` here.\n\n![portrait](img.png) Captain Ahab.");
        assert!(out.contains("Use foo.py here."));
        assert!(out.contains("portrait Captain Ahab."));
    }
}
