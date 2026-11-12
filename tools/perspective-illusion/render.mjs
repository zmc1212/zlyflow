// Frame-accurate capture: headless Chromium renders each frame deterministically,
// PNGs are written to disk, ffmpeg encodes them.
//
// usage:
//   node render.mjs --stills 0,2.15,4.5,6.7
//   node render.mjs --preview            (960x540, whole loop)
//   node render.mjs --final              (1920x1080, whole loop)
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

function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : def;
}
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
  if (process.env.FFMPEG) return process.env.FFMPEG;
  return 'ffmpeg';
}

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    p.stdout.on('data', (d) => (out += d));
    p.stderr.on('data', (d) => (out += d));
    p.on('error', reject);
    p.on('close', (code) => (code === 0 ? resolve(out) : reject(new Error(cmd + ' failed (' + code + '):\n' + out.slice(-2500)))));
  });
}

const PREVIEW = has('--preview');
const STILLS = has('--stills');
const W = parseInt(arg('--w', PREVIEW ? '960' : '1920'), 10);
const H = parseInt(arg('--h', PREVIEW ? '540' : '1080'), 10);
const FPS = parseFloat(arg('--fps', '30'));
const DURATION = parseFloat(arg('--duration', '10'));
const frameCount = Math.round(FPS * DURATION);

async function main() {
  fs.mkdirSync(TMP, { recursive: true });
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
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') console.log('[page]', m.type(), m.text());
  });
  page.on('pageerror', (e) => console.log('[pageerror]', e.message));
  await page.goto(`http://127.0.0.1:${port}/scene.html?w=${W}&h=${H}${has('--raw') ? '&raw=1' : ''}${has('--noaux') ? '&noaux=1' : ''}`, { waitUntil: 'load' });
  await page.waitForFunction('window.READY === true', { timeout: 120000 });
  console.log('GPU:', await page.evaluate('window.__gpu'));

  const save = async (t, file) => {
    const dataUrl = await page.evaluate((tt) => window.grabFrame(tt), t);
    const b64 = dataUrl.slice(dataUrl.indexOf(',') + 1);
    fs.writeFileSync(file, Buffer.from(b64, 'base64'));
  };

  if (STILLS) {
    const times = (arg('--stills-in', '') || (process.argv[process.argv.indexOf('--stills') + 1] || '')).split(',').filter(Boolean);
    const list = times.length ? times.map(Number) : [0, 1.05, 2.15, 2.95, 3.65, 4.5, 5.1, 5.95, 6.7, 7.5, 8.3, 9.1];
    const dir = path.join(TMP, PREVIEW ? 'stills-preview' : 'stills');
    fs.mkdirSync(dir, { recursive: true });
    for (const t of list) {
      const f = path.join(dir, `t${t.toFixed(2).padStart(5, '0')}.png`);
      const info = await page.evaluate((tt) => window.renderAt(tt), t);
      await save(t, f);
      console.log('still', t, JSON.stringify(info), '->', path.relative(PROJECT, f));
    }
    await browser.close();
    server.close();
    return;
  }

  const framesDir = path.join(TMP, PREVIEW ? 'frames-preview' : 'frames');
  fs.rmSync(framesDir, { recursive: true, force: true });
  fs.mkdirSync(framesDir, { recursive: true });
  const t0 = Date.now();
  for (let i = 0; i < frameCount; i++) {
    const t = i / FPS;
    await save(t, path.join(framesDir, String(i).padStart(5, '0') + '.png'));
    if (i % 15 === 0 || i === frameCount - 1) {
      const el = (Date.now() - t0) / 1000;
      const per = el / (i + 1);
      console.log(`frame ${i + 1}/${frameCount}  ${per.toFixed(2)}s/frame  eta ${((frameCount - i - 1) * per).toFixed(0)}s`);
    }
  }
  await browser.close();
  server.close();

  const out = PREVIEW
    ? path.join(TMP, 'preview.mp4')
    : path.join(DELIVERY, arg('--out', '正交错觉_雨夜十字路口_10s.mp4'));
  fs.mkdirSync(path.dirname(out), { recursive: true });
  await run(ffmpegBin(), [
    '-y',
    '-framerate', String(FPS),
    '-i', path.join(framesDir, '%05d.png'),
    '-c:v', 'libx264',
    '-preset', 'slow',
    '-crf', PREVIEW ? '20' : '16',
    '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart',
    '-r', String(FPS),
    out,
  ]);
  console.log('wrote', out);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
