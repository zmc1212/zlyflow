// Procedural canvas textures. No external assets, no network.
import * as THREE from 'three';

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function rnd() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function canvas(w, h) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return c;
}

function toTexture(c, { srgb = true, repeat = [1, 1], aniso = 4 } = {}) {
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeat[0], repeat[1]);
  t.anisotropy = aniso;
  t.needsUpdate = true;
  return t;
}

/* ---------------------------------- ground --------------------------------- */

export function asphaltTexture(seed = 7) {
  const c = canvas(512, 512);
  const g = c.getContext('2d');
  g.fillStyle = '#22262e';
  g.fillRect(0, 0, 512, 512);
  const rnd = mulberry32(seed);
  for (let i = 0; i < 24000; i++) {
    const x = rnd() * 512;
    const y = rnd() * 512;
    const v = rnd();
    g.fillStyle = v > 0.55 ? `rgba(88,98,116,${0.10 + rnd() * 0.22})` : `rgba(10,13,18,${0.12 + rnd() * 0.24})`;
    g.fillRect(x, y, 1 + rnd() * 2, 1 + rnd() * 2);
  }
  // faint long smears (wet traffic lanes)
  for (let i = 0; i < 26; i++) {
    const x = rnd() * 512;
    const grad = g.createLinearGradient(x, 0, x + 40, 512);
    grad.addColorStop(0, 'rgba(96,108,132,0)');
    grad.addColorStop(0.5, `rgba(96,108,132,${0.07 + rnd() * 0.07})`);
    grad.addColorStop(1, 'rgba(96,108,132,0)');
    g.fillStyle = grad;
    g.fillRect(x, 0, 30 + rnd() * 50, 512);
  }
  return toTexture(c, { repeat: [40, 40] });
}

export function sidewalkTexture(seed = 11) {
  const c = canvas(256, 256);
  const g = c.getContext('2d');
  g.fillStyle = '#272a33';
  g.fillRect(0, 0, 256, 256);
  const rnd = mulberry32(seed);
  for (let i = 0; i < 5000; i++) {
    g.fillStyle = `rgba(150,160,180,${0.02 + rnd() * 0.05})`;
    g.fillRect(rnd() * 256, rnd() * 256, 2, 2);
  }
  g.strokeStyle = 'rgba(10,12,16,0.9)';
  g.lineWidth = 2;
  for (let i = 0; i <= 4; i++) {
    g.beginPath();
    g.moveTo(i * 64, 0);
    g.lineTo(i * 64, 256);
    g.stroke();
    g.beginPath();
    g.moveTo(0, i * 64);
    g.lineTo(256, i * 64);
    g.stroke();
  }
  return toTexture(c, { repeat: [8, 8] });
}

/* --------------------------------- facades --------------------------------- */

// One texture per building "style": dark wall, window grid, a few lit windows.
export function facadeTexture({
  seed = 1,
  cols = 6,
  rows = 10,
  wall = '#171b24',
  frame = '#0d1016',
  lit = 0.42,
  warm = [255, 196, 128],
  cool = [150, 190, 235],
} = {}) {
  const cw = 64;
  const ch = 64;
  const c = canvas(cols * cw, rows * ch);
  const g = c.getContext('2d');
  const rnd = mulberry32(seed);
  g.fillStyle = wall;
  g.fillRect(0, 0, c.width, c.height);
  // concrete streaks
  for (let i = 0; i < 900; i++) {
    g.fillStyle = `rgba(255,255,255,${rnd() * 0.02})`;
    g.fillRect(rnd() * c.width, rnd() * c.height, 1, 2 + rnd() * 18);
  }
  for (let r = 0; r < rows; r++) {
    for (let col = 0; col < cols; col++) {
      const x = col * cw + 8;
      const y = r * ch + 10;
      const w = cw - 16;
      const h = ch - 22;
      g.fillStyle = frame;
      g.fillRect(x - 3, y - 3, w + 6, h + 6);
      const isLit = rnd() < lit;
      if (isLit) {
        const useWarm = rnd() < 0.72;
        const base = useWarm ? warm : cool;
        const k = 0.55 + rnd() * 0.45;
        const grad = g.createLinearGradient(x, y, x, y + h);
        grad.addColorStop(0, `rgba(${base[0] * k},${base[1] * k},${base[2] * k},1)`);
        grad.addColorStop(1, `rgba(${base[0] * k * 0.62},${base[1] * k * 0.62},${base[2] * k * 0.66},1)`);
        g.fillStyle = grad;
        g.fillRect(x, y, w, h);
        // desk / curtain silhouette
        if (rnd() < 0.45) {
          g.fillStyle = 'rgba(20,22,30,0.55)';
          g.fillRect(x, y + h * (0.55 + rnd() * 0.3), w, h * 0.45);
        }
      } else {
        g.fillStyle = `rgba(28,34,46,${0.5 + rnd() * 0.3})`;
        g.fillRect(x, y, w, h);
      }
    }
  }
  return toTexture(c, { repeat: [1, 1] });
}

/* ---------------------------------- signs ---------------------------------- */

export const SHOP_WORDS = ['居酒屋', '拉麵', '焼肉', '薬', 'KARAOKE', '24H', '珈琲', '麻雀', '占い', '酒場', '書店', 'ゲーム'];

