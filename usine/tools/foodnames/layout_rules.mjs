// layout_rules.mjs —— 这条产线的版式契约与阈值（**唯一事实源**）
//
// 为什么单独成文件：版式门有两道——`check_video_layout.mjs` 量**已渲染的成片**，
// `check_scene_tokens.mjs` 量**手搭/智能体交付的场景页面**。两道门必须用**同一份**
// 阈值与品牌色，否则「成片过了但手搭页面没过」会变成一句没人查得出的口话。
//
// 阈值与品牌色的依据（不许比被改进对象自己的文件更严）：
//   · `other_token_opacity: 0.45` —— 产线自己的视频模板 `templates/video_style.css`
//     第 17 行写死 `.tok.dim { opacity: 0.45; }`；README「两条视频门」一节复述同一句。
//   · `BRAND` 三色 —— 产线自己的模板第 23–25 行用 `rgba(201,64,58,.18)` /
//     `rgba(47,93,158,.18)` / `rgba(184,134,11,.18)` 给当前词上高亮，
//     换算成十六进制正是 `c9403a` / `2f5d9e` / `b8860b`（页脚图例承诺的三色）。
//
// 契约（token 的类名）同样来自产线自己的模板：`.tok` / `.dim` / `.sung` / `.cur`。
// **通用技能给的模板也是这一套类名**（`skills/karaoke-video/assets/template/scenes.html`
// 的 `.tok.dim` / `.tok.sung` / `.tok.cur`）——所以同一个尺子对两臂都量得动。
export const TH = {
  hero_height_ratio: 0.12, //  主角墨迹高 ≥ 画面高 12%
  hero_width_ratio: 0.30, //   或 主角墨迹宽 ≥ 画面宽 30%
  max_empty_band: 0.15, //  最大空白水平带 ≤ 画面高 15%
  other_token_opacity: 0.45, //  非当前 token 的最低不透明度
  annot_offset_px: 3, //  注音列与字心的水平偏差
}

// 页脚图例承诺的三色（元音红 / 辅音蓝 / 声调灰金）
export const BRAND = ['c9403a', '2f5d9e', 'b8860b']

// token 的类名契约（产线视频模板 + 通用 karaoke 模板共用这一套）
export const TOKEN_CLASS = { token: 'tok', dim: 'dim', sung: 'sung', cur: 'cur' }
