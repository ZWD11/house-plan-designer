# 运行环境：Windows / macOS / Linux / 云端容器

## 依赖

- Python 3.9+：`pip install numpy pillow opencv-python scipy pymupdf ezdxf pypdf`（scipy 给 rectify.py；后三个给 CAD 图纸和 qa_files 用）
- Node 18+：在 `scripts/` 目录 `npm install`（只装 puppeteer-core，不下载浏览器）
- `package-lock.json` 指向官方源 `registry.npmjs.org`。国内网络慢可以临时换镜像：`npm install --registry=https://registry.npmmirror.com`（不要把镜像地址写回 lock 文件，云端代理常拒绝镜像源）

## 浏览器（所有 .mjs 都从 `scripts/browser.mjs` 启动）

找浏览器的顺序：环境变量 `CHROME_PATH` / `PUPPETEER_EXECUTABLE_PATH` → 系统 Chrome / Edge / Chromium（Windows、macOS、Linux 常见路径，含 `/usr/bin/chromium`、snap）→ Playwright 缓存（`~/.cache/ms-playwright`）→ Puppeteer 缓存。都没有时：

```bash
npx playwright install chromium        # 装到 ~/.cache/ms-playwright，自动找到
# 或 apt install chromium，或 export CHROME_PATH=/path/to/chrome
```

- Linux 以 root 运行、或在 Docker / K8s 容器里：自动加 `--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage`（`CHROME_NO_SANDBOX=0/1` 可强制关 / 开）。
- 额外参数：`CHROME_ARGS="--foo --bar"`。
- 不需要任何包装脚本；不要再复制一份 qa_local.mjs。

## 没有显卡（云端容器、远程桌面、虚拟机）

- `check.mjs`、`walktest.mjs`、`clicktest.mjs` 本来就用软件渲染（SwiftShader），结果稳定，照常跑。
- `qa.mjs` 启动时检测 WebGL 渲染器：是 SwiftShader / llvmpipe 就进**慢速模式**——每项超时放宽 4 倍；3D / 漫游 / 中控 / 日照这类纯渲染步骤只因超时失败（没有页面报错、没有异常文字）时记「⚠ 未验证」，不算失败，`report.md` 顶部写明。**未验证的项必须人工看 `qa/shots/` 截图**（第一次云端实战里 8 项“超时失败”，截图显示其实已经进了漫游）。`--soft` 强制进慢速模式。
- 推荐：`node scripts/qa.mjs 设计器.html qa --lite --quick`（约 40 分钟无显卡 / 11 分钟有显卡）。
- 导出文件的下载目录用浏览器级 CDP 设置（`setDownloadDir`），`qa_files.py qa`（传 qa 目录或 downloads 都行）；**0 个文件会判失败**，不再显示“0 / 0 正常”。
- `walktest.mjs` 无显卡整条路线要 10 分钟以上：只改了某几层时 `--floors 1,2`。

## 路径

脚本都按相对 skill 目录找模板和参考文件，不依赖任何本机绝对路径。设计器源码仓库：<https://github.com/ZWD11/house-plan-designer>（模板由设计器项目 `npm run skill:sync` 打包进 `assets/template.html`）。