export function neonSignTexture(word, { seed = 3, hue = 330 } = {}) {
  const c = canvas(128, 512);
  const g = c.getContext('2d');
  g.fillStyle = '#0b0d12';
  g.fillRect(0, 0, 128, 512);
  const neon = `hsl(${hue}, 92%, 62%)`;
  const neon2 = `hsl(${(hue + 40) % 360}, 95%, 70%)`;
  g.strokeStyle = neon;
  g.lineWidth = 6;
  g.shadowColor = neon;
  g.shadowBlur = 22;
  g.strokeRect(10, 10, 108, 492);
  g.shadowBlur = 26;
  g.fillStyle = '#ffffff';
  const chars = [...word];
  const fs = Math.min(84, 440 / Math.max(chars.length, 1));
  g.font = `900 ${fs}px "Microsoft YaHei","PingFang SC",sans-serif`;
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  chars.forEach((chr, i) => {
    const y = 256 + (i - (chars.length - 1) / 2) * fs * 1.06;
    g.shadowColor = neon2;
    g.fillText(chr, 64, y);
  });
  return toTexture(c);
}

export function ledScreenTexture(seed = 5) {
  const c = canvas(512, 288);
  const g = c.getContext('2d');
  const rnd = mulberry32(seed);
  const grad = g.createLinearGradient(0, 0, 512, 288);
  grad.addColorStop(0, '#2a0f4a');
  grad.addColorStop(0.45, '#7b1fa2');
  grad.addColorStop(1, '#0e2a4a');
  g.fillStyle = grad;
  g.fillRect(0, 0, 512, 288);
  for (let i = 0; i < 40; i++) {
    g.fillStyle = `rgba(255,255,255,${rnd() * 0.06})`;
    g.fillRect(rnd() * 512, rnd() * 288, 2 + rnd() * 60, 2 + rnd() * 6);
  }
  g.fillStyle = 'rgba(255,255,255,0.94)';
  g.font = '900 120px "Microsoft YaHei",sans-serif';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.shadowColor = '#22d3ee';
  g.shadowBlur = 30;
  g.fillText('雨夜', 256, 118);
  g.font = '900 54px "Microsoft YaHei",sans-serif';
  g.shadowColor = '#ff2d78';
  g.fillStyle = '#ffe7f2';
  g.fillText('TOKYO NIGHT', 256, 212);
  // scanlines
  g.shadowBlur = 0;
  g.fillStyle = 'rgba(0,0,0,0.22)';
  for (let y = 0; y < 288; y += 4) g.fillRect(0, y, 512, 2);
  return toTexture(c);
}

export function shopfrontTexture(seed = 9, hue = 30) {
  const c = canvas(256, 128);
  const g = c.getContext('2d');
  const rnd = mulberry32(seed);
  g.fillStyle = `hsl(${hue}, 40%, 12%)`;
  g.fillRect(0, 0, 256, 128);
  // warm interior glow behind glass
  const grad = g.createLinearGradient(0, 20, 0, 128);
  grad.addColorStop(0, `hsla(${hue}, 90%, 62%, 0.95)`);
  grad.addColorStop(0.55, `hsla(${hue}, 85%, 46%, 0.8)`);
  grad.addColorStop(1, `hsla(${hue}, 70%, 30%, 0.6)`);
  g.fillStyle = grad;
  g.fillRect(8, 26, 240, 96);
  // silhouettes inside
  g.fillStyle = 'rgba(20,16,14,0.7)';
  for (let i = 0; i < 6; i++) {
    const x = 20 + rnd() * 210;
    g.fillRect(x, 60 + rnd() * 30, 8 + rnd() * 14, 62);
  }
  // mullions
  g.fillStyle = '#0d1014';
  for (let x = 8; x < 248; x += 60) g.fillRect(x, 26, 4, 96);
  g.fillRect(8, 26, 240, 5);
  // awning
  g.fillStyle = `hsl(${(hue + 180) % 360}, 55%, 26%)`;
  g.fillRect(0, 0, 256, 26);
  return toTexture(c);
}

/* -------------------------------- utilities -------------------------------- */

// Vertical gradient with a soft wavy core: used for wet-ground light smears.
export function streakTexture() {
  const c = canvas(64, 256);
  const g = c.getContext('2d');
  const grad = g.createLinearGradient(0, 0, 0, 256);
  grad.addColorStop(0, 'rgba(255,255,255,0.95)');
  grad.addColorStop(0.35, 'rgba(255,255,255,0.45)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 256);
  const rnd = mulberry32(21);
  for (let i = 0; i < 140; i++) {
    g.globalCompositeOperation = 'destination-out';
    g.fillStyle = `rgba(0,0,0,${0.25 + rnd() * 0.5})`;
    g.fillRect(rnd() * 64, rnd() * 256, 2 + rnd() * 8, 1 + rnd() * 3);
  }
  return toTexture(c, { srgb: true });
}

export function glowTexture() {
  const c = canvas(128, 128);
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(0.25, 'rgba(255,255,255,0.55)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  return toTexture(c);
}

export function skyTexture() {
  const c = canvas(512, 512);
  const g = c.getContext('2d');
  const grad = g.createLinearGradient(0, 0, 0, 512);
  grad.addColorStop(0, '#05070d');
  grad.addColorStop(0.55, '#0d1424');
  grad.addColorStop(0.8, '#1e2338');
  grad.addColorStop(1, '#3a2a33');
  g.fillStyle = grad;
  g.fillRect(0, 0, 512, 512);
  return toTexture(c);
}

export { toTexture, canvas };
