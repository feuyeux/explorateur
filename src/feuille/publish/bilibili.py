# -*- coding: utf-8 -*-
"""bilibili.py — B 站发布器（⑨）：分区/创作声明双硬闸门 + 二次确认 + .txt 字幕

搬运自 yiyezhiqiu/scripts/publish_bilibili_yyzq.py（函数体逐字节照搬，
坑注释一字不动——尤其 set_bili_statement 的假阳性注释与 publish_one 尾部的
「稿件投递成功」全词判定）。

**已核实缺陷的修复**（逐条指认，公共件在 base.py）：
- ③ 写死的 Chrome 绝对路径 → `base.launch`（resolver）。
- ① 防风控节流 → `base.run_tasks`（循环内）；本平台节流间隔沿用原版 4s。

**双硬闸门**（纪律 19：宁可整条不发，也不带病发布）：
- 创作声明选不中 → 中止投稿（对外声明涉及责任，绝不跳过）；
- 封面没换上 → 中止投稿。

**使用契约**：
- tasks 是 `feuille.manifest.build_manifest` 的产物；profile 默认
  `base.PROFILES["bilibili"]`；截图与 result JSON 全部落 log_dir。
- .txt 字幕从 subs_dir/{lang}.txt 取（原项目布局 build/subs/，参数化），
  文件不存在就如实跳过——不编路径。
- 必填项取值由用户明确指定（见 BILI_ZONE / BILI_STMT_REQUIRED 的注释），
  换项目时由调用方传入，不在本模块里私自改。

用法：
    from feuille.publish import bilibili
    bilibili.publish(tasks, log_dir="build", subs_dir="build/subs")
"""
from __future__ import annotations

import time
from pathlib import Path

from . import base

UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"
BILI_WALL = ("扫码登录", "密码登录", "手机号登录", "登录后")

# 必填项取值。分区与创作声明由用户 2026-10-06 明确指定：
#   分区 = 知识；创作声明 = 自制/原创（不标注 AI 生成）
BILI_ZONE = "知识"
# 必填的「创作声明」只认这 6 项之一。
# ⚠️ 「内容为自制：未经作者允许，禁止转载」属于**非必选**的「内容授权声明」，
# 勾上它**填不满必填字段**——点「立即投稿」会报红字「请添加创作声明」，
# 稿件一条都投不出去。栽过：日志打「✓ 创作声明 = …」是假阳性，
# 蓝色对勾只是版权声明的选中态，必填框仍是占位符。
BILI_STMT_REQUIRED = ("内容无需标注", "含AI生成内容", "含虚构演绎内容",
                      "内容含营销信息", "个人观点，仅供参考", "内容为转载")
# 用户 2026-10-06 指定：不标注 AI 生成 + 保留「自制」版权声明，两者同时勾。
BILI_STMT_OPTIONAL = "内容为自制：未经作者允许，禁止转载"

# B 站成功页文案是「**稿件投递成功**」，不是「投稿/提交成功」。
# 栽过：词表里没有「投递」二字，脚本判成「已提交未确认」，
# 实际稿件早就进管理后台了。URL 也不会变，只能靠文案判定。
BILI_SUCCESS_WORDS = ("稿件投递成功", "投递成功", "投稿成功",
                      "稿件提交成功", "发布成功", "提交成功",
                      "已进入审核", "审核中")


def blocking(page) -> list[str]:
    out = []
    for sel, name in (("button:has-text('立即投稿')", "立即投稿确认"),
                      ("button:has-text('提交稿件')", "提交稿件确认"),
                      (".semi-modal button:has-text('确定')", "确定弹窗")):
        try:
            if page.locator(sel).first.is_visible(timeout=500):
                out.append(name)
        except Exception:
            pass
    return out


