# -*- coding: utf-8 -*-
"""xhs.py — 小红书发布器（⑨）：像素探测发布键 + 风控停等 + 每条 reset_page

搬运自 yiyezhiqiu/scripts/publish_xhs_yyzq.py（函数体逐字节照搬，坑注释一字不动）。

**已核实缺陷的修复**（逐条指认）：
- ① **防风控节流写在循环外**（publish_xhs_yyzq.main 原版：循环结束后才
  `time.sleep(35)`，注释却写「每条之间多歇一会儿」——整批只睡了最后一次）。
  修复：publish() 走 `base.run_tasks(between_s=35)`，节流在循环**内**、
  每条之间都睡（实测教训：连发 2 条就撞风控）。
- ③ 写死的 Chrome 绝对路径 → `base.launch`（resolver，见 base.resolve_chrome）。

**发布键为什么用像素探测**：底栏「发布」不在主文档流里（get_by_text /
querySelectorAll / elementFromPoint 全扫不到，很可能是跨源 iframe 合成层），
唯一可信的证据就是**真实像素**——品牌红 #FF2442 的实心药丸（见 submit_btn 注释）。

**使用契约**：
- tasks 是 `feuille.manifest.build_manifest` 的产物；profile 默认
  `base.PROFILES["xiaohongshu"]`；截图与 result JSON 全部落 log_dir。
- 封面是硬闸门：换不上预制带文字版就整条不发（纪律 19，PUBLISH-RULES 规则 1）。
- 风控撞上**绝不自动重试**（纪律 21）：停下等你本人扫码，解除后确认遮罩消失。

用法：
    from feuille.publish import xhs
    xhs.publish(tasks, log_dir="build")
    xhs.publish(tasks, log_dir="build", only="1,7", dry_run=1)
"""
from __future__ import annotations

import time
from pathlib import Path

from . import base

UPLOAD_URL = "https://creator.xiaohongshu.com/publish/publish"

# 小红书登录墙/风控/成功词表（publish_xhs_yyzq 实测词表）
XHS_WALL = ("扫码登录", "验证码登录", "手机号登录", "立即登录")
XHS_SUCCESS_WORDS = ("发布成功", "提交成功", "笔记已发布")

_LAST_HINT = ""   # 抑制重复的「未找到」噪音


def reset_page(page, label: str = "") -> bool:
    """每条开始前强制回到干净的投稿页。

    这不是洁癖，是实测踩出来的坑：风控「Scan to verify」弹窗扫完之后，
    页面会留下一层 `d-modal-mask` + WebGL canvas 不消失，把后续所有点击
    都拦下来（Playwright 报 'intercepts pointer events'）。原先只在
    URL 不匹配时才 goto，于是脏状态跨条污染——第 5 条的编辑器里躺着的
    还是第 3 条的德语封面。
    """
    for attempt in range(3):
        try:
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"   ⚠️ 重置导航失败 {type(e).__name__}")
            time.sleep(3)
            continue
        time.sleep(6)
        blocked = base.modal_mask(page)
        if not blocked or blocked.get("disp") == "none" or blocked.get("w", 0) < 50:
            return True
        print(f"   ⚠️ 残留遮罩 {blocked}{' ' + label if label else ''}，重置第 {attempt+1} 次")
        page.keyboard.press("Escape")
        time.sleep(1.5)
    return False


def pick_tab(page, name: str) -> bool:
    """切到「上传视频」页签。小红书默认可能是图文页。"""
    try:
        loc = page.get_by_text(name, exact=True)
        for i in range(min(loc.count(), 6)):
            el = loc.nth(i)
            if el.is_visible(timeout=800):
                el.click()
                time.sleep(3)
                return True
    except Exception:
        pass
    return False


