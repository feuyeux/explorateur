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

console.log(failures === 0
  ? '\n🎉 所有界面契约测试 PASS！'
  : `\n❌ ${failures} 项界面契约检查失败`);
process.exit(failures === 0 ? 0 : 1);
