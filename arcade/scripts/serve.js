// Zero-dependency static server. The arcade is plain files, but fetch() for the
// hall config needs a real http origin, so serve the folder instead of opening
// index.html from disk.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const requested = Number(process.env.PORT);
const port = Number.isInteger(requested) && requested > 0 ? requested : 8123;
const host = '127.0.0.1';

const types = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.ttf': 'font/ttf'
};

const server = http.createServer((req, res) => {
  const urlPath = decodeURIComponent((req.url || '/').split('?')[0]);
  const target = path.join(root, urlPath === '/' ? '/index.html' : urlPath);

  if (!target.startsWith(root)) {
    res.writeHead(403, { 'content-type': 'text/plain' }).end('forbidden');
    return;
  }

  fs.readFile(target, (err, buf) => {
    if (err) {
      res.writeHead(404, { 'content-type': 'text/plain' }).end(`404 ${urlPath}`);
      return;
    }
    res.writeHead(200, {
      'content-type': types[path.extname(target).toLowerCase()] || 'application/octet-stream',
      'cache-control': 'no-store'
    });
    res.end(buf);
  });
});

server.listen(port, host, () => {
  console.log(`nebula arcade -> http://${host}:${port}/`);
});