def _pixel_probe(page, b64: str) -> dict:
    """把 Playwright 截图喂回浏览器，用 canvas 解码，量底栏的品牌红像素。

    为什么要绕这一圈：底栏「发布」既不在主文档流里（elementsFromPoint /
    querySelectorAll / get_by_text 全部扫不到，很可能是跨源 iframe 合成层），
    但 Playwright 截图能合成出来。所以唯一可信的证据就是**真实像素**。
    这里不依赖 PIL（Playwright 那个解释器没装），改用浏览器自带的 canvas。
    """
    return page.evaluate("""async (b64) => {
      const img = new Image();
      img.src = 'data:image/png;base64,' + b64;
      try { await img.decode(); } catch (e) { return {err: 'decode:' + e}; }
      const c = document.createElement('canvas');
      c.width = img.width; c.height = img.height;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      const H = c.height, W = c.width;
      const y0 = Math.max(0, H - 90), y1 = H - 2;
      const d = ctx.getImageData(0, y0, W, y1 - y0).data;
      const iw = W, ih = y1 - y0;
      // 小红书品牌红 #FF2442
      let n = 0, minx = 1e9, maxx = -1, miny = 1e9, maxy = -1;
      for (let y = 0; y < ih; y++) {
        for (let x = 0; x < iw; x++) {
          const o = (y * iw + x) * 4;
          const r = d[o], g = d[o+1], b = d[o+2];
          if (r > 220 && g < 90 && b < 105 && (r - g) > 140) {
            n++;
            if (x < minx) minx = x;
            if (x > maxx) maxx = x;
            if (y < miny) miny = y;
            if (y > maxy) maxy = y;
          }
        }
      }
      return { W, H, n, scanY: [y0, y1] };
    }""", b64)


def find_red_button(page) -> tuple | None:
    """在底栏里框出品牌红药丸，返回 (中心x, 中心y, 红像素数, 包围盒)。"""
    import base64
    shot = page.screenshot()
    info = _pixel_probe(page, base64.b64encode(shot).decode())
    if info.get("err"):
        print(f"   ⚠️ 截图解码失败 {info['err']}")
        return None
    n = info.get("n", 0)
    if n < 800:                      # 太小说明不是那颗实心药丸
        global _LAST_HINT
        msg = f"底栏红像素 {n}（阈值 800）"
        if msg != _LAST_HINT:
            print(f"   · {msg}，不认定")
            _LAST_HINT = msg
        return None

    # 用第二次扫描取出精确包围盒
    shot2 = page.screenshot()
    b64 = base64.b64encode(shot2).decode()
    box = page.evaluate("""async (b64) => {
      const img = new Image();
      img.src = 'data:image/png;base64,' + b64;
      await img.decode();
      const c = document.createElement('canvas');
      c.width = img.width; c.height = img.height;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      const H = c.height, W = c.width, y0 = Math.max(0, H - 90), ih = H - 2 - y0;
      const d = ctx.getImageData(0, y0, W, ih).data;
      const pts = [];
      for (let y = 0; y < ih; y++) for (let x = 0; x < W; x++) {
        const o = (y * W + x) * 4, r = d[o], g = d[o+1], b = d[o+2];
        if (r > 220 && g < 90 && b < 105 && (r - g) > 140) pts.push([x, y + y0]);
      }
      if (!pts.length) return null;
      const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
      return { x0: Math.min(...xs), x1: Math.max(...xs),
               y0: Math.min(...ys), y1: Math.max(...ys), n: pts.length };
    }""", b64)
    if not box:
        return None
    cx = (box["x0"] + box["x1"]) // 2
    cy = (box["y0"] + box["y1"]) // 2
    bw, bh = box["x1"] - box["x0"], box["y1"] - box["y0"]
    if bw < 60 or bh < 24 or bw > 300 or bh > 80:
        print(f"   · 红块尺寸 {bw}x{bh} 不像按钮，不认定")
        return None
    return cx, cy, box["n"], (box["x0"], box["y0"], box["x1"], box["y1"])


