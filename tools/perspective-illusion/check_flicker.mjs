// Flicker / pop check: renders nothing, just measures the frame-to-frame mean
// luma of a video and flags frames that jump far more than their neighbours.
//
// usage: node check_flicker.mjs <video.mp4> [--json]
import { spawn } from 'node:child_process';

const FFPROBE_ARGS = ['-hide_banner', '-nostats', '-i'];

function ffmpegBin() {
  return process.env.FFMPEG || 'ffmpeg';
}

function meanLuma(file) {
  return new Promise((resolve, reject) => {
    const p = spawn(ffmpegBin(), [
      '-hide_banner',
      '-nostats',
      '-i',
      file,
      '-vf',
      'signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-',
      '-f',
      'null',
      '-',
    ]);
    let out = '';
    let err = '';
    p.stdout.on('data', (d) => (out += d));
    p.stderr.on('data', (d) => (err += d));
    p.on('error', (e) => reject(new Error('ffmpeg missing: ' + e.message)));
    p.on('close', (code) => {
      if (code !== 0) return reject(new Error('ffmpeg failed: ' + err.slice(-800)));
      const vals = [...out.matchAll(/lavfi\.signalstats\.YAVG=([0-9.]+)/g)].map((m) => parseFloat(m[1]));
      resolve(vals);
    });
  });
}

function median(arr) {
  const a = arr.slice().sort((x, y) => x - y);
  return a.length ? a[Math.floor(a.length / 2)] : 0;
}

const file = process.argv[2];
if (!file) {
  console.error('usage: node check_flicker.mjs <video.mp4>');
  process.exit(2);
}

const luma = await meanLuma(file);
if (luma.length < 3) {
  console.error('not enough frames read');
  process.exit(2);
}

const deltas = [];
for (let i = 1; i < luma.length; i++) deltas.push(Math.abs(luma[i] - luma[i - 1]));
const med = median(deltas);
const p95 = deltas.slice().sort((a, b) => a - b)[Math.floor(deltas.length * 0.95)];
const worst = deltas.slice().sort((a, b) => b - a).slice(0, 5);

// A real cut or a flash shows up as a jump far above the p95 of the move itself.
const threshold = Math.max(med * 6, p95 * 2.5, 1.2);
const flagged = [];
deltas.forEach((d, i) => {
  if (d > threshold) flagged.push({ frame: i + 1, delta: +d.toFixed(3) });
});

const report = {
  file,
  frames: luma.length,
  lumaFirst: +luma[0].toFixed(2),
  lumaLast: +luma[luma.length - 1].toFixed(2),
  deltaMedian: +med.toFixed(3),
  deltaP95: +p95.toFixed(3),
  deltaMax: +Math.max(...deltas).toFixed(3),
  worst5: worst.map((d) => +d.toFixed(3)),
  threshold: +threshold.toFixed(3),
  flagged,
  loopSeam: +Math.abs(luma[0] - luma[luma.length - 1]).toFixed(3),
};

console.log(JSON.stringify(report, null, 2));
process.exit(flagged.length ? 1 : 0);
