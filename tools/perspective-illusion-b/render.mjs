// Deterministic frame-by-frame renderer: browser screenshots -> ffmpeg.
//   node render.mjs --stills 0,1.5,2.6,4.5,7.4
//   node render.mjs --preview                # 960x540 / 30fps -> out/preview.mp4
//   node render.mjs --final                  # 1920x1080 / 30fps -> out/final.mp4
//   node render.mjs --w=1280 --h=720 --fps=30 --dur=10 --sub=4 --out=out/x.mp4
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';
import { startServer } from './serve.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, 'out');
const LOOP_MS = 10000;

const has = (n) => process.argv.includes(n);
const arg = (n, d) => {
  const i = process.argv.indexOf(n);
  return i >= 0 ? process.argv[i + 1] : d;
};
const opt = (k, d) => {
  const a = process.argv.find((x) => x.startsWith(`--${k}=`));
  return a ? parseFloat(a.split('=')[1]) : d;
};

function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const root = path.join(
    process.env.LOCALAPPDATA || path.join(process.env.USERPROFILE || '', 'AppData', 'Local'),
    'ms-playwright'
  );
  if (fs.existsSync(root)) {
    const dirs = fs.readdirSync(root)
      .filter((d) => /^chromium-\d+$/.test(d))
      .sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]));
    for (const d of dirs) {
      const exe = path.join(root, d, 'chrome-win64', 'chrome.exe');
      if (fs.existsSync(exe)) return exe;
    }
  }
  for (const exe of [
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  ]) if (fs.existsSync(exe)) return exe;
  throw new Error('Chromium not found; set CHROME_PATH');
}

const JIT = [[-0.375, -0.125], [0.125, -0.375], [0.375, 0.125], [-0.125, 0.375]];

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const preview = has('--preview');
  const final = has('--final');
  const W = Math.round(opt('w', preview ? 960 : final ? 1920 : 960));
  const H = Math.round(opt('h', preview ? 540 : final ? 1080 : 540));
  const FPS = opt('fps', 30);
  const DUR = opt('dur', 10);
  const SUB = opt('sub', preview ? 2 : 4);     // minimum sub-renders per frame (AA)
  const MAXSUB = opt('maxsub', preview ? 6 : 12);
  const STEP = opt('step', 9);                  // probe px per sub-render before adding more

  const { server, port } = await startServer(0);
  const browser = await chromium.launch({
    executablePath: findChrome(),
    headless: true,
    args: [
      '--use-gl=angle', '--use-angle=d3d11', '--enable-gpu',
      '--ignore-gpu-blocklist', '--enable-unsafe-swiftshader',
      '--disable-lcd-text', '--force-color-profile=srgb', '--hide-scrollbars',
    ],
  });
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  page.on('pageerror', (e) => { console.error('[pageerror]', e.message); process.exitCode = 1; });
  page.on('console', (m) => { if (m.type() === 'error') console.log('[page]', m.text()); });
  const dbg = (has('--raw') ? '&raw=1' : '') + (has('--noink') ? '&noink=1' : '');
  await page.goto(`http://127.0.0.1:${port}/scene.html?w=${W}&h=${H}${dbg}`, { waitUntil: 'load' });
  await page.waitForFunction('window.READY === true', { timeout: 180000 });
  console.log('GPU:', JSON.stringify(await page.evaluate('window.__gpu')));
  const view = await page.$('#view');

  if (has('--stills')) {
    const dir = path.join(OUT, 'stills');
    fs.mkdirSync(dir, { recursive: true });
    const list = (arg('--stills', '0') || '').split(',').filter(Boolean).map(Number);
    for (const t of list) {
      const info = await page.evaluate((ms) => window.render(ms), t * 1000);
      const f = path.join(dir, `t${t.toFixed(2).padStart(5, '0')}.png`);
      await view.screenshot({ path: f });
      console.log('still', t.toFixed(2), JSON.stringify(info), '->', path.relative(HERE, f));
    }
    await browser.close(); server.close();
    return;
  }

  const out = path.resolve(HERE, arg('--out', preview ? 'out/preview.mp4' : 'out/final.mp4'));
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const n = Math.round(DUR * FPS);
  const dt = 1000 / FPS;
  const ff = spawn(process.env.FFMPEG || 'ffmpeg', [
    '-y', '-loglevel', 'error',
    '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-',
    '-vf', `scale=${W}:${H}:flags=lanczos`,
    '-r', String(FPS), '-c:v', 'libx264',
    '-preset', preview ? 'veryfast' : 'slow',
    '-crf', preview ? '20' : '15',
    '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
    '-frames:v', String(n), out,
  ], { stdio: ['pipe', 'inherit', 'inherit'] });
  const done = new Promise((r) => ff.on('close', r));
  const put = async (buf) => {
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
  };

  const wrap = (ms) => ((ms % LOOP_MS) + LOOP_MS) % LOOP_MS;
  let subs = 0;
  const T = Date.now();
  for (let i = 0; i < n; i++) {
    const mid = i * dt;
    const a = mid - dt / 2, c = mid + dt / 2;
    const [P, Q] = await page.evaluate(([a, c]) => [window.probe(a), window.probe(c)], [wrap(a), wrap(c)]);
    let px = 0;
    for (let j = 0; j < Math.min(P.length, Q.length); j++) {
      if (P[j][2] > 0 && Q[j][2] > 0) px = Math.max(px, Math.hypot(P[j][0] - Q[j][0], P[j][1] - Q[j][1]));
    }
    let k = SUB;
    while (k < MAXSUB && px / k > STEP) k *= 2;
    if (k > MAXSUB) k = MAXSUB;
    const list = [];
    for (let j = 0; j < k; j++) {
      const jj = JIT[j % 4];
      list.push([wrap(a + ((j + 0.5) / k) * (c - a)), jj[0], jj[1]]);
    }
    await page.evaluate((l) => window.renderMany(l), list);
    subs += k;
    const buf = await view.screenshot(preview ? { type: 'jpeg', quality: 94 } : { type: 'png' });
    await put(buf);
    if (i % 45 === 0) {
      const el = (Date.now() - T) / 1000;
      console.log(`frame ${i}/${n}  move ${px.toFixed(0)}px  k=${k}  ${el.toFixed(0)}s  eta ${(((n - i) * el) / (i + 1)).toFixed(0)}s`);
    }
  }
  ff.stdin.end();
  await done;
  console.log('done:', out, '| sub-renders:', subs, '|', ((Date.now() - T) / 60000).toFixed(1), 'min');
  await browser.close();
  server.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