def submit_btn(page):
    """发布键：底栏右侧的小红书红药丸「发布」。

    这个按钮的怪癖（连踩五轮实测）：
      - `get_by_text('发布')` count=0
      - `querySelectorAll('*')` 全文遍历也找不到
      - `document.elementFromPoint` 在视口底部扫不到
      → 它不在主文档的可命中区域里（很可能是跨源 iframe / 合成层），
        但 Playwright 截图能合成出来。
    所以唯一可信的判据是**真实像素**：在底栏找品牌红 #FF2442 的实心药丸。
    找不到就不点，宁可不发布。
    """
    # 先试文本（万一以后 DOM 改了能命中）
    for cand in ("发布", "提交"):
        try:
            loc = page.get_by_text(cand, exact=True)
            for i in range(min(loc.count(), 8)):
                el = loc.nth(i)
                if not el.is_visible(timeout=400):
                    continue
                b = el.bounding_box()
                if b and b["x"] > 400 and b["y"] > 600:
                    return ("loc", el), cand
        except Exception:
            continue

    r = find_red_button(page)
    if r is None:
        return None, None
    cx, cy, n, box = r
    print(f"   · 像素命中：红色药丸 {box[2]-box[0]}x{box[3]-box[1]} "
          f"@({cx},{cy}) 红像素 {n}")
    return ("xy", (cx, cy)), "发布"


def blocking(page) -> list[str]:
    out = []
    for sel, name in ((".semi-modal button:has-text('确定')", "确定弹窗"),
                      ("button:has-text('去发布')", "去发布提示")):
        try:
            if page.locator(sel).first.is_visible(timeout=500):
                out.append(name)
        except Exception:
            pass
    return out


def pick_cover(cov: str, *, alt_dir: str = "covers-3x4",
               from_size: str = "1080x1920", to_size: str = "1080x1440") -> str:
    """小红书封面画布是 3:4。优先用预裁好的 3:4 版（零裁切，位置与裁切审计一致），
    没有就退回 9:16 原图让平台自己适配。

    alt_dir/from_size/to_size 是**调用方**的素材目录约定（原项目 yiyezhiqiu
    的布局：封面 9:16 与预裁 3:4 分放两个目录、同名不同尺寸后缀），参数化不写死。
    """
    p = Path(cov)
    alt = p.parent.parent / alt_dir / p.name.replace(f"_{from_size}.png", f"_{to_size}.png")
    return str(alt) if alt.exists() else cov


def set_xhs_cover(page, cov: str) -> bool:
    """换封面：hover 缩略图 → 点「编辑封面」→ 「+ 上传」喂预制图 → 「完成」。

    真实结构（probe_xhs_cover4.py 实测）：
      .default--ai-cover-layout  封面缩略图（默认是纯叶子的视频首帧）
      .cover-edit-entry          hover 才显形的「编辑封面」按钮
      .upload-slot > .upload-label「上传」  编辑器底部「+ 上传」
      input[type=file][accept*=image]     编辑器打开后才动态挂上
      「完成」按钮
    注意：编辑器里还有「✨生成封面」「✨获取封面建议」两个 AI 入口，一律不碰。
    """
    # 1) 滚到封面区
    page.evaluate("""() => {
        const t = document.querySelector('.cover-plugin-title');
        if (t) t.scrollIntoView({block: 'center'});
    }""")
    time.sleep(1.2)

    thumb = page.locator(".default--ai-cover-layout").first
    try:
        tb = thumb.bounding_box(timeout=8000)
    except Exception as e:
        print(f"   ⚠️ 封面缩略图没出现：{type(e).__name__}")
        return False
    if not tb:
        print("   ⚠️ 封面缩略图无尺寸")
        return False

    # 2) hover 让「编辑封面」显形，再点它
    page.mouse.move(tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] / 2)
    time.sleep(1.0)
    entry = page.locator(".cover-edit-entry").first
    try:
        eb = entry.bounding_box(timeout=4000)
    except Exception:
        eb = None
    if not eb:
        print("   ⚠️ hover 后「编辑封面」未显形")
        return False
    page.mouse.move(eb["x"] + eb["width"] / 2, eb["y"] + eb["height"] / 2)
    time.sleep(0.3)
    page.mouse.click(eb["x"] + eb["width"] / 2, eb["y"] + eb["height"] / 2)
    print("   ✓ 打开封面编辑器")

    # 3) 等编辑器里的图片 file input 挂上来
    img_in = page.locator("input[type='file'][accept*='image']").first
    try:
        img_in.wait_for(state="attached", timeout=15000)
    except Exception:
        print("   ⚠️ 编辑器里没出现图片上传口")
        return False
    time.sleep(1.0)
    img_in.set_input_files(cov)
    print(f"   ✓ 预制封面已送入 {Path(cov).name}")
    time.sleep(4.0)

    # 4) 「完成」
    for kw in ("完成", "确定", "保存"):
        loc = page.get_by_text(kw, exact=True)
        for i in range(min(loc.count(), 6)):
            el = loc.nth(i)
            try:
                if not el.is_visible(timeout=500):
                    continue
                b = el.bounding_box()
                if not b or b["y"] < 600:   # 「完成」在编辑器右下角
                    continue
                el.click()
                print(f"   ✓ 点「{kw}」关闭编辑器")
                time.sleep(2.5)
                return True
            except Exception:
                continue
    print("   ⚠️ 找不到「完成」键，封面可能未落库")
    return False


