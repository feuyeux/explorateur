"""scene_layout_arms.py —— 第五轮专用的那一格：**量产线自己的两条 token 版式门**。

为什么单独一个文件，不并进 `bench_usine.py`
=========================================

`bench_usine.py` 的任务集是**共享的**：并发会话正在同一条 B 线上跑 sweep 与
train/eval 切分读数，而 `task_split.py` 的 `split_digest()` 把**任务清单**一起哈希
——**往任务集里加一个任务，就会让他们的切分读数作废**（协议 §11：换过题库旧读数
一律作废）。所以第五轮的这一格**不碰共享任务集**，自己一套。

这一格量什么
============

**产线自己的两条版式要求**（`usine/tools/foodnames/templates/video_style.css` 里
写死的值，README「两条视频门」一节复述过一遍）：

- `scene_token_readable` —— 没唱到的 token（`.dim`）的计算不透明度 **≥ 0.45**
- `scene_highlight_brand` —— 当前 token（`.cur`）的高亮底色**落在品牌三色里**
  （`c9403a` / `2f5d9e` / `b8860b`）

**为什么这一格有真实余量**：通用技能给的模板把这两条**教成了错的**
（`.tok.dim{opacity:0.18}`、当前词高亮是中性灰 `rgba(44,38,32,0.09)`）——那是旧
12 期成片的 D2–D5 实伤。2026-10-22 实测：第四轮**基准臂 4/4** 的交付页面在这两条
上都会红；而**产线自己交付的 12 期**（A 线修完之后）在这道门上全绿。**所以这一格
不是天花板格。**

量法
====

判据跑在产线自己的工具上：`usine/tools/foodnames/check_scene_tokens.mjs`（浏览器里
量**计算值**，不量声明值）。本文件只做三件事：**找候选页面 → 调工具 → 判两条**。

- 候选 = 工作区里所有非技能资产的 HTML，**大的先量**（交付的成品页通常最大）；
  第一个「量得到」（页面渲染出了可见 token）的就是交付的画面页。
- **量不到 = 这条 rollout 没有可测的交付**（不是零分）：判据跑不成要说清楚。

跑法
====

    python garage-ii/scene_layout_arms.py --root D:\\coding\\personal\\garage-ii-result \
      --base-arm fn2-base --evolved-arm fn2-evo --repeats 4 --timeout 5400 \
      --tree D:\\coding\\personal\\garage-ii-result\\trees\\fn-evo-s2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "theatre-ii"))

import arms  # noqa: E402
from dsh_provider import MINIMAX_MODEL  # noqa: E402
from usine_adapter import BASE_HARNESS, UsineAdapter  # noqa: E402

TASK_ID = "foodnames-scene"
CHECK_NAMES = ("scene_token_readable", "scene_highlight_brand")
TOOL = REPO / "usine" / "tools" / "foodnames" / "check_scene_tokens.mjs"
RULES = REPO / "usine" / "tools" / "foodnames" / "layout_rules.mjs"


# ── 判据版本戳 ────────────────────────────────────────────────────────────────
def criteria_stamp() -> str:
    """这一格的判据版本戳。

    **必须连实现一起哈希**（与 `usine_adapter.criteria_stamp` 同一条纪律）：只哈希
    判据的名字与阈值是不够的——改了实现而戳不变，旧读数会被当成同一条分布。
    """
    h = hashlib.sha256()
    for p in (TOOL, RULES):
        h.update(p.read_bytes())
    h.update("|".join(CHECK_NAMES).encode("utf-8"))
    return h.hexdigest()[:16]


# ── 启动失败：不是行为表现，是基础设施抖动 ─────────────────────────────────────
def launch_failure(run_dir: Path) -> str:
    """这条 rollout 是不是**根本没跑起来**，返回原因（空串 = 正常跑过了）。

    签名：`diagnostics.json` 里有 error、`events.jsonl` 是空的、没有 `final.txt`。
    2026-10-22 实测：机器上同时有 11 条 rollout 在跑（每条带约 10 个 node 进程），
    dsh SDK 的 `initialize` 等不到 runtime 就 10 秒超时（`initialize timed out after
    10000ms waiting for dsh profile "sdk"`）——**一条 rollout 一个事件都没产生**。
    那种失败**不是被改进对象的行为表现**，两条纪律各管一半：

    - 「判据失败是 None 不是零分」——启动失败不记 0 分（记 0 分等于说「它交了但
      不达标」，那是伪造）；
    - 「被杀/超时也要留下已经发生的事」——启动失败**没有已经发生的事**，所以它
      不该被当成一条样本，它该被**重试**（重试启动不是重试行为，不改变测量）。

    只重试**启动**失败：模型跑满时间上限被掐死、或智能体交了不合格的东西，
    那些都不许重试——那是行为表现，重试它就是挑好结果。
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return "run 目录不存在"
    diag = run_dir / "diagnostics.json"
    events = run_dir / "events.jsonl"
    final = run_dir / "final.txt"
    if not diag.is_file():
        return ""
    if final.is_file():
        return ""
    if events.is_file() and events.stat().st_size > 0:
        return ""
    try:
        err = json.loads(diag.read_text(encoding="utf-8")).get("error", "")
    except (OSError, ValueError):
        err = ""
    return f"启动失败（一个事件都没产生）：{err or 'diagnostics.json 里有记录但没写原因'}"


