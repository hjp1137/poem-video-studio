const { chromium } = require('@playwright/test');
const OUT = 'D:/projects/hjp/poem-video-studio/Walkthroughes/screenshots/20260928_模板管理与真实出片闭环';
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  await page.goto('http://127.0.0.1:18080/workflows', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: OUT + '/01_模板管理_真实工作流已设默认.png', fullPage: true });
  await page.goto('http://127.0.0.1:18080/batches/bb80a8ab447d', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: OUT + '/02_春宵批次_生成中与默认模板标签.png', fullPage: true });
  await browser.close();
  console.log('done');
})().catch(e => { console.error(e.message); process.exit(1); });
