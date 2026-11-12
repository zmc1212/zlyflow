// Speed-adaptive renderer: each output frame averages k jittered sub-renders
// on the GPU inside the page (window.renderMany), so ONE image per frame
// leaves the browser instead of up to 32.
//   - 4 sub-frames minimum: rotated-grid sub-pixel jitter = anti-aliasing
//   - up to 32 on fast moves, sized by how far window.probe points travel
//     during the shutter — fast dolly zooms smear gaplessly instead of strobing
//   - shutter 1.0 = 360 deg: one frame's streak meets the next
// usage:
//   node render_fast.mjs --preview          (960x540, 30fps, light AA, JPEG)
//   node render_fast.mjs                    (1920x1080, 60fps, full AA, PNG)
//   node render_fast.mjs --stills 0.3,1.5,2.6,4.5,6.7,8.3
//   node render_fast.mjs --from=2 --to=4 --fps=30   (partial range)
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';
import { startServer } from './serve.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT = path.resolve(HERE, '..', '..');
const TMP = path.join(PROJECT, 'tmp', 'perspective-illusion');
const DELIVERY = path.join(PROJECT, '交付视频');
const LOOP_MS = 10000;

function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : def;
}
const opt = (k, def) => {
  const a = process.argv.find((x) => x.startsWith(`--${k}=`));
  return a ? parseFloat(a.split('=')[1]) : def;
};
const has = (name) => process.argv.includes(name);

function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const roots = [
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'ms-playwright'),
    process.env.USERPROFILE && path.join(process.env.USERPROFILE, 'AppData', 'Local', 'ms-playwright'),
    'C:\\Users\\Administrator\\AppData\\Local\\ms-playwright',
  ].filter(Boolean);
  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    const dirs = fs
      .readdirSync(root)
      .filter((d) => d.startsWith('chromium-') && !d.includes('headless'))
      .sort();
    for (const d of dirs.reverse()) {
      const exe = path.join(root, d, 'chrome-win64', 'chrome.exe');
      if (fs.existsSync(exe)) return exe;
    }
  }
  throw new Error('no chrome.exe found under ' + roots.join(', '));
}

function ffmpegBin() {
  return process.env.FFMPEG || 'ffmpeg';
}

const PREVIEW = has('--preview');
const W = PREVIEW ? 960 : 1920;
const H = PREVIEW ? 540 : 1080;
const FPS = opt('fps', PREVIEW ? 30 : 60);
const FROM = opt('from', 0);
const TO = opt('to', 10);
const STEP = opt('step', PREVIEW ? 3 : 2); // probe px between sub-frames
const MINK = opt('mink', PREVIEW ? 1 : 4);
const MAXK = PREVIEW ? 32 : 32;
const SHUT = 0.75; // 270-degree shutter: streaks stay dense, fast zooms read crisp
const JIT = [
  [-0.375, -0.125],
  [0.125, -0.375],
  [0.375, 0.125],
  [-0.125, 0.375],
];