def submit_btn(page):
    """B站真正的提交键：标签是 BUTTON 且文本**精确**为「立即投稿」/「提交稿件」。

    踩过的坑（继承自抖音）：用子串匹配 `has-text('发布')` 会命中左上角
    「作品发布」导航，点完只跳草稿页。所以必须 exact=True。
    这里不再强制 class 含 primary——实测 B 站那个蓝色主按钮的 class
    并不含该串，硬性要求会把真按钮也过滤掉；标签+精确文本已经够严。
    """
    # B 站的「立即投稿」不是 <button>，是 div/span 画的主按钮，
    # 所以不限定标签；但**必须 exact 文本**（子串会命中左侧「作品发布」导航，
    # 这是从抖音继承来的教训）。取纵坐标最大的那个——那才是页面底部的提交键。
    for txt in ("立即投稿", "提交稿件"):
        try:
            loc = page.get_by_text(txt, exact=True)
            best, best_y = None, -1
            for i in range(min(loc.count(), 8)):
                el = loc.nth(i)
                if not el.is_visible(timeout=400):
                    continue
                # 往上一层拿可点的容器
                cand = el
                for _ in range(3):
                    cand = cand.locator("xpath=..")
                    b = cand.bounding_box()
                    if b and b["height"] > 20 and b["width"] > 60:
                        break
                bb = cand.bounding_box() or el.bounding_box()
                if not bb:
                    continue
                if bb["y"] > best_y:
                    best, best_y = cand, bb["y"]
            if best is not None:
                return best, txt
        except Exception:
            continue
    return None, None


def dump_submit_candidates(page) -> None:
    """提交键没找到时，打印页面上所有可见 BUTTON，方便定位。"""
    try:
        btns = page.evaluate("""() => {
          const out=[];
          document.querySelectorAll('button').forEach(el=>{
            const r=el.getBoundingClientRect();
            if(r.width<20||r.height<10) return;
            const cs=getComputedStyle(el);
            if(cs.display==='none'||cs.visibility==='hidden') return;
            out.push({t:(el.innerText||'').trim().slice(0,20),
                      cls:(el.className||'').toString().slice(0,60),
                      dis: el.disabled===true, y:Math.round(r.y)});
          });
          return out;
        }""")
        print(f"   ⚠️ 页面可见 BUTTON 共 {len(btns)} 个：")
        for b in btns:
            print(f"      y={b['y']:5d} disabled={b['dis']} {b['t']!r} cls={b['cls']}")
    except Exception as e:
        print(f"   ⚠️ 诊断失败：{type(e).__name__}")


def dismiss_bili_dialogs(page) -> int:
    """关掉挡路的浮层。返回关掉几个。

    踩过的坑：上传完视频后 B 站弹「开启后视频上传完成第一时间通知」，
    遮罩 class 是 videoup-notification-dialog bcc-dialog__wrap-mask，
    把标题、简介、封面的点击全拦了（element is not stable / intercepts pointer events），
    表现成「封面上传失败」，实际是弹窗挡路。
    另外浏览器级的通知授权框也会叠上来，用 grant_permissions 提前授予就不会弹。
    """
    closed = 0
    for _ in range(4):
        hit = False
        # batch-dialog：上条投稿后表单没重置，再传文件被当成「批量上传」，
        # 弹「批量上传将生成多条动态，打扰粉丝」，遮罩会拦死标题/简介/封面的点击。
        for sel, kws in (
            ("div[class*='videoup-notification-dialog']", ("知道了", "我知道了")),
            ("div[class*='batch-dialog']", ("知道了", "我知道了", "取消", "确定", "关闭")),
            ("div[class*='bcc-dialog__wrap']", ("知道了", "我知道了", "取消", "确定", "关闭")),
        ):
            dlg = page.locator(sel).first
            try:
                if not dlg.is_visible(timeout=800):
                    continue
            except Exception:
                continue
            for kw in kws:
                try:
                    btn = dlg.get_by_text(kw, exact=True).first
                    if not btn.is_visible(timeout=500):
                        continue
                    btn.click(timeout=3000)
                    print(f"      · 已关闭浮层（{kw}）")
                    time.sleep(1.2)
                    closed += 1
                    hit = True
                    break
                except Exception:
                    continue
            if hit:
                break
        if not hit:
            break
    return closed