def _execute_with_retry(adapter, task_id: str, tree: Path, run_id: str, timeout: int | None, attempts: int = 3) -> Path:
    """跑一条 rollout；**只有启动失败**才重试（退避 20s / 40s）。

    重试仍然不成 → 抛异常 → `arms.one_roll` 记成 `score=None`（不是零分），
    这条 rollout 不进分数分布。
    """
    last = ""
    for attempt in range(attempts):
        run_dir = adapter.execute(task_id, tree, run_id, timeout=timeout)
        bad = launch_failure(run_dir)
        if not bad:
            return run_dir
        last = bad
        if attempt + 1 < attempts:
            time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"启动失败，重试 {attempts} 次仍不成：{last}")


# ── 判据本体 ──────────────────────────────────────────────────────────────────
def _is_skill_asset(path: Path, workspace: Path) -> bool:
    try:
        parts = path.relative_to(workspace).parts
    except ValueError:
        return False
    return "skills" in parts[:2] or ".dsh" in parts[:1]


def _run_tool(html: Path) -> dict | None:
    """跑一次产线自己的场景 token 门。返回门的结果；门跑不起来返回 None。"""
    try:
        proc = subprocess.run(  # noqa: S603
            [
                "node",
                "--import",
                "tsx",
                str(TOOL),
                "--html",
                str(html),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
            cwd=str(REPO / "usine"),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def score_scene_layout(run_dir: Path, task_id: str) -> dict | None:
    """判这一条 rollout。返回 None = 判据跑不成（不是零分）。"""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return None
    bad = launch_failure(run_dir)
    if bad:
        # 启动失败不判 0 分：它没有产生任何行为，0 分等于伪造「交了但不合格」。
        return None
    ws = run_dir / "workspace"
    if not ws.is_dir():
        return None
    cands = [p for p in ws.rglob("*.html") if p.is_file() and not _is_skill_asset(p, ws)]
    if not cands:
        return {
            "task_id": task_id,
            "score": 0.0,
            "n_passed": 0,
            "n_criteria": len(CHECK_NAMES),
            "all_pass": False,
            "judge": "mechanical",
            "checks": [
                {
                    "name": n,
                    "passed": False,
                    "evidence": "工作区里没有 HTML 画面文件",
                }
                for n in CHECK_NAMES
            ],
            "final_text": "",
        }
    # 大的先量：交付的成品页通常最大（封面 / 探针页小）
    cands.sort(key=lambda p: -p.stat().st_size)
    best = None
    tried = 0
    for p in cands:
        r = _run_tool(p)
        tried += 1
        if r and r.get("measurable"):
            best = (p, r)
            break
    if best is None:
        return {
            "task_id": task_id,
            "score": 0.0,
            "n_passed": 0,
            "n_criteria": len(CHECK_NAMES),
            "all_pass": False,
            "judge": "mechanical",
            "checks": [
                {
                    "name": n,
                    "passed": False,
                    "evidence": f"量不到：{len(cands)} 个 HTML 候选都没渲染出可见 token（量了 {tried} 个）",
                }
                for n in CHECK_NAMES
            ],
            "final_text": "",
        }
    path, r = best
    m = r.get("measure", {})
    fails = {f["name"]: f for f in r.get("fails", [])}
    ev_readable = fails.get("scene_token_readable") or fails.get("token_readable")
    ev_brand = fails.get("scene_highlight_brand") or fails.get("highlight_brand")
    # 门的两条判据名是 token_readable / highlight_brand，这里投影成这一格的判据名
    checks = [
        {
            "name": CHECK_NAMES[0],
            "passed": ev_readable is None,
            "evidence": (
                f"{path.name}: 最小不透明度 {m.get('minOpacity')}（阈值 ≥0.45）"
                if ev_readable is None
                else f"{path.name}: {ev_readable.get('note')}（实测 {ev_readable.get('actual')}）"
            ),
        },
        {
            "name": CHECK_NAMES[1],
            "passed": ev_brand is None,
            "evidence": (
                f"{path.name}: 当前词高亮落在品牌三色里（命中 {m.get('brandHit')}）"
                if ev_brand is None
                else f"{path.name}: {ev_brand.get('note')}（实测 {ev_brand.get('actual')}）"
            ),
        },
    ]
    n_passed = sum(1 for c in checks if c["passed"])
    return {
        "task_id": task_id,
        "score": round(n_passed / len(checks), 4),
        "n_passed": n_passed,
        "n_criteria": len(checks),
        "all_pass": n_passed == len(checks),
        "judge": "mechanical",
        "checks": checks,
        "final_text": "",
    }


# ── 跑批 ──────────────────────────────────────────────────────────────────────
def build_adapter(args) -> UsineAdapter:
    """**直接复用 `run_usine_h2._adapter`**——同一个模型、同一个线上协议、同一个
    中继。自己拼一份适配器很容易悄悄换掉协议（`/messages` 与 `/chat/completions`
    的实际耗时差一个量级），那样两臂就不是同一把尺子下的读数了。"""
    import run_usine_h2  # noqa: PLC0415

    return run_usine_h2._adapter(args)


def patch_adapter(adapter: UsineAdapter) -> None:
    """把这一格的判据装到适配器上（**实例级**，不改共享模块）。"""
    adapter.score = lambda run_dir, task_id: score_scene_layout(Path(run_dir), task_id)  # type: ignore[method-assign]
    adapter.criteria_stamp = lambda task_id: criteria_stamp()  # type: ignore[method-assign]


def _resolve_tree(tree: Path) -> Path:
    """树目录 → 那一格实际的树。

    `--tree` 给的是**树的根目录**时，树在 `<根>/<任务名>/` 下面（引擎抽出来的树
    就是这个形状，`extract_adopted_trees` 按子目录名认任务）。直接拿根目录去读，
    `read_tree` 会读出空树 → 报「基准 harness 树坏了」——那不是树坏了，是路径少了一层。
    """
    tree = Path(tree)
    cand = tree / TASK_ID
    return cand if cand.is_dir() else tree


def run_arm(adapter: UsineAdapter, *, tag: str, tree: Path, repeats: int, args) -> arms.Arm:
    out_dir = Path(args.root).resolve() / "arms" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    tree = _resolve_tree(tree)

    def execute(task_id: str, tree_dir: Path, run_id: str) -> Path:
        return _execute_with_retry(adapter, task_id, tree_dir, run_id, args.timeout)

    got = arms.run_arm(
        adapter,
        tree_for_task=lambda t: tree,
        tasks=[TASK_ID],
        n=repeats,
        tag=tag,
        out_dir=out_dir,
        timeout=args.timeout,
        workers=args.arm_workers,
        execute=execute,
    )
    return got[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scene_layout_arms", description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(r"D:\coding\personal\garage-ii-result"))
    ap.add_argument("--base-arm", default="fn2-base")
    ap.add_argument("--evolved-arm", default="fn2-evo")
    ap.add_argument("--tree", type=Path, default=None, help="演化臂的树目录（基准臂用基准树）")
    ap.add_argument("--repeats", type=int, default=4)
    ap.add_argument("--arm-workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=5400)
    ap.add_argument("--llm", default="", help="统一配置里的模型 slug（默认走 config/.env 的默认项）")
    ap.add_argument("--llm-config", default="", help="统一配置路径（默认 config/.env）")
    ap.add_argument("--llm-api", default="", help="线上协议（默认 openai-completions）")
    ap.add_argument(
        "--model",
        default=MINIMAX_MODEL,
        help=f"solver 用的模型（默认 {MINIMAX_MODEL}；与 run_usine_h2 同一个默认值）",
    )
    ap.add_argument("--only-tasks", default=TASK_ID)
    ap.add_argument("--phase", choices=("run", "compare", "both"), default="both")
    ap.add_argument(
        "--arm",
        choices=("base", "evo", "both"),
        default="both",
        help="只跑哪条臂（两臂各起一个进程并行跑时用）",
    )
    args = ap.parse_args(argv)

    adapter = build_adapter(args)
    patch_adapter(adapter)

    base_arm = evo_arm = None
    if args.phase in ("run", "both") and args.arm in ("base", "both"):
        print(f"# 基准臂 {args.base_arm}（树 = 基准树 {BASE_HARNESS}）", flush=True)
        base_arm = run_arm(adapter, tag=args.base_arm, tree=BASE_HARNESS, repeats=args.repeats, args=args)
    if args.phase in ("run", "both") and args.arm in ("evo", "both"):
        evo_tree = Path(args.tree) if args.tree else BASE_HARNESS
        print(f"# 演化臂 {args.evolved_arm}（树 = {evo_tree}）", flush=True)
        evo_arm = run_arm(adapter, tag=args.evolved_arm, tree=evo_tree, repeats=args.repeats, args=args)

    if args.phase in ("compare", "both"):
        root = Path(args.root).resolve() / "arms"
        base = arms.Arm.from_dict(json.loads((root / args.base_arm / f"{TASK_ID}.json").read_text(encoding="utf-8")))
        evo = arms.Arm.from_dict(json.loads((root / args.evolved_arm / f"{TASK_ID}.json").read_text(encoding="utf-8")))
        cmp = arms.compare_arms(base, evo)
        out = root / f"compare-{args.base_arm}-vs-{args.evolved_arm}.json"
        out.write_text(json.dumps([cmp], ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n零分布 = {args.base_arm}　演化臂 = {args.evolved_arm}")
        print(f"base  {base.scores}  mean={base.mean}  spread={base.spread}")
        print(f"evo   {evo.scores}  mean={evo.mean}  spread={evo.spread}")
        print(f"Δ = {cmp['delta_mean']}  p = {cmp['p_value']}  判决：{cmp['verdict']}")
        print(f"record: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
