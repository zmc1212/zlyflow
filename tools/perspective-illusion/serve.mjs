// Minimal static file server for the perspective-illusion scene.
// Root = this folder (so /node_modules/three/... and /src/... resolve).
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.glsl': 'text/plain; charset=utf-8',
};

export function startServer(port = 0) {
  const server = http.createServer((req, res) => {
    const url = decodeURIComponent((req.url || '/').split('?')[0]);
    let rel = url === '/' ? '/scene.html' : url;
    const abs = path.normalize(path.join(ROOT, rel));
    if (!abs.startsWith(ROOT)) {
      res.writeHead(403).end('forbidden');
      return;
    }
    fs.readFile(abs, (err, buf) => {
      if (err) {
        res.writeHead(404).end('not found: ' + rel);
        return;
      }
      res.writeHead(200, {
        'Content-Type': MIME[path.extname(abs).toLowerCase()] || 'application/octet-stream',
        'Cache-Control': 'no-store',
      });
      res.end(buf);
    });
  });
  return new Promise((resolve) => {
    server.listen(port, '127.0.0.1', () => resolve({ server, port: server.address().port }));
  });
}

if (process.argv[1] && process.argv[1].endsWith('serve.mjs')) {
  const { port } = await startServer(5701);
  console.log(`scene server: http://127.0.0.1:${port}/scene.html`);
}
