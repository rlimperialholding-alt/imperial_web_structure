const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.EVERYDAY_PREVIEW_URL || 'http://127.0.0.1:18084/site-preview/everyday-homes';
const root = path.resolve(__dirname);
const screenshotRoot = path.join(root, 'screenshots', 'decision-pages');
const renderedRoot = path.join(root, 'rendered', 'decision-pages');
const reportPath = path.join(root, 'decision-pages-report.json');

const routes = [
  '/szamolok/havi-teher',
  '/szamolok/teljes-projektkeret',
  '/szamolok/utemterv',
  '/szamolok/felujitas-vagy-uj',
  '/szamolok/energia-es-koltseg',
  '/szamolok/gyors-hazellenorzes',
];

const viewports = [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'desktop', width: 1440, height: 1000 },
];

const forbiddenPublicPhrases = [
  'látható karakter',
  'önálló fejezet',
  'szakmai kérdés',
  'QA kötelez',
  'NIM CMS',
];

function slug(route) {
  return route.replace(/^\//, '').replaceAll('/', '--');
}

fs.mkdirSync(screenshotRoot, { recursive: true });
fs.mkdirSync(renderedRoot, { recursive: true });

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROME_PATH || undefined,
  });
  const report = { base_url: baseUrl, generated_at: new Date().toISOString(), checks: [] };
  let failed = false;

  for (const route of routes) {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport });
      const page = await context.newPage();
      const consoleErrors = [];
      const pageErrors = [];
      const requestFailures = [];
      const badResponses = [];

      page.on('console', message => {
        if (message.type() === 'error') consoleErrors.push(message.text());
      });
      page.on('pageerror', error => pageErrors.push(error.message));
      page.on('requestfailed', request => requestFailures.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ''}`));
      page.on('response', response => {
        if (response.status() >= 400 && response.url().startsWith(baseUrl)) badResponses.push(`${response.status()} ${response.url()}`);
      });

      const response = await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle', timeout: 45000 });
      await page.waitForSelector('.decision-page', { timeout: 10000 });
      await page.evaluate(async () => {
        await document.fonts.ready;
        const imageUrls = [...document.querySelectorAll('.decision-hero__photo')]
          .map(element => getComputedStyle(element).backgroundImage.match(/url\(["']?(.*?)["']?\)/)?.[1])
          .filter(Boolean);
        await Promise.all(imageUrls.map(url => new Promise((resolve, reject) => {
          const image = new Image();
          image.onload = resolve;
          image.onerror = reject;
          image.src = url;
        })));
      });

      const dom = await page.evaluate(forbidden => {
        const main = document.querySelector('main');
        const visibleText = main?.innerText || '';
        const documentWidth = document.documentElement.clientWidth;
        const horizontalOverflow = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) > documentWidth + 2;
        const clipped = [...document.querySelectorAll('main h1, main h2, main h3, main p, main li, main summary, main .button, main span, main strong')]
          .filter(element => {
            const style = getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = element.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return false;
            const overflowX = element.scrollWidth > element.clientWidth + 2 && ['hidden', 'clip'].includes(style.overflowX);
            const overflowY = element.scrollHeight > element.clientHeight + 2 && ['hidden', 'clip'].includes(style.overflowY);
            return overflowX || overflowY;
          })
          .map(element => ({ tag: element.tagName, text: (element.textContent || '').trim().slice(0, 100) }));
        const outside = [...document.querySelectorAll('main *')]
          .filter(element => {
            const rect = element.getBoundingClientRect();
            if (!(rect.width > 0 && (rect.left < -2 || rect.right > documentWidth + 2))) return false;
            let ancestor = element.parentElement;
            while (ancestor && ancestor !== document.body) {
              const overflowX = getComputedStyle(ancestor).overflowX;
              if (['auto', 'scroll', 'hidden', 'clip'].includes(overflowX)) return false;
              ancestor = ancestor.parentElement;
            }
            return true;
          })
          .slice(0, 20)
          .map(element => ({ tag: element.tagName, className: element.className, text: (element.textContent || '').trim().slice(0, 80) }));
        return {
          title: document.title,
          decisionPages: document.querySelectorAll('.decision-page').length,
          faqItems: document.querySelectorAll('.decision-faq details').length,
          toolMounts: document.querySelectorAll('[data-nim-widget]').length,
          backgroundImage: getComputedStyle(document.querySelector('.decision-hero__photo')).backgroundImage,
          forbidden: forbidden.filter(phrase => visibleText.includes(phrase)),
          horizontalOverflow,
          clipped,
          outside,
        };
      }, forbiddenPublicPhrases);

      const check = {
        route,
        viewport: viewport.name,
        http_status: response?.status() || null,
        console_errors: consoleErrors,
        page_errors: pageErrors,
        request_failures: requestFailures,
        bad_responses: badResponses,
        ...dom,
      };
      check.passed = check.http_status === 200 && check.decisionPages === 1 && check.faqItems === 4 && check.toolMounts === 1 && check.backgroundImage !== 'none' && !check.horizontalOverflow && check.clipped.length === 0 && check.outside.length === 0 && check.forbidden.length === 0 && check.console_errors.length === 0 && check.page_errors.length === 0 && check.request_failures.length === 0 && check.bad_responses.length === 0;
      if (!check.passed) failed = true;
      report.checks.push(check);

      await page.screenshot({ path: path.join(screenshotRoot, `${slug(route)}--${viewport.name}.png`), fullPage: true });
      if (viewport.name === 'desktop') fs.writeFileSync(path.join(renderedRoot, `${slug(route)}.html`), await page.content(), 'utf8');
      await context.close();
    }
  }

  report.passed = !failed;
  report.summary = {
    routes: routes.length,
    viewports: viewports.length,
    checks: report.checks.length,
    failures: report.checks.filter(check => !check.passed).length,
  };
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  await browser.close();
  console.log(JSON.stringify(report.summary));
  if (failed) process.exit(1);
})().catch(error => {
  console.error(error);
  process.exit(1);
});
