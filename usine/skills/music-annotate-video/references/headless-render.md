# Headless 截图旗标（本产线唯一清单）

> 为什么单独一篇：工作区的 `plugin-parity` 机检把 `SKILL.md` 里所有 `--xxx`
> 当成 `feuille` CLI 旗标核对。浏览器旗标不是 CLI 旗标，写进 SKILL 会被判
> 「旗标不存在」。所以精确清单落在这里，SKILL.md 只指路。

## 命令

```bash
"<浏览器可执行文件>" \
  --headless=new \
  --disable-gpu \
  --use-mock-keychain \
  --password-store=basic \
  --force-device-scale-factor=1 \
  --hide-scrollbars \
  --virtual-time-budget=10000 \
  --window-size=1920,1080 \
  --screenshot="<输出 PNG 的绝对路径>" \
  "file:///<页面绝对路径>?scene=A&state=2&ph=26.4"
```

`<浏览器可执行文件>` 来自 `@feuille/core` 的 `platform.browserPath()`
（Edge 优先，Chrome 次选；`$CHROME_BIN` 可显式覆盖）。不要把路径写进脚本。

## 每条旗标为什么在

| 旗标 | 作用 | 去掉会怎样 |
|---|---|---|
| `--headless=new` | 新 headless 模式 | 旧 `--headless` 会抢占已开着的桌面浏览器 |
| `--disable-gpu` | 关 GPU 路径 | 不同机器光栅化不一致 |
| `--use-mock-keychain` | 不碰真实钥匙串 | 隔离 HOME 下首启挂起，Edge 以 2 退出 |
| `--password-store=basic` | 同上 | 同上 |
| `--force-device-scale-factor=1` | 钉 1x 缩放 | 截图随系统缩放漂移（HiDPI 上尤其明显） |
| `--hide-scrollbars` | 隐藏滚动条 | 排版宽度 ≠ 窗口宽，补偿宽度算错 |
| `--virtual-time-budget=10000` | 等页面 JS 跑完 | 截图抓到半渲染（空纸/缺数据） |
| `--window-size=W,H` | 精确画幅 | 默认窗口尺寸，画面被裁 |

## 绝对不要加

- **`user-data-dir`**：macOS + Edge 实测图能出但**进程永不退出**，整个 build
  挂死（`usine/AGENTS.md:104`；实现见 `packages/karaoke/src/build_video.ts`
  的 `renderChrome`）。`--headless=new` 不会抢占桌面浏览器，不需要这个隔离。
- 相对路径的 `file://` URL：会被当成主机名，Chrome fallback 到 Google 搜索页。
  URL 一律绝对路径。

## 截图后的哨兵

1. 立刻跑含墨扫描（`assets/template/ink-scan.mjs`）。阈值 0.2%，暖纸空页 0%
   必 FAIL。
2. 同场景不同 state 的 PNG 字节数如果完全相等，先怀疑 TDZ/空纸
   （traps §5），再用含墨扫描确认。
3. 每场景每个同步点抽帧人眼复核——机器绿不等于画面对。
