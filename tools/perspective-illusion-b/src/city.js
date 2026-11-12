// ---------------------------------------------------------------------------
// city.js — a procedurally drawn rainy-night street. True metre scale, one
// long axis along -z, repeated things at many depths, filled corner views.
// Everything static is merged by material into a handful of draw calls.
// ---------------------------------------------------------------------------
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import {
  makeAsphalt, makePavement, makeSignAtlas, signUV,
  makeGlow, makePosterAtlas,
} from './textures.js';

const C = {
  wall:   ['#26314c', '#2b3550', '#1f2a44', '#33304f', '#24344a', '#2e2a48'],
  dark:   '#141b2d', trim: '#3c4a68', metal: '#4a5876', wet: '#1b2740',
  warm:   ['#ffd08a', '#ffc267', '#ffe0a8', '#f7b26a'],
  cold:   ['#8fd8ff', '#a9c8ff', '#7fe6e0', '#b8c6ff'],
  off:    '#1a2338',
  neon:   ['#ff4d8d', '#37e0d0', '#ffcb3d', '#7f8cff', '#ff7a45', '#b2f06a'],
};

function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const pick = (r, arr) => arr[(r() * arr.length) | 0];

function tint(g, hex) {
  const c = new THREE.Color(hex);
  const n = g.attributes.position.count;
  const a = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { a[3 * i] = c.r; a[3 * i + 1] = c.g; a[3 * i + 2] = c.b; }
  g.setAttribute('color', new THREE.BufferAttribute(a, 3));
  return g;
}
function setUV(g, [u0, v0, du, dv]) {
  const uv = g.attributes.uv;
  for (let i = 0; i < uv.count; i++) uv.setXY(i, u0 + uv.getX(i) * du, v0 + uv.getY(i) * dv);
  return g;
}
function box(w, h, d, x, y, z, hex, ry = 0) {
  const g = new THREE.BoxGeometry(w, h, d);
  if (ry) g.applyMatrix4(new THREE.Matrix4().makeRotationY(ry));
  g.translate(x, y, z);
  return tint(g, hex);
}
function pZ(w, h, x, y, z, hex, face = 1, uv = null) {
  const g = new THREE.PlaneGeometry(w, h);
  if (face < 0) g.rotateY(Math.PI);
  g.translate(x, y, z);
  if (uv) return setUV(tint(g, '#ffffff'), uv);
  return tint(g, hex);
}
function pX(w, h, x, y, z, hex, face = 1, uv = null) {
  const g = new THREE.PlaneGeometry(w, h);
  g.rotateY(face < 0 ? -Math.PI / 2 : Math.PI / 2);
  g.translate(x, y, z);
  if (uv) return setUV(tint(g, '#ffffff'), uv);
  return tint(g, hex);
}
function pY(w, h, x, y, z, hex, uv = null) {
  const g = new THREE.PlaneGeometry(w, h);
  g.rotateX(-Math.PI / 2);
  g.translate(x, y, z);
  if (uv) return setUV(tint(g, '#ffffff'), uv);
  return tint(g, hex);
}
const merge = (list) => (list.length ? mergeGeometries(list, false) : null);
function meshOf(scene, list, material, layer = 0) {
  const g = merge(list);
  if (!g) return null;
  const m = new THREE.Mesh(g, material);
  m.layers.set(layer);
  m.frustumCulled = false;
  scene.add(m);
  return m;
}

