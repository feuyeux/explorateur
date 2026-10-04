"""P1-4 验收①：重构前后 FONT_CSS / FLAG / langLabel 取值必须逐字节相同。

重构把三张字面量表换成了 languages/<locale>/manifest.json 派生。判据不是「渲出来像」，
是「值一模一样」——这是能在重渲之前就判死的便宜检查（渲染一卡要几分钟）。
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 旧值（从重构前的 intro_cards.py 原样抄来，作为「重构前的事实」快照）
OLD_FONT = {
    "zh-CN": "'Microsoft YaHei', sans-serif", "zh-HK": "'Microsoft YaHei', sans-serif",
    "en-US": "'Segoe UI', Arial, sans-serif", "fr-FR": "'Segoe UI', Arial, sans-serif",
    "de-DE": "'Segoe UI', Arial, sans-serif", "es-ES": "'Segoe UI', Arial, sans-serif",
    "it-IT": "'Segoe UI', Arial, sans-serif", "ru-RU": "'Segoe UI', Arial, sans-serif",
    "el-GR": "'Segoe UI', Arial, sans-serif",
    "ja-JP": "'Yu Gothic UI', 'Meiryo', sans-serif", "ko-KR": "'Malgun Gothic', sans-serif",
    "hi-IN": "'Nirmala UI', sans-serif", "ar-SA": "'Segoe UI', 'Tahoma', sans-serif",
    "he-IL": "'Segoe UI', Arial, sans-serif",
}
OLD_FLAG = {
    "zh-CN": "\U0001F1E8\U0001F1F3", "en-US": "\U0001F1FA\U0001F1F8",
    "fr-FR": "\U0001F1EB\U0001F1F7", "de-DE": "\U0001F1E9\U0001F1EA",
    "es-ES": "\U0001F1EA\U0001F1F8", "ru-RU": "\U0001F1F7\U0001F1FA",
    "el-GR": "\U0001F1EC\U0001F1F7", "ar-SA": "\U0001F1F8\U0001F1E6",
    "hi-IN": "\U0001F1EE\U0001F1F3", "ja-JP": "\U0001F1EF\U0001F1F5",
    "ko-KR": "\U0001F1F0\U0001F1F7", "it-IT": "\U0001F1EE\U0001F1F9",
    "he-IL": "\U0001F1EE\U0001F1F1", "zh-HK": "\U0001F1ED\U0001F1F0",
}
# langLabel 取自 git HEAD 版的 personas.json（重构时被摘掉）
OLD_LABEL = {
    "zh-CN": "汉语", "zh-HK": "粤语", "en-US": "英语", "fr-FR": "法语",
    "de-DE": "德语", "es-ES": "西班牙语", "it-IT": "意大利语", "ru-RU": "俄语",
    "el-GR": "希腊语", "ja-JP": "日语", "ko-KR": "韩语", "hi-IN": "印地语",
    "ar-SA": "阿拉伯语", "he-IL": "希伯来语",
}

from usine.intro_cards import FONT_CSS, FLAG          # noqa: E402
from usine.data import lang_label, personas          # noqa: E402

fails = 0


def cmp(name, old, new):
    global fails
    same = old == new
    print(f"  [{'PASS' if same else 'FAIL'}] {name}：{len(old)} 个语种逐值一致")
    if not same:
        for k in sorted(set(old) | set(new)):
            if old.get(k) != new.get(k):
                print(f"        {k}: 旧 {old.get(k)!r} → 新 {new.get(k)!r}")
    fails += not same


cmp("FONT_CSS 字体栈", OLD_FONT, FONT_CSS)
cmp("FLAG 国旗", OLD_FLAG, FLAG)
cmp("langLabel 语种文字", OLD_LABEL,
    {loc: lang_label(loc) for loc in OLD_LABEL})

# 所有人设的 locale 都得能取到语种名——原来靠 langLabel 挂在人设上，取不到会 KeyError
missing = sorted({p["locale"] for p in personas().values()} - set(OLD_LABEL))
print(f"  [{'PASS' if not missing else 'FAIL'}] 28 个人设的 locale 全部有语种目录"
      + (f"（缺 {missing}）" if missing else ""))
fails += bool(missing)

# 反向验证：删掉一个目录必须炸，不能静默回落成裸 locale
import shutil                                            # noqa: E402
import usine.data as D                                   # noqa: E402

victim = ROOT / "languages" / "it-IT"
bak = ROOT / "languages" / "_it-IT.bak"
shutil.move(str(victim), str(bak))
try:
    D.reload_all()
    try:
        lang_label("it-IT")
        caught = False
    except KeyError as exc:
        caught = "无此语种目录" in str(exc)
finally:
    shutil.move(str(bak), str(victim))
    D.reload_all()
print(f"  [{'PASS' if caught else 'FAIL'}] 反向验证：删掉 languages/it-IT 后 lang_label 报错并说清怎么补")
fails += not caught

print(f"\n{'OK' if not fails else 'FAIL'}：P1-4 取值等价性 {4 - fails}/4 项")
sys.exit(1 if fails else 0)
