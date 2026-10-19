<script>
// ?lang=zh-CN&state=-1|0..K-1|K   -1 = pre-roll (all dim), K = done (all full)
const q = new URLSearchParams(location.search);
const lang = q.get("lang");
const state = parseInt(q.get("state") ?? "-1", 10);
const vert = q.get("fmt") === "v";
if (vert) { document.body.classList.add("vert"); document.documentElement.classList.add("vert"); }

// per-scene stage box (CSS px) for the fit
const STAGE_W = vert ? 940 : 1740;
const STAGE_H = vert ? 900 : 430;

for (const sc of document.querySelectorAll(".scene")) {
  if (sc.dataset.lang !== lang) continue;
  sc.classList.add("on");
  const word = sc.querySelector(".word");
  // fit: largest font size keeping the word inside the stage box
  let lo = 20, hi = 420;
  for (let i = 0; i < 30; i++) {
    const mid = (lo + hi) / 2;
    word.style.fontSize = mid + "px";
    const r = word.getBoundingClientRect();
    if (r.width <= STAGE_W && r.height <= STAGE_H) lo = mid; else hi = mid;
  }
  word.style.fontSize = lo + "px";

  const toks = sc.querySelectorAll(".tok");
  toks.forEach((t, i) => {
    t.classList.remove("dim", "sung", "cur");
    if (state < 0) t.classList.add("dim");
    else if (state >= toks.length) t.classList.add("sung");
    else if (i < state) t.classList.add("sung");
    else if (i === state) t.classList.add("cur");
    else t.classList.add("dim");
  });
}
</script>
