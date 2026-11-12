// textures.js — everything is drawn with canvas 2D; no external assets.
import * as THREE from 'three';

export function canvasTex(w, h, draw) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d');
  draw(g, w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.NoColorSpace;   // exact values: colour management is off
  t.anisotropy = 8;
  return t;
}

function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Road: one surface, markings painted on, never coplanar planes (no z-fighting).
// u spans x [-9,9], v spans z [+30,-170]. Crossing is at z=-14 -> v=0.22.
export function makeAsphalt() {
  return canvasTex(1024, 2048, (g, w, h) => {
    const r = rng(7713);
    g.fillStyle = '#151c2c'; g.fillRect(0, 0, w, h);
    for (let i = 0; i < 26000; i++) {
      const x = r() * w, y = r() * h, a = r() * 0.09;
      g.fillStyle = r() > 0.5 ? `rgba(150,175,220,${a})` : `rgba(0,0,0,${a * 1.5})`;
      g.fillRect(x, y, 1 + r() * 2, 1 + r() * 2);
    }
    // wet streaks along the street (v axis)
    for (let i = 0; i < 190; i++) {
      const x = r() * w, y = r() * h, len = 25 + r() * 190;
      const grd = g.createLinearGradient(x, y, x, y + len);
      grd.addColorStop(0, 'rgba(120,160,220,0)');
      grd.addColorStop(0.5, `rgba(${90 + r() * 60 | 0},${140 + r() * 60 | 0},220,${0.03 + r() * 0.07})`);
      grd.addColorStop(1, 'rgba(120,160,220,0)');
      g.fillStyle = grd; g.fillRect(x, y, 2 + r() * 12, len);
    }
    const X = (m) => ((m + 9) / 18) * w;
    const V = (z) => ((30 - z) / 200) * h;
    // kerb shadow bands
    g.fillStyle = 'rgba(4,7,16,0.55)';
    g.fillRect(0, 0, X(-8.55), h); g.fillRect(X(8.55), 0, w - X(8.55), h);
    // centre double line
    g.fillStyle = '#c9a25a';
    g.fillRect(X(-0.42), 0, 3, h); g.fillRect(X(0.20), 0, 3, h);
    // lane dashes
    g.fillStyle = 'rgba(210,220,235,0.55)';
    for (let z = -168; z < 30; z += 7) {
      g.fillRect(X(-4.4), V(z), 3, (5 / 200) * h);
      g.fillRect(X(4.3), V(z), 3, (5 / 200) * h);
    }
    // zebra crossing at the junction (two bands)
    for (const zc of [-14, -19]) {
      for (let i = -8; i <= 8; i += 1.15) {
        g.fillStyle = 'rgba(222,230,240,0.72)';
        g.fillRect(X(i), V(zc - 1.5), (0.72 / 18) * w, (3 / 200) * h);
      }
    }
    // stop lines
    g.fillStyle = 'rgba(225,232,242,0.6)';
    g.fillRect(X(-8.4), V(-9), (16.8 / 18) * w, 5);
    g.fillRect(X(-8.4), V(-24), (16.8 / 18) * w, 5);
    // drains + manholes
    for (let i = 0; i < 26; i++) {
      const x = X(-8.2 + r() * 16.4), y = V(28 - r() * 195);
      g.strokeStyle = 'rgba(8,12,22,0.8)'; g.lineWidth = 2;
      g.fillStyle = 'rgba(40,52,74,0.9)';
      g.beginPath(); g.ellipse(x, y, 9, 5, 0, 0, 7); g.fill(); g.stroke();
    }
    // puddle stains
    for (let i = 0; i < 60; i++) {
      const x = r() * w, y = r() * h;
      const grd = g.createRadialGradient(x, y, 0, x, y, 12 + r() * 55);
      grd.addColorStop(0, 'rgba(90,135,190,0.10)'); grd.addColorStop(1, 'rgba(90,135,190,0)');
      g.fillStyle = grd; g.beginPath(); g.ellipse(x, y, 40, 22, 0, 0, 7); g.fill();
    }
  });
}

