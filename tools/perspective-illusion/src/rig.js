// The camera rig — the heart of the illusion.
//
// Method (the perspective-illusion doctrine, reimplemented for this scene):
// - The camera is always LEVEL: it never pitches or rolls, so every vertical
//   stays vertical and the scene reads like an architect's elevation.
//   "Looking down" is done by raising the camera and shifting the lens (el),
//   never by tilting.
// - A shot is a plain object:
//     { x, y, zf, W, fov, H, el, yaw, lay, cs }
//   x, y   pivot side position and height (m)
//   zf     the focus plane (z where W is framed)
//   W      width framed at the focus plane (m). Holding W while fov widens is
//          the dolly zoom: the subject stays put, the space behind stretches.
//   fov    horizontal lens angle (deg): ~2 = flat poster, 25-90 = deep
//   H      where the horizon sits (-1 bottom, 0 middle, 1 top), applied as a
//          lens shift on the projection matrix
//   el     elevation: the camera is raised D*tan(el) above the pivot and the
//          lens shifted back so the pivot stays framed — no tilt
//   yaw    swing around the pivot for corner views (still level)
//   lay    swap-object layout (0 row, 1 diagonal) — changes only during flat
//          holds, where depth cannot betray the trick
//   cs     swap-object scale for the flat view
// - Every parameter runs through one monotone cubic (Fritsch-Carlson) track;
//   W and fov interpolate in log space so speed never jumps. Holds get tiny
//   drift shots so the frame breathes instead of freezing.
// - The loop ends on the shot it starts on, and the first/last keys are equal
//   so the seam joins with zero velocity.
import * as THREE from 'three';
import { cubicTrack } from './curve.js';

export const DURATION = 10;
const LOOP = DURATION;

// The flat poster: the avenue squashed into one elevation. At 2 deg the whole
// street wall reads flat; H pushes the horizon low so the near road occupies
// only a thin band and the facade fills the frame edge to edge.
const flat = { x: 0, y: 7, zf: -26, W: 46, fov: 2, H: -0.34, el: 0, yaw: 0, lay: 0, cs: 1 };
const worm = { x: 0.3, y: 0.7, zf: 12, W: 26, fov: 90, H: -0.72, el: 0, yaw: 0, lay: 0, cs: 1 };
// corner view 1: pivot just past the crossing on the right kerb; yaw -15 keeps
// the frame clear of the near-left blocks while still reading as an oblique.
const obl1T = { x: 3, y: 2, zf: 2, W: 26, fov: 4, H: -0.12, el: 10, yaw: -15, lay: 0, cs: 1 };
const diag = { x: 0.3, y: 7, zf: 10, W: 22, fov: 80, H: 0.66, el: 0, yaw: 0, lay: 1, cs: 1 };
const obl2T = { x: -2, y: 1, zf: 0, W: 36, fov: 4, H: -0.25, el: 24, yaw: 36, lay: 1, cs: 1 };
const low = { x: 0.2, y: 3.6, zf: 10, W: 21, fov: 75, H: 0.14, el: 0, yaw: 0, lay: 1, cs: 1 };

export const SHOTS = {
  flat,
  flat2: { ...flat, W: 44.4 }, // drift: W x 0.965
  flatD: { ...flat, W: 45.3, lay: 1 }, // drift + swapped
  flat2D: { ...flat, W: 44.4, lay: 1 },
  worm,
  worm2: { ...worm, x: 0.05, W: 24.7 },
  // corner view 1: starts on a 4 deg telephoto (reads flat), then opens wide.
  // The turn goes away from the LED tower so the reveal shows something new.
  obl1T,
  obl1T2: { ...obl1T, W: 25, yaw: -13 },
  obl1W: { ...obl1T, W: 21, fov: 30 },
  // high diagonal: the bollards run into depth
  diag,
  diag1b: { ...diag, x: 0.2, W: 20.7 },
  // corner view 2, the other side, higher: telephoto first, then wide
  obl2T,
  obl2T2: { ...obl2T, W: 34.5, yaw: 34 },
  obl2W: { ...obl2T, W: 28, fov: 46 },
  // low diagonal at knee-to-chest height
  low,
  low2: { ...low, x: -0.1, W: 19.9 },
};

// flat -> worm's eye -> corner view (flat, then 3D) -> flat (swap) -> high
// diagonal -> other corner (flat, then 3D) -> low -> flat. Times in seconds.
// The two compression whips (worm2->obl1T, diag1b->obl2T) get 0.5 s each: fast
// enough to read as a snap, slow enough that 32 motion-blur samples stay dense.
const TIMELINE = [
  [0.0, 'flat2'],
  [0.6, 'flat'],
  [1.15, 'worm'],
  [1.76, 'worm2'],
  [2.3, 'obl1T'],
  [2.73, 'obl1T2'],
  [3.37, 'obl1W'],
  [3.78, 'flat'],
  [4.33, 'flatD'],
  [4.87, 'flat2D'],
  [5.33, 'diag'],
  [6.1, 'diag1b'],
  [6.75, 'obl2T'],
  [7.18, 'obl2T2'],
  [7.85, 'obl2W'],
  [8.22, 'low'],
  [9.3, 'low2'],
  [9.8, 'flat2D'],
  [9.92, 'flat2'],
  [10.0, 'flat2'],
];

