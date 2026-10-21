"""train / eval 切分：**按产线层分层**，且**固定种子可复现**。

为什么要有这个模块
==================

2026-10-21 之前，`usine_adapter.tasks()` 收 `split` 参数但**完全忽略它**——`all` /
`train` / `eval` 返回同一批任务，而 `run_usine_h2.py` 传的是 `split="all"`。于是
**提案者读到的失败轨迹与最终判分的任务，是同一批 7 个**：这是过拟合的定义，而且它
在读数上不可见——两臂都在同一批题上，你只会看到「分高」或「分低」，看不到「只在
训练题上高」。

引擎侧的切分机制是**齐的**（`harness2/benchmarks/tasks.py:62` 的 `select()`：校验
重叠、重复、未知 ID），`schedule.run_sweep(split=…)` 也一路透传。缺的只是本层没接
上。这个模块补的就是那一截。

判据口径
========

**切分只按 `Task.domain` 分层，绝不看任务内容、不看判据、不看历史分数。** 理由是
纪律里那条「判据不许比被改进对象自己的文件更严」的同族：切分一旦看分数，就成了
「按已知结果挑题」，那是有偏的——等于先把难题塞进 train。

`test` 只切一次、之后冻结（`SPLIT_SEED` 常量）。**改任务集会让旧切分失效**，所以
`split_digest()` 把任务清单与切分结果一起哈希，读数里带上它——换了切分之后旧读数
自动对不上，这是有意的（协议 §11：换过题面/判据/环境的旧读数一律作废）。
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

#: 切分种子。**改它等于换一套题**——旧读数全部作废，必须重跑。
SPLIT_SEED = 20261021

#: train 侧的比例。0.5 是引擎自带 `split_tasks.py` 的默认值，照抄以保持两处一致。
TRAIN_FRACTION = 0.5

#: 单层少于这个数就不切（切了每边只剩 1 个，噪声大于信号）。
MIN_PER_DOMAIN = 2


def _domain_map(tasks) -> dict[str, list[str]]:
    by: dict[str, list[str]] = {}
    for t in tasks:
        by.setdefault(t.domain, []).append(t.task_id)
    return {d: sorted(ids) for d, ids in sorted(by.items())}


def make_split(tasks, *, seed: int = SPLIT_SEED, train_fraction: float = TRAIN_FRACTION) -> dict:
    """按领域分层切 train / eval。

    **领域内洗牌后对半切**，不是「按任务名排序后对半」——因为任务 id 是人工排的
    （`routing-poster` 与 `routing-poster-vague` 相邻），按名字切会把同族任务全塞进
    同一侧，那是另一种泄漏：variants 之间共享题面结构，一侧有另一侧没有，量的就不是
    泛化了。

    领域内任务数 `< MIN_PER_DOMAIN` 的层**不切**，整层归 train：宁可让 eval 少一层，
    也不让某一层在 eval 里只有 1 个任务（那种一格的读数没有统计意义，却会被当成
    「这一层泛化了」）。
    """
    if not 0 < train_fraction < 1:
        raise ValueError(f"train_fraction 必须在 (0,1)：{train_fraction}")
    by_domain = _domain_map(tasks)
    rng = random.Random(seed)
    train: list[str] = []
    test: list[str] = []
    unsplit: list[str] = []
    for domain, ids in by_domain.items():
        ids = list(ids)
        if len(ids) < MIN_PER_DOMAIN:
            train.extend(ids)
            unsplit.append(domain)
            continue
        rng.shuffle(ids)
        cut = max(1, min(len(ids) - 1, round(len(ids) * train_fraction)))
        train.extend(sorted(ids[:cut]))
        test.extend(sorted(ids[cut:]))
    return {
        "benchmark": "usine-dsh",
        "seed": seed,
        "train_fraction": train_fraction,
        "train": sorted(train),
        "test": sorted(test),
        # 哪些层因为太小而没切——报告里要说出来，别让「eval 少了三层」变成谜。
        "unsplit_domains": sorted(unsplit),
    }


def select(tasks, split: str, *, split_data: dict | None = None) -> list[str]:
    """按 split 取任务 id。**未知 split 一律抛错**，不静默全给。"""
    if split not in ("all", "train", "test"):
        raise ValueError(f"未知 split：{split!r}（只认 all / train / test）")
    ids = [t.task_id for t in tasks]
    if split == "all":
        return ids
    data = split_data or make_split(tasks)
    picked = data.get(split) or []
    unknown = set(picked) - set(ids)
    if unknown:
        # 任务集改了而切分没重生成：**必须炸**，不能悄悄少跑几个。
        raise ValueError(
            f"切分里的任务在任务集里不存在：{sorted(unknown)}——"
            f"任务集改过之后要重生成切分（`make_split`）"
        )
    missing = set(ids) - set(data.get("train", [])) - set(data.get("test", []))
    if missing:
        raise ValueError(f"这些任务哪一边都没进：{sorted(missing)}")
    if set(data.get("train", [])) & set(data.get("test", [])):
        raise ValueError("train 与 test 重叠——这是切分实现错误，不是配置问题")
    return sorted(picked)


def split_digest(tasks, *, split_data: dict | None = None) -> str:
    """切分 + 任务清单的指纹。**读数里必须带它**：换了切分，旧读数就对不上。"""
    data = split_data or make_split(tasks)
    payload = {
        "tasks": sorted(t.task_id for t in tasks),
        "train": data.get("train"),
        "test": data.get("test"),
        "seed": data.get("seed"),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def write_split(tasks, path: Path, *, seed: int = SPLIT_SEED) -> dict:
    """落盘成引擎 `select()` 认的格式（`{benchmark, train, test}`）。"""
    data = make_split(tasks, seed=seed)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 显式 `\n`：这个文件会被哈希与逐字比对，平台默认换行会让它莫名其妙地"变了"。
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return data


def read_split(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def coverage(tasks) -> str:
    """人读的一行摘要：每层多少个、切到哪边。"""
    data = make_split(tasks)
    tr, te = set(data["train"]), set(data["test"])
    by_domain = _domain_map(tasks)
    bits = []
    for domain, ids in by_domain.items():
        n_tr = sum(1 for i in ids if i in tr)
        n_te = sum(1 for i in ids if i in te)
        bits.append(f"{domain} {n_tr}/{n_te}")
    return f"train/eval 共 {len(tr)}/{len(te)}，分层：{', '.join(bits)}"
