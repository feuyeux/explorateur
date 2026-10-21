<script>
// ?lang=zh-CN&state=-1|0..K-1|K   -1 = pre-roll (all dim), K = done (all full)
const q = new URLSearchParams(location.search);
const lang = q.get("lang");
const state = parseInt(q.get("state") ?? "-1", 10);
const vert = q.get("fmt") === "v";
if (vert) { document.body.classList.add("vert"); document.documentElement.classList.add("vert"); }

// D2 fit box (CSS px) for the hero word — its own element, not a token.
// portrait 1080x1920: box 800x700 → height-bound fit gives ink ≈ 0.7×620 ≈ 430px
// (≥ 12% = 230px); width-bound fit gives 800px wide (≥ 30% = 324px).
// landscape 1920x1080: box 1700x420.
//
// ⚠️ 竖屏的框宽从 960 收到 800：实测（2026-10-21）960 时**短词**（he-IL「תה」）被撑到
// ~870px 字号，字形上方那圈行内上边距（≈0.25em ≈ 218px）就成了「画面空掉一大块」——
// 那一帧的最大空带 293px = 15.26%，超阈值 15%。收到 800 后同一帧 278px = 14.48%，
// 而其余 143 个组合实测无变化（空带都在 9% 上下）。D2 的宽度下限（≥30% 帧宽 = 324px）
// 在 800 下仍有 800px，余量充足。
const STAGE_W = vert ? 800 : 1700;
const STAGE_H = vert ? 700 : 420;

for (const sc of document.querySelectorAll(".scene")) {
  if (sc.dataset.lang !== lang) continue;
  sc.classList.add("on");

  // --- D2: fit the standalone word element to the stage box
  const hero = sc.querySelector(".hero");
  if (hero) {
    let lo = 20, hi = 900;
    for (let i = 0; i < 34; i++) {
      const mid = (lo + hi) / 2;
      hero.style.fontSize = mid + "px";
      const r = hero.getBoundingClientRect();
      if (r.width <= STAGE_W && r.height <= STAGE_H) lo = mid; else hi = mid;
    }
    hero.style.fontSize = lo + "px";
  }

  // --- karaoke over the sentence tokens (order = the spoken sentence, 1:1)
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
