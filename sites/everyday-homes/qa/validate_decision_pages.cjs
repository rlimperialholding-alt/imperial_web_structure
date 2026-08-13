const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.EVERYDAY_PREVIEW_URL || 'http://127.0.0.1:18084/site-preview/everyday-homes';
const previewRoot = process.env.EVERYDAY_PREVIEW_ROOT ? path.resolve(process.env.EVERYDAY_PREVIEW_ROOT) : null;
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
  '/muszaki-adatok',
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
  const contextByViewport = new Map();
  const report = { base_url: baseUrl, generated_at: new Date().toISOString(), checks: [] };
  let failed = false;

  for (const route of routes) {
    for (const viewport of viewports) {
      let context = contextByViewport.get(viewport.name);
      if (!context) {
        context = await browser.newContext({ viewport });
        if (previewRoot) {
          const basePath = new URL(baseUrl).pathname.replace(/\/$/, '');
          await context.route('**/*', async route => {
            const requestUrl = new URL(route.request().url());
            if (!requestUrl.pathname.startsWith(`${basePath}/`) && requestUrl.pathname !== basePath) {
              await route.continue();
              return;
            }
            const relativePath = decodeURIComponent(requestUrl.pathname.slice(basePath.length)).replace(/^\/+/, '');
            let target = path.resolve(previewRoot, relativePath || 'index.html');
            if (!target.startsWith(previewRoot)) {
              await route.fulfill({ status: 403, body: 'Forbidden' });
              return;
            }
            if (fs.existsSync(target) && fs.statSync(target).isDirectory()) target = path.join(target, 'index.html');
            if (!fs.existsSync(target)) {
              await route.fulfill({ status: 404, body: 'Not found' });
              return;
            }
            await route.fulfill({ path: target });
          });
        }
        contextByViewport.set(viewport.name, context);
      }
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

      const response = await page.goto(`${baseUrl}${route}`, { waitUntil: 'commit', timeout: 20000 });
      await page.waitForSelector('.decision-page', { timeout: 30000 });
      await page.evaluate(async () => {
        await document.fonts.ready;
      });
      await page.waitForTimeout(500);

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
          contentCharacters: (main?.textContent || '').replace(/\s+/g, ' ').trim().length,
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
      const minimumFaq = 25;
      const minimumContentCharacters = 12000;
      check.minimum_faq = minimumFaq;
      check.minimum_content_characters = minimumContentCharacters;
      check.passed = check.http_status === 200 && check.decisionPages === 1 && check.faqItems >= minimumFaq && check.contentCharacters >= minimumContentCharacters && check.toolMounts === 1 && check.backgroundImage !== 'none' && !check.horizontalOverflow && check.clipped.length === 0 && check.outside.length === 0 && check.forbidden.length === 0 && check.console_errors.length === 0 && check.page_errors.length === 0 && check.request_failures.length === 0 && check.bad_responses.length === 0;
      if (!check.passed) failed = true;
      report.checks.push(check);

      await page.screenshot({ path: path.join(screenshotRoot, `${slug(route)}--${viewport.name}.png`), fullPage: true });
      if (viewport.name === 'desktop') fs.writeFileSync(path.join(renderedRoot, `${slug(route)}.html`), await page.content(), 'utf8');
      await page.close();
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
  await Promise.all([...contextByViewport.values()].map(context => context.close()));
  await browser.close();
  console.log(JSON.stringify(report.summary));
  if (failed) process.exit(1);
})().catch(error => {
  console.error(error);
  process.exit(1);
});
