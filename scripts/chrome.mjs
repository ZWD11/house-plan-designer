// 无头 Chrome 的显卡后端。WebGL 走 ANGLE：
//   Windows  d3d11（与原来写死的参数相同）
//   macOS    metal
//   Linux    有硬件 Vulkan 就试 Vulkan（无 X11 也能用），否则有 DRM 渲染节点就试 OpenGL；
//            建不出硬件 WebGL 就改用 SwiftShader（新版 Chrome 要带 --enable-unsafe-swiftshader）
// 覆盖（命令行优先于环境变量，二者都优先于脚本自己的指定）：
//   CHROME_ANGLE=d3d11|metal|gl|gles|vulkan|swiftshader|auto
//   --angle=<同上>
// 选了哪个打在 stderr，避免 check.mjs 的 JSON 被插进一行。
import fs from 'fs';
import path from 'path';

const BACKENDS = ['d3d11', 'metal', 'gl', 'gles', 'vulkan', 'swiftshader', 'auto'];
const KEEP_AWAKE = ['--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows'];

export function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium', '/usr/bin/chromium-browser', '/snap/bin/chromium',
    '/usr/local/bin/google-chrome',
  ].filter(Boolean);
  return candidates.find(p => fs.existsSync(p));
}

function argAngle(argv) {
  for (const a of argv) {
    const m = /^--angle=(.*)$/.exec(a);
    if (m) return m[1].trim().toLowerCase();
  }
}

/** @returns {{ backend: string, why: string, forced: boolean }} */
export function explainAngle(scriptAngle) {
  const fromArg = argAngle(process.argv);
  const fromEnv = (process.env.CHROME_ANGLE || '').trim().toLowerCase();
  const fromScript = (scriptAngle || '').trim().toLowerCase();
  const raw = fromArg || fromEnv || fromScript || 'auto';
  if (!BACKENDS.includes(raw)) {
    console.error(`不认识的 ANGLE 后端“${raw}”。可用：${BACKENDS.join('、')}`);
    process.exit(1);
  }
  if (raw === 'auto') return { ...detect(), forced: false };
  const why = fromArg ? `命令行 --angle=${raw}` : fromEnv ? `环境变量 CHROME_ANGLE=${raw}` : `脚本指定 ${raw}`;
  return { backend: raw, why, forced: true };
}

function detect() {
  if (process.platform === 'win32') return { backend: 'd3d11', why: 'Windows' };
  if (process.platform === 'darwin') return { backend: 'metal', why: 'macOS' };
  if (process.platform === 'linux') return detectLinux();
  return { backend: 'swiftshader', why: `平台 ${process.platform}，用 SwiftShader` };
}

function usable(p) {
  try { fs.accessSync(p, fs.constants.R_OK | fs.constants.W_OK); return true; } catch { return false; }
}

function driNodes() {
  let names = [];
  try { names = fs.readdirSync('/dev/dri'); } catch { return []; }
  const ok = names.filter(n => /^(renderD|card)\d+$/.test(n) && usable('/dev/dri/' + n));
  ok.sort((a, b) => (a.startsWith('renderD') ? 0 : 1) - (b.startsWith('renderD') ? 0 : 1));
  return ok;
}

function hardwareIcds() {
  const dirs = ['/usr/share/vulkan/icd.d', '/etc/vulkan/icd.d', '/usr/local/share/vulkan/icd.d'];
  if (process.env.HOME) dirs.push(path.join(process.env.HOME, '.local/share/vulkan/icd.d'));
  const files = [];
  const extra = process.env.VK_DRIVER_FILES || process.env.VK_ICD_FILENAMES;
  if (extra) files.push(...extra.split(path.delimiter).filter(Boolean));
  for (const d of dirs) {
    try { for (const f of fs.readdirSync(d)) if (f.endsWith('.json')) files.push(path.join(d, f)); } catch { /* 没有这个目录 */ }
  }
  return files.filter(f => {
    const base = path.basename(f).toLowerCase();
    if (/lvp|lavapipe|swiftshader/.test(base)) return false;
    try { return !/lvp|lavapipe|swiftshader/.test(fs.readFileSync(f, 'utf8').toLowerCase()); }
    catch { return false; }
  });
}