def set_bili_cover(page, cover_path: str, tag: str, *, log_dir) -> bool:
    """把预制带文字封面设上去。**必须上传成功且裁切框里看得见文字**。

    B 站的封面不是 file input：表单上那个 `* 封面` 是 `div.cover-empty` 的
    「+ 添加封面」占位块，点了才弹出「封面制作」编辑器；编辑器底部才有
    「上传封面 · 拖拽图片或点击上传」，对应 `cover-editor-panel-select-`
    下的 `input[type=file][accept='image/png, image/jpeg']`。
    弹窗里那排缩略图是「智能生成封面 / 系统推荐封面」——**不许用**。

    编辑器有 4:3（首页推荐）和 16:9（个人空间）两个裁切框，两边都得有文字。
    """
    log_dir = Path(log_dir)
    # 1) 打开「添加封面」
    pill = None
    for sel in ("div[class*='cover-empty-pill']", "div[class*='cover-empty']",
                "div[class*='cover-slot']"):
        loc = page.locator(sel).first
        try:
            if loc.is_visible(timeout=1500):
                pill = loc
                break
        except Exception:
            continue
    if pill is None:
        print("      ⚠️ 找不到「添加封面」入口")
        return False
    pill.scroll_into_view_if_needed(); time.sleep(0.8)
    pill.click()
    time.sleep(3.5)

    dlg = page.get_by_text("封面制作", exact=True).first
    try:
        if not dlg.is_visible(timeout=4000):
            print("      ⚠️ 「封面制作」弹窗没开")
            page.screenshot(path=str(log_dir / f"coverfail-bili-{tag}-nomodal.png"))
            return False
    except Exception:
        print("      ⚠️ 「封面制作」弹窗没开")
        return False
    print("      · 已打开「封面制作」")

    # 2) 喂给编辑器里那个图片上传口
    up = page.locator(
        "div[class*='cover-editor-panel-select'] input[type='file']"
    ).first
    try:
        if not up.count():
            up = page.locator("input[type='file'][accept*='image']").first
        up.set_input_files(cover_path, timeout=15000)
        print("      · 封面文件已送入上传口")
    except Exception as e:
        print(f"      ⚠️ 上传口喂不进去：{type(e).__name__}")
        page.screenshot(path=str(log_dir / f"coverfail-bili-{tag}-noup.png"))
        return False
    time.sleep(5)
    page.screenshot(path=str(log_dir / f"bilicov-{tag}-uploaded.png"))

    # 3) 选中新加的那张（它会落在底部胶片条上），否则裁切框仍是旧帧
    try:
        strip = page.locator("div[class*='cover-editor'] img").last
        strip.click(timeout=4000)
        time.sleep(2)
        print("      · 已选中新上传的封面")
    except Exception:
        print("      ⚠️ 没能点中新缩略图（可能上传后已自动选中）")
    time.sleep(1.5)
    page.screenshot(path=str(log_dir / f"bilicov-{tag}-selected.png"))

    # 4) 完成
    done = False
    for kw in ("完成", "确定", "保存"):
        try:
            b = page.get_by_text(kw, exact=True)
            for i in range(min(b.count(), 6)):
                el = b.nth(i)
                if not el.is_visible(timeout=500):
                    continue
                el.click(timeout=5000)
                print(f"      · 已点「{kw}」")
                time.sleep(3)
                done = True
                break
            if done:
                break
        except Exception:
            continue
    if not done:
        print("      ⚠️ 找不到确认键")
        page.screenshot(path=str(log_dir / f"coverfail-bili-{tag}-noconfirm.png"))
        return False

    time.sleep(2)
    # 5) 判据：表单上那个封面位不该还是「添加封面」空块
    still_empty = False
    try:
        still_empty = page.locator("div[class*='cover-empty-pill']").first.is_visible(timeout=2500)
    except Exception:
        pass
    if still_empty:
        print("      ⚠️ 确认后封面位仍是空的 → 未生效")
        page.screenshot(path=str(log_dir / f"coverfail-bili-{tag}-stillempty.png"))
        return False
    print("      ✓ 封面已设置（占位块消失）")
    page.screenshot(path=str(log_dir / f"bilicov-{tag}-done.png"))
    return True


def _js_click(page, locator) -> bool:
    """用 DOM 直接派发 click，绕开 Playwright 的 actionability 检查。

    B 站这两个下拉框有进场动画，Playwright 判定 element is not stable，
    普通 click 会一直重试到超时（栽过）。DOM click 立刻生效。
    """
    try:
        locator.evaluate("e => e.click()")
        return True
    except Exception:
        return False


