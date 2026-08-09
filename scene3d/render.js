// Render one beat of a talking-character scene to an mp4.
//
//   node render.js job.json
//
// job.json: { out, width, height, fps, seconds, room, speaker, shot,
//             levels: [0..1 per frame], spread: [0..1 per frame] }
//
// Both arrays come from the real narration, sampled once per frame, so the
// mouth stops when the voice stops -- driving it from a timer instead is what
// makes a talking character look dubbed. `levels` is how far the jaw is down
// and `spread` is how wide the mouth is; see animate3d._analyse for why one
// value was not enough.
const puppeteer = require('puppeteer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

const MIME = { '.html': 'text/html', '.js': 'text/javascript',
               '.glb': 'model/gltf-binary', '.json': 'application/json' };

function serve(root) {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'scene.html';
    const file = path.join(root, rel);
    if (!file.startsWith(root) || !fs.existsSync(file)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise(done => server.listen(0, '127.0.0.1',
    () => done({ server, port: server.address().port })));
}

const CHROME = [
  process.env.CHROME_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium',
].filter(Boolean).find(p => fs.existsSync(p));

(async () => {
  const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const fps = job.fps || 24;
  const frames = Math.max(1, Math.round((job.seconds || 3) * fps));
  const levels = job.levels || [];
  const spread = job.spread || [];
  const at = (arr, i, fallback) =>
    arr.length ? (arr[Math.min(i, arr.length - 1)] || 0) : fallback;
  const t0 = Date.now();

  const browser = await puppeteer.launch({
    headless: 'new',
    executablePath: CHROME,
    // Leave --use-angle=default alone. Chrome 137 removed the automatic fall
    // back to software WebGL, which reads as an argument for naming
    // swiftshader-webgl explicitly on a machine with no discrete GPU. Measured
    // on this one, the same 120-frame job renders at 11 fps on `default` and
    // 2.9 fps on `swiftshader-webgl` -- nearly four times slower, because
    // `default` is finding a faster backend than the pure software rasteriser.
    // --enable-unsafe-swiftshader stays as the safety net if it ever cannot.
    args: ['--use-gl=angle', '--use-angle=default', '--enable-unsafe-swiftshader',
           '--ignore-gpu-blocklist', '--no-sandbox', '--disable-dev-shm-usage'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: job.width || 1280, height: job.height || 720 });
  const problems = [];
  page.on('pageerror', e => problems.push(String(e).slice(0, 160)));

  const { server, port } = await serve(__dirname);
  await page.goto(`http://127.0.0.1:${port}/scene.html?w=${job.width}&h=${job.height}`,
                  { waitUntil: 'networkidle0', timeout: 120000 });

  // The whole job goes to the page, not just the room. Passing a hand-picked
  // subset here meant actorA/actorB never arrived and the page quietly fell
  // back to its default model, so every character came out looking the same
  // no matter which file the job named.
  await page.evaluate(cfg => window.__setup(cfg), {
    room: job.room || 'classroom',
    actorA: job.actorA,
    actorB: job.actorB,
    varyB: job.varyB,
    turn: job.turn,
    clip: job.clip,
    mouthUp: job.mouthUp,
  });
  await page.waitForFunction('window.__ready === true || window.__error', { timeout: 120000 });

  const info = await page.evaluate('window.__info()');
  if (info.error) {
    console.error('SETUP FAIL:', info.error, problems.join(' | '));
    await browser.close(); server.close(); process.exit(1);
  }

  const ff = spawn(process.env.FFMPEG || 'ffmpeg', [
    '-y', '-v', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-i', '-',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '23', job.out,
  ]);
  ff.stderr.on('data', d => process.stderr.write(String(d)));

  for (let i = 0; i < frames; i++) {
    const dataUrl = await page.evaluate(
      (t, spk, lv, wd, sh) => window.__renderFrame(t, spk, lv, wd, sh),
      i / fps, job.speaker || 0, at(levels, i, 0.5), at(spread, i, 0.4),
      job.shot || 'wide');
    ff.stdin.write(Buffer.from(dataUrl.split(',')[1], 'base64'));
  }
  ff.stdin.end();
  await new Promise(res => ff.on('close', res));
  await browser.close(); server.close();

  const secs = (Date.now() - t0) / 1000;
  console.log(JSON.stringify({
    out: job.out, frames, seconds: +secs.toFixed(1),
    fps_render: +(frames / secs).toFixed(1),
    clips: info.clips, morphs: info.morphs, mouths: info.mouths,
  }));
})();
