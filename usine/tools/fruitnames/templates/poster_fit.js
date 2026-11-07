<script>
// per-cell auto-fit (fruit): 每格 4 行词，统一字号 = 4 行都装得下的最大字号。
// ⚠️ 首行注释「per-cell auto-fit」是 make-covers 的 BOOT 注入锚点，别改写——
// 改了封面变体类（.lc/.pt/.t34）静默加不上，封面按海报原尺寸渲染被裁
// （ep01 实测）。
// 约束两条：① 每行宽 ≤ 格宽减徽章列；② **4 行总高 ≤ 词区高**（.wordrows
// 的 scrollHeight 不超 clientHeight）——只约束单行高会让 4 行在矮格里
// 互相叠字（lc 封面 195px 高的格实测撞过）。
function fitCell(cell) {
  const words = [...cell.querySelectorAll('.word[data-fit]')];
  if (!words.length) return;
  const rowsBox = cell.querySelector('.wordrows');
  const cellRect = cell.getBoundingClientRect();
  const availW = cellRect.width - 70;
  let lo = 8, hi = 110;
  const fits = (fs) => {
    words.forEach(w => w.style.fontSize = fs + 'px');
    if (rowsBox.scrollHeight > rowsBox.clientHeight + 1) return false;
    return words.every(w => w.getBoundingClientRect().width <= availW);
  };
  while (hi - lo > 0.5) {
    const mid = (lo + hi) / 2;
    if (fits(mid)) lo = mid; else hi = mid;
  }
  fits(lo);
  words.forEach(w => w.style.fontSize = lo + 'px');
}
function fitAll() {
  document.querySelectorAll('.cell').forEach(fitCell);
}
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(fitAll);
} else {
  window.addEventListener('load', fitAll);
}

// ?verify=1 → dump diagnostics as JSON into the <title>
if (/verify=1/.test(location.search + location.hash)) {
  (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve())
    .then(() => setTimeout(() => {
      const diag = [];
      document.querySelectorAll('.cell').forEach(cell => {
        const rows = [...cell.querySelectorAll('.wrow .word')].map(w => {
          const r = w.getBoundingClientRect();
          return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)];
        });
        const cr = cell.getBoundingClientRect();
        const rowsBox = cell.querySelector('.wordrows');
        diag.push({
          lang: cell.querySelector('.lang').firstChild.textContent.trim(),
          fs: parseFloat(cell.querySelector('.wrow .word').style.fontSize) || null,
          overflowX: rows.some(r => r[0] < cr.left - 0.5 || r[0] + r[2] > cr.right + 0.5),
          overflowY: rowsBox.scrollHeight > rowsBox.clientHeight + 1,
          rows
        });
      });
      const fonts = [...document.fonts].map(f => f.family + ':' + f.status).join(',');
      document.title = 'DIAG ' + JSON.stringify({fonts: fonts, cells: diag});
      const pre = document.createElement('pre'); pre.id = 'diag';
      pre.textContent = document.title; document.body.appendChild(pre);
    }, 300));
}
window.addEventListener('load', fitAll);
</script>
