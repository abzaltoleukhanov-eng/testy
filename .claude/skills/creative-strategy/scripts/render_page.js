// Opens a page in a real Chromium (Playwright) and prints JSON {status, title, url, html, challenge} to stdout.
// Used by `voc.py web-page` when a plain request is refused: a real browser runs the page's JavaScript, so pages
// built by JS and passive bot checks ("Just a moment...") load as they would for a visitor. An interactive check
// ("Verify you are human" checkbox) is reported as challenge=NOT_PASSED and left alone: that one needs a person.
//
// Usage: node render_page.js <url> [screenshot.png]
// Needs the playwright package (global npm) and a Chromium (PLAYWRIGHT_BROWSERS_PATH); xvfb-run is optional.
const { chromium } = require('playwright');

const CHECK = /just a moment|attention required|security verification|verify you are human/i;

(async () => {
  const [url, shot] = process.argv.slice(2);
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
  const browser = await chromium.launch({
    headless: !process.env.DISPLAY,
    proxy: proxy ? { server: proxy } : undefined,
  });
  const page = await browser.newPage({ locale: 'en-US', viewport: { width: 1366, height: 900 } });
  const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  // a passive check reloads the page by itself within a few seconds
  for (let i = 0; i < 6 && CHECK.test(await page.title()); i++) await page.waitForTimeout(5000);
  await page.waitForTimeout(2000);
  const title = await page.title();
  const body = await page.evaluate(() => document.body ? document.body.innerText : '');
  // still on the check after ~30 s: it wants a person (Cloudflare Turnstile checkbox, captcha)
  const challenge = CHECK.test(title) || CHECK.test(body.slice(0, 1500)) ? 'NOT_PASSED' : '';
  if (shot) await page.screenshot({ path: shot, fullPage: true });
  process.stdout.write(JSON.stringify({
    status: resp ? resp.status() : 0, title, url: page.url(), html: await page.content(), challenge,
  }));
  await browser.close();
})().catch(e => { process.stdout.write(JSON.stringify({ error: e.message })); process.exit(1); });
