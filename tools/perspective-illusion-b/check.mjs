// Loop-seam and blink check on an encoded video.
//   node check.mjs out/preview.mp4
// Reads a small grayscale copy of every frame and reports:
//   seam  = mean |last - first|            (loop join; want < ~6/255)
//   diff  = mean |frame i - frame i-1|     (motion / stutter)
//   blink = pixels changing > 40 in near-still stretches (unwanted flicker)
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const file = path.resolve(HERE, process.argv[2] || 'out/preview.mp4');
const FF = process.env.FFMPEG || 'ffmpeg';
const W = 160, H = 90, SZ = W * H;

const probe = spawnSync('ffprobe', [
  '-v', 'error', '-select_streams', 'v:0',
  '-show_entries', 'stream=width,height,nb_frames,r_frame_rate',
  '-of', 'json', file,
], { encoding: 'utf8', shell: true });
if (probe.status !== 0) { console.error('ffprobe failed:', probe.stderr); process.exit(1); }
const meta = JSON.parse(probe.stdout).streams[0];

const dec = spawnSync(FF, [
  '-v', 'error', '-i', file,
  '-vf', `scale=${W}:${H},format=gray`,
  '-f', 'rawvideo', '-',
], { maxBuffer: 1 << 30, shell: true });
if (dec.status !== 0) { console.error('ffmpeg failed:', dec.stderr?.toString()); process.exit(1); }
const n = Math.floor(dec.stdout.length / SZ);
if (n < 2) { console.error('not enough frames'); process.exit(1); }

const frame = (i) => dec.stdout.subarray(i * SZ, (i + 1) * SZ);
const meanAbs = (a, b) => {
  let s = 0; for (let k = 0; k < SZ; k++) s += Math.abs(a[k] - b[k]);
  return s / SZ;
};
const seam = meanAbs(frame(n - 1), frame(0));
const diffs = [];
for (let i = 1; i < n; i++) diffs.push(meanAbs(frame(i), frame(i - 1)));
const mean = diffs.reduce((a, b) => a + b, 0) / diffs.length;
const max = Math.max(...diffs);
const maxAt = diffs.indexOf(max) + 1;

// near-still stretches: the camera holds; anything popping there is a blink
let still = 0, blinking = 0, worst = 0, worstAt = -1;
for (let i = 1; i < n; i++) {
  if (diffs[i - 1] > mean * 0.55) continue;
  still++;
  let cnt = 0;
  const a = frame(i - 1), b = frame(i);
  for (let k = 0; k < SZ; k++) if (Math.abs(a[k] - b[k]) > 40) cnt++;
  const frac = cnt / SZ;
  if (frac > 0.02) { blinking++; if (frac > worst) { worst = frac; worstAt = i; } }
}

console.log(`file      : ${path.relative(HERE, file)}`);
console.log(`stream    : ${meta.width}x${meta.height} @ ${meta.r_frame_rate}, ${meta.nb_frames || n} frames`);
console.log(`seam      : ${seam.toFixed(2)} / 255   ${seam < 6 ? 'OK' : 'CHECK: loop join is visible'}`);
console.log(`frame diff: mean ${mean.toFixed(2)}  max ${max.toFixed(2)} @ frame ${maxAt}`);
console.log(`still     : ${still} frames, blinking ${blinking} (worst ${(worst * 100).toFixed(1)}% @ ${worstAt})`);
console.log(`verdict   : ${seam < 6 && blinking < still * 0.15 ? 'PASS' : 'REVIEW'}`);