def set_bili_zone(page, zone: str) -> bool:
    """设主分区。点开下拉 → 在 `human-type-list` 里点目标分区。

    踩过的坑：点左侧「分区」标签文字没用，得点右边显示当前值的框。
    主分区列表容器 class 是 `drop-list-v2-container human-type-list`。
    """
    # 分区框的当前值在 `p.select-item-cont` 里，每次加载可能是 vlog/动物/音乐…
    # 不一样，不能按「当前值文本」反查，直接按容器 class 定位。
    ctl = page.locator("div.video-human-type div.select-controller").first
    try:
        if not ctl.is_visible(timeout=4000):
            print("   ⚠️ 找不到分区选择框")
            return False
        ctl.scroll_into_view_if_needed(); time.sleep(0.6)
    except Exception:
        print("   ⚠️ 找不到分区选择框")
        return False
    if not _js_click(page, ctl):
        return False
    time.sleep(2.2)

    lst = page.locator("div[class*='human-type-list']").first
    try:
        if not lst.is_visible(timeout=2500):
            print("   ⚠️ 主分区列表没弹出来")
            return False
        item = lst.get_by_text(zone, exact=True).first
        item.scroll_into_view_if_needed(); time.sleep(0.4)
        _js_click(page, item)
        time.sleep(2)
    except Exception as e:
        print(f"   ⚠️ 分区选择失败：{type(e).__name__}")
        return False

    # 确认：`.select-item-cont` 的文本应该变成目标分区
    try:
        cur = page.locator("div.video-human-type p.select-item-cont").first
        if cur.is_visible(timeout=2500):
            got = (cur.inner_text() or "").strip()
            if got == zone:
                print(f"   ✓ 分区已设为「{zone}」")
                return True
            print(f"   ⚠️ 分区现在是「{got}」，不是「{zone}」")
            return False
    except Exception:
        pass
    print(f"   ⚠️ 分区没设成「{zone}」")
    return False


