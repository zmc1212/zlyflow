// Night scramble crossing: the scene the camera flies through.
// Everything is built at real-world scale (metres) because the illusion only
// works if the lens, the focus plane and the object sizes agree.
import * as THREE from 'three';
import * as TX from './textures.js';

export const FOCUS = new THREE.Vector3(0, 1.05, -1.5);

const R = TX.mulberry32(20261110);

/* -------------------------------------------------------------------------- */

export function buildScene() {
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x0b1018, 0.0062);

  const root = new THREE.Group();
  scene.add(root);

  const aux = new THREE.Group(); // rain, glows, wet smears: beauty pass only
  aux.name = 'aux';
  root.add(aux);

  const updaters = [];
  const swapObjects = [];

  /* ------------------------------- lighting ------------------------------- */

  scene.add(new THREE.AmbientLight(0x2c3a54, 2.7));
  const hemi = new THREE.HemisphereLight(0x35507a, 0x0a0d12, 1.5);
  scene.add(hemi);

  const moon = new THREE.DirectionalLight(0xbfd6ff, 1.9);
  moon.position.set(-42, 58, 46);
  moon.castShadow = true;
  moon.shadow.mapSize.set(2048, 2048);
  moon.shadow.camera.near = 1;
  moon.shadow.camera.far = 220;
  moon.shadow.camera.left = -48;
  moon.shadow.camera.right = 48;
  moon.shadow.camera.top = 48;
  moon.shadow.camera.bottom = -48;
  moon.shadow.bias = -0.0006;
  moon.shadow.normalBias = 0.05;
  scene.add(moon);
  scene.add(moon.target);

  /* -------------------------------- helpers ------------------------------- */

  function bakeFlat(mesh, color) {
    const col = new THREE.Color(color);
    let g = mesh.geometry;
    if (g.userData.flatColor && !g.userData.flatColor.equals(col)) {
      g = g.clone();
      mesh.geometry = g;
    }
    if (!g.userData.flatColor) {
      const n = g.attributes.position.count;
      const arr = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        arr[i * 3] = col.r;
        arr[i * 3 + 1] = col.g;
        arr[i * 3 + 2] = col.b;
      }
      g.setAttribute('color', new THREE.BufferAttribute(arr, 3));
      g.userData.flatColor = col;
    }
    return mesh;
  }

  function add(geo, mat, color, opts = {}) {
    const m = new THREE.Mesh(geo, mat);
    bakeFlat(m, color);
    m.castShadow = opts.cast !== false;
    m.receiveShadow = opts.receive !== false;
    if (opts.pos) m.position.set(opts.pos[0], opts.pos[1], opts.pos[2]);
    if (opts.rot) m.rotation.set(opts.rot[0], opts.rot[1], opts.rot[2]);
    (opts.parent || root).add(m);
    return m;
  }

  /* --------------------------------- ground -------------------------------- */

  const asphalt = TX.asphaltTexture();
  const asphaltMat = new THREE.MeshStandardMaterial({
    map: asphalt,
    color: 0xdfe6f2,
    roughness: 0.5,
    metalness: 0.18,
    emissive: 0x16202c,
    emissiveIntensity: 1,
  });
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(1500, 1500), asphaltMat);
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  bakeFlat(ground, 0x14161c);
  root.add(ground);

  const walkTex = TX.sidewalkTexture();
  const walkMat = new THREE.MeshStandardMaterial({
    map: walkTex,
    color: 0xb6bfd0,
    roughness: 0.55,
    metalness: 0.22,
  });

  // Kerb quadrants around the crossing.
  const QUAD = [
    [10.6, 34, 10.6, 46],
    [10.6, 34, -46, -10.6],
    [-34, -10.6, 10.6, 46],
    [-34, -10.6, -46, -10.6],
  ];
  for (const [x0, x1, z0, z1] of QUAD) {
    const w = x1 - x0;
    const d = z1 - z0;
    add(
      new THREE.BoxGeometry(w, 0.16, d),
      walkMat,
      0x2a2e38,
      { pos: [(x0 + x1) / 2, 0.08, (z0 + z1) / 2], cast: false }
    );
  }

  // Long sidewalks down the four street arms.
  for (const s of [-1, 1]) {
    add(new THREE.BoxGeometry(6, 0.16, 60), walkMat, 0x2a2e38, {
      pos: [s * 13.2, 0.08, s > 0 ? 40 : -40],
      cast: false,
    });
  }

  /* ------------------------------- crosswalks ------------------------------ */

  const paintMat = new THREE.MeshStandardMaterial({
    color: 0xc9d2e0,
    roughness: 0.45,
    metalness: 0.1,
    emissive: 0x101822,
    emissiveIntensity: 1,
  });

  function zebra(cx, cz, width, length, along, yaw = 0) {
    const g = new THREE.Group();
    g.position.set(cx, 0.012, cz);
    g.rotation.y = yaw;
    const stripe = 0.62;
    const gap = 0.58;
    const count = Math.floor(width / (stripe + gap));
    const startX = -((count - 1) * (stripe + gap)) / 2;
    for (let i = 0; i < count; i++) {
      const geo = new THREE.BoxGeometry(stripe, 0.012, length);
      const m = new THREE.Mesh(geo, paintMat);
      m.position.set(startX + i * (stripe + gap), 0, 0);
      m.receiveShadow = true;
      bakeFlat(m, 0x9aa4b4);
      g.add(m);
    }
    if (along === 'x') g.rotation.y += Math.PI / 2;
    root.add(g);
    return g;
  }

  zebra(0, 7.6, 20, 5.6, 'z'); // near side: bars run along the street axis
  zebra(0, -7.6, 20, 5.6, 'z'); // far side
  zebra(-7.6, 0, 20, 5.6, 'x');
  zebra(7.6, 0, 20, 5.6, 'x');
  // thin diagonal guide lines instead of a second set of bars: they read as a
  // scramble crossing from the poster view without turning the junction into
  // a pile of overlapping planks up close
  for (const yaw of [Math.PI / 4, -Math.PI / 4]) {
    const ax = Math.cos(yaw);
    const az = -Math.sin(yaw);
    for (const off of [-3.0, 0, 3.0]) {
      const bar = new THREE.Mesh(new THREE.BoxGeometry(0.45, 0.01, 14.5), paintMat);
      bakeFlat(bar, 0x9aa4b4);
      bar.position.set(ax * off, 0.011, az * off);
      bar.rotation.y = yaw;
      root.add(bar);
    }
  }

  // lane markings on the four approach arms so the asphalt is never empty
  for (const s of [-1, 1]) {
    for (let i = 0; i < 6; i++) {
      const z = s * (18 + i * 5.4);
      add(new THREE.BoxGeometry(0.18, 0.012, 2.6), paintMat, 0x8f99aa, { pos: [0, 0.012, z], cast: false });
      const x = s * (18 + i * 5.4);
      add(new THREE.BoxGeometry(2.6, 0.012, 0.18), paintMat, 0x8f99aa, { pos: [x, 0.012, 0], cast: false });
    }
  }

  // stop lines
  for (const [x, z, w, d] of [
    [0, 11.4, 20, 0.4],
    [0, -11.4, 20, 0.4],
  ]) {
    add(new THREE.BoxGeometry(w, 0.012, d), paintMat, 0x8f99aa, { pos: [x, 0.014, z], cast: false });
  }

  // manholes / drains
  const drainMat = new THREE.MeshStandardMaterial({ color: 0x1c2028, roughness: 0.4, metalness: 0.7 });
  for (let i = 0; i < 10; i++) {
    const m = add(new THREE.CylinderGeometry(0.34, 0.34, 0.02, 14), drainMat, 0x14181f, {
      pos: [R() * 24 - 12, 0.02, R() * 40 - 26],
      cast: false,
    });
    m.receiveShadow = true;
  }

  /* -------------------------------- buildings ------------------------------ */

  const mkStyle = (opts) => ({ tex: TX.facadeTexture(opts), cols: opts.cols || 6, rows: opts.rows || 12 });
  const facadeStyles = [
    mkStyle({ seed: 2, cols: 6, rows: 12, wall: '#171b25', lit: 0.4 }),
    mkStyle({ seed: 5, cols: 5, rows: 14, wall: '#1b1a24', lit: 0.3, warm: [255, 210, 160] }),
    mkStyle({ seed: 8, cols: 7, rows: 9, wall: '#141821', lit: 0.52, cool: [140, 190, 255] }),
    mkStyle({ seed: 12, cols: 4, rows: 16, wall: '#1e1d26', lit: 0.36 }),
    mkStyle({ seed: 17, cols: 8, rows: 10, wall: '#12151d', lit: 0.46, warm: [255, 180, 120] }),
  ];

  // Shopfront / awning bands used on street-facing walls and on the ground floor
  // of every block (the flat telephoto view mostly sees the z-facing ends).
  const shopFrontMats = [28, 44, 12, 200, 320].map((hue, i) => {
    const t = TX.shopfrontTexture(31 + i, hue);
    return new THREE.MeshStandardMaterial({
      map: t,
      emissiveMap: t,
      emissive: 0xffffff,
      emissiveIntensity: 1.05,
      roughness: 0.5,
    });
  });

  function building(x0, x1, z0, z1, h, styleIdx, opts = {}) {
    const w = x1 - x0;
    const d = z1 - z0;
    const style = facadeStyles[styleIdx % facadeStyles.length];
    const tex = style.tex.clone();
    tex.needsUpdate = true;
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    // keep one window roughly 2.5 m wide and one floor 2.9 m high
    tex.repeat.set(Math.max(0.5, Math.max(w, d) / (style.cols * 2.1)), Math.max(0.5, h / (style.rows * 2.7)));

    const mat = new THREE.MeshStandardMaterial({
      map: tex,
      emissiveMap: tex,
      emissive: new THREE.Color(0xffffff),
      emissiveIntensity: 0.9,
      roughness: 0.82,
      metalness: 0.05,
    });

    const geo = new THREE.BoxGeometry(w, h, d);
    const b = add(geo, mat, 0x1a1f2a, {
      pos: [(x0 + x1) / 2, h / 2, (z0 + z1) / 2],
      cast: true,
    });
    b.receiveShadow = true;

    // ground floor: a lit shop band so the street level is never a blank wall.
    // The band sits 0.45 m in front of the facade: from the 1300 m telephoto,
    // surfaces a few cm apart fight each other and flicker.
    if (h >= 7 && opts.shops !== false) {
      const bandH = 3.0;
      const bandGeo = new THREE.PlaneGeometry(w * 0.96, bandH);
      const f1 = new THREE.Mesh(bandGeo, shopFrontMats[(styleIdx * 3 + 1) % shopFrontMats.length]);
      bakeFlat(f1, 0x3a2a1c);
      f1.position.set((x0 + x1) / 2, bandH / 2 + 0.18, z1 + 0.45);
      f1.receiveShadow = false;
      root.add(f1);
      const f2 = new THREE.Mesh(bandGeo, shopFrontMats[(styleIdx * 3 + 3) % shopFrontMats.length]);
      bakeFlat(f2, 0x3a2a1c);
      f2.position.set((x0 + x1) / 2, bandH / 2 + 0.18, z0 - 0.45);
      f2.rotation.y = Math.PI;
      f2.receiveShadow = false;
      root.add(f2);
    }

    // roof clutter
    if (opts.roof !== false) {
      const rw = w * (0.28 + R() * 0.2);
      const rd = d * (0.28 + R() * 0.2);
      add(new THREE.BoxGeometry(rw, 1.6, rd), mat, 0x1a1f2a, {
        pos: [x0 + w * (0.25 + R() * 0.5), h + 0.8, z0 + d * (0.25 + R() * 0.5)],
      });
      if (R() < 0.5) {
        add(new THREE.CylinderGeometry(0.07, 0.07, 3.4, 6), darkMat, 0x101318, {
          pos: [x0 + w * (0.2 + R() * 0.6), h + 2.4, z0 + d * (0.2 + R() * 0.6)],
        });
      }
    }
    return b;
  }

  const darkMat = new THREE.MeshStandardMaterial({ color: 0x0e1116, roughness: 0.7, metalness: 0.4 });

  // Street walls lining the main axis (camera looks down -z).
  // The two blocks nearest the crossing stay low (7 m, plaza kiosks): corner
  // views swing past them, and a tall near corner would wall off the reveal.
  const rightBlocks = [
    [13, 27, 24, 6, 7, 0],
    [13, 25, 6, -10, 24, 2],
    [13, 29, -10, -28, 16, 1],
    [13, 26, -28, -46, 27, 3],
    [13, 28, -46, -66, 19, 4],
    [13, 30, -66, -90, 31, 0],
    [13, 27, -90, -118, 22, 2],
  ];
  const leftBlocks = [
    [-27, -13, 26, 6, 7, 3],
    [-25, -13, 6, -12, 17, 1],
    [-29, -13, -12, -32, 29, 0],
    [-26, -13, -32, -52, 20, 4],
    [-28, -13, -52, -74, 25, 2],
    [-30, -13, -74, -98, 17, 3],
    [-27, -13, -98, -122, 28, 1],
  ];
  for (const [x0, x1, z0, z1, h, s] of [...rightBlocks, ...leftBlocks]) {
    building(x0, x1, z0, z1, h, s);
  }

  // A wall of buildings closing the far end of the street (depth stacking).
  // The blocks overlap by 1 m: from the 1300 m telephoto even a 1 m slit of
  // horizon sky between towers reads as a solid pink stripe down the frame.
  for (let i = 0; i < 9; i++) {
    const x0 = -54 + i * 12;
    // 24-39 m: the wall tops clear the flat shot's upper edge, so the poster
    // is elevation edge to edge with no sky slits between the blocks
    building(x0, x0 + 13, -142, -158, 24 + ((i * 5) % 16), i % 5, { roof: false });
  }
  for (let i = 0; i < 6; i++) {
    building(-66 + i * 22, -56 + i * 22, -128, -140, 26 + ((i * 8) % 14), (i + 2) % 5, { roof: false });
  }

  // Buildings behind the camera (visible in the wide/corner shots).
  building(20, 46, 34, 60, 18, 1);
  building(-46, -20, 34, 60, 24, 4);

  /* ------------------------------- shopfronts ------------------------------ */

  function shopfront(x, y, z, w, h, rotY, idx) {
    const m = add(new THREE.PlaneGeometry(w, h), shopFrontMats[idx % shopFrontMats.length], 0x3a2a1c, {
      pos: [x, y, z],
      rot: [0, rotY, 0],
      cast: false,
    });
    m.receiveShadow = false;
    return m;
  }

  for (let i = 0; i < 7; i++) {
    // 0.45 m off the facade line: surfaces a few cm apart z-fight at telephoto
    shopfront(12.45, 1.5, 16 - i * 9, 7.4, 2.6, -Math.PI / 2, i);
    shopfront(-12.45, 1.5, 14 - i * 9, 7.4, 2.6, Math.PI / 2, i + 2);
  }

  /* -------------------------------- signage -------------------------------- */

  const signMats = [];
  for (let i = 0; i < 14; i++) {
    const word = TX.SHOP_WORDS ? TX.SHOP_WORDS[i % TX.SHOP_WORDS.length] : '店';
    const hue = [330, 190, 45, 275, 0, 160][i % 6];
    const t = TX.neonSignTexture(word, { seed: 40 + i, hue });
    signMats.push(
      new THREE.MeshStandardMaterial({
        map: t,
        emissiveMap: t,
        emissive: 0xffffff,
        emissiveIntensity: 1.9,
        side: THREE.DoubleSide,
        roughness: 0.6,
      })
    );
  }

  function verticalSign(x, y, z, w, h, rotY, idx) {
    const m = add(new THREE.PlaneGeometry(w, h), signMats[idx % signMats.length], 0x2a2030, {
      pos: [x, y, z],
      rot: [0, rotY, 0],
      cast: false,
    });
    m.receiveShadow = false;
    // tiny bracket so it reads as attached
    add(new THREE.BoxGeometry(0.08, 0.08, 0.5), darkMat, 0x101318, {
      pos: [x + Math.sin(rotY) * 0.28, y + h * 0.42, z + Math.cos(rotY) * 0.28],
      rot: [0, rotY, 0],
      cast: false,
    });
    return m;
  }

  const signSlots = [
    [12.45, 6.4, 15, -Math.PI / 2],
    [12.45, 9.2, 2, -Math.PI / 2],
    [12.45, 5.0, -12, -Math.PI / 2],
    [12.45, 8.4, -24, -Math.PI / 2],
    [12.45, 6.0, -38, -Math.PI / 2],
    [12.45, 10.2, -54, -Math.PI / 2],
    [-12.45, 6.8, 12, Math.PI / 2],
    [-12.45, 9.6, -3, Math.PI / 2],
    [-12.45, 5.4, -18, Math.PI / 2],
    [-12.45, 8.8, -33, Math.PI / 2],
    [-12.45, 6.2, -50, Math.PI / 2],
    [-12.45, 11.0, -70, Math.PI / 2],
  ];
  signSlots.forEach((s, i) => verticalSign(s[0], s[1], s[2], 1.35, 3.6, s[3], i));

  // Two LED screens facing the crossing.
  const ledA = TX.ledScreenTexture(5);
  const ledMat = new THREE.MeshStandardMaterial({
    map: ledA,
    emissiveMap: ledA,
    emissive: 0xffffff,
    emissiveIntensity: 1.9,
    roughness: 0.35,
  });
  add(new THREE.PlaneGeometry(8.4, 4.7), ledMat, 0x40204a, {
    pos: [12.4, 12.6, -19],
    rot: [0, -Math.PI / 2, 0],
    cast: false,
  });
  add(new THREE.PlaneGeometry(7.2, 4.0), ledMat, 0x40204a, {
    pos: [-12.4, 13.4, -36],
    rot: [0, Math.PI / 2, 0],
    cast: false,
  });
  // one screen across the far end so the street has a light source
  add(new THREE.PlaneGeometry(10, 5.6), ledMat, 0x40204a, {
    pos: [0, 15, -141.6],
    rot: [0, 0, 0],
    cast: false,
  });

  /* ---------------------------- poles and signals --------------------------- */

  const poleMat = new THREE.MeshStandardMaterial({ color: 0x232830, roughness: 0.45, metalness: 0.75 });
  const lampMat = new THREE.MeshStandardMaterial({
    color: 0xfff0d0,
    emissive: 0xffd9a0,
    emissiveIntensity: 2.6,
    roughness: 0.4,
  });
  const redMat = new THREE.MeshStandardMaterial({ color: 0x3a0a0a, emissive: 0xff2a1a, emissiveIntensity: 5 });
  const greenMat = new THREE.MeshStandardMaterial({ color: 0x0a2a14, emissive: 0x38e08a, emissiveIntensity: 4 });

  const lampGlows = [];

  function streetLamp(x, z, dir = 1) {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    root.add(g);
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.16, 8.2, 8), poleMat);
    bakeFlat(pole, 0x232830);
    pole.position.y = 4.1;
    pole.castShadow = true;
    g.add(pole);
    const arm = new THREE.Mesh(new THREE.BoxGeometry(2.2, 0.12, 0.12), poleMat);
    bakeFlat(arm, 0x232830);
    arm.position.set(dir * 1.1, 8.1, 0);
    g.add(arm);
    const head = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.16, 0.34), lampMat);
    bakeFlat(head, 0xffe6b8);
    head.position.set(dir * 2.1, 8.0, 0);
    g.add(head);
    const glow = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: TX.glowTexture(),
        color: 0xffd9a0,
        transparent: true,
        opacity: 0.28,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    glow.scale.set(1.3, 1.3, 1);
    glow.position.set(dir * 2.1, 8.0, 0);
    aux.add(glow);
    lampGlows.push(glow);
    // wet ground smear under the lamp
    const smear = new THREE.Mesh(
      new THREE.PlaneGeometry(2.6, 15),
      new THREE.MeshBasicMaterial({
        map: TX.streakTexture(),
        color: 0xffc98a,
        transparent: true,
        opacity: 0.3,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    smear.rotation.x = -Math.PI / 2;
    smear.position.set(x + dir * 2.1, 0.02, z + 7.2);
    aux.add(smear);
    return g;
  }

  streetLamp(11.8, 9.6, -1);
  streetLamp(-11.8, -9.6, 1);
  streetLamp(11.8, -20, -1);
  streetLamp(-11.8, 22, 1);
  streetLamp(11.8, -48, -1);
  streetLamp(-11.8, -62, 1);

  // Practical lights: cheap point lights (no shadow) so the wet road and the
  // shopfronts read instead of going black at night.
  for (const [x, z, dir] of [
    [11.8, 9.6, -1],
    [-11.8, -9.6, 1],
    [11.8, -20, -1],
    [-11.8, 22, 1],
    [11.8, -48, -1],
    [-11.8, -62, 1],
  ]) {
    const l = new THREE.PointLight(0xffd0a0, 260, 40, 2);
    l.position.set(x + dir * 2.1, 7.8, z);
    scene.add(l);
  }
  for (let i = 0; i < 4; i++) {
    const l = new THREE.PointLight(0xff9a5c, 70, 18, 2);
    l.position.set(i % 2 === 0 ? 11.4 : -11.4, 2.4, 12 - i * 18);
    scene.add(l);
  }
  const crossingFill = new THREE.PointLight(0x8ea6d8, 520, 70, 2);
  crossingFill.position.set(0, 15, 0);
  scene.add(crossingFill);
  // over-crossing spill so the zebra and the crowd stay legible from above
  const crossTop = new THREE.PointLight(0xa9bde0, 900, 110, 1.7);
  crossTop.position.set(0, 24, 2);
  scene.add(crossTop);
  for (const z of [-32, -58, -86]) {
    const l = new THREE.PointLight(0x9db4e0, 300, 55, 2);
    l.position.set(0, 12, z);
    scene.add(l);
  }

  // Overhead city glow: lights the ground far from any practical, so the road
  // never turns into a black band in the long-lens view.
  const cityGlow = new THREE.DirectionalLight(0x6f86b8, 1.15);
  cityGlow.position.set(6, 120, 10);
  cityGlow.target.position.set(0, 0, -30);
  scene.add(cityGlow);
  scene.add(cityGlow.target);

  function trafficLight(x, z, rotY, state) {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    g.rotation.y = rotY;
    root.add(g);
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.13, 5.6, 8), poleMat);
    bakeFlat(pole, 0x232830);
    pole.position.y = 2.8;
    pole.castShadow = true;
    g.add(pole);
    const arm = new THREE.Mesh(new THREE.BoxGeometry(4.6, 0.11, 0.11), poleMat);
    bakeFlat(arm, 0x232830);
    arm.position.set(2.3, 5.5, 0);
    g.add(arm);
    const box = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.46, 0.28), darkMat);
    bakeFlat(box, 0x101318);
    box.position.set(4.2, 5.32, 0);
    g.add(box);
    const cols = [redMat, lampMat, greenMat];
    for (let i = 0; i < 3; i++) {
      const lamp = new THREE.Mesh(new THREE.CircleGeometry(0.14, 12), i === state ? cols[i] : darkMat);
      bakeFlat(lamp, i === state ? 0xff3322 : 0x0a0c10);
      lamp.position.set(3.62 + i * 0.52, 5.32, 0.16);
      g.add(lamp);
    }
    return g;
  }

  trafficLight(10.4, 10.4, Math.PI * 0.25, 2);
  trafficLight(-10.4, -10.4, Math.PI * 1.25, 0);
  trafficLight(-10.4, 10.4, Math.PI * 0.75, 2);
  trafficLight(10.4, -10.4, Math.PI * 1.75, 0);

  // Utility poles + overhead wires along the right sidewalk.
  const wirePts = [];
  for (let i = 0; i < 4; i++) {
    const z = 4 - i * 22;
    const p = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.2, 9.4, 7), poleMat);
    bakeFlat(p, 0x232830);
    p.position.set(12.2, 4.7, z);
    p.castShadow = true;
    root.add(p);
    for (let k = 0; k < 3; k++) {
      const armB = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.07, 0.07), poleMat);
      bakeFlat(armB, 0x232830);
      armB.position.set(12.2, 8.6 - k * 0.42, z);
      root.add(armB);
    }
    if (i > 0) {
      for (let k = 0; k < 3; k++) {
        wirePts.push(
          new THREE.Vector3(12.2 - 0.8, 8.6 - k * 0.42, z),
          new THREE.Vector3(12.2 - 0.8, 8.6 - k * 0.42, z + 22)
        );
      }
    }
  }
  const wires = new THREE.LineSegments(
    new THREE.BufferGeometry().setFromPoints(wirePts),
    new THREE.LineBasicMaterial({ color: 0x0a0c11 })
  );
  root.add(wires);

  /* -------------------------------- crowd ---------------------------------- */

  const coats = [0x2b3340, 0x3a2f33, 0x22303a, 0x413a2c, 0x2d2a3c, 0x1f262f];
  const umbColors = [0x1b2430, 0x5e6876, 0x22262e, 0x7a828e, 0x2a3550, 0x4e5666];

  const people = [];
  const bodyGeo = new THREE.CapsuleGeometry(0.16, 0.62, 4, 8);
  const headGeo = new THREE.SphereGeometry(0.105, 10, 8);
  const legGeo = new THREE.BoxGeometry(0.09, 0.58, 0.1);
  const umbGeo = new THREE.ConeGeometry(0.52, 0.2, 12, 1, true);
  const stickGeo = new THREE.CylinderGeometry(0.014, 0.014, 0.8, 5);

  function person(i) {
    const g = new THREE.Group();
    const coat = coats[i % coats.length];
    const body = new THREE.Mesh(bodyGeo, new THREE.MeshStandardMaterial({ color: coat, roughness: 0.85 }));
    bakeFlat(body, coat);
    body.position.y = 1.02;
    body.castShadow = true;
    g.add(body);
    const head = new THREE.Mesh(headGeo, new THREE.MeshStandardMaterial({ color: 0x2a2622, roughness: 0.8 }));
    bakeFlat(head, 0x2a2622);
    head.position.y = 1.52;
    head.castShadow = true;
    g.add(head);
    const legMat = new THREE.MeshStandardMaterial({ color: 0x14171d, roughness: 0.9 });
    for (const s of [-1, 1]) {
      const leg = new THREE.Mesh(legGeo, legMat);
      bakeFlat(leg, 0x14171d);
      leg.position.set(s * 0.08, 0.42, 0);
      leg.castShadow = true;
      g.add(leg);
    }
    const uc = umbColors[(i * 3) % umbColors.length];
    const umb = new THREE.Mesh(umbGeo, new THREE.MeshStandardMaterial({ color: uc, roughness: 0.6, side: THREE.DoubleSide }));
    bakeFlat(umb, uc);
    umb.position.set(0.06, 1.92, 0.02);
    umb.rotation.x = 0.06;
    umb.castShadow = true;
    g.add(umb);
    const stick = new THREE.Mesh(stickGeo, darkMat);
    bakeFlat(stick, 0x101318);
    stick.position.set(0.06, 1.6, 0.02);
    g.add(stick);
    root.add(g);
    return { g, body, head, legs: g.children.slice(2, 4) };
  }

  // The crowd: everyone walks a local line and turns back, one whole
  // out-and-back per 10 s loop (period = LOOP exactly), with a whole number of
  // step cycles per loop — the crowd is seamless at the loop seam. Spans stay
  // short so paces read as walking (1.6-2.6 m/s), not sprinting.
  const crossZ = [-6.5, -3, 0.6, 4.2];
  const crossX = [-8, -4, 0, 4, 8];
  for (let i = 0; i < 56; i++) {
    const p = person(i);
    const lane = i % 4;
    const isAlongZ = i % 3 !== 0;
    const span = i % 7 === 0 ? 2.2 + R() * 1.4 : 8 + R() * 6; // a few just shuffle in place
    let cx;
    let cz;
    if (isAlongZ) {
      cx = crossX[(i * 3) % crossX.length] + (R() - 0.5) * 2.2;
      cz = (R() - 0.5) * 2 * (11 - span / 2);
    } else {
      cx = (R() - 0.5) * 2 * (11 - span / 2);
      cz = crossZ[(i * 2) % crossZ.length] + (R() - 0.5) * 2.4;
    }
    people.push({
      ...p,
      cx,
      cz,
      alongZ: isAlongZ,
      span,
      phase: R(),
      steps: Math.max(6, Math.round((span * 2) / 1.45)), // whole step cycles per loop
      sway: R() * Math.PI * 2,
      lane,
      size: 0.9 + R() * 0.16,
    });
  }

  const tmpV = new THREE.Vector3();

  function updatePeople(t) {
    const TAU = Math.PI * 2;
    for (const p of people) {
      // ping-pong along the local line, period exactly the loop length
      const u = 0.5 - 0.5 * Math.cos(TAU * (t / 10 + p.phase));
      const off = (u - 0.5) * p.span;
      const dir = Math.sin(TAU * (t / 10 + p.phase)); // sign = travel direction
      if (p.alongZ) {
        p.g.position.set(p.cx, Math.abs(Math.sin(TAU * p.steps * (t / 10) + p.sway)) * 0.02, p.cz + off);
        p.g.rotation.y = dir >= 0 ? 0 : Math.PI;
      } else {
        p.g.position.set(p.cx + off, Math.abs(Math.sin(TAU * p.steps * (t / 10) + p.sway)) * 0.02, p.cz);
        p.g.rotation.y = dir >= 0 ? Math.PI / 2 : -Math.PI / 2;
      }
      p.g.scale.setScalar(p.size);
      const swing = Math.sin(TAU * p.steps * (t / 10) + p.sway) * 0.42;
      p.legs[0].rotation.x = swing;
      p.legs[1].rotation.x = -swing;
      p.g.children[0].rotation.z = Math.sin(TAU * p.steps * (t / 10) + p.sway) * 0.02;
    }
  }

  /* ------------------------------ swap objects ------------------------------ */

  // Five bollards: a row while the view is flat, a diagonal once depth opens.
  // They carry the reveal, so they read big and bright from every shot.
  const bollardMat = new THREE.MeshStandardMaterial({ color: 0xe0391f, roughness: 0.5, emissive: 0x521206, emissiveIntensity: 1 });
  const bandMat = new THREE.MeshStandardMaterial({ color: 0xf2ecdc, roughness: 0.5, emissive: 0x3a362c, emissiveIntensity: 1 });

  const swapBase = [];
  for (let i = 0; i < 5; i++) {
    const g = new THREE.Group();
    const x = -9 + i * 4.2;
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.22, 1.06, 12), bollardMat);
    bakeFlat(body, 0xe0391f);
    body.position.y = 0.53;
    body.castShadow = true;
    g.add(body);
    for (const yy of [0.78, 0.38]) {
      const band = new THREE.Mesh(new THREE.CylinderGeometry(0.212, 0.218, 0.14, 12), bandMat);
      bakeFlat(band, 0xf2ecdc);
      band.position.y = yy;
      g.add(band);
    }
    root.add(g);
    swapBase.push({ g, x, z0: 6.4 });
    swapObjects.push(g);
  }

  function updateSwap(lay, cs = 1) {
    swapBase.forEach((s, i) => {
      // row -> diagonal: same x, depth staggered backwards; cs scales the
      // props in the flat view so their size reads right under the telephoto
      s.g.position.set(s.x, 0, s.z0 - lay * i * 2.6);
      s.g.scale.setScalar(cs);
    });
  }

  /* --------------------------------- cars ---------------------------------- */

  const carBody = new THREE.MeshStandardMaterial({ color: 0x1b1f27, roughness: 0.28, metalness: 0.8 });
  const glassMat = new THREE.MeshStandardMaterial({ color: 0x0b1018, roughness: 0.1, metalness: 0.9 });
  const tailMat = new THREE.MeshStandardMaterial({ color: 0x300606, emissive: 0xff2a1a, emissiveIntensity: 4 });
  const headMat = new THREE.MeshStandardMaterial({ color: 0x222018, emissive: 0xfff0c8, emissiveIntensity: 5 });

  function car(x, z, rotY, taxi = false) {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    g.rotation.y = rotY;
    root.add(g);
    const body = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.62, 4.4), carBody);
    bakeFlat(body, 0x1b1f27);
    body.position.y = 0.62;
    body.castShadow = true;
    g.add(body);
    const cabin = new THREE.Mesh(new THREE.BoxGeometry(1.62, 0.56, 2.2), glassMat);
    bakeFlat(cabin, 0x0b1018);
    cabin.position.set(0, 1.16, -0.2);
    cabin.castShadow = true;
    g.add(cabin);
    for (const s of [-1, 1]) {
      const tl = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.12, 0.06), tailMat);
      bakeFlat(tl, 0xff2a1a);
      tl.position.set(s * 0.62, 0.72, 2.2);
      g.add(tl);
      const hl = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.12, 0.06), headMat);
      bakeFlat(hl, 0xfff0c8);
      hl.position.set(s * 0.62, 0.66, -2.2);
      g.add(hl);
    }
    if (taxi) {
      const sign = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.2, 0.24), lampMat);
      bakeFlat(sign, 0xffe6b8);
      sign.position.set(0, 1.55, -0.2);
      g.add(sign);
    }
    return g;
  }

  car(-5.2, -16.5, 0, true);
  car(6.4, -22, Math.PI, false);
  car(-7.5, 18, Math.PI, false);

  /* ---------------------------------- rain --------------------------------- */

  const rainCount = 2600;
  const rainGeo = new THREE.PlaneGeometry(0.016, 0.5);
  const rainMat = new THREE.MeshBasicMaterial({
    color: 0xa9c2e8,
    transparent: true,
    opacity: 0.2,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const rain = new THREE.InstancedMesh(rainGeo, rainMat, rainCount);
  rain.frustumCulled = false;
  aux.add(rain);

  const rainSeed = [];
  for (let i = 0; i < rainCount; i++) {
    rainSeed.push({
      x: (R() - 0.5) * 70,
      z: (R() - 0.5) * 90,
      phase: R(),
      speed: 0.55 + R() * 0.5,
      cycles: 2 + Math.floor(R() * 3), // whole volume-heights per loop
      len: 0.6 + R() * 0.9,
    });
  }
  const mtx = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const eul = new THREE.Euler();
  const scl = new THREE.Vector3();
  const pos = new THREE.Vector3();

  function updateRain(t) {
    for (let i = 0; i < rainCount; i++) {
      const s = rainSeed[i];
      // each streak falls a whole number of volume heights per 10 s loop, so
      // the rain field is identical at the seam
      const y = 26 - ((s.cycles * 26 * (t / 10) + s.phase * 26) % 26);
      pos.set(s.x + y * 0.02, y, s.z);
      eul.set(0, 0, 0.05);
      q.setFromEuler(eul);
      scl.set(1, s.len, 1);
      mtx.compose(pos, q, scl);
      rain.setMatrixAt(i, mtx);
    }
    rain.instanceMatrix.needsUpdate = true;
  }

  /* ------------------------------ wet ground -------------------------------- */

  // Puddle sheen: thin additive ellipses that catch the neon above them. They
  // are kept on the four approach arms so no colour ever spills onto the zebra.
  for (let i = 0; i < 16; i++) {
    const side = i % 4;
    const p = new THREE.Mesh(
      new THREE.CircleGeometry(1.2 + R() * 2.2, 20),
      new THREE.MeshBasicMaterial({
        map: TX.glowTexture(),
        color: i % 5 === 0 ? 0xffb9d0 : 0x8fc0e8,
        transparent: true,
        opacity: 0.035 + R() * 0.035,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    p.rotation.x = -Math.PI / 2;
    const off = 18 + R() * 34;
    if (side < 2) {
      p.position.set((R() - 0.5) * 12, 0.008, side === 0 ? off : -off);
    } else {
      p.position.set(side === 2 ? off : -off, 0.008, (R() - 0.5) * 12);
    }
    aux.add(p);
  }

  // Neon smears under the big signs and screens.
  function smear(x, z, w, len, color, opacity) {
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(w, len),
      new THREE.MeshBasicMaterial({
        map: TX.streakTexture(),
        color,
        transparent: true,
        opacity,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    m.rotation.x = -Math.PI / 2;
    m.position.set(x, 0.015, z + len * 0.5);
    aux.add(m);
  }
  smear(10.5, -19, 5.4, 16, 0xff4da0, 0.12);
  smear(-10.5, -36, 4.6, 14, 0x7a5bff, 0.11);
  smear(0, -140, 8, 40, 0x59d0ff, 0.08);
  smear(10.8, 14, 3.2, 12, 0xffb066, 0.11);
  smear(-10.8, 12, 3.2, 12, 0xff5c8a, 0.11);
  smear(11.8, -20, 3.4, 16, 0xffd9a0, 0.17);

  /* -------------------------------- lifecycle ------------------------------- */

  function update(t) {
    updatePeople(t);
    updateRain(t);
  }

  updateSwap(0);
  update(0);

  function setAuxVisible(v) {
    aux.visible = v;
  }

  // Fog has to be rescaled per shot: the same density that reads right 30 m from
  // the crossing erases the whole frame from 340 m away.
  function setFog(dist) {
    const d = Math.max(0.00035, Math.min(0.0075, 0.0055 * (34 / Math.max(dist, 1))));
    scene.fog.density = d;
  }

  return { scene, root, aux, update, updateSwap, setAuxVisible, setFog, moon, swapObjects, people };
}
