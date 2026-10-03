"""反向验证：新加的「文本契约」检查是否真能抓到修复前的三个缺陷。

把修复前的真实数据喂进 qa_scene 的检查逻辑里，要求全部被判 FAIL；
再喂修复后的数据，要求全部判 PASS。空转的检查（永远返回真）会被这里抓出来。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from usine.qa_scene import (  # noqa: E402
    ASCII_SEMICOLON, QMARK_BY_SCRIPT, script_of,
)

ROOT = Path(__file__).resolve().parents[1]
SCENE = json.loads((ROOT / "scene_colors.json").read_text(encoding="utf-8"))


def punct_bad(lines):
    """与 qa_scene 2a 同逻辑：返回违规行描述列表。"""
    out = []
    for ln in lines:
        t = (ln.get("text") or "").strip()
        if not t:
            continue
        if t[-1] == ASCII_SEMICOLON:
            out.append(f"#{ln['i']} 句末半角分号 U+003B")
        if ln.get("isQuestion"):
            want = QMARK_BY_SCRIPT.get(script_of(t), "?")
            if t[-1] != want:
                out.append(f"#{ln['i']} 问号 U+{ord(t[-1]):04X}≠U+{ord(want):04X}")
    return out


def level_bad(lines, marker):
    """与 qa_scene 2b 同逻辑。"""
    a_on = [str(l["i"]) for l in lines if l["speaker"] == "A" and marker in l["text"]]
    b_off = [str(l["i"]) for l in lines if l["speaker"] == "B" and marker not in l["text"]]
    return a_on, b_off


print("=" * 66)
print("反向验证：检查能否抓到修复前的缺陷")
print("=" * 66)
fails = 0

# ---- 1. el-GR：修复前 7 个疑问行用半角分号收尾 ----
# 注意：这里一律用 \u 转义写死码位。直接敲字面字符会被编辑器/工具链归一化，
# 「;」和「;」肉眼几乎一样，曾把两个码位静默合并成一个。
SEMI = chr(0x003B)      # 半角分号（修复前的错字）
QMARK = chr(0x037E)      # 希腊问号（修复后的正解）
old_el = [
    {"i": 1, "isQuestion": True, "text": f"Καλά. Πώς παίζεται{SEMI}"},
    {"i": 2, "isQuestion": True, "text": f'Όταν λέω "κόκκινο" — σε τι σκέφτεσαι{SEMI}'},
    {"i": 3, "isQuestion": False, "text": "Στο κόκκινο αυγό του Πάσχα."},
]
new_el = [{**d, "text": d["text"].replace(SEMI, QMARK)} for d in old_el]
b = punct_bad(old_el)
print(f"\n[1] el-GR 修复前 → {'FAIL(抓到) ✓' if b else 'PASS ✗ 没抓到'}")
for x in b:
    print(f"      {x}")
fails += 0 if b else 1
b2 = punct_bad(new_el)
print(f"    el-GR 修复后 → {'PASS ✓' if not b2 else 'FAIL ✗ ' + str(b2)}")
fails += 1 if b2 else 0

# ---- 2. ko-KR：修复前 B 全线해체（A=반말/서연=敬语体 的承诺未落地）----
old_ko = [
    {"i": 0, "speaker": "A", "text": "야, 서연아! 가기 전에 색깔 게임 하나만!"},
    {"i": 1, "speaker": "B", "text": "좋아. 어떻게 해?"},        # 해체，无 요
    {"i": 3, "speaker": "B", "text": "태극기가 떠올라."},         # 해체
    {"i": 4, "speaker": "B", "text": "파란색 하면?"},             # 해체
]
new_ko = [
    {"i": 0, "speaker": "A", "text": "야, 서연아! 색깔 게임 하나만!"},
    {"i": 1, "speaker": "B", "text": "좋아요. 어떻게 해요?"},      # 해요体
    {"i": 3, "speaker": "B", "text": "태극기가 떠올라요."},
    {"i": 4, "speaker": "B", "text": "파란색 하면요?"},
]
mk = SCENE["speechLevels"]["ko-KR"]["marker"]
a_on, b_off = level_bad(old_ko, mk)
ok = bool(b_off)
print(f"\n[2] ko-KR 修复前 → {'FAIL(抓到) ✓' if ok else 'PASS ✗ 没抓到'}")
print(f"      B 缺해요体标记的行：{b_off}")
fails += 0 if ok else 1
a_on2, b_off2 = level_bad(new_ko, mk)
ok2 = not a_on2 and not b_off2
print(f"    ko-KR 修复后 → {'PASS ✓' if ok2 else 'FAIL ✗'}")
fails += 0 if ok2 else 1

# ---- 3. 时长预算：修复前 he-IL/hi-IN/ar-SA 超限 ----
lo, hi = SCENE["durationBudget"]
old_dur = {"he-IL": 60.04, "hi-IN": 56.97, "ar-SA": 56.45}
print(f"\n[3] 时长预算 {lo:g}–{hi:g}s")
for lc, d in old_dur.items():
    caught = not (lo <= d <= hi)
    print(f"      修复前 {lc} {d}s → {'FAIL(抓到) ✓' if caught else 'PASS ✗ 没抓到'}")
    fails += 0 if caught else 1
    newd = json.loads(
        (ROOT / "build" / "scene" / "audio" / f"scene-colors_{lc}.timeline.json").read_text("utf-8")
    )["duration"]
    now_ok = lo <= newd <= hi
    print(f"      修复后 {lc} {newd}s → {'PASS ✓' if now_ok else 'FAIL ✗'}")
    fails += 0 if now_ok else 1

print("\n" + "=" * 66)
print("反向验证结果：" + ("全部按预期 ✓" if fails == 0 else f"{fails} 项未按预期 ✗"))
sys.exit(1 if fails else 0)
