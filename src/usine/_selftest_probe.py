"""在教学页副本里追加一段自测脚本：load 期自动遍历 14 个语种调用 show()，
把结果写进页面顶部。用来在无法注入交互事件的浏览器里验证 tab 切换逻辑。
只生成临时验证文件，不改动 build_lesson.py 与交付物。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(r"D:\coding\personal\une_usine_avec_des_machines_rugissantes")
src = (ROOT / "build" / "lesson" / "index.html").read_text(encoding="utf-8")

PROBE = r"""
<script>
(function(){
  var out = [];
  function chk(lc){
    var before = document.querySelectorAll('.tab.is-on').length;
    show(lc);
    var onTabs = [].slice.call(document.querySelectorAll('.tab.is-on'))
                     .map(function(t){ return t.dataset.lc; });
    var shown  = [].slice.call(document.querySelectorAll('.lc:not([hidden])'))
                     .map(function(s){ return s.dataset.lc; });
    // RTL 语种的 h3 里会追加 <em>RTL</em> 徽标，比较前先剥掉
    var meta   = ((document.querySelector('#rmeta h3')||{}).textContent || '').replace(/\s*RTL\s*$/, '');
    var vsrc   = (document.getElementById('pv').getAttribute('src')||'');
    var d      = DATA[lc] || {};
    var want   = d.src || '';
    return { lc: lc, onTabs: onTabs, shown: shown, meta: meta.trim(),
             vsrc: vsrc, want: want, before: before };
  }
  var fails = [];
  ORDER.forEach(function(lc){
    var r = chk(lc);
    var problems = [];
    if (r.onTabs.length !== 1 || r.onTabs[0] !== lc) { problems.push('tab高亮=' + JSON.stringify(r.onTabs)); }
    if (r.shown.length !== 1 || r.shown[0] !== lc)   { problems.push('可见段=' + JSON.stringify(r.shown)); }
    if (r.meta !== (DATA[lc] && DATA[lc].label))    { problems.push('rmeta=' + r.meta); }
    if (r.vsrc !== r.want)                           { problems.push('video=' + r.vsrc + ' 期望=' + r.want); }
    if (problems.length) { fails.push(lc + ' :: ' + problems.join(' | ')); }
  });
  // 再验证回到第一个语种
  var back = chk(ORDER[0]);
  if (back.shown.length !== 1 || back.shown[0] !== ORDER[0]) { fails.push('回首位失败 :: ' + JSON.stringify(back.shown)); }

  var box = document.createElement('div');
  box.id = 'selftest';
  box.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;background:#fff;color:#000;'
                    + 'font:14px/1.6 monospace;padding:10px;max-width:100%;white-space:pre-wrap;border:3px solid #c00';
  box.textContent = fails.length
    ? ('SELFTEST FAIL (' + fails.length + '/' + ORDER.length + ')\n' + fails.join('\n'))
    : ('SELFTEST PASS: ' + ORDER.length + '/' + ORDER.length
       + ' 语种切换全部正确\n'
       + 'ORDER=' + ORDER.join(',') + '\n'
       + '末态 tab=' + JSON.stringify(chk(ORDER[ORDER.length-1]).onTabs)
       + ' 可见段=' + JSON.stringify(back.shown) + ' meta=' + back.meta);
  document.body.appendChild(box);
})();
</script>
"""

assert "<script" in src
out = src.replace("</body>", PROBE + "</body>", 1)
assert out != src
(ROOT / "build" / "lesson" / "_selftest.html").write_text(out, encoding="utf-8")
print("wrote _selftest.html", len(out), "chars;  追加位置校验:", out.count("SELFTEST"))
