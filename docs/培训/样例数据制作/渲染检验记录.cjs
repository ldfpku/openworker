// 用 Playwright 把《检验记录表.html》的三条记录渲染成 JPEG。
// 用法：在 <repo> 根目录下 `node docs/培训/样例数据制作/渲染检验记录.cjs`
// 不带参数则渲染 1/2/3 三张到 docs/培训/OpenWorker培训/06-返厂检验/ 下。

const path = require('path');
const fs = require('fs');
const { pathToFileURL } = require('url');

const repo = path.resolve(__dirname, '..', '..', '..');
const { chromium } = require(path.join(repo, 'surfaces', 'gui', 'node_modules', 'playwright'));

const htmlPath = path.join(__dirname, '检验记录表.html');
const outDir = path.join(repo, 'docs', '培训', 'OpenWorker培训', '06-返厂检验');

const RECORDS = [
  { id: '1', toolId: 'YZJ-0417' },
  { id: '2', toolId: 'YZJ-0432' },
  { id: '3', toolId: 'YZJ-0502' },
];

async function main() {
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({
      viewport: { width: 1600, height: 2200 },
      deviceScaleFactor: 1,
    });

    const url = pathToFileURL(htmlPath);

    for (const rec of RECORDS) {
      url.search = `?id=${rec.id}`;
      await page.goto(url.toString(), { waitUntil: 'load' });

      const scene = page.locator('#scene');
      await scene.waitFor({ state: 'visible' });

      const outPath = path.join(outDir, `返厂检验记录-${rec.toolId}.jpg`);
      await scene.screenshot({ path: outPath, type: 'jpeg', quality: 82 });

      const stat = fs.statSync(outPath);
      console.log(`写出 ${outPath}  (${(stat.size / 1024).toFixed(1)} KB)`);
    }
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
