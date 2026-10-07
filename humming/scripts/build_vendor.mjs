#!/usr/bin/env node
/**
 * Vendor 构建脚本：将 @spotify/basic-pitch + tfjs 打包为免打包器可用的 IIFE bundle，
 * 并把 TFJS 模型文件拷贝到 src/vendor/。
 * 产物:
 *   src/vendor/basic-pitch.bundle.js          (主线程推理, 暴露 window.BasicPitchLib)
 *   src/vendor/basic-pitch-model/             (model.json + 权重, ~917KB)
 * 幂等：源文件与 package.json 均未变化时跳过重建。
 *
 * 由 tauri.conf.json 的 beforeDevCommand / beforeBuildCommand 自动调用，
 * 因此 `cargo tauri dev` / `cargo tauri build` 会先确保 vendor 产物就绪。
 */
import { execFileSync } from 'child_process';
import { existsSync, mkdirSync, cpSync, statSync, readFileSync, writeFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const VENDOR = path.join(ROOT, 'src', 'vendor');
const ESBUILD = path.join(ROOT, 'node_modules', '.bin', 'esbuild');

if (!existsSync(ESBUILD)) {
  console.error(
    '[vendor] 缺少构建依赖 esbuild。请先在仓库根目录执行 `npm install`（仅 vendor 构建需要，' +
    '桌面应用本身由 `cargo tauri dev/build` 驱动）。'
  );
  process.exit(1);
}

// 注: 不构建 Web Worker 版 bundle —— tfjs 的 WebGL 计算在 worker 中会挂起
// (实测 0.3s 音频卡死 >60s)，且 WKWebView (macOS Tauri 目标) 基本不支持 worker 内 WebGL。
const TARGETS = [
  {
    entry: path.join(ROOT, 'src', 'dsp', 'basic_pitch_entry.js'),
    outfile: path.join(VENDOR, 'basic-pitch.bundle.js')
  }
];

const MODEL_SRC = path.join(ROOT, 'node_modules', '@spotify', 'basic-pitch', 'model');
const MODEL_DST = path.join(VENDOR, 'basic-pitch-model');

// --- 增量检查: 任一入口/依赖包比产物新则重建 ---
function newestMtime(p) {
  let newest = 0;
  try {
    const st = statSync(p);
    if (st.isFile()) return st.mtimeMs;
    if (st.isDirectory()) {
      // 只看包根的 package.json，避免递归整棵 node_modules
      if (p.includes('node_modules')) {
        const pkg = path.join(p, 'package.json');
        return existsSync(pkg) ? statSync(pkg).mtimeMs : 0;
      }
    }
  } catch { /* missing → treat as stale */ }
  return newest;
}

function needsRebuild(outfile, inputs) {
  if (!existsSync(outfile)) return true;
  const outMtime = statSync(outfile).mtimeMs;
  return inputs.some((p) => (p.includes('node_modules') || existsSync(p)) && newestMtime(p) > outMtime);
}

const depRoots = [
  path.join(ROOT, 'node_modules', '@spotify', 'basic-pitch'),
  path.join(ROOT, 'node_modules', '@tensorflow')
];

mkdirSync(VENDOR, { recursive: true });

let rebuilt = false;
for (const t of TARGETS) {
  const inputs = [t.entry, ...depRoots];
  if (!needsRebuild(t.outfile, inputs)) {
    console.log(`[vendor] up-to-date: ${path.relative(ROOT, t.outfile)}`);
    continue;
  }
  console.log(`[vendor] building ${path.relative(ROOT, t.outfile)} ...`);
  execFileSync(ESBUILD, [
    t.entry,
    '--bundle',
    '--minify',
    '--format=iife',
    '--platform=browser',
    `--outfile=${t.outfile}`,
    '--log-level=warning'
  ], { stdio: 'inherit' });
  rebuilt = true;
}

// --- 模型文件拷贝 ---
const modelMarker = path.join(MODEL_DST, '.copied');
const modelPkgJson = path.join(MODEL_SRC, '..', 'package.json');
if (!existsSync(modelMarker) || statSync(modelPkgJson).mtimeMs > statSync(modelMarker).mtimeMs) {
  mkdirSync(MODEL_DST, { recursive: true });
  cpSync(MODEL_SRC, MODEL_DST, { recursive: true });
  writeFileSync(modelMarker, 'ok');
  console.log(`[vendor] model files copied → ${path.relative(ROOT, MODEL_DST)}`);
} else {
  console.log('[vendor] model files up-to-date');
}

// --- 注: tfjs WASM 后端未采用 ---
// tfjs 3.21 的 wasm 后端缺少 tf.signal.frame 算子支持，而 Basic Pitch 的 prepareData
// 依赖该算子，会抛 "Unknown dtype undefined"。实测 WebGL 后端可用且最快 (1s 音频 ~0.7s)。

console.log('[vendor] done');
