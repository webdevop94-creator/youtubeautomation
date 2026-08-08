// Load a page headlessly and print whatever it puts on window.__out.
// Used to inspect models without a full render.
const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');
const http = require('http');

const MIME = { '.html': 'text/html', '.js': 'text/javascript',
               '.glb': 'model/gltf-binary', '.fbx': 'application/octet-stream' };

function serve(root) {
  const s = http.createServer((req, res) => {
    const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '');
    const f = path.join(root, rel);
    if (!f.startsWith(root) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' });
    fs.createReadStream(f).pipe(res);
  });
  return new Promise(d => s.listen(0, '127.0.0.1', () => d({ s, port: s.address().port })));
}

const CHROME = ['C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
                'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
                '/usr/bin/google-chrome'].find(p => fs.existsSync(p));

(async () => {
  const pageFile = process.argv[2] || 'fbxinfo.html';
  const browser = await puppeteer.launch({
    headless: 'new', executablePath: CHROME,
    args: ['--use-gl=angle', '--enable-unsafe-swiftshader', '--no-sandbox'],
  });
  const page = await browser.newPage();
  page.on('pageerror', e => console.error('page error:', String(e).slice(0, 200)));
  const { s, port } = await serve(__dirname);
  await page.goto(`http://127.0.0.1:${port}/${pageFile}`, { waitUntil: 'networkidle0' });
  await page.waitForFunction('window.__done === true', { timeout: 300000 });
  console.log(JSON.stringify(await page.evaluate('window.__out'), null, 2));
  await browser.close(); s.close();
})();
