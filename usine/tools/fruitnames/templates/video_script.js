<script>
// ?lang=zh-CN&state=-1|0..K-1|K   -1 = pre-roll (all dim), K = done (all full)
// fruit 版（用户定稿）：**不加另一份大字**——卡片上原有的词直接放大，
// state = 当前念到第几张卡；当前卡金圈 + 词的品牌底色，其余卡 dim ≥ 0.45。
const q = new URLSearchParams(location.search);
const lang = q.get("lang");
const state = parseInt(q.get("state") ?? "-1", 10);
const vert = q.get("fmt") === "v";
if (vert) { document.body.classList.add("vert"); document.documentElement.classList.add("vert"); }

for (const sc of document.querySelectorAll(".scene")) {
  if (sc.dataset.lang !== lang) continue;
  sc.classList.add("on");

  // 每张卡的词拟合到自己的词框（同一语种 4 词同框型；字号各自收敛）
  sc.querySelectorAll(".card").forEach((card) => {
    const box = card.querySelector(".wordbox");
    const word = card.querySelector(".word");
    const availW = box.clientWidth - 8;
    const availH = box.clientHeight - 2;
    let lo = 10, hi = 220;
    for (let i = 0; i < 28; i++) {
      const mid = (lo + hi) / 2;
      word.style.fontSize = mid + "px";
      const r = word.getBoundingClientRect();
      if (r.width <= availW && r.height <= availH) lo = mid; else hi = mid;
    }
    word.style.fontSize = lo + "px";
  });

  // karaoke：当前卡亮品牌底 + 金圈；未唱卡 dim ≥ 0.45（版式门下限）
  const cards = sc.querySelectorAll(".card");
  cards.forEach((card, i) => {
    const tok = card.querySelector(".tok");
    tok.classList.remove("dim", "sung", "cur");
    card.classList.remove("cur");
    const kind = tok.dataset.kind || "kt";
    if (state < 0) tok.classList.add("dim");
    else if (state >= cards.length) tok.classList.add("sung");
    else if (i < state) tok.classList.add("sung");
    else if (i === state) { tok.classList.add("cur", "k" + kind); card.classList.add("cur"); }
    else tok.classList.add("dim");
  });
}
</script>