def republish_after_reset(page, t: dict) -> bool:
    """重置页面后重走上传 + 填词（封面重试用）。"""
    vid = t["video"]
    try:
        pick_tab(page, "上传视频")
        fis = page.locator("input[type='file']").first
        fis.set_input_files(vid)
        tb = page.locator("input[placeholder*='标题']").first
        for _ in range(140):
            if tb.is_visible(timeout=600):
                break
            time.sleep(1.5)
        else:
            return False
        for kw in ("我知道了", "知道了"):
            loc = page.get_by_text(kw, exact=True)
            for i in range(min(loc.count(), 3)):
                try:
                    if loc.nth(i).is_visible(timeout=500):
                        loc.nth(i).click(); time.sleep(1.2)
                except Exception:
                    pass
        tb.click(); tb.fill(t["title"][:20])
        body = page.locator(
            "div[contenteditable='true'], textarea, .ql-editor, "
            "div[placeholder*='正文'], div[data-placeholder*='正文']").first
        if body.is_visible(timeout=3000):
            body.click()
            page.keyboard.press("Meta+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(t["body"])
            time.sleep(0.5)
        print("   ✓ 重置后已重填标题/正文")
        return True
    except Exception as e:
        print(f"   ⚠️ 重填失败 {type(e).__name__}: {str(e)[:80]}")
        return False


def publish_one(page, t: dict, auto: bool, *, log_dir) -> dict:
    log_dir = Path(log_dir)
    vid = t["video"]
    cov = pick_cover(t["cover"])
    res = {"no": t["no"], "lang": t["lang"], "ok": False, "stage": ""}
    print(f"\n🚀 [{t['no']:02d}] {t['lang']}  {Path(vid).name}")
    print(f"   标题: {t['title']}")

    if not Path(vid).exists():
        res["stage"] = "素材缺失"; print("   ❌ 视频不存在"); return res

    # 每条都强制回到干净投稿页（脏状态会跨条污染，见 reset_page 注释）
    if not reset_page(page, f"[{t['no']:02d}]"):
        res["stage"] = "页面重置失败"
        print("   ❌ 页面重置失败，放弃本条")
        return res
    pick_tab(page, "上传视频")

    fis = page.locator("input[type='file']")
    if fis.count() == 0:
        res["stage"] = "无上传控件"; print("   ❌ 没有 file input"); return res
    fis.first.set_input_files(vid)
    print("   ✓ 视频已送入上传通道")

    # 等标题框（上传+校验完成）
    title_box = None
    for _ in range(140):
        for sel in ("input[placeholder*='标题']", "input[placeholder*='写标题']"):
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
        res["stage"] = "上传/表单未就绪"; print("   ❌ 标题框未出现")
        return res
    print("   ✓ 上传完成，编辑表单就绪")

    try:
        title_box.click()
        title_box.fill(t["title"][:20])   # 小红书标题上限 20
        print(f"   ✓ 标题已录入（{len(t['title'][:20])}/20）")
    except Exception as e:
        print(f"   ⚠️ 标题：{e}")

    # 正文：话题已在 body 末行，整体一次填入
    body = page.locator(
        "div[contenteditable='true'], textarea, .ql-editor, "
        "div[placeholder*='正文'], div[data-placeholder*='正文']"
    ).first
    try:
        if body.is_visible(timeout=3000):
            body.click()
            page.keyboard.press("Meta+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(t["body"])
            time.sleep(0.5)
            print("   ✓ 正文已录入（含末行话题）")
        else:
            print("   ⚠️ 没找到正文框")
    except Exception as e:
        print(f"   ⚠️ 正文：{e}")

    # 封面：必须换成预制带文字版（PUBLISH-RULES.md 规则 1）。
    # 小红书默认截视频第一帧，那是纯叶子的画面，不算封面。
    cover_ok = set_xhs_cover(page, cov)
    if not cover_ok:
        # 编辑器开不出来通常是脏状态残留，重置一次再来
        print("   ⚠️ 封面首次失败，重置页面重试一次")
        try:
            page.keyboard.press("Escape"); time.sleep(1.5)
        except Exception:
            pass
        if reset_page(page, f"[{t['no']:02d}] 封面重试"):
            # 重置后要重走一遍上传与填词
            if republish_after_reset(page, t):
                cover_ok = set_xhs_cover(page, cov)

    # 硬闸门：封面没换上就整条不发
    if not cover_ok:
        res["stage"] = "封面未生效（已中止发布）"
        print("   🛑 封面未生效 → 中止本条，不点发布")
        print(f"      预制封面：{cov}")
        try:
            page.screenshot(path=str(log_dir / f"coverfail-xhs-{t['no']:02d}.png"))
        except Exception:
            pass
        return res
    print("   ✓ 封面已是预制带文字版，继续")

    print("   ⏳ 等待发布键解禁…")
    btn = txt = None
    for k in range(24):
        btn, txt = submit_btn(page)
        if btn is not None:
            print(f"   ✓ 发布键「{txt}」已就绪"); break
        if k == 6:
            # 底栏有时懒渲染，滚到底再试
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
        time.sleep(2.5)
    if btn is None:
        res["stage"] = "发布键未就绪"
        print("   ❌ 找不到可用的发布键")
        try:
            page.screenshot(path=str(log_dir / f"nobtn-xhs-{t['no']:02d}.png"))
            print(f"      frame 数={len(page.frames)}  innerH={page.evaluate('window.innerHeight')}"
                  f"  scrollY={page.evaluate('window.scrollY')}")
            for fr in page.frames:
                try:
                    hits = fr.evaluate("""() => {
                      const out=[];
                      document.querySelectorAll('*').forEach(e=>{
                        const t=(e.textContent||'').trim();
                        if (!/^发布$|^暂存离开$|^发布\\s*$/.test(t) && t!=='发布') return;
                        const r=e.getBoundingClientRect();
                        const cs=getComputedStyle(e);
                        out.push({t, tag:e.tagName,
                          cls:(e.className||'').toString().slice(0,130),
                          box:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)],
                          pos:cs.position, vis:cs.visibility, disp:cs.display, opa:cs.opacity,
                          path:(()=>{let s=[],n=e;for(let i=0;i<6&&n;i++){
                            s.push(n.tagName+(typeof n.className==='string'&&n.className
                              ?'.'+n.className.split(' ').filter(Boolean).slice(0,2).join('.') :''));n=n.parentElement;}
                            return s.join(' < ');})()});
                      });
                      return out;
                    }""")
                except Exception:
                    hits = []
                for h in hits:
                    print(f"      [{fr.url.rsplit('/', 1)[-1][:28]}|{h['tag']}] 「{h['t']}」 "
                          f"box={h['box']} pos={h['pos']} vis={h['vis']} disp={h['disp']} opa={h['opa']}")
                    print(f"          cls={h['cls'][:100]}")
                    print(f"          path={h['path'][:190]}")
        except Exception as e:
            print("      诊断异常", type(e).__name__, e)
        return res

    if not auto:
        page.screenshot(path=str(log_dir / f"dryrun-xhs-{t['no']:02d}.png"))
        left = blocking(page)
        res.update(ok=not left, stage="已填词(dry-run，未发布)" if not left else f"残留弹窗 {left}")
        print(f"   🧪 dry-run：未发布。截图 dryrun-xhs-{t['no']:02d}.png")
        return res

    kind, payload = btn
    if kind == "xy":
        page.mouse.click(payload[0], payload[1])
    else:
        payload.scroll_into_view_if_needed(); time.sleep(0.5)
        payload.click()
    print(f"   ✅ 已点「{txt}」")
    time.sleep(4)
    page.screenshot(path=str(log_dir / f"postxhs-{t['no']:02d}.png"))

    # 风控检测：撞上就停下来等用户扫码，不自动重试
    if base.risk_hit(page):
        if not base.wait_risk_clear(page, no=t["no"], log_dir=log_dir,
                                    hint="用 REDnote APP 扫码",
                                    reset=lambda pg: reset_page(pg, "风控后")):
            res["stage"] = "风控未解除（已中止）"
            return res
        time.sleep(3)
        page.screenshot(path=str(log_dir / f"postxhs-{t['no']:02d}.png"))

    if base.wait_success(page, XHS_SUCCESS_WORDS):
        res.update(ok=True, stage="已发布")
        print("   ✅ 发布成功"); return res

    res["stage"] = "已提交未确认"
    print(f"   ⚠️ 已提交但未确认，URL={page.url}")
    return res


def publish(tasks, *, profile_dir=None, log_dir, only=None, frm=None,
            dry_run=0, headless=False) -> int:
    """批量发布。**节流在循环内**（缺陷①修复）：between_s=35，每条之间都歇。"""
    tasks = base.filter_tasks(tasks, only, frm)
    profile_dir = profile_dir or base.profile_dir("xiaohongshu")

    with base.launch(profile_dir, headless=headless,
                     viewport={"width": 1600, "height": 1000}) as (ctx, page):
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(6)
        if base.login_wall(page, XHS_WALL):
            print("⚠️ 小红书未登录，请在弹出的 Chrome 窗口扫码")
            if not base.wait_login(page, 600, kws=XHS_WALL):
                print("❌ 登录超时"); return 1
        print("✅ 小红书创作服务平台就绪\n")

        results = base.run_tasks(page, tasks, publish_one, upload_url=UPLOAD_URL,
                                 log_dir=log_dir, between_s=35, dry_run=dry_run,
                                 result_json="publish-xhs-result.json")
    return base.summarize(results, "小红书")


# ── CLI 适配层（cli.py 路由叶子；业务在 publish()，这里只接线） ────────


def main(argv=None) -> int:
    """cli.py 路由入口：`feuille publish xhs <manifest.json> --log-dir D`。

    manifest.json = plans 契约经 `feuille.manifest.build_manifest` 落盘的清单，
    本入口取其中的 "xiaohongshu" 段作为 tasks。
    """
    import argparse
    import json
    ap = argparse.ArgumentParser(prog="feuille publish xhs")
    ap.add_argument("manifest", help="build_manifest 落盘的清单 JSON")
    ap.add_argument("--log-dir", required=True,
                    help="每条的过程截图 / result JSON 落盘目录")
    ap.add_argument("--only", default=None, help="只发指定序号（如 1,7；续跑用）")
    ap.add_argument("--frm", type=int, default=None, help="从指定序号起发")
    ap.add_argument("--dry-run", type=int, default=0, help="只走前 N 条的干跑")
    ap.add_argument("--headless", action="store_true")
    a = ap.parse_args(argv)
    tasks = json.loads(Path(a.manifest).read_text("utf-8"))["xiaohongshu"]
    return publish(tasks, log_dir=a.log_dir, only=a.only, frm=a.frm,
                   dry_run=a.dry_run, headless=a.headless)
