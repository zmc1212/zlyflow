// Monotone cubic (Fritsch-Carlson) interpolation.
// Every camera parameter runs through one of these tracks so speed never jumps
// and a parameter that holds keeps holding (no overshoot).

export function cubicTrack(keys, { log = false } = {}) {
  const pts = keys.slice().sort((a, b) => a[0] - b[0]);
  const ts = pts.map((k) => k[0]);
  const vs = pts.map((k) => (log ? Math.log(k[1]) : k[1]));
  const n = ts.length;
  if (n === 1) return () => (log ? Math.exp(vs[0]) : vs[0]);

  const d = new Array(n - 1);
  for (let i = 0; i < n - 1; i++) d[i] = (vs[i + 1] - vs[i]) / (ts[i + 1] - ts[i]);

  const m = new Array(n);
  m[0] = d[0];
  m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;

  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / d[i];
    const b = m[i + 1] / d[i];
    const s = a * a + b * b;
    if (s > 9) {
      const tau = 3 / Math.sqrt(s);
      m[i] = tau * a * d[i];
      m[i + 1] = tau * b * d[i];
    }
  }

  return function evalAt(t) {
    if (t <= ts[0]) return log ? Math.exp(vs[0]) : vs[0];
    if (t >= ts[n - 1]) return log ? Math.exp(vs[n - 1]) : vs[n - 1];
    let i = 0;
    while (i < n - 2 && t > ts[i + 1]) i++;
    const h = ts[i + 1] - ts[i];
    const u = (t - ts[i]) / h;
    const u2 = u * u;
    const u3 = u2 * u;
    const h00 = 2 * u3 - 3 * u2 + 1;
    const h10 = u3 - 2 * u2 + u;
    const h01 = -2 * u3 + 3 * u2;
    const h11 = u3 - u2;
    const y = h00 * vs[i] + h10 * h * m[i] + h01 * vs[i + 1] + h11 * h * m[i + 1];
    return log ? Math.exp(y) : y;
  };
}

export function smoothstep(a, b, x) {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
}
