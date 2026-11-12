// ---------------------------------------------------------------------------
// rig.js — the camera parameter sheet. This is the whole trick.
//
// The camera never tilts. fov is the HORIZONTAL lens angle; W is the width (m)
// framed on the focus plane. dist = (W/2)/tan(fov/2), so holding W while
// opening the lens is a dolly zoom: the subject keeps its size, the space
// behind it stretches open. H is the lens shift (where the horizon sits in
// NDC y). yaw swings round the focus point for the corner views.
// ---------------------------------------------------------------------------
import * as THREE from 'three';

export const LOOP_MS = 10000;
export const FOCUS_Z = -14;

//  t     W    fov     H     x     y    yaw   lay
//  Flat -> dolly zoom -> low -> corner(flat->3D) -> flat(swap) -> dolly zoom
//  -> other corner -> flat(swap back) -> flat.  Frame 10 s === frame 0 s.
export const KEYS = [
  { t: 0.00, W: 22, fov: 2.2, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 0 },
  { t: 0.85, W: 22, fov: 2.2, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 0 },
  { t: 0.95, W: 22, fov: 2.3, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 0 },
  { t: 1.85, W: 22, fov: 42,  H: 0.05, x:  0.0, y:  4.0, yaw:   0, lay: 0 },
  { t: 2.35, W: 22, fov: 48,  H:-0.12, x: -0.6, y:  1.6, yaw:   0, lay: 0 },
  { t: 2.85, W: 22, fov: 48,  H:-0.12, x: -0.6, y:  1.6, yaw:   0, lay: 0 },
  { t: 3.20, W: 22, fov: 4.5, H: -0.15, x: -5.0, y: 11.0, yaw:  24, lay: 0 },
  { t: 3.62, W: 22, fov: 4.5, H: -0.15, x: -5.0, y: 11.0, yaw:  24, lay: 0 },
  { t: 4.18, W: 22, fov: 36,  H: 0.35, x: -5.0, y: 11.0, yaw:  24, lay: 0 },
  { t: 4.65, W: 22, fov: 36,  H: 0.30, x: -3.0, y:  9.0, yaw:  18, lay: 0 },
  { t: 5.05, W: 22, fov: 2.2, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 0 },
  { t: 5.15, W: 22, fov: 2.2, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 0 },
  { t: 5.32, W: 22, fov: 2.2, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 1 },
  { t: 5.95, W: 22, fov: 2.2, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 1 },
  { t: 6.10, W: 22, fov: 2.3, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 1 },
  { t: 6.95, W: 22, fov: 46,  H:-0.20, x:  0.4, y:  1.8, yaw:   0, lay: 1 },
  { t: 7.55, W: 22, fov: 46,  H:-0.20, x:  0.4, y:  1.8, yaw:   0, lay: 1 },
  { t: 7.90, W: 22, fov: 5.0, H: -0.10, x:  4.5, y: 12.0, yaw: -26, lay: 1 },
  { t: 8.25, W: 22, fov: 5.0, H: -0.10, x:  4.5, y: 12.0, yaw: -26, lay: 1 },
  { t: 8.72, W: 22, fov: 38,  H: 0.30, x:  3.5, y:  9.0, yaw: -22, lay: 1 },
  { t: 9.10, W: 22, fov: 2.2, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 1 },
  { t: 9.25, W: 22, fov: 2.2, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 1 },
  { t: 9.45, W: 22, fov: 2.2, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 0 },
  { t: 9.80, W: 22, fov: 2.2, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 0 },
  { t:10.00, W: 22, fov: 2.2, H: -0.45, x:  0.0, y:  7.5, yaw:   0, lay: 0 },
];

const LOG_KEYS = new Set(['W', 'fov']);
const CHANNELS = ['W', 'fov', 'H', 'x', 'y', 'yaw', 'lay'];

// Fritsch–Carlson monotone cubic (PCHIP). Speed never jumps at a key.
function slopes(ts, ys) {
  const n = ts.length;
  const h = [], d = [], m = new Array(n);
  for (let i = 0; i < n - 1; i++) { h[i] = ts[i + 1] - ts[i]; d[i] = (ys[i + 1] - ys[i]) / h[i]; }
  m[0] = d[0]; m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) {
    if (d[i - 1] * d[i] <= 0) m[i] = 0;
    else {
      const w1 = 2 * h[i] + h[i - 1], w2 = h[i] + 2 * h[i - 1];
      m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i]);
    }
  }
  return m;
}

const TS = KEYS.map((k) => k.t);
const CURVES = {};
for (const c of CHANNELS) {
  const raw = KEYS.map((k) => (LOG_KEYS.has(c) ? Math.log(k[c]) : k[c]));
  CURVES[c] = { ys: raw, m: slopes(TS, raw) };
}

function hermite(curve, t) {
  const { ys, m } = curve;
  let i = 0;
  while (i < TS.length - 2 && t > TS[i + 1]) i++;
  const h = TS[i + 1] - TS[i];
  const s = Math.max(0, Math.min(1, (t - TS[i]) / h));
  const s2 = s * s, s3 = s2 * s;
  return (2 * s3 - 3 * s2 + 1) * ys[i]
       + (s3 - 2 * s2 + s) * h * m[i]
       + (-2 * s3 + 3 * s2) * ys[i + 1]
       + (s3 - s2) * h * m[i + 1];
}

export function sample(ms) {
  const t = ((ms % LOOP_MS) + LOOP_MS) % LOOP_MS / 1000;
  const s = {};
  for (const c of CHANNELS) {
    const v = hermite(CURVES[c], t);
    s[c] = LOG_KEYS.has(c) ? Math.exp(v) : v;
  }
  s.lay = Math.max(0, Math.min(1, s.lay));
  return s;
}

const _dir = new THREE.Vector3();
const _focus = new THREE.Vector3();
const _look = new THREE.Vector3();

export function applyCamera(cam, s, aspect, wpx, hpx, jx = 0, jy = 0) {
  const hf = (s.fov * Math.PI) / 180;
  const tanH = Math.tan(hf / 2);
  const dist = (s.W / 2) / tanH;
  const yaw = (s.yaw * Math.PI) / 180;

  _dir.set(-Math.sin(yaw), 0, -Math.cos(yaw));
  _focus.set(s.x, s.y, FOCUS_Z);
  cam.position.copy(_focus).addScaledVector(_dir, -dist);
  cam.up.set(0, 1, 0);
  _look.copy(cam.position).add(_dir);
  cam.lookAt(_look);                       // level: verticals stay vertical

  // Asymmetric frustum = lens shift. Horizon lands exactly at NDC y = H.
  const halfV = tanH / aspect;
  const top = halfV * (1 - s.H);
  const bottom = -halfV * (1 + s.H);
  cam.projectionMatrix.makePerspective(-tanH, tanH, top, bottom, 0.3, 2200);
  cam.projectionMatrix.elements[8] += (2 * jx) / wpx;
  cam.projectionMatrix.elements[9] += (2 * jy) / hpx;
  cam.projectionMatrixInverse.copy(cam.projectionMatrix).invert();
  cam.updateMatrixWorld(true);
  return { dist, tanH, halfV, yaw };
}

// A few world points, projected to screen by main.js: used to size motion blur.
export const PROBE_POINTS = [
  [-8.6, 0.2, -6], [8.6, 0.2, -6], [0, 6.5, -14],
  [-9.4, 16, -30], [9.4, 16, -30], [0, 0.2, -60], [0, 22, -120],
];