/** 纯判断，方便核对。nodes / nvidia 是设备名或路径；icds 里名字带 lavapipe / SwiftShader 的不当硬件。 */
export function linuxChoice({ nodes = [], nvidia = [], icds = [] }) {
  icds = icds.filter(f => !/lvp|lavapipe|swiftshader/i.test(f));
  if (icds.length && (nodes.length || nvidia.length)) {
    const dev = nodes.length ? (nodes[0].startsWith('/') ? nodes[0] : `/dev/dri/${nodes[0]}`) : nvidia[0];
    const icd = icds[0].includes('/') ? path.basename(icds[0]) : icds[0];
    return { backend: 'vulkan', why: `Linux，硬件 Vulkan（${dev}，ICD ${icd}）` };
  }
  if (nodes.length) {
    const dev = nodes[0].startsWith('/') ? nodes[0] : `/dev/dri/${nodes[0]}`;
    return { backend: 'gl', why: `Linux，硬件 OpenGL（${dev}）` };
  }
  return { backend: 'swiftshader', why: 'Linux，没有可用的硬件渲染节点' };
}

function detectLinux() {
  return linuxChoice({
    nodes: driNodes(),
    nvidia: ['/dev/nvidia0', '/dev/nvidiactl'].filter(usable),
    icds: hardwareIcds(),
  });
}

export function angleArgs(backend) {
  if (backend === 'swiftshader') return ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', ...KEEP_AWAKE];
  // d3d11 / metal 保持原来 qa.mjs 那一组，不额外加 --use-gl
  const args = [`--use-angle=${backend}`, '--enable-gpu', '--ignore-gpu-blocklist', ...KEEP_AWAKE];
  if (backend === 'gl' || backend === 'gles' || backend === 'vulkan') args.unshift('--use-gl=angle');
  if (backend === 'vulkan') args.push('--disable-vulkan-surface');
  return args;
}

function logChoice(choice) {
  console.error(`Chrome ANGLE 后端：${choice.backend}（${choice.why}）`);
}

function softwareRenderer(s) {
  return /swiftshader|llvmpipe|softpipe|lavapipe|microsoft basic render/i.test(s || '');
}

async function webglRenderer(browser) {
  const page = (await browser.pages())[0] || await browser.newPage();
  try {
    await page.goto('data:text/html,<canvas id=c width=8 height=8></canvas>', { waitUntil: 'load', timeout: 20000 });
    return await page.evaluate(() => {
      const c = document.getElementById('c');
      const gl = c.getContext('webgl2') || c.getContext('webgl');
      if (!gl) return '';
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      return String(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
    });
  } catch { return ''; }
  finally { await page.goto('about:blank').catch(() => {}); }
}

function launchOpts(exe, backend, o) {
  const opts = { executablePath: exe, headless: o.headless ?? 'new', args: [...angleArgs(backend), ...(o.extraArgs || [])] };
  if (o.viewport) opts.defaultViewport = o.viewport;
  if (o.protocolTimeout) opts.protocolTimeout = o.protocolTimeout;
  return opts;
}

/**
 * @param {import('puppeteer-core')} puppeteer
 * @param {{ headless?: boolean|'new', viewport?: {width:number,height:number}, protocolTimeout?: number, extraArgs?: string[], angle?: string }} [o]
 * angle：脚本想用的后端。命令行 --angle= 和环境变量 CHROME_ANGLE 仍优先。
 */
export async function launchChrome(puppeteer, o = {}) {
  const exe = findChrome();
  if (!exe) { console.error('找不到 Chrome/Edge，设置环境变量 CHROME_PATH'); process.exit(1); }
  let choice = explainAngle(o.angle);
  const tryHardware = !choice.forced && (choice.backend === 'gl' || choice.backend === 'vulkan');
  let browser;
  try { browser = await puppeteer.launch(launchOpts(exe, choice.backend, o)); }
  catch (e) {
    if (!tryHardware) throw e;
    choice = { backend: 'swiftshader', why: `Linux，${choice.backend === 'gl' ? 'OpenGL' : 'Vulkan'} 启动失败（${e.message || e}），改用 SwiftShader`, forced: true };
    browser = await puppeteer.launch(launchOpts(exe, choice.backend, o));
  }
  if (tryHardware && choice.backend !== 'swiftshader') {
    const renderer = await webglRenderer(browser);
    if (!renderer || softwareRenderer(renderer)) {
      await browser.close().catch(() => {});
      const which = choice.backend === 'gl' ? 'OpenGL' : 'Vulkan';
      choice = { backend: 'swiftshader', why: `Linux，${which} 没有硬件 WebGL（${renderer || '没有 WebGL 上下文'}），改用 SwiftShader`, forced: true };
      browser = await puppeteer.launch(launchOpts(exe, choice.backend, o));
    }
  }
  logChoice(choice);
  return browser;
}