// Track order. W and fov are interpolated in log space.
const PARAM_KEYS = ['x', 'y', 'zf', 'W', 'fov', 'H', 'lay', 'cs', 'yaw', 'el'];
const LOG_KEYS = new Set(['W', 'fov']);

export class Rig {
  constructor(camera) {
    this.camera = camera;
    this.jit = [0, 0];
    const names = TIMELINE.map((k) => k[0]);
    const times = TIMELINE.map((k) => k[1] * 1000); // ms, matching the render hooks
    this.tracks = {};
    for (const key of PARAM_KEYS) {
      const pts = TIMELINE.map(([t, name]) => [t * 1000, SHOTS[name][key] ?? 0]);
      this.tracks[key] = cubicTrack(pts, { log: LOG_KEYS.has(key) });
    }
    this._times = times;
    this._names = names;
    this.state = { x: 0, y: 0, zf: 0, W: 0, fov: 0, H: 0, el: 0, yaw: 0, lay: 0, cs: 1, d: 0 };
  }

  // Sample every track and place the level camera through a shifted frustum.
  apply(tMs) {
    const ms = ((tMs % (LOOP * 1000)) + LOOP * 1000) % (LOOP * 1000);
    const s = this.state;
    s.x = this.tracks.x(ms);
    s.y = this.tracks.y(ms);
    s.zf = this.tracks.zf(ms);
    s.W = this.tracks.W(ms);
    s.fov = Math.min(118, this.tracks.fov(ms));
    s.H = THREE.MathUtils.clamp(this.tracks.H(ms), -1.6, 1.6);
    s.lay = THREE.MathUtils.clamp(this.tracks.lay(ms), 0, 1);
    s.cs = this.tracks.cs(ms);
    s.yaw = this.tracks.yaw(ms);
    s.el = this.tracks.el(ms);
    this.place(s);
    return s;
  }

  place(s) {
    const cam = this.camera;
    const aspect = cam.aspect || 16 / 9;
    const hf = THREE.MathUtils.degToRad(s.fov);
    // Dolly-zoom framing: the distance follows from W and fov, so the subject
    // keeps its size while the lens opens.
    const D = s.W / 2 / Math.tan(hf / 2);
    const vt = Math.tan(hf / 2) / aspect;
    const te = Math.tan(THREE.MathUtils.degToRad(s.el));
    const yw = THREE.MathUtils.degToRad(s.yaw);
    const camY = s.y + D * te;
    const Hs = s.H + te / vt;
    const camX = s.x + Math.sin(yw) * D;
    const camZ = s.zf + Math.cos(yw) * D;

    cam.fov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(hf / 2) / aspect));
    cam.position.set(camX, camY, camZ);
    cam.up.set(0, 1, 0);
    // Always level, always facing the focus point's horizontal bearing.
    cam.lookAt(camX - Math.sin(yw), camY, camZ - Math.cos(yw));
    cam.updateMatrixWorld(true);
    cam.near = Math.max(0.05, Math.min(1, (Math.min(camZ, D) - 8) * 0.5));
    cam.far = Math.hypot(camX, camZ + 158, camY) + 60;
    cam.updateProjectionMatrix();
    // Lens shift puts the horizon at H; jitter rides along for AA.
    cam.projectionMatrix.elements[9] = -Hs + this.jit[1];
    cam.projectionMatrix.elements[8] += this.jit[0];
    cam.projectionMatrixInverse.copy(cam.projectionMatrix).invert();
    s.d = D;
    return s;
  }

  setJitter(jx, jy) {
    // Sub-pixel lens offset, given in canvas pixels, stored in NDC units:
    // the projection shift terms are ±1 across the half-frame.
    const w = this.camera._probeW || 1920;
    const h = this.camera._probeH || 1080;
    this.jit = [(jx * 2) / w, (jy * 2) / h];
  }

  // Where the probe points land on screen at time ms (canvas pixels + clip z).
  // The renderer compares consecutive calls to size the motion blur.
  probe(ms) {
    const s = this.apply(ms);
    const cam = this.camera;
    const w = cam._probeW || 1920;
    const h = cam._probeH || 1080;
    cam.updateMatrixWorld();
    const out = PROBE.map((v) => {
      const q = v.clone().project(cam);
      return [q.x * (w / 2), q.y * (h / 2), q.z];
    });
    return { state: s, points: out };
  }
}

// Probe points: a grid of street points, dense where the shots look.
const PROBE = [];
for (const x of [-12, -6, 0, 6, 12]) {
  for (const y of [0, 6, 13]) {
    for (const z of [10, -6, -24, -60, -110]) {
      PROBE.push(new THREE.Vector3(x, y, z));
    }
  }
}

export { TIMELINE, LOOP };