def set_bili_statement(page, keywords: tuple[str, ...], *, log_dir) -> str:
    """设创作声明。返回实际选中的文案，没选成返回空串。

    这是对外声明，涉及责任，**选不中就如实报错，绝不跳过**。
    用户 2026-10-06 明确指示：选「自制 / 原创」，不标注 AI 生成。
    """
    log_dir = Path(log_dir)
    # 「请选择符合…」是 input 的 placeholder，不是文本节点，get_by_text
    # 永远找不到；按容器 class 定位。
    sel = page.locator("div.statement-main div.bcc-select").first
    try:
        if not sel.is_visible(timeout=4000):
            print("   ⚠️ 找不到创作声明选择框")
            return ""
        sel.scroll_into_view_if_needed(); time.sleep(0.6)
    except Exception:
        print("   ⚠️ 找不到创作声明选择框")
        return ""
    if not _js_click(page, sel):
        return ""
    time.sleep(2.2)

    # 把浮层里所有可点的选项文本捞出来
    # 创作声明不是下拉浮层，是点开后**内联**在页面上的选项列表，
    # 用 dropdown/popup 那套选择器读不到（栽过）。改成扫视口内可见文本。
    opts = page.evaluate("""() => {
      const out=[];
      document.querySelectorAll('body *').forEach(el=>{
        const r=el.getBoundingClientRect();
        if(r.width<6||r.height<6) return;
        if(r.y<0||r.y>window.innerHeight) return;
        const cs=getComputedStyle(el);
        if(cs.display==='none'||cs.visibility==='hidden') return;
        const own=[...el.childNodes].filter(n=>n.nodeType===3)
                    .map(n=>n.textContent.trim()).join('').trim();
        if(own&&own.length<40&&!out.includes(own)) out.push(own);
      });
      return out;
    }""")
    # 只保留像声明项的（排除导航/栏位等噪声）
    STMT_NOISE = ("主站", "试试更多", "成为UP主", "投稿", "首页", "内容管理",
                  "数据中心", "粉丝管理", "互动管理", "收益管理", "花生",
                  "updream", "创作成长", "任务中心", "必火推广", "创作学院",
                  "创作权益", "社区公约", "创作设置", "添加封面", "以下为系统",
                  "AI生成", "标题", "创作声明", "分区", "标签", "记录",
                  "中国", "歪果仁", "还可以添加", "是否添加内容授权声明",
                  "遇到问题")
    cands = [o for o in opts
             if o not in STMT_NOISE and len(o) >= 4
             and not o.startswith("*") and o not in ("12/80", "80", "7")]
    if not cands:
        print("   ⚠️ 创作声明选项没读到")
        page.screenshot(path=str(log_dir / "bili-stmt-debug.png"))
        return ""
    print(f"   · 创作声明可选：{cands}")
    opts = cands

    inp = page.locator("div.statement-main input.bcc-select-input-inner").first

    def cur_value() -> str:
        try:
            return (inp.input_value(timeout=2000) or "").strip()
        except Exception:
            return ""

    def pick(target: str) -> bool:
        """在已展开的浮层里点中 target，并以「是否回写到 input」为准。"""
        el = None
        for sel in (
            "ul.bcc-select-option-list article.option-hover-tips span.option-text",
            "ul.bcc-select-option-list li.bcc-option span",
        ):
            cand = page.locator(sel).filter(has_text=target)
            try:
                if cand.count():
                    el = cand.first
                    break
            except Exception:
                continue
        if el is None:
            return False
        try:
            el.scroll_into_view_if_needed(); time.sleep(0.3)
            bb = el.bounding_box()
            if not bb:
                return False
            # 真实鼠标点击：JS 合成 click 触发不了 Vue 的选项事件
            page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
            time.sleep(1.5)
        except Exception:
            return False
        return cur_value() == target

    # ① 必填项：必须真的回写到 input 才算数。
    #    「内容为自制…」在**非必选**的版权声明区，勾上它填不满必填框，
    #    点提交会报红字「请添加创作声明」，稿件一条都投不出去。
    want = None
    for kw in keywords:
        for o in opts:
            if kw in o:
                want = o
                break
        if want:
            break
    if not want:
        print(f"   ⚠️ 必填声明选项里没有含 {keywords} 的")
        return ""
    if not pick(want):
        print(f"   ⚠️ 必填声明「{want}」点了但没进框里")
        return ""
    print(f"   ✓ 必填创作声明 = {want}")

    # ② 选填：用户指定的版权声明，勾上但不作必填依据
    try:
        if BILI_STMT_OPTIONAL in opts:
            page.evaluate("e => e.click()",
                          page.locator("div.statement-main div.bcc-select").first)
            time.sleep(1.8)
            o2 = page.evaluate("""() => {
              const out=[];
              document.querySelectorAll('ul.bcc-select-option-list span')
                .forEach(s => { const t=(s.innerText||'').trim();
                                if(t&&!out.includes(t)) out.push(t); });
              return out;
            }""")
            if BILI_STMT_OPTIONAL in o2 and pick(BILI_STMT_OPTIONAL):
                print(f"   ✓ 另勾版权声明：{BILI_STMT_OPTIONAL}")
            else:
                print("   ⚠️ 版权声明没勾上（不影响必填）")
            page.keyboard.press("Escape"); time.sleep(1.2)
        else:
            print("   （浮层里没有版权声明项，跳过）")
    except Exception as e:
        print(f"   ⚠️ 补勾版权声明异常：{type(e).__name__}")

    if cur_value() != want:
        print(f"   ⚠️ 收尾校验：必填框现在是「{cur_value() or '空'}」")
        return ""
    return want

    # ↓↓↓ 以下是原版保留的历史代码（return 之后不可达），只作坑记录搬运 ↓↓↓
    # Vue 的选中逻辑挂在父级 label/li 上。表现是日志打「✓ 已选」、
    # 框里却还是占位符。改成逐级向上点，并以 input 读回值为准。

    def is_selected() -> bool:
        """判断目标项是否处于选中态。

        栽过两次：① 只看 input.value——「内容为自制」这条属于内容授权声明，
        选中后不回写 input，永远读回空；② 找 `.bcc-icon-ic_MenuButton-tick`
        对勾——那个 class 在这条上并没有。

        实际可见的选中特征是**文字变成高亮蓝**。直接比对该项与其余项的
        computed color：不同即视为选中。
        """
        try:
            return bool(page.evaluate("""(want) => {
              const spans = [...document.querySelectorAll(
                'ul.bcc-select-option-list span')];
              if (!spans.length) return false;
              const mine = spans.find(s => (s.innerText||'').trim().includes(want));
              if (!mine) return false;
              const other = spans.find(s => s !== mine
                                        && (s.innerText||'').trim()
                                        && (s.innerText||'').trim() !== want);
              const c1 = getComputedStyle(mine).color;
              const c2 = other ? getComputedStyle(other).color : null;
              const box = mine.closest('li,article');
              const hasSelCls = box ? /selected|active|checked|is-check/i
                                       .test(box.className || '') : false;
              return hasSelCls || (c2 !== null && c1 !== c2);
            }""", want))
        except Exception:
            return False

    def dump_sel() -> None:
        try:
            h = page.evaluate("""(want) => {
              const s = [...document.querySelectorAll(
                'ul.bcc-select-option-list span')]
                .find(x => (x.innerText||'').trim().includes(want));
              if (!s) return '(找不到)';
              const b = s.closest('li,article');
              return (b ? b.outerHTML : s.outerHTML).slice(0,460);
            }""", want)
            print("      · 选中项 HTML:", h)
        except Exception:
            pass

    el = None
    for sel in (
        "ul.bcc-select-option-list article.option-hover-tips span.option-text",
        "ul.bcc-select-option-list li.bcc-option span",
    ):
        cand = page.locator(sel).filter(has_text=want)
        try:
            if cand.count():
                el = cand.first
                break
        except Exception:
            continue
    if el is None:
        print("   ⚠️ 找不到声明选项元素")
        return ""
    try:
        el.scroll_into_view_if_needed(); time.sleep(0.4)
    except Exception as e:
        print(f"   ⚠️ 声明选项定位失败：{type(e).__name__}")
        return ""

    page.screenshot(path=str(log_dir / "bili-stmt-debug.png"))
    return ""
    print(f"   ✓ 创作声明 = {want}")
    return want


