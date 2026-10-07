/**
 * 界面契约测试 (UI Contract Test)
 *
 * 背景：main.js 通过 document.getElementById() 绑定界面元素。
 * 若某个 id 在 index.html 中缺失，监听器会通过可选链 `?.` 被**静默跳过**，
 * 表现为「界面正常渲染但按钮点了没反应」，且控制台没有任何报错——
 * 这类缺陷极难排查。
 *
 * 本测试把 main.js 里引用的关键元素 id 与 index.html 实际提供的 id 做交叉校验，
 * 确保「代码期望的界面契约」与「实际存在的界面」始终一致。
 */
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.join(ROOT, '..', 'src');
const html = readFileSync(path.join(FRONTEND, 'index.html'), 'utf8');
const appJs = readFileSync(path.join(FRONTEND, 'main.js'), 'utf8');
const css = readFileSync(path.join(FRONTEND, 'css', 'style.css'), 'utf8');

let failures = 0;
const check = (label, cond, detail = '') => {
  if (cond) {
    console.log(`✅ PASS: ${label}`);
  } else {
    failures++;
    console.log(`❌ FAIL: ${label}${detail ? ` — ${detail}` : ''}`);
  }
};

const hasId = (id) => new RegExp(`id="${id}"`).test(html);

// 1. 五阶段流水线面板：main.js 的 updateStageStatus() 依赖 stage-1..5
//    历史上这些 id 完全缺失，导致整个流水线进度显示静默失效。
console.log('=== 五阶段流水线面板契约 ===');
check('pipeline-panel 容器存在', hasId('pipeline-panel'));
check('pipeline-panel 默认带 hidden 类', /id="pipeline-panel"[^>]*class="[^"]*\bhidden\b/.test(html));
for (let i = 1; i <= 5; i++) {
  check(`stage-${i} 存在`, hasId(`stage-${i}`));
  check(`stage-${i}-details 存在`, hasId(`stage-${i}-details`));
}
check('main.js 引用了 resetPipelinePanel', appJs.includes('resetPipelinePanel'));
check('main.js 在 executePipeline 开头重置面板',
  /async executePipeline\(audioBuffer\)\s*\{[\s\S]{0,200}?this\.resetPipelinePanel\(\)/.test(appJs));

// 2. 流水线面板的 CSS 类必须真实存在于样式表中，否则会退化成无样式的裸 div
console.log('\n=== 流水线面板样式契约 ===');
for (const cls of ['pipeline-panel', 'pipeline-stage', 'stage-status-badge', 'stage-desc', 'metric-chip']) {
  check(`.${cls} 有 CSS 规则`, new RegExp(`\\.${cls}\\b`).test(css));
}
check('.pipeline-panel.hidden 有隐藏规则', /\.pipeline-panel\.hidden/.test(css));

// 3. 导出/播放入口：这些按钮被 disabled 属性控制，识谱后由 JS 解除
console.log('\n=== 导出与播放入口契约 ===');
for (const id of ['btn-export-midi', 'btn-export-xml', 'btn-play-synth', 'btn-play-original']) {
  check(`${id} 存在`, hasId(id));
}

// 4. 快捷键焦点守卫：下拉框获得焦点时不得触发音符编辑
console.log('\n=== 快捷键焦点守卫契约 ===');
const guardMatch = /if \(\[(.*?)\]\.includes\(document\.activeElement\?\.tagName\)\) return;/.exec(appJs);
check('存在快捷键焦点守卫', !!guardMatch, '未找到 activeElement tagName 守卫');
if (guardMatch) {
  const tags = guardMatch[1];
  check('守卫包含 SELECT（下拉框聚焦时不改音高）', tags.includes("'SELECT'"), `实际: ${tags}`);
  check('守卫包含 BUTTON（按钮聚焦时空格不误触发试听）', tags.includes("'BUTTON'"), `实际: ${tags}`);
}

// 5. 单屏工作台布局契约：保证页面不滚动、只有侧栏与乐谱区内部滚动
console.log('\n=== 单屏工作台布局契约 ===');
check('存在 app-shell 外壳', hasId('pipeline-panel') && /class="app-shell"/.test(html));
check('存在 workspace 两栏容器', /class="workspace"/.test(html));
check('存在 sidebar 侧栏', /class="sidebar"/.test(html));
check('存在 score-area 乐谱区', /class="score-area"/.test(html));
check('存在 score-viewport 内部滚动区', /class="score-viewport"/.test(html));
check('pipeline-toggle 展开按钮存在', hasId('pipeline-toggle'));
check('app.js 绑定了 pipeline-toggle',
  /pipeline-toggle/.test(appJs));
// 标签闭合平衡
const opens = (html.match(/<div\b/g) || []).length;
const closes = (html.match(/<\/div>/g) || []).length;
check('div 标签闭合平衡', opens === closes, `开 ${opens} / 闭 ${closes}`);
// 流水线面板只应出现一次（避免重复渲染两份）
const pipelineCount = (html.match(/id="pipeline-panel"/g) || []).length;
check('pipeline-panel 只出现一次', pipelineCount === 1, `实际 ${pipelineCount} 次`);

// 6. 侧栏窄容器溢出契约
// .monitor-body 的第二列写死 280px，而单屏布局下侧栏只有约 270px 宽；
// 原来的 max-width 断点看的是「视口宽度」，桌面端永不触发，子卡片会横向溢出卡片边界。
console.log('\n=== 侧栏窄容器溢出契约 ===');
check('侧栏内监控屏强制单列（避免 280px 固定列溢出）',
  /\.sidebar\s+\.monitor-body\s*\{[^}]*grid-template-columns:\s*1fr/.test(css));
check('侧栏内标题与状态徽章上下堆叠（避免徽章被压成竖排文字）',
  /\.sidebar\s+\.monitor-header\s*\{[^}]*flex-direction:\s*column/.test(css));
// 断点回归：临时改成 100px 会在桌面端误降级为单列，必须保持 860px
check('单屏断点为 860px（未被临时改小）',
  /@media\s*\(max-width:\s*860px\)/.test(css) && !/@media\s*\(max-width:\s*100px\)/.test(css));

// 7. BPM 可直接输入数值
console.log('\n=== BPM 数值输入契约 ===');
check('存在 BPM 数字输入框', /id="input-bpm-num"/.test(html));
check('数字输入框为 number 类型且有 min/max/step',
  /id="input-bpm-num"[^>]*type="number"[\s\S]*?min="\d+"[\s\S]*?max="\d+"[\s\S]*?step="1"/.test(html) ||
  /type="number"[^>]*id="input-bpm-num"/.test(html));
check('main.js 绑定了数字框的 change/blur 事件',
  /input-bpm-num/.test(appJs) && /getElementById\('input-bpm-num'\)/.test(appJs));
check('main.js 支持回车提交', /key === 'Enter'/.test(appJs));
check('BPM 范围由常量约束（两处取值范围不打架）',
  /const BPM_MIN = \d+/.test(appJs) && /const BPM_MAX = \d+/.test(appJs));
check('数字框定宽不参与挤压 (flex: 0 0 auto)',
  /#input-bpm-num\s*\{[^}]*flex:\s*0 0 auto/.test(css));
check('隐藏数字框微调箭头（避免挤占宽度）',
  /#input-bpm-num::-webkit-inner-spin-button/.test(css));
check('节拍行允许换行（窄容器不横向溢出）',
  /\.sidebar\s+\.bpm-row\s*\{[^}]*flex-wrap:\s*wrap/.test(css));
// 已删除的旧只读数字 span 不得残留引用，否则会静默失效
check('旧只读 bpm-val 已彻底移除（HTML/CSS/JS 均无残留）',
  !/bpm-val/.test(html) && !/bpm-val/.test(css) && !/bpm-val/.test(appJs));

// 8. 「对照原声」必须可停 + 原声驱动乐谱游标
//    背景：旧实现是「再点一次从头重播」——既停不下来（用户报「原声无法停止」），
//    也没有任何游标推进（用户报「原声不跟乐谱走」）。本组断言锁死这两条不变量。
console.log('\n=== 「对照原声」播放契约 ===');
check('存在「对照原声」按钮', hasId('btn-play-original'));
check('按钮绑定了 playOriginalAudio', /getElementById\('btn-play-original'\)[\s\S]{0,120}?playOriginalAudio\(\)/.test(appJs));
// 切换语义：播放中再点必须走停止分支，而不是无条件 stop 后立刻重新 start
check('playOriginalAudio 内含「再点即停」的 toggle 分支',
  /playOriginalAudio\(\)\s*\{[\s\S]{0,600}?if \(this\.originalAudioSource\)\s*\{\s*this\.stopOriginalAudio\('stopped'\);\s*return;/.test(appJs));
check('按钮文案随播放状态切换（存在停止态文案）',
  /setOriginalButtonState\(playing\)[\s\S]{0,400}?停止原声/.test(appJs));
check('播放态与停止态文案分别写入 innerHTML',
  /停止原声 \(Stop\)/.test(appJs) && /对照原声/.test(appJs));
// 旧实现的信号：stop 之后紧跟无条件 src.start() 且没有 return
check('旧缺陷（stop 后无条件重播、无 return）已消除',
  !/playOriginalAudio\(\)\s*\{[\s\S]{0,600}?this\.originalAudioSource\.stop\(\);[\s\S]{0,200}?\}\s*\n\s*const src =/.test(appJs));
check('停止时会清理游标定时器，避免泄漏',
  /stopOriginalAudio\(reason = 'stopped'\)\s*\{[\s\S]{0,600}?clearInterval\(this\.originalCursorTimer\)/.test(appJs));

// 原声跟随乐谱：游标必须由播放位置推进，且定位用二分而非线性扫
check('存在游标跟随函数 followScoreWithOriginal', /followScoreWithOriginal\(elapsed\)/.test(appJs));
check('播放中按固定节拍推进游标',
  /setInterval\(\(\) => \{[\s\S]{0,220}?followScoreWithOriginal\(/ .test(appJs));
check('游标定位使用二分查找（音符多时仍能实时跟随）',
  /while \(lo <= hi\)[\s\S]{0,200}?view\[mid\]\.time <= elapsed/.test(appJs));
// 关键：渲染层 data-note-index 是 quantizedNotes 的**原始**下标，
// 而 quantizedNotes 不保证按 startTime 有序，因此必须还原成原始下标再高亮
check('游标按 startTime 排序视图定位（quantizedNotes 本身无序）',
  /_originalTimeIndex = notes[\s\S]{0,200}?\.sort\(\(a, b\) => a\.time - b\.time\)/.test(appJs));
check('高亮时传回原始数组下标而非排序下标',
  /this\._originalCursorIdx = idx;[\s\S]{0,220}?staffRenderer\.setPlayhead\(idx\)/.test(appJs));
check('同一时刻的叠音固定取第一个（高亮不来回闪）',
  /view\[found - 1\]\.time === view\[found\]\.time/.test(appJs));
check('重新量化后作废时间索引（BPM 改动不指向错位音符）',
  /reQuantizeAndRender\(\)\s*\{[\s\S]{0,300}?this\._originalTimeIndex = null/.test(appJs));
// 三个视图必须一起复位，否则停止后 pianoRoll 的播放线会残留在最后一个音符上
check('停止时三个渲染视图游标一并清除',
  /clearScorePlayhead\(\)\s*\{[\s\S]{0,400}?staffRenderer\.clearPlayhead\(\)[\s\S]{0,200}?numberedRenderer\.clearPlayhead\(\)[\s\S]{0,200}?pianoRollRenderer\.clearPlayhead\(\)/.test(appJs));
check('乐谱试听结束也走同一套游标复位（原先漏了 pianoRoll）',
  /synth\.onPlaybackEnd = \(reason\) => \{[\s\S]{0,200}?clearScorePlayhead\(\)/.test(appJs));

console.log(failures === 0
  ? '\n🎉 所有界面契约测试 PASS！'
  : `\n❌ ${failures} 项界面契约检查失败`);
process.exit(failures === 0 ? 0 : 1);
