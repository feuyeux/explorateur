<script>
// ?lang=zh-CN&state=-1|0..K-1|K   -1 = pre-roll (all dim), K = done (all full)
const q = new URLSearchParams(location.search);
const lang = q.get("lang");
const state = parseInt(q.get("state") ?? "-1", 10);
const vert = q.get("fmt") === "v";
if (vert) { document.body.classList.add("vert"); document.documentElement.classList.add("vert"); }

// D2 fit box (CSS px) for the hero word — its own element, not a token.
// portrait 1080x1920: box 960x700 → height-bound fit gives ink ≈ 0.7×620 ≈ 430px
// (≥ 12% = 230px); width-bound fit gives 960px wide (≥ 30% = 324px).
// landscape 1920x1080: box 1700x420.
const STAGE_W = vert ? 960 : 1700;
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
