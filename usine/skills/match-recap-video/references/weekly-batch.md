# 周更多队产线（一次做完「本周五强」的成片）

「本周五支球队各出一支集锦解说」是这条产线的**周期性需求**，不是一次性的：默认阵容五队
（意甲 AC米兰 / 西甲 巴塞罗那 / 英超 利物浦 / 德甲 多特蒙德 / 法甲 巴黎圣日耳曼），
加上跨赛事口径（欧冠 / 欧联），一个自然周里可能有 4–5 场要同时做。2026-11-08 首轮
实跑（欧冠第 4 轮 × 4 + 欧联第 4 轮 × 1，母版 98–246s，成片 11–14 窗）把流程与坑
固化在这里。**单支队的作业细节（探针 → 映射 → 窗口表 → 机检 → TTS → 装配）以
SKILL.md 为准**，本文只写「多队并发」新增的东西。

## 口径先定：本周 = asof 所在自然周，跨赛事算数

- 「本周」用 `scripts/resolve_week.py --asof <日期>` 解析，**不要手翻赛程页**：
  它给每队的本周候选、按开球时间取最晚、把数据缺口写进 `gaps`；
- 跨赛事周（欧冠轮 + 欧联轮）同一队可能有两场——选哪场、为什么，要在 fact pack
  里留依据；五队可能分布在两个赛事，**事实源接口也不同**（欧冠用 UEFA v5 列表接口，
  欧联的列表接口可能为空，要走俱乐部官网赛程面反查比赛 id，见 `league-fact-sources.md`）；
- 事实先集中落一份 `facts/matches.json`（每字段带来源 URL、每队一个 `gaps` 列表），
  五支并行作业都只读它——**禁止各 worker 各自抓页、各编各的**。

## 并发分工：一人一支，工具与门禁共享

- 每支队伍一个目录（`<项目根>/<team>/`），worker 只写自己的目录；skill 目录只读；
- 作业手册（给并行执行者的 brief）要写死：母版路径、比分、事实源文件、命令清单、
  「不许编事实 / 不许挪落点 / 不许加 BGM」三条红线、交付物清单（ffprobe 读数 +
  窗口表摘要 + 两条机检退出码 + 抽帧所见 + 显式降级项）；
- **母版下载是公共瓶颈**（yt-dlp 超时要重试），单独分派一个 worker 先行；下载到的
  文件必须抽帧核对「标题对、内容也对」（本轮实拍：巴萨标题命中的是 CBS 频道的
  另一场比赛），错文件改名留档；
- 收口人（最后验收的人）**必须自己抽帧**：烧录链的 overlay 参数错会让全部字幕卡
  静默消失，每支的机检与 ffprobe 都是绿的——抽三帧看卡，一帧都不能省
  （`scripts/verify_final.py` 把抽帧存档做成默认动作）。

## 每支的流水线命令（skill 版，路径参数，无 team-key 耦合）

```bash
cd <项目根>/<team>/
SKILL=../../../skills/match-recap-video/scripts
python -I $SKILL/cuts.py ../masters/<team>.mp4                 # 切点 → cuts.json
python -I $SKILL/probe_scoreboard.py ../masters/<team>.mp4     # 候选带 + 竖拼长图
python -I $SKILL/read_scoreboard.py ../masters/<team>.mp4 --crop <人眼确认的裁窗> --out sb.json
python -I $SKILL/plan_windows.py cuts.json sb.json             # 候选窗 = 切点 ∪ 时钟跳变
python -I $SKILL/frame_sheet.py ../masters/<team>.mp4 --step 4 # 全片拼版（人眼读画面）
#   ……写 windows.json + players.json……
python -I $SKILL/check_windows.py windows.json                 # 判据门 1
python -I $SKILL/check_roster.py --roster players.json --windows windows.json   # 门 2
python -I $SKILL/check_budget.py windows.json                  # 门 3（TTS 之前拦超窗）
node --import tsx $SKILL/tts_windows.ts --windows windows.json --out-dir . --voice zh-CN-YunjianNeural --rate -5%
python -I $SKILL/place_voice.py plan --windows windows.json --voice voice-report.json --total <母版秒> --out place.json
python -I $SKILL/assemble.py --team-dir . --master ../masters/<team>.mp4
python -I $SKILL/verify_final.py --final final.mp4 --master ../masters/<team>.mp4
```

## 预算与压词（五支 51 段实测）

- 写稿预算 `t1 − anchor − LEAD(0.45)`；中文 TTS（zh-CN-YunjianNeural，rate −5%）
  实测 **0.24–0.40 s/字，中位数 ≈ 0.33**；
- `check_budget.py`（估算 0.28 s/字）拦结构性错误，`place_voice.py`（TTS 实测）
  是落点的最终判决——**报告自带的余量按窗长算，为正仍可能越界**；
- 超窗零点几秒 = **删一个字**（≈0.3s）；超得多 = 三拍砍成一拍或拆窗。
  实拍案例：2.44s 的 jump 窗 7 字 → 5 字（估）→ 实测仍差 0.05s → 4 字过；
- **改完窗口表必须重跑 TTS**：旧 voice-report 与新 say 不同代，实测判据全被污染
  （`check_budget --voice` 的同代检测会拦：任一段 s/字出 0.10–0.60 即整份作废）。

## 五支实跑的显式降级项（写进交付说明的样式）

- 无视觉输入/未读画面的窗：`visible: unread` + 机检 WARN，交人工抽帧复核后才算冻结；
- 母版比分牌只有比分没有时钟（某支的转播版式）：窗口锚点只能用「比分变化 + 官方
  分钟」推，精度低于其余几支——逐窗在 `see` 里写明推法；
- 被整段跳过的进球（现场镜头不在母版）：`kind=jump` + `visible=absent`，比分在 stat 卡；
- 官方页没有的轴（VAR 判决、首发名单）：不写，`gaps` 里留痕；
- 母版自带的采访/片尾卡：裁掉，成片时长按裁后母版对账。

## 收口清单（收口人对每支出）

1. `verify_final.py` 退出码 0（ffprobe 可读、时长 = 裁后母版、有音轨）；
2. 抽帧 ≥3 帧真的看过（卡片在位、不遮比分牌、三层不越界）；
3. 抽听一段：旁白起点与 `place.json` 的落点对得上（±0.2s），人声 − 原声 ≥ 8 dB；
4. 三条机检 + TTS 校窗 + 落点判决的退出码归档（0/0/0/0/0）；
5. 降级项逐条写进交付说明，不冒充全绿。