export function makePavement() {
  const t = canvasTex(512, 512, (g, w, h) => {
    const r = rng(9931);
    g.fillStyle = '#252c3e'; g.fillRect(0, 0, w, h);
    for (let y = 0; y < h; y += 64) {
      for (let x = 0; x < w; x += 64) {
        g.fillStyle = `rgba(${120 + r() * 22 | 0},${135 + r() * 22 | 0},${160 + r() * 22 | 0},0.07)`;
        g.fillRect(x + 2, y + 2, 60, 60);
        g.strokeStyle = 'rgba(8,12,22,0.55)'; g.lineWidth = 2;
        g.strokeRect(x + 2, y + 2, 60, 60);
      }
    }
    for (let i = 0; i < 4000; i++) {
      g.fillStyle = `rgba(190,205,230,${r() * 0.05})`;
      g.fillRect(r() * w, r() * h, 2, 2);
    }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(2, 26);
  return t;
}

// 4x4 atlas of invented shop signs. Cell (col,row) -> uv rect.
export const SIGN_COLS = 4;
export const SIGN_ROWS = 4;
export const SIGN_LABELS = [
  '夜灯', 'MARU', 'ラーメン', 'KIRIN',
  '電器', 'COFFEE', '青空', '24H',
  'BOOKS', '月見', 'NOCTURNE', '食堂',
  '花屋', 'BAR', 'TOKYO', '音盤',
];
export function signUV(i) {
  const c = i % SIGN_COLS, r = (i / SIGN_COLS) | 0;
  const s = 1 / SIGN_COLS, t = 1 / SIGN_ROWS;
  return [c * s, 1 - (r + 1) * t, s, t];
}

export function makeSignAtlas() {
  return canvasTex(1024, 1024, (g, w, h) => {
    const S = w / SIGN_COLS;
    g.clearRect(0, 0, w, h);
    const palette = [
      ['#ff4d8d', '#2a0f28'], ['#37e0d0', '#08262c'], ['#ffcb3d', '#2a1e08'], ['#7f8cff', '#151a35'],
      ['#ff7a45', '#2c140c'], ['#b2f06a', '#13240e'], ['#ff5f5f', '#2a1010'], ['#59b8ff', '#0c1c2e'],
      ['#f7e6b0', '#2b2417'], ['#c58cff', '#1d1030'], ['#ff9ecb', '#2a1020'], ['#8ff0c0', '#0c241a'],
      ['#ffd166', '#2a1c0a'], ['#6ce5ff', '#08222b'], ['#ff8a5c', '#2a140c'], ['#a0a8ff', '#14142c'],
    ];
    const r = rng(5501);
    SIGN_LABELS.forEach((label, i) => {
      const x = (i % 4) * S, y = ((i / 4) | 0) * S;
      const [fg, bg] = palette[i];
      g.fillStyle = bg; g.fillRect(x + 6, y + 6, S - 12, S - 12);
      g.strokeStyle = fg; g.lineWidth = 6; g.strokeRect(x + 12, y + 12, S - 24, S - 24);
      g.strokeStyle = 'rgba(255,255,255,0.18)'; g.lineWidth = 2;
      g.strokeRect(x + 22, y + 22, S - 44, S - 44);
      g.fillStyle = fg;
      g.textAlign = 'center'; g.textBaseline = 'middle';
      const isCJK = /[^\x00-\x7F]/.test(label);
      if (isCJK) {
        g.font = `bold ${label.length > 2 ? 58 : 84}px "Microsoft YaHei","Noto Sans CJK SC",sans-serif`;
        const chars = [...label];
        const step = 74;
        chars.forEach((ch, k) => g.fillText(ch, x + S / 2, y + S / 2 + (k - (chars.length - 1) / 2) * step));
      } else {
        g.font = `bold ${label.length > 6 ? 34 : label.length > 4 ? 46 : 58}px "Arial",sans-serif`;
        g.fillText(label, x + S / 2, y + S / 2);
      }
      g.fillStyle = 'rgba(255,255,255,0.55)';
      g.font = '20px Arial';
      g.fillText(`No.${String(i + 1).padStart(2, '0')}`, x + S / 2, y + S - 34);
      // tiny bulbs
      for (let k = 0; k < 8; k++) {
        g.fillStyle = `rgba(255,255,255,${0.25 + r() * 0.5})`;
        g.beginPath(); g.arc(x + 28 + k * (S - 56) / 7, y + 26, 3, 0, 7); g.fill();
      }
    });
  });
}

export function makeGlow() {
  return canvasTex(256, 256, (g, w, h) => {
    const grd = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    grd.addColorStop(0, 'rgba(255,255,255,1)');
    grd.addColorStop(0.12, 'rgba(255,255,255,0.72)');
    grd.addColorStop(0.38, 'rgba(255,255,255,0.18)');
    grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd; g.fillRect(0, 0, w, h);
  });
}

export function makePosterAtlas() {
  return canvasTex(512, 512, (g, w, h) => {
    const r = rng(3312);
    g.fillStyle = '#e8e2d2'; g.fillRect(0, 0, w, h);
    const words = ['雨', 'SALE', '夜', 'LIVE', '_OPEN', '市', 'LOOP', '光'];
    for (let i = 0; i < 8; i++) {
      const x = (i % 4) * 128, y = ((i / 4) | 0) * 256;
      g.fillStyle = ['#d8445c', '#2f4d80', '#e0a83b', '#3b7a68'][i % 4];
      g.fillRect(x + 8, y + 8, 112, 240);
      g.fillStyle = '#f4efe2'; g.textAlign = 'center';
      g.font = 'bold 46px "Microsoft YaHei",sans-serif';
      g.fillText(words[i], x + 64, y + 100);
      g.font = '16px Arial';
      g.fillText('NEON CITY', x + 64, y + 150);
      for (let k = 0; k < 5; k++) {
        g.fillStyle = `rgba(20,20,30,${0.1 + r() * 0.2})`;
        g.fillRect(x + 18, y + 175 + k * 12, 92 - r() * 30, 3);
      }
    }
  });
}
