<script>
// per-cell auto-fit: binary-search the largest font size that keeps the word
// inside its wordbox (width and height), so every script fills its own cell.
function fitCell(cell) {
  const box = cell.querySelector('.wordbox');
  const word = cell.querySelector('.word');
  const availW = box.clientWidth;
  const availH = box.clientHeight;
  let lo = 10, hi = 400;
  while (hi - lo > 0.5) {
    const mid = (lo + hi) / 2;
    word.style.fontSize = mid + 'px';
    const r = word.getBoundingClientRect();
    if (r.width <= availW && r.height <= availH) lo = mid; else hi = mid;
  }
  word.style.fontSize = lo + 'px';
}
function fitAll() {
  document.querySelectorAll('.cell').forEach(fitCell);
}
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(fitAll);
} else {
  window.addEventListener('load', fitAll);
}

// ?verify=1 → dump per-cell fit diagnostics as JSON into the <title>
if (/verify=1/.test(location.search + location.hash)) {
  (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve())
    .then(() => setTimeout(() => {
      const diag = [];
      document.querySelectorAll('.cell').forEach(cell => {
        const word = cell.querySelector('.word');
        const wr = word.getBoundingClientRect();
        const cr = cell.getBoundingClientRect();
        diag.push({
          lang: cell.querySelector('.lang').firstChild.textContent.trim(),
          fs: parseFloat(word.style.fontSize) || null,
          overflowX: wr.right > cr.right + 0.5 || wr.left < cr.left - 0.5,
          overflowY: wr.bottom > cr.bottom + 0.5,
          word: [Math.round(wr.left), Math.round(wr.top), Math.round(wr.width), Math.round(wr.height)]
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