def publish_one(page, t: dict, auto: bool, *, log_dir, subs_dir=None) -> dict:
    log_dir = Path(log_dir)
    vid, cov = t["video"], t["cover"]
    res = {"no": t["no"], "lang": t["lang"], "ok": False, "stage": ""}
    print(f"\n🚀 [{t['no']:02d}] {t['lang']}  {Path(vid).name}")
    print(f"   标题: {t['title']}")

    if not Path(vid).exists():
        res["stage"] = "素材缺失"; print("   ❌ 视频不存在"); return res

    # 每条都**强制**重新导航到投稿页，不能只在 URL 不含 upload 时才刷。
    # 否则上条投稿后表单还留着旧视频，再送一个文件会被 B 站当成「批量上传」，
    # 弹出 batch-dialog 遮罩，后面标题/简介/封面的点击全被拦死。
    page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    # 视频：挑第一个非 .txt 的 file input
    fis = page.locator("input[type='file']")
    vinput = None
    for i in range(fis.count()):
        acc = fis.nth(i).get_attribute("accept") or ""
        if ".mp4" in acc:
            vinput = fis.nth(i); break
    if vinput is None and fis.count():
        vinput = fis.first
    vinput.set_input_files(vid)
    print("   ✓ 视频已送入上传通道")
    # 批量上传弹窗往往在送入文件后才冒出来，先清一轮
    for _ in range(2):
        time.sleep(2)
        dismiss_bili_dialogs(page)

    # 等上传完成：出现标题输入框
    title_box = None
    for _ in range(120):
        for sel in ("input[placeholder*='标题']", "input[maxlength='80']"):
            loc = page.locator(sel).first
            try:
                if loc.is_visible(timeout=600):
                    title_box = loc; break
            except Exception:
                continue
        if title_box:
            break
        time.sleep(1.5)
    if title_box is None:
        res["stage"] = "上传/表单未就绪"; print("   ❌ 标题框未出现（上传可能失败）")
        return res
    print("   ✓ 上传完成，编辑表单就绪")

    # 通知弹窗会盖住整个表单，先清干净再动输入框
    n = dismiss_bili_dialogs(page)
    if n:
        print(f"   ✓ 已清掉 {n} 个浮层")

    # 标题
    try:
        title_box.click()
        title_box.fill(t["title"][:80])
        print(f"   ✓ 标题已录入（{len(t['title'][:80])} 字）")
    except Exception as e:
        print(f"   ⚠️ 标题：{e}")

    # 必填项：分区 + 创作声明（B 站不填这两个 投稿键不解禁）
    zone_ok = set_bili_zone(page, BILI_ZONE)
    stmt = set_bili_statement(page, BILI_STMT_REQUIRED, log_dir=log_dir)
    if not stmt:
        res["stage"] = "创作声明未选定（已中止投稿）"
        print("   🛑 创作声明没选上 → 中止，不投")
        try:
            page.screenshot(path=str(log_dir / f"coverfail-bili-{t['no']:02d}-stmt.png"))
        except Exception:
            pass
        return res

    # 简介：B站正文是 contenteditable
    desc = page.locator(
        "div[contenteditable='true'], textarea[placeholder*='简介'], "
        "div.editor-kit-editor, .ql-editor"
    ).first
    try:
        if desc.is_visible(timeout=2500):
            desc.click()
            page.keyboard.press("Meta+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(t["body"])
            page.keyboard.type("\n\n")
            time.sleep(0.3)
            for tag in t["tags"]:
                page.keyboard.type(tag if tag.startswith("#") else f"#{tag}")
                page.keyboard.type(" ")
                time.sleep(0.3)
            print(f"   ✓ 简介与 {len(t['tags'])} 个话题已录入")
        else:
            print("   ⚠️ 没找到简介框")
    except Exception as e:
        print(f"   ⚠️ 简介：{e}")

    # 字幕：.txt file input（文件从 subs_dir/{lang}.txt 取，参数化不写死）
    txtf = None
    for i in range(page.locator("input[type='file']").count()):
        f = page.locator("input[type='file']").nth(i)
        try:
            if (f.get_attribute("accept") or "") == ".txt":
                txtf = f; break
        except Exception:
            pass
    if txtf is not None and subs_dir is not None:
        srt = Path(subs_dir) / f"{t['lang']}.txt"
        if srt.exists():
            try:
                txtf.set_input_files(str(srt))
                print(f"   ✓ 字幕已上传 {srt.name}")
            except Exception as e:
                print(f"   ⚠️ 字幕：{e}")
        else:
            print(f"   （无字幕文件 {srt.name}，跳过）")
    else:
        print("   （未找到 .txt 字幕口，跳过）" if txtf is None
              else "   （未给 subs_dir，跳过字幕）")

    # 封面：必须换成预制带文字版（PUBLISH-RULES.md 规则 1）。
    # 不允许用「系统推荐封面 / AI 生成封面」，也不允许退回视频首帧。
    cover_ok = set_bili_cover(page, cov, f"{t['no']:02d}", log_dir=log_dir)

    # 硬闸门：封面没换上就整条不投
    if not cover_ok:
        res["stage"] = "封面未生效（已中止投稿）"
        print("   🛑 封面未生效 → 中止本条，不点投稿")
        print(f"      预制封面：{cov}")
        try:
            page.screenshot(path=str(log_dir / f"coverfail-bili-{t['no']:02d}.png"))
        except Exception:
            pass
        return res
    print("   ✓ 封面已是预制带文字版，继续")

    # 等投稿按钮解禁
    print("   ⏳ 等待提交按钮解禁…")
    ok = False
    for _ in range(90):
        el, txt = submit_btn(page)
        if el is not None and el.get_attribute("disabled") is None:
            ok = True
            print(f"   ✓ 提交键「{txt}」已可用")
            break
        time.sleep(1)
    if not ok:
        res["stage"] = "提交按钮未就绪"; print("   ❌ 提交按钮未就绪")
        dump_submit_candidates(page)
        try:
            page.screenshot(path=str(log_dir / f"coverfail-bili-{t['no']:02d}-submit.png"))
        except Exception:
            pass
        return res

    if not auto:
        page.screenshot(path=str(log_dir / f"dryrun-bili-{t['no']:02d}.png"))
        left = blocking(page)
        res.update(ok=not left, stage="已填词(dry-run，未发布)" if not left else f"残留弹窗 {left}")
        print(f"   🧪 dry-run：未发布。截图 dryrun-bili-{t['no']:02d}.png")
        return res

    el, txt = submit_btn(page)
    el.scroll_into_view_if_needed(); time.sleep(0.5)
    el.click()
    print(f"   ✅ 已点「{txt}」")
    time.sleep(4)
    page.screenshot(path=str(log_dir / f"postbili-{t['no']:02d}.png"))

    # ⚠️ 点「立即投稿」之后**还有一道二次确认**，不点等于没投。
    # 栽过：2026-10-06 首轮 11 条全卡在这，稿件管理里一条都没有，
    # 而汇总只打「已提交未确认」。这里把可能的确认键全试一遍。
    for kw2 in ("确认投稿", "确定", "确认", "提交稿件", "知道了", "完成"):
        try:
            b = page.get_by_text(kw2, exact=True)
            for i in range(min(b.count(), 6)):
                el = b.nth(i)
                if not el.is_visible(timeout=500):
                    continue
                el.scroll_into_view_if_needed(); time.sleep(0.3)
                if _js_click(page, el):
                    print(f"      · 已点二次确认「{kw2}」")
                    time.sleep(3)
                    break
            else:
                continue
            break
        except Exception:
            continue
    time.sleep(2)
    page.screenshot(path=str(log_dir / f"postbili-{t['no']:02d}-confirm.png"))

    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            tip = page.inner_text("body", timeout=8000)
            # B 站成功页文案是「**稿件投递成功**」，不是「投稿/提交成功」。
            # 栽过：词表里没有「投递」二字，脚本判成「已提交未确认」，
            # 实际稿件早就进管理后台了。URL 也不会变，只能靠文案判定。
            if any(k in tip for k in BILI_SUCCESS_WORDS):
                res.update(ok=True, stage="已发布")
                print("   ✅ 投稿成功")
                return res
        except Exception:
            pass
        if "upload" not in page.url and "frame" not in page.url:
            res.update(ok=True, stage="已跳转")
            print(f"   ✅ 已跳转 {page.url}")
            return res
        time.sleep(2)

    res["stage"] = "已提交未确认"
    print(f"   ⚠️ 已提交但未确认，URL={page.url}")
    return res


def publish(tasks, *, profile_dir=None, log_dir, subs_dir=None, only=None,
            frm=None, dry_run=0, headless=False) -> int:
    """批量投稿（骨架在 base.run_tasks：异常隔离 + 循环内节流 + result JSON）。"""
    tasks = base.filter_tasks(tasks, only, frm)
    profile_dir = profile_dir or base.profile_dir("bilibili")

    with base.launch(profile_dir, headless=headless,
                     viewport={"width": 1600, "height": 1000}) as (ctx, page):
        # 提前授予通知权限，否则上传完会弹浏览器级授权框盖住整个表单
        try:
            ctx.grant_permissions(["notifications"], origin="https://member.bilibili.com")
            print("✓ 已授予通知权限（避免上传完成弹授权框）")
        except Exception as e:
            print(f"⚠️ 授予通知权限失败：{type(e).__name__}")
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)
        if base.login_wall(page, BILI_WALL):
            print("⚠️ B站未登录，请在弹出的 Chrome 窗口扫码")
            if not base.wait_login(page, 600, kws=BILI_WALL):
                print("❌ 登录超时"); return 1
        print("✅ B站创作中心就绪\n")

        def one(page, t, auto, *, log_dir):
            return publish_one(page, t, auto, log_dir=log_dir, subs_dir=subs_dir)

        results = base.run_tasks(page, tasks, one, upload_url=UPLOAD_URL,
                                  log_dir=log_dir, between_s=4, dry_run=dry_run,
                                  result_json="publish-bilibili-result.json")
    return base.summarize(results, "B站")