async function main() {
  fs.mkdirSync(TMP, { recursive: true });
  const stills = has('--stills');
  const { server, port } = await startServer(0);
  const browser = await chromium.launch({
    executablePath: findChrome(),
    headless: true,
    args: [
      '--use-gl=angle',
      '--use-angle=d3d11',
      '--enable-gpu',
      '--ignore-gpu-blocklist',
      '--enable-unsafe-swiftshader',
      '--disable-lcd-text',
      '--force-color-profile=srgb',
      '--hide-scrollbars',
    ],
  });
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  page.on('pageerror', (e) => {
    console.error('[pageerror]', e.message);
    process.exitCode = 1;
  });
  page.on('console', (m) => {
    if (m.type() === 'error') console.log('[page]', m.text());
  });
  const dbgFlags = (has('--raw') ? '&raw=1' : '') + (has('--noaux') ? '&noaux=1' : '');
  await page.goto(`http://127.0.0.1:${port}/scene.html?w=${W}&h=${H}${dbgFlags}`, { waitUntil: 'load' });
  await page.waitForFunction('window.READY === true && window.probe', { timeout: 180000 });
  console.log('GPU:', JSON.stringify(await page.evaluate('window.__gpu')));

  const frame = await page.$('#view');

  if (stills) {
    const list = (arg('--stills', '') || '').split(',').filter(Boolean).map(Number);
    const dir = path.join(TMP, PREVIEW ? 'stills-preview' : 'stills');
    fs.mkdirSync(dir, { recursive: true });
    for (const t of list) {
      const info = await page.evaluate((ms) => window.render(ms), t * 1000);
      const f = path.join(dir, `t${t.toFixed(2).padStart(5, '0')}.png`);
      await frame.screenshot({ path: f });
      console.log('still', t, JSON.stringify(info), '->', path.relative(PROJECT, f));
    }
    await browser.close();
    server.close();
    return;
  }

  const n = Math.round((TO - FROM) * FPS);
  const dt = 1000 / FPS;
  const t0 = FROM * 1000;

  // How far the fastest visible probe point moves during one shutter (canvas px).
  const move = async (a, c) => {
    const [P, Q] = await page.evaluate(
      ([a, c]) => [window.probe(a), window.probe(c)],
      [((a % LOOP_MS) + LOOP_MS) % LOOP_MS, ((c % LOOP_MS) + LOOP_MS) % LOOP_MS]
    );
    let m = 0;
    P.forEach((u, i) => {
      const v = Q[i];
      if (Math.abs(u[2]) < 1 && Math.abs(v[2]) < 1 && Math.abs(u[0]) < W && Math.abs(v[0]) < W) {
        m = Math.max(m, Math.hypot(u[0] - v[0], u[1] - v[1]));
      }
    });
    return m;
  };

  const out = has('--out')
    ? path.resolve(PROJECT, arg('--out', ''))
    : PREVIEW
      ? path.join(TMP, 'preview.mp4')
      : path.join(DELIVERY, arg('--name', '正交错觉_雨夜十字路口_10s.mp4'));
  fs.mkdirSync(path.dirname(out), { recursive: true });

  const ff = spawn(
    ffmpegBin(),
    [
      '-y',
      '-loglevel', 'error',
      '-f', 'image2pipe',
      '-framerate', String(FPS),
      '-i', '-',
      '-vf', `scale=${W}:${H}:flags=lanczos`,
      '-r', String(FPS),
      '-c:v', 'libx264',
      '-preset', PREVIEW ? 'veryfast' : 'slow',
      '-crf', PREVIEW ? '21' : '15',
      '-pix_fmt', 'yuv420p',
      '-movflags', '+faststart',
      '-frames:v', String(n),
      out,
    ],
    { stdio: ['pipe', 'inherit', 'inherit'] }
  );
  const done = new Promise((r) => ff.on('close', r));
  const put = async (buf) => {
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
  };

  let renders = 0;
  const T = Date.now();
  for (let i = 0; i < n; i++) {
    const mid = t0 + i * dt;
    const a = mid - (dt * SHUT) / 2;
    const c = mid + (dt * SHUT) / 2;
    const px = await move(a, c);
    let k = MINK;
    while (k < MAXK && px / k > STEP) k *= 2;
    const list = [];
    for (let j = 0; j < k; j++) {
      const jj = JIT[j % 4];
      list.push([
        ((k === 1 ? mid : a + ((j + 0.5) / k) * (c - a)) % LOOP_MS + LOOP_MS) % LOOP_MS,
        k > 1 ? jj[0] : 0,
        k > 1 ? jj[1] : 0,
      ]);
    }
    await page.evaluate((l) => window.renderMany(l), list);
    renders += k;
    const buf = await frame.screenshot(PREVIEW ? { type: 'jpeg', quality: 92 } : { type: 'png' });
    await put(buf);
    if (i % 60 === 0) {
      const el = (Date.now() - T) / 1000;
      console.log(`frame ${i}/${n}  move ${px.toFixed(0)}px  k=${k}  ${el.toFixed(0)}s  eta ${(((n - i) * el) / (i + 1)).toFixed(0)}s`);
    }
  }
  ff.stdin.end();
  await done;
  console.log('done', out, 'renders', renders, 'in', ((Date.now() - T) / 60000).toFixed(1), 'min');
  await browser.close();
  server.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
