#!/usr/bin/env python3
"""Audit: every char rendered by an embedded-first font family must exist in its
fonts.json subset text list — prevents tofu blocks after copy edits.

Usage: audit_charset.py [poster_src.html] [fonts.json]
Depends on fonts.json entries carrying "classes" (CSS classes that render with
that family, e.g. "f-deva"); a family whose classes include the translit row's
class covers the Latin line too. Any class that sets its own font-family in CSS
(.annot, .jyut, .tagline …) belongs in that list — the audit sees families only
through it.

Family attribution is a STACK mirroring CSS font-family inheritance:

- an element whose class maps to a family pushes that family;
- any other element (classless, or a class not in fonts.json) INHERITS the
  enclosing family. The per-letter coloring wrappers (.stack/.lay/.top/.t/.c/
  .sp, Korean .ksyl patches, .zi/.hz/.annot columns) are all class-bearing
  WITHOUT a mapped family — a flat "reset on every class-bearing tag" blinded
  the audit exactly there: whole overlay words (a01 धन्यवाद / a02 माफ़ कीजिए)
  escaped the tofu gate until the stack fix;
- a closing tag pops.

Hand-authored poster sources close every tag explicitly; implicit-close HTML
(p/li/td) could only desync toward OVER-attribution, which fails loudly. Void
elements and self-closed tags never push (no closing tag would ever pop them).

Second gate — patch-rule binding (A-03): `.ksyl` patch rules are named `k%04X`
from `ord(glyph)` by measure_korean.py, so a rule pasted under the WRONG name
is silently worn by the wrong glyph, and NOTHING else catches it: measure_korean
verifies a rule against its OWN labels, and the subset audit only checks
page chars ⊆ fonts.json. Shipped once as A-03 (class `.kB9CC` = 만's geometry on
the 많 glyph). Asserts, per patched syllable: class codepoint == glyph
codepoint, the rule exists, and no rule is orphaned.
"""
import html, json, pathlib, re, sys

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}

PATCH_CLASS = re.compile(r"^k([0-9A-Fa-f]{4})$")


def check(src_path, spec_path):
    """Return (missing, counts): missing = [(family, char, hex(ord))] for every
    char attributed to a family but absent from its subset text; counts =
    {family: n_distinct_chars_checked}."""
    spec = json.loads(pathlib.Path(spec_path).read_text())
    fams = {e["family"]: e["text"] for e in spec}
    class2fam = {}
    for e in spec:
        for c in e.get("classes", []):
            class2fam[c] = e["family"]

    src = pathlib.Path(src_path).read_text()
    # strip comments and style/script blocks; walk the body only
    body = src.split("<body>", 1)[1] if "<body>" in src else src
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"<script>.*?</script>", "", body, flags=re.S)
    body = re.sub(r"<style>.*?</style>", "", body, flags=re.S)

    # tokenise tags, tracking the family stack per the module docstring
    stack = []          # innermost family last; None = inside no family
    use = {}            # family -> set of chars
    for m in re.finditer(r"<(/?)(\w+)([^>]*)>|([^<]+)", body):
        closing, name, attrs = m.group(1), m.group(2), m.group(3) or ""
        if closing:
            if stack:
                stack.pop()
            continue
        if name:
            if name.lower() in VOID or attrs.rstrip().endswith("/"):
                continue        # never gets a closing tag
            fam = stack[-1] if stack else None      # inherit by default
            cm = re.search(r'class="([^"]*)"', attrs)
            if cm:
                for c in cm.group(1).split():
                    if c in class2fam:
                        fam = class2fam[c]
                        break
            stack.append(fam)
        else:
            text = html.unescape(m.group(4) or "")
            # skip script bodies heuristically
            if "function" in text or "const " in text or "document." in text:
                continue
            if stack and stack[-1]:
                use.setdefault(stack[-1], set()).update(
                    ch for ch in text if not ch.isspace())

    missing = []
    for fam, chars in sorted(use.items()):
        for ch in sorted(chars):
            if ch not in fams[fam] and ch != " ":
                missing.append((fam, ch, hex(ord(ch))))
    return missing, {f: len(c) for f, c in use.items()}


def check_patch_bindings(src_path):
    """Return a list of patch-rule binding problems (see module docstring)."""
    src = pathlib.Path(src_path).read_text(encoding="utf-8")
    defined = set()
    for sty in re.findall(r"<style[^>]*>(.*?)</style>", src, re.S):
        sty = re.sub(r"/\*.*?\*/", "", sty, flags=re.S)   # CSS comments are prose,
        defined |= {m.group(1).upper() for m in        # not rules
                    re.finditer(r"\.k([0-9A-Fa-f]{4})\s*[,{]", sty)}

    body = src.split("<body>", 1)[1] if "<body>" in src else src
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"<script>.*?</script>", "", body, flags=re.S)
    body = re.sub(r"<style>.*?</style>", "", body, flags=re.S)

    problems, used, open_cls = [], set(), []
    for m in re.finditer(r"<(/?)([\w-]+)([^>]*)>|([^<]+)", body):
        closing, name, attrs, text = m.group(1), m.group(2), m.group(3) or "", m.group(4)
        if closing:
            if open_cls:
                open_cls.pop()
            continue
        if name:
            if name.lower() in VOID or attrs.rstrip().endswith("/"):
                continue                      # never gets a closing tag
            cm = re.search(r'class="([^"]*)"', attrs)
            pcs = [c for c in (cm.group(1).split() if cm else []) if PATCH_CLASS.match(c)]
            open_cls.append(pcs)
            continue
        glyphs = html.unescape(text or "").strip()
        if not open_cls or not open_cls[-1] or not glyphs:
            continue                          # outside a patched span / plain space
        for cls in open_cls[-1]:
            want = int(cls[1:], 16)
            used.add("%04X" % want)
            if len(glyphs) != 1:
                problems.append(f"{cls}: expected ONE glyph, found {len(glyphs)}: {glyphs!r}")
            elif ord(glyphs) != want:
                problems.append(f"{cls}: glyph {glyphs!r} is U+{ord(glyphs):04X}, "
                                f"not U+{want:04X} — wearing another glyph's patches")
            if cls[1:].upper() not in defined:
                problems.append(f"{cls}: no CSS rule .{cls} defined in the poster")
    for cp in sorted(defined - used):
        problems.append(f"orphan rule .k{cp} is defined but worn by no glyph")
    return problems


def main():
    src_path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "poster_src.html")
    spec_path = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "fonts.json")
    missing, counts = check(src_path, spec_path)
    # Both gates report every finding before exiting: a subset failure must not
    # mask a patch-binding failure (A-03 shipped with BOTH live at once — the
    # glyph wore another syllable's rule AND the subset no longer covered it).
    patch = check_patch_bindings(src_path)
    if missing:
        print("MISSING from subsets:")
        for fam, ch, code in missing:
            print(f"  {fam}: {ch!r} {code}")
    if patch:
        print("PATCH-RULE BINDING PROBLEMS:")
        for p in patch:
            print(f"  {p}")
    if missing or patch:
        sys.exit(1)
    print("charset audit: all chars covered")
    for fam, n in sorted(counts.items()):
        print(f"  {fam}: {n} distinct chars checked")
    print("  patch rules: every .ksyl glyph wears the rule of its own codepoint")


if __name__ == "__main__":
    main()
