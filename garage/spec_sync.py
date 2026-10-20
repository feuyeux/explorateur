"""spec_sync.py —— 规范同步闸：改了被规范的代码，必须同批更新规范。

## 为什么要这道闸

RSI 流水线里，规范文档是被**自动化流程消费**的对象：出题席读它、Actor 按它
干活、验证席按它判「改对了没有」。一旦规范与代码漂移，后果不是「文档过时」
这么轻——它会让下一轮把已经改过的东西当成待办再改一遍。

真实案例（2026-10-20）：DRS 那一轮改了 `usine_video_generation` 拒答分支 4
的文案，却没更新 `packages/dsh-plugin/test/refusal-audit.md`；那份文档当时
写着分支 4「保留」并贴出改写前的旧文案。规范漂移是**可复现的**，不是「可能
发生」。

## 口径：锚点写在规范文档自己身上（单一事实源）

规范文档里放一个 ```` ```anchors ```` 围栏块，每行两条：

    <仓库相对路径> <该文件里必须仍然存在的字面量>

例如 `packages/dsh-plugin/test/refusal-audit.md` 里写：

    packages/dsh-plugin/src/tools.ts 操作员在宿主的审批界面取消了这个请求

这一行断言的是**规范声称的代码事实**。代码一旦不再包含这个字面量，规范就
已经与代码不一致——要么代码退化了，要么规范该改。

为什么锚点写在文档里而不是本模块的注册表里：注册表会变成**第二份事实源**
（纪律 10：多副本数据源是反模式）。文档自己声明自己钉住什么，改文档就同时
改了锚点，二者不可能分叉。本模块只保留一份**指针**——哪些文档受管辖
（`config/spec-sync.json`），那不是内容，是路由。

## 判定规则

对每个受管辖的规范文档 S：

1. 读 S 的**基线版本**（合并前的工作树），解析出 ```` ```anchors ```` 块。
2. 逐条锚点 (P, L) 判定：L 是否仍出现在 P 的**候选版本**里
   （P 落在本次 delta 内 → 用候选字节；否则 → 用工作树现文件）。
3. 若有锚点失效：
   - S **不在**本次 delta 内 → **违规**：规范与代码漂移且没同批修。候选被拒。
   - S **在**本次 delta 内 → 规范已同批更新，放行；但还要拿**候选版** S 重新
     解析锚点，逐条对候选代码复判一遍——新规范自己说错话，同样违规。
4. 没有锚点失效 → 放行，规范不必改（不要制造无谓的文档抖动）。

## 不做什么

- 不判断「这次改动好不好」——那是验证席与门禁的活；本闸只管**规范与代码
  是否还对得上**。
- 不解析散文。锚点块是机器面，散文是给人读的；两者分家，避免「文档改了
  散文但锚点没改」这种半更新。
- 不做语义猜测。锚点是字面量，命中与否是二值判定。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Iterable

HERE = pathlib.Path(__file__).resolve().parent

# 围栏块的起止：```anchors ... ```。允许 ```anchors 后面跟别的词，但围栏本身
# 必须是 ``` 独占一行。
_FENCE_OPEN = re.compile(r"^```\s*anchors\b[^\n]*$")
_FENCE_CLOSE = re.compile(r"^```\s*$")

# 锚点行：<路径> <字面量>。路径不含空白，字面量是行内第一个空白之后的全部内容
# （含首尾空白以外的一切）。空行与 # 开头的注释行跳过。
_ANCHOR_LINE = re.compile(r"^(?P<path>\S+)\s{1,}(?P<literal>\S.*?)\s*$")


class SpecSyncError(RuntimeError):
    """规范同步闸自身出错了（配置坏、文档读不了）。"""


def registry_path() -> pathlib.Path:
    """受管辖规范文档的注册表路径。

    ``GARAGE_SPEC_SYNC_REGISTRY`` 可覆盖它：冒烟测试与「这份仓不承载那套
    规范」的部署形态需要指向别的名单。默认是本模块旁边的 ``config/spec-sync.json``。
    """
    override = os.environ.get("GARAGE_SPEC_SYNC_REGISTRY")
    if override:
        return pathlib.Path(override)
    return HERE / "config" / "spec-sync.json"


def load_registry(path: pathlib.Path | None = None) -> list[str]:
    """受管辖的规范文档列表（相对 usine 项目根）。

    这是一份**指针**不是内容——锚点本体在规范文档自己身上。配置坏了就报错，
    不静默降级成「没有受管辖的文档」：那会让整道闸静默失效，而失效的闸比
    没有闸更坏。
    """
    target = path or registry_path()
    if not target.is_file():
        raise SpecSyncError(f"spec-sync registry is missing: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SpecSyncError(f"spec-sync registry is unreadable: {exc}") from exc
    docs = payload.get("spec_docs")
    if not isinstance(docs, list) or not all(isinstance(d, str) and d for d in docs):
        raise SpecSyncError(
            "spec-sync registry must carry a non-empty list of strings under "
            "'spec_docs'")
    return list(docs)


def parse_anchors(text: str) -> list[tuple[str, str]]:
    """从规范文档正文里解析 ```` ```anchors ```` 块。

    没有锚点块 → 返回空列表（这份文档不声明任何代码事实，闸对它无话可说）。
    """
    anchors: list[tuple[str, str]] = []
    inside = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not inside:
            if _FENCE_OPEN.match(line):
                inside = True
            continue
        if _FENCE_CLOSE.match(line):
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ANCHOR_LINE.match(stripped)
        if match is None:
            raise SpecSyncError(
                "an anchors line must be '<path> <literal>', got: " + stripped[:80])
        anchors.append((match.group("path"), match.group("literal")))
    return anchors


def render_anchors(anchors: Iterable[tuple[str, str]]) -> str:
    """把锚点渲染回文档块（供测试与文档生成用）。"""
    return "\n".join(f"{path} {literal}" for path, literal in anchors)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def check(spec_docs: list[str],
          delta: dict,
          candidate_bytes: dict,
          read_text) -> dict:
    """判定本次 delta 是否破坏了规范与代码的一致性。

    ``delta``        —— {"modified": [...], "added": [...], "deleted": [...]},
                        路径相对 usine 项目根。
    ``candidate_bytes`` —— {rel: bytes}，本次 delta 里候选的字节。
    ``read_text``    —— callable(rel) -> str | None，读工作树现文件；文件不存在
                        返回 None。

    返回 ``{"violations": [...], "notices": [...]}``：

    * violations —— 规范与代码对不上，必须拦。空列表 = 放行。
    * notices   —— 闸没生效或没约束到东西的情况（如这份仓根本不承载该规范
      文档）。**不拦，但必须被看见**：一道静默失效的闸比没有闸更坏，所以它
      记下来而不是消失。

    两种「不拦」的区别是有意的：

    * 规范文档不在本仓（另一种部署形态、冒烟用的临时仓库）→ notice。规范
      管辖的代码也不在，闸无话可说。
    * 规范文档在，但它的锚点没失效 → 放行，规范不必改（不制造无谓抖动）。
    """
    touched = set(delta.get("modified") or []) | set(delta.get("added") or [])
    deleted = set(delta.get("deleted") or [])
    violations: list[dict] = []
    notices: list[dict] = []

    def content_of(rel: str) -> str | None:
        if rel in candidate_bytes:
            return _decode(candidate_bytes[rel])
        if rel in deleted:
            return None
        return read_text(rel)

    for spec_rel in spec_docs:
        baseline_text = read_text(spec_rel)
        if baseline_text is None:
            notices.append({
                "spec": spec_rel,
                "reason": "规范文档不在本仓（该仓不承载这份规范）",
                "detail": ("规范同步闸对这份规范没有生效——本仓里找不到 "
                           f"{spec_rel}，锚点无从校验。这不是漂移，但也"
                           "意味着这道闸在本次合并上没干活。"),
            })
            continue
        baseline_anchors = parse_anchors(baseline_text)
        if not baseline_anchors:
            # 这份文档不声明代码事实——它不受锚点约束，但仍在管辖名单里，
            # 将来加上围栏块就自动生效。
            notices.append({
                "spec": spec_rel,
                "reason": "规范文档没有 anchors 围栏块",
                "detail": ("这份规范没有声明任何代码事实，规范同步闸对它"
                           "暂时无话可说；加围栏块后自动生效。"),
            })
            continue
        # 一条锚点有三种状态：**基线就断**（合并前代码里已经没有这个字面量）、
        # **基线还在**、**候选还在**。只有「基线还在、候选没了」才是本次候选
        # 造成的漂移——那才拦。基线就断的锚点是**存量漂移**：候选没有把它弄坏，
        # 拿它去否决候选是冤判，而且会让整条流水线卡死（闸一旦失效就没人
        # 知道它失效了）。存量漂移记成 notice：可见，但不拦。
        broken_at_baseline: list[tuple[str, str]] = []
        broken_by_candidate: list[tuple[str, str, str]] = []
        for code_rel, literal in baseline_anchors:
            baseline_body = read_text(code_rel)
            baseline_ok = (baseline_body is not None
                           and literal in baseline_body)
            candidate_body = content_of(code_rel)
            candidate_ok = (candidate_body is not None
                            and literal in candidate_body)
            if baseline_ok and not candidate_ok:
                broken_by_candidate.append(
                    (code_rel, literal,
                     "被规范的文件在候选里不存在" if candidate_body is None
                     else "字面量已不在被规范的文件里"))
            elif not baseline_ok and not candidate_ok:
                broken_at_baseline.append((code_rel, literal))
        if broken_at_baseline:
            notices.append({
                "spec": spec_rel,
                "reason": f"规范里有 {len(broken_at_baseline)} 条锚点在合并前"
                          f"就已经与代码对不上（存量漂移，不是本次候选造成的）",
                "detail": ("这些锚点在基线代码里就已经不存在了——本次候选没有"
                           "弄坏它们，所以不据此否决候选；但规范确实已经与"
                           "代码对不上，需要有人去修规范（"
                           + "；".join(f"{p} 「{l[:30]}」" for p, l in broken_at_baseline[:3])
                           + "）。"),
            })
        if not broken_by_candidate:
            continue
        if spec_rel not in touched:
            for code_rel, literal, why in broken_by_candidate:
                violations.append({
                    "spec": spec_rel,
                    "code": code_rel,
                    "anchor": literal,
                    "reason": why,
                    "detail": ("规范声称的代码事实已失效，但规范文档没有随本次候选"
                               "一起更新——规范与代码漂移，必须同 commit 更新规范"
                               f"（{spec_rel}）"),
                })
            continue
        # 规范同批更新了：拿候选版的锚点复判一遍，新规范自己说错话同样违规。
        candidate_spec_text = content_of(spec_rel)
        if candidate_spec_text is None:
            violations.append({
                "spec": spec_rel,
                "code": broken_by_candidate[0][0],
                "anchor": broken_by_candidate[0][1],
                "reason": "候选删除了规范文档",
                "detail": ("规范文档在本次候选里被删除，但它管辖的代码事实"
                           "已经失效——删除规范等于让漂移变成不可见"),
            })
            continue
        baseline_anchor_set = set(baseline_anchors)
        for code_rel, literal in parse_anchors(candidate_spec_text):
            body = content_of(code_rel)
            candidate_ok = body is not None and literal in body
            if candidate_ok:
                continue
            if (code_rel, literal) in baseline_anchor_set:
                # 这条锚点基线就断着，候选只是把旧锚点原样带过来——存量漂移，
                # 不算候选说谎（否则一次「顺手重写规范」就会被自己的旧债拦死）。
                continue
            violations.append({
                "spec": spec_rel,
                "code": code_rel,
                "anchor": literal,
                "reason": ("候选版规范锚定的文件在候选里不存在"
                           if body is None
                           else "候选版规范锚定的字面量不在候选代码里"),
                "detail": "候选版规范自己说错话",
            })
    return {"violations": violations, "notices": notices}


def describe(violations: list[dict]) -> str:
    """把违规列表压成一行人能读的理由（写进合并报告的 reason 字段）。"""
    if not violations:
        return ""
    first = violations[0]
    head = (f"规范漂移：{first['spec']} 声称 {first['code']} 含 "
            f"「{first['anchor'][:40]}」，但候选里已不成立（{first['reason']}）")
    if len(violations) > 1:
        head += f"；另有 {len(violations) - 1} 处"
    return head


def describe_notices(notices: list[dict]) -> str:
    """把 notice 列表压成一行人能读的话（写进合并报告）。"""
    if not notices:
        return ""
    return "；".join(f"{n['spec']}：{n['reason']}" for n in notices)