export function buildCity(scene, LOOP_MS) {
  const r = rng(20261111);
  const solid = [], signs = [], posters = [], glows = [], refls = [];
  const fx = [];               // objects on layer 1 (never in the geo pass)
  const atlas = makeSignAtlas();
  const posterAtlas = makePosterAtlas();
  const glowTex = makeGlow();

  // ---- ground: one surface, markings painted into the texture -------------
  const road = new THREE.Mesh(
    new THREE.PlaneGeometry(18, 200),
    new THREE.MeshBasicMaterial({ map: makeAsphalt() })
  );
  road.rotation.x = -Math.PI / 2;
  road.position.set(0, 0, -70);
  road.frustumCulled = false;
  scene.add(road);
  // The telephoto looks almost level: the ground has to reach far beyond the
  // built street or the lower half of the flat frame falls through to sky.
  const farGround = new THREE.Mesh(
    new THREE.PlaneGeometry(500, 1800),
    new THREE.MeshBasicMaterial({ color: '#141c2e' })
  );
  farGround.rotation.x = -Math.PI / 2;
  farGround.position.set(0, -0.03, -1070);
  farGround.frustumCulled = false;
  scene.add(farGround);
  const paveMat = new THREE.MeshBasicMaterial({ map: makePavement() });
  for (const s of [-1, 1]) {
    const p = new THREE.Mesh(new THREE.PlaneGeometry(2.5, 200), paveMat);
    p.rotation.x = -Math.PI / 2;
    p.position.set(s * 10.05, 0.15, -70);
    scene.add(p);
    solid.push(box(0.32, 0.3, 200, s * 8.82, 0.15, -70, C.trim));
    // kerb drains, bollards along the pavement edge
    for (let z = 22; z > -168; z -= 6.5) {
      solid.push(box(0.55, 0.035, 0.35, s * 8.7, 0.31, z, '#1a2338'));
    }
  }

  // ---- buildings ---------------------------------------------------------
  function building(side, z, w, d, h, idx) {
    const cx = side * (9.05 + w / 2);
    const wall = C.wall[idx % C.wall.length];
    solid.push(box(w, h, d, cx, h / 2, z, wall));
    // roof parapet + rooftop clutter (corner views expose these)
    solid.push(box(w + 0.4, 0.5, d + 0.4, cx, h + 0.25, z, C.dark));
    solid.push(box(1.6, 1.5, 1.6, cx - w * 0.25, h + 1.0, z - d * 0.2, C.metal));
    solid.push(box(0.09, 3.4, 0.09, cx + w * 0.3, h + 2.0, z + d * 0.2, C.trim));
    solid.push(box(0.9, 0.09, 0.09, cx + w * 0.3, h + 3.4, z + d * 0.2, C.trim));
    for (let k = 0; k < 3; k++) {
      solid.push(box(0.7, 0.7, 0.3, cx + w * 0.1 + k * 1.1, h + 0.9, z + d * 0.32, C.dark));
    }
    const faceX = side * (9.05 - 0.28);       // 0.28 m off the wall: no z-fight
    const nx = -side;                          // normal pointing at the street
    // window grid on the street facade
    const floors = Math.max(2, Math.floor((h - 4.2) / 2.55));
    for (let f = 0; f < floors; f++) {
      const y = 5.1 + f * 2.55;
      for (let c = 0; c < Math.floor(d / 2.15); c++) {
        const wz = z - d / 2 + 1.3 + c * 2.15;
        const q = r();
        const col = q < 0.40 ? pick(r, C.warm) : q < 0.66 ? pick(r, C.cold) : C.off;
        solid.push(pX(1.25, 1.5, faceX, y, wz, col, nx));
        solid.push(box(0.08, 1.72, 0.08, faceX + nx * 0.04, y, wz - 0.7, C.dark));
        if (r() < 0.32) solid.push(box(1.5, 0.1, 0.32, faceX + nx * 0.16, y - 0.86, wz, C.trim));
        if (r() < 0.18) solid.push(box(0.55, 0.42, 0.32, faceX + nx * 0.2, y - 1.1, wz + 0.4, C.metal));
      }
    }
    // FRONT facade (+z): on a 2-degree lens the whole street collapses into
    // these cross-sections, so this is the face that fills the flat poster.
    const frontZ = z + d / 2 + 0.3;
    const ff = Math.max(2, Math.floor((h - 4.6) / 2.4));
    for (let f = 0; f < ff; f++) {
      const y = 5.0 + f * 2.4;
      for (let c = 0; c < Math.max(3, Math.floor(w / 1.95)); c++) {
        const wx = cx - w / 2 + 1.15 + c * 1.95;
        const q = r();
        const col = q < 0.40 ? pick(r, C.warm) : q < 0.64 ? pick(r, C.cold) : C.off;
        solid.push(pZ(1.28, 1.5, wx, y, frontZ, col, 1));
        solid.push(box(0.07, 1.7, 0.07, wx - 0.7, y, frontZ + 0.04, C.dark));
        if (r() < 0.30) solid.push(box(1.5, 0.09, 0.3, wx, y - 0.86, frontZ + 0.16, C.trim));
        if (r() < 0.22) solid.push(pZ(0.35, 0.45, wx + 0.3, y - 0.95, frontZ + 0.05, '#c7d4e8', 1));
      }
    }
    // front shopfront, horizontal sign and vertical neon (read in the flat view)
    const shopCol2 = r() < 0.5 ? '#ffcf85' : '#8fd8ff';
    solid.push(pZ(w * 0.80, 2.45, cx, 1.62, frontZ, shopCol2, 1));
    solid.push(box(w * 0.86, 0.16, 1.1, cx, 3.15, frontZ + 0.5, C.neon[(idx + 2) % 6]));
    const cellF = (idx * 7 + 5) % 16;
    signs.push(pZ(w * 0.62, 1.15, cx, 4.15, frontZ + 0.06, '#ffffff', 1, signUV(cellF)));
    const cellV = (idx * 3 + 11) % 16;
    const vx = cx + w * 0.32;
    signs.push(pZ(1.1, 4.3, vx, 7.9, frontZ + 0.07, '#ffffff', 1, signUV(cellV)));
    glows.push(pZ(2.8, 5.8, vx, 7.9, frontZ + 0.12, C.neon[cellV % 6], 1));
    refls.push(pY(1.6, 7.0, vx * 0.16, 0.025, frontZ + 1.5, C.neon[cellV % 6]));
    // ground floor: awning, lit shop window, door, poster
    const shopCol = r() < 0.5 ? '#ffcf85' : '#8fd8ff';
    solid.push(pX(d * 0.78, 2.5, faceX, 1.65, z, shopCol, nx));
    solid.push(box(1.15, 0.16, d * 0.86, faceX + nx * 0.55, 3.15, z, C.neon[idx % 6]));
    for (let k = 0; k < 4; k++) {
      solid.push(box(0.07, 2.5, 0.07, faceX + nx * 0.02, 1.65, z - d * 0.38 + k * (d * 0.25), C.dark));
    }
    solid.push(pX(1.0, 2.2, faceX, 1.5, z - d * 0.38, C.dark, nx));
    // vertical neon sign hung off the facade
    if (idx % 2 === 0 || r() < 0.5) {
      const cell = (idx * 3 + (side > 0 ? 1 : 0)) % 16;
      const sy = 6.5 + (idx % 3) * 1.3;
      const sz = z + d * 0.30;
      signs.push(pX(1.15, 4.4, faceX + nx * 0.42, sy, sz, '#ffffff', nx, signUV(cell)));
      glows.push(pX(3.0, 6.0, faceX + nx * 0.5, sy, sz, C.neon[cell % 6], nx));
      refls.push(pY(1.5, 7.0, 0.6 * side, 0.02, sz, C.neon[cell % 6]));
    }
    // horizontal shop sign
    if (r() < 0.75) {
      const cell = (idx * 5 + 3) % 16;
      signs.push(pX(d * 0.7, 1.15, faceX + nx * 0.12, 4.15, z, '#ffffff', nx, signUV(cell)));
    }
    // posters and stickers: wear & story
    for (let k = 0; k < 3; k++) {
      const pz = z - d * 0.4 + k * 1.2;
      posters.push(pX(0.75, 1.05, faceX + nx * 0.05, 1.1 + r() * 1.2, pz, '#ffffff', nx,
        [(k % 4) * 0.25, 1 - (((idx + k) % 2) + 1) * 0.5, 0.25, 0.5]));
    }
    // drain pipe, fire escape, AC units on the street side
    solid.push(box(0.16, h - 1, 0.16, side * (9.05 - 0.1), (h - 1) / 2, z - d * 0.45, C.metal));
    for (let f = 1; f < 4; f++) {
      solid.push(box(0.8, 0.06, 1.6, side * (9.05 - 0.45), f * 3.2, z + d * 0.15, C.metal));
    }
  }

  // Sign gates spanning the street. On the long lens they stack into horizontal
  // bands of the flat drawing; when the lens opens they separate in depth.
  function overpass(z, y, idx) {
    solid.push(box(19.6, 0.34, 0.55, 0, y + 1.55, z, C.metal));
    solid.push(box(19.6, 0.10, 0.10, 0, y + 2.4, z, C.trim));
    for (const s of [-1, 1]) {
      solid.push(box(0.22, y + 1.5, 0.22, s * 9.5, (y + 1.5) / 2, z, C.metal));
    }
    solid.push(pZ(9.6, 2.0, 0, y + 0.55, z + 0.15, '#101a2e', 1));
    signs.push(pZ(8.8, 1.65, 0, y + 0.55, z + 0.45, '#ffffff', 1, signUV(idx)));
    glows.push(pZ(11.0, 3.2, 0, y + 0.55, z + 0.5, C.neon[idx % 6], 1));
    for (let k = -4; k <= 4; k++) {
      solid.push(box(0.12, 0.12, 0.12, k * 2.1, y + 1.3, z + 0.3, '#ffe6ae'));
    }
  }
  [[-32, 6.3, 2], [-68, 7.1, 9], [-110, 6.7, 5], [-152, 7.5, 13]].forEach((a) => overpass(...a));

  // Low banners across the street: they fill the lower band of the flat frame
  // and, once the lens opens, become four separate objects at four depths.
  function lowBanner(z, y, idx) {
    solid.push(box(17.5, 0.14, 0.3, 0, y + 0.85, z, C.trim));
    solid.push(pZ(13.0, 1.35, 0, y, z + 0.16, '#101a2e', 1));
    signs.push(pZ(12.4, 1.1, 0, y, z + 0.46, '#ffffff', 1, signUV(idx)));
    glows.push(pZ(15.0, 2.4, 0, y, z + 0.5, C.neon[idx % 6], 1));
    for (const s of [-1, 1]) {
      solid.push(box(0.16, y + 0.9, 0.16, s * 8.6, (y + 0.9) / 2, z, C.metal));
    }
  }
  [[-26, 5.6, 1], [-58, 6.2, 6], [-96, 5.5, 10], [-134, 6.1, 14]].forEach((a) => lowBanner(...a));

  // far backdrop: low, wide, dense with windows. Guarantees the flat frame is
  // full edge to edge while leaving a thin strip of painted sky above it.
  const bz = -430;
  solid.push(box(150, 13.5, 4, 0, 6.75, bz, '#1d2740'));
  for (let f = 0; f < 4; f++) {
    for (let c = 0; c < 44; c++) {
      const wx = -62 + c * 2.9, wy = 2.0 + f * 2.9;
      const col = r() < 0.33 ? '#c2a479' : r() < 0.55 ? '#7f9dc0' : '#2b3654';
      solid.push(pZ(1.6, 1.7, wx, wy, bz + 2.05, col, 1));
    }
  }

  let bi = 0;
  for (const side of [-1, 1]) {
    let z = 22;
    while (z > -168) {
      const d = 8.5 + r() * 3.2;
      const w = 9 + r() * 6;
      const h = 15 + r() * 24;
      building(side, z - d / 2, w, d, h, bi + (side > 0 ? 7 : 0));
      z -= d + 0.7 + r() * 1.3;
      bi++;
    }
  }
  // distant wall of facades: a dense backdrop that the telephoto stacks up
  for (let row = 0; row < 2; row++) {
    for (let i = 0; i < 14; i++) {
      const x = -33 + i * 5.0 + r() * 1.2;
      const h = 20 + r() * 34;
      const z = -205 - row * 46 - r() * 12;
      solid.push(box(4.6 + r() * 1.2, h, 6, x, h / 2, z, row ? '#1a2338' : '#212b46'));
      for (let f = 0; f < Math.floor(h / 2.3); f++) {
        for (let c = 0; c < 2; c++) {
          solid.push(pZ(1.05, 1.15, x - 1.15 + c * 2.3, 3.0 + f * 2.3, z + 3.05,
            r() < 0.42 ? (row ? '#6c6f86' : '#d6b785') : '#2a3452', 1));
        }
      }
      solid.push(box(5.2, 0.4, 6.4, x, h + 0.2, z, '#121a2c'));
    }
  }

  // ---- street furniture --------------------------------------------------
  for (let z = 18; z > -166; z -= 13) {
    for (const s of [-1, 1]) {
      const x = s * 8.45;
      solid.push(box(0.17, 6.6, 0.17, x, 3.3, z, C.metal));
      solid.push(box(1.5, 0.13, 0.13, x - s * 0.72, 6.5, z, C.metal));
      solid.push(box(0.9, 0.16, 0.42, x - s * 1.4, 6.38, z, '#f6e2ae'));
      glows.push(pZ(2.6, 2.6, x - s * 1.4, 6.3, z + 0.08, '#ffd68a', 1));
      refls.push(pY(1.5, 9.0, x - s * 1.4, 0.025, z, '#ffcf7a'));
      // utility box, bin, bollard at the pole base
      if (r() < 0.65) {
        solid.push(box(0.7, 1.2, 0.5, s * 9.9, 0.75, z - 2.1, '#3a4a63'));
        solid.push(pX(0.5, 0.8, s * 9.55, 0.78, z - 2.1, '#6a7d9c', -s));
      }
    }
    // traffic signal over the crossing
    if (Math.abs(z + 14) < 8) {
      solid.push(box(0.2, 5.2, 0.2, 8.7, 2.6, z, C.metal));
      solid.push(box(3.2, 0.16, 0.16, 7.1, 5.1, z, C.metal));
      solid.push(pZ(0.9, 0.9, 5.7, 4.8, z + 0.12, '#ff5a4d', 1));
      glows.push(pZ(2.4, 2.4, 5.7, 4.8, z + 0.2, '#ff5a4d', 1));
    }
  }
  // overhead wires: a few long catenary lines (layer 1, no ink)
  const wirePts = [];
  for (const s of [-1, 1]) {
    for (const y0 of [7.4, 8.1, 9.0]) {
      for (let z = 16; z > -160; z -= 26) {
        for (let k = 0; k < 10; k++) {
          const a = z - k * 2.6, b = z - (k + 1) * 2.6;
          const sag = (t) => 0.55 * Math.sin(Math.PI * t);
          wirePts.push(s * 9.4, y0 - sag(k / 10), a, s * 9.4, y0 - sag((k + 1) / 10), b);
        }
      }
    }
  }
  const wireGeo = new THREE.BufferGeometry();
  wireGeo.setAttribute('position', new THREE.Float32BufferAttribute(wirePts, 3));
  const wires = new THREE.LineSegments(wireGeo, new THREE.LineBasicMaterial({ color: '#4c5875', transparent: true, opacity: 0.85 }));
  wires.layers.set(1); wires.frustumCulled = false; scene.add(wires); fx.push(wires);

  // vending machines, bikes, bins, hydrants, signs
  for (let i = 0; i < 18; i++) {
    const s = i % 2 ? 1 : -1;
    const z = 14 - i * 10.3;
    const x = s * 10.6;
    solid.push(box(1.0, 1.9, 0.8, x, 0.95, z, '#8e3550'));
    solid.push(pX(0.75, 1.2, x - s * 0.42, 1.15, z, '#ffd6a0', -s));
    solid.push(box(0.05, 0.4, 0.5, x - s * 0.5, 0.35, z + 0.3, C.dark));
    if (i % 3 === 0) {
      solid.push(box(0.12, 1.0, 0.12, s * 10.9, 0.5, z - 2.4, '#c4483f'));
      solid.push(box(0.5, 0.12, 0.12, s * 10.9, 0.95, z - 2.4, '#c4483f'));
    }
  }

  // ---- the swap objects: a row that becomes a depth diagonal -------------
  const coneGeo = new THREE.ConeGeometry(0.28, 0.82, 8);
  coneGeo.translate(0, 0.41, 0);
  tint(coneGeo, '#ff6a4d');
  const baseGeo = new THREE.BoxGeometry(0.62, 0.07, 0.62);
  tint(baseGeo, '#e9e4d8');
  const bandGeo = new THREE.CylinderGeometry(0.19, 0.23, 0.14, 8);
  bandGeo.translate(0, 0.42, 0);
  tint(bandGeo, '#f4efe4');
  const coneParts = mergeGeometries([coneGeo, baseGeo, bandGeo], false);
  const cones = new THREE.InstancedMesh(
    coneParts,
    new THREE.MeshBasicMaterial({ vertexColors: true }),
    6
  );
  cones.frustumCulled = false;
  cones.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  scene.add(cones);
  const coneDummy = new THREE.Object3D();

  // ---- walkers with umbrellas -------------------------------------------
  const umbrella = new THREE.ConeGeometry(0.62, 0.3, 10);
  umbrella.translate(0, 1.92, 0); tint(umbrella, '#4a3a63');
  const body = new THREE.BoxGeometry(0.32, 0.95, 0.26);
  body.translate(0, 1.18, 0); tint(body, '#1b2338');
  const legs = new THREE.BoxGeometry(0.24, 0.62, 0.22);
  legs.translate(0, 0.42, 0); tint(legs, '#12182a');
  const handle = new THREE.BoxGeometry(0.04, 0.85, 0.04);
  handle.translate(0, 1.5, 0); tint(handle, '#6a587f');
  const walkerGeo = mergeGeometries([umbrella, body, legs, handle], false);
  const walkers = new THREE.InstancedMesh(walkerGeo, new THREE.MeshBasicMaterial({ vertexColors: true }), 46);
  walkers.frustumCulled = false;
  walkers.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  scene.add(walkers);
  const walkerDummy = new THREE.Object3D();
  const walkerSeed = Array.from({ length: 46 }, () => ({
    side: r() < 0.5 ? -1 : 1,
    z0: 24 - r() * 190,
    x: 9.4 + r() * 1.6,
    dir: r() < 0.5 ? -1 : 1,
    size: 0.88 + r() * 0.26,
    col: new THREE.Color(['#5b4776', '#3b5b7c', '#7a4258', '#4a6b6a', '#6b5a3d'][(r() * 5) | 0]),
  }));
  walkers.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(46 * 3), 3);
  walkerSeed.forEach((w, i) => walkers.setColorAt(i, w.col));

  // ---- cars (loop an exact whole number of cycles) -----------------------
  const carParts = [];
  carParts.push(box(1.9, 0.72, 4.1, 0, 0.65, 0, '#8f3f56'));
  carParts.push(box(1.7, 0.62, 2.2, 0, 1.28, -0.25, '#26324b'));
  carParts.push(pZ(1.5, 0.5, 0, 1.28, 0.88, '#9fc4e6', 1));
  carParts.push(pZ(0.36, 0.18, -0.62, 0.72, 2.06, '#ffe6a8', 1));
  carParts.push(pZ(0.36, 0.18, 0.62, 0.72, 2.06, '#ffe6a8', 1));
  carParts.push(pZ(0.34, 0.16, -0.62, 0.72, -2.06, '#ff5a4d', -1));
  carParts.push(pZ(0.34, 0.16, 0.62, 0.72, -2.06, '#ff5a4d', -1));
  const carGeo = merge(carParts);
  const carMat = new THREE.MeshBasicMaterial({ vertexColors: true });
  const cars = [
    { x0: -3.2, z: -11.5, speed: 52, rot: Math.PI / 2 },
    { x0: 3.1, z: -25, speed: -52, rot: Math.PI / 2 },
    { x0: 0, z: -55, speed: 40, rot: 0 },
  ].map((c) => {
    const m = new THREE.Mesh(carGeo, carMat);
    m.rotation.y = c.rot;
    m.frustumCulled = false;
    scene.add(m);
    return { ...c, mesh: m };
  });

  // ---- rain: pure function of ms, whole cycles per loop ------------------
  const NRAIN = 900;
  const rainSeed = Array.from({ length: NRAIN }, () => ({
    x: -13 + r() * 26, y0: r() * 42, z: 26 - r() * 200, len: 0.5 + r() * 0.9,
  }));
  const rainGeo = new THREE.BufferGeometry();
  rainGeo.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(NRAIN * 6), 3));
  const rain = new THREE.LineSegments(rainGeo, new THREE.LineBasicMaterial({ color: '#b9cdf0', transparent: true, opacity: 0.32 }));
  rain.layers.set(1); rain.frustumCulled = false; scene.add(rain); fx.push(rain);

  // ---- merged static meshes ---------------------------------------------
  const solidMat = new THREE.MeshBasicMaterial({ vertexColors: true });
  meshOf(scene, solid, solidMat);
  meshOf(scene, signs, new THREE.MeshBasicMaterial({
    map: atlas, side: THREE.DoubleSide, transparent: true, alphaTest: 0.35,
  }));
  meshOf(scene, posters, new THREE.MeshBasicMaterial({ map: posterAtlas, side: THREE.DoubleSide }));
  const fxMat = new THREE.MeshBasicMaterial({
    map: glowTex, vertexColors: true, transparent: true,
    blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
    opacity: 0.55,
  });
  meshOf(scene, glows, fxMat, 1);
  const reflMat = new THREE.MeshBasicMaterial({
    map: glowTex, vertexColors: true, transparent: true,
    blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
    opacity: 0.30,
  });
  meshOf(scene, refls, reflMat, 1);

  function update(ms, s) {
    const phase = (ms % LOOP_MS) / LOOP_MS;

    // cones: only depth changes, so the flat telephoto frame cannot see it
    for (let i = 0; i < 6; i++) {
      const x = -3.0 + i * 1.2;
      const z = -8 - s.lay * i * 3.6;
      coneDummy.position.set(x, 0.04, z);
      coneDummy.rotation.set(0, 0, 0);
      coneDummy.scale.setScalar(1);
      coneDummy.updateMatrix();
      cones.setMatrixAt(i, coneDummy.matrix);
    }
    cones.instanceMatrix.needsUpdate = true;

    // walkers
    for (let i = 0; i < 46; i++) {
      const w = walkerSeed[i];
      let z = w.z0 + w.dir * phase * 200;
      z = ((((z + 170) % 200) + 200) % 200) - 170;
      walkerDummy.position.set(w.side * w.x, 0.16, z);
      walkerDummy.rotation.set(0, w.dir > 0 ? 0 : Math.PI, 0);
      walkerDummy.scale.setScalar(w.size);
      walkerDummy.updateMatrix();
      walkers.setMatrixAt(i, walkerDummy.matrix);
    }
    walkers.instanceMatrix.needsUpdate = true;

    // cars
    for (const c of cars) {
      const p = (((c.x0 + phase * c.speed + 30) % 60) + 60) % 60 - 30;
      if (c.rot) c.mesh.position.set(p, 0, c.z);
      else c.mesh.position.set(c.x0, 0,
        (((c.z + phase * c.speed + 170) % 200) + 200) % 200 - 170);
    }

    // rain
    const arr = rainGeo.attributes.position.array;
    for (let i = 0; i < NRAIN; i++) {
      const d = rainSeed[i];
      let y = d.y0 - phase * 84;
      y = (((y % 42) + 42) % 42);
      const k = i * 6;
      arr[k] = d.x; arr[k + 1] = y; arr[k + 2] = d.z;
      arr[k + 3] = d.x + 0.08; arr[k + 4] = y - d.len; arr[k + 5] = d.z;
    }
    rainGeo.attributes.position.needsUpdate = true;
  }

  return { update, fx };
}
