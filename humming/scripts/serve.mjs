/**
 * Humming-to-Score 本地静态服务
 * 零外部依赖，纯 Node.js HTTP 服务器 (ES Module)
 *
 * 仅用于浏览器模式下的前端调试。桌面应用 (Tauri) 不需要此服务 ——
 * 转谱推理全部在 webview 内以 tfjs 本地完成，不需要 Python 或任何后端。
 *
 * 挂在仓库根目录跑：`npm run serve`。
 *
 * 文档根设为 **src/**，与 tauri.conf.json 的 frontendDist (= ../src) 完全一致 ——
 * 即 Tauri 把 src/ 当作 web 根。若这里改为把 / 直接映射到 /src/index.html，
 * 浏览器会以为 base 是 `/`，从而把 index.html 里的相对路径 (css/style.css、main.js)
 * 解析成 /css/style.css、/main.js 并全部 404，页面将完全没有样式与脚本。
 */
import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = parseInt(process.env.PORT || '3000', 10);
const HOST = process.env.HOST || '127.0.0.1';
// 文档根 = 前端源码目录，与 Tauri frontendDist 保持一致
const BASE_DIR = path.join(path.dirname(__dirname), 'src');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.wav': 'audio/wav',
  '.mp3': 'audio/mpeg',
  '.m4a': 'audio/mp4',
  '.aac': 'audio/aac',
  '.ogg': 'audio/ogg',
  '.mid': 'audio/midi',
  '.midi': 'audio/midi',
  '.xml': 'application/xml',
  '.musicxml': 'application/vnd.recordare.musicxml+xml',
  '.ico': 'image/x-icon'
};

const server = http.createServer((req, res) => {
  const urlPath = req.url.split('?')[0];

  // 静态文件处理
  let safePath = path.normalize(urlPath).replace(/^(\.\.[\/\\])+/, '');
  if (safePath === '/' || safePath === '\\') {
    safePath = '/index.html';
  }

  const filePath = path.join(BASE_DIR, safePath);

  if (!filePath.startsWith(BASE_DIR)) {
    res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('403 Forbidden');
    return;
  }

  fs.stat(filePath, (err, stats) => {
    if (err || !stats.isFile()) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end(`404 Not Found: ${safePath}`);
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME_TYPES[ext] || 'application/octet-stream';

    // 处理音频 Seek Range 请求
    // 解析失败或越界时回退到 200 全量响应：绝不能把 NaN 传给 createReadStream
    // (会同步抛 ERR_OUT_OF_RANGE 直接终止整个进程)
    const range = req.headers.range;
    if (range && (ext === '.m4a' || ext === '.wav' || ext === '.mp3')) {
      const total = stats.size;
      const parsed = parseByteRange(range, total);

      if (parsed) {
        const { start, end } = parsed;
        const chunksize = end - start + 1;

        res.writeHead(206, {
          'Content-Range': `bytes ${start}-${end}/${total}`,
          'Accept-Ranges': 'bytes',
          'Content-Length': chunksize,
          'Content-Type': contentType,
          'Access-Control-Allow-Origin': '*'
        });

        const stream = fs.createReadStream(filePath, { start, end });
        stream.on('error', () => res.destroy());
        stream.pipe(res);
        return;
      }
    }

    res.writeHead(200, {
      'Content-Type': contentType,
      'Content-Length': stats.size,
      'Accept-Ranges': 'bytes',
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      'Access-Control-Allow-Origin': '*'
    });

    const stream = fs.createReadStream(filePath);
    stream.pipe(res);
  });
});

/**
 * 解析单段 HTTP Range 头 (bytes=start-end) 为文件内绝对字节区间
 *
 * 支持三种写法：
 *   bytes=0-1023    闭区间
 *   bytes=1024-     从偏移到文件末尾
 *   bytes=-500      后缀形式: 文件末尾的 500 字节
 *
 * @param {string} header - 原始 Range 请求头
 * @param {number} total - 文件总字节数
 * @returns {{start:number,end:number}|null} 合法区间；语法错误、多段或越界时返回 null
 *   (返回 null 表示"按普通 200 整体响应处理"，符合 RFC 9110 允许的行为)
 */
function parseByteRange(header, total) {
  const m = /^bytes=(\d*)-(\d*)$/.exec((header || '').trim());
  if (!m) return null;

  const [, rawStart, rawEnd] = m;
  // 两端都为空 (如 "bytes=-") 不是合法区间
  if (rawStart === '' && rawEnd === '') return null;

  let start;
  let end;

  if (rawStart === '') {
    // 后缀形式: 末尾 N 字节
    const suffixLen = parseInt(rawEnd, 10);
    if (!Number.isFinite(suffixLen) || suffixLen <= 0) return null;
    if (total === 0) return null;
    start = Math.max(0, total - suffixLen);
    end = total - 1;
  } else {
    start = parseInt(rawStart, 10);
    if (!Number.isFinite(start) || start < 0) return null;
    // 越界起点: 无法满足 → 回退全量
    if (start >= total) return null;
    end = rawEnd === '' ? total - 1 : parseInt(rawEnd, 10);
    if (!Number.isFinite(end) || end < start) return null;
    // 终点超过文件末尾: 截断到末尾 (RFC 允许)
    end = Math.min(end, total - 1);
  }

  if (total === 0) return null;
  return { start, end };
}

server.listen(PORT, HOST, () => {
  console.log(`\n======================================================`);
  console.log(`  🎵 哼唱识谱 (Humming-to-Score Studio) 已就绪`);
  console.log(`  🔗 本地访问地址: http://${HOST}:${PORT}`);
  console.log(`======================================================\n`);
});
