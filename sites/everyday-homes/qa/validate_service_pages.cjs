const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.EVERYDAY_PREVIEW_URL || 'http://127.0.0.1:18084/site-preview/everyday-homes';
const previewRoot = process.env.EVERYDAY_PREVIEW_ROOT ? path.resolve(process.env.EVERYDAY_PREVIEW_ROOT) : null;
const root = path.resolve(__dirname);
const screenshotRoot = path.join(root, 'screenshots', 'service-pages');
const renderedRoot = path.join(root, 'rendered', 'service-pages');
const reportPath = path.join(root, 'service-pages-report.json');
const canonicalRoutes = ['/mi-intezzuk/tervezes','/mi-intezzuk/general-kivitelezes','/mi-intezzuk/finanszirozas','/mi-intezzuk/felujitas','/mi-intezzuk/tetoter','/mi-intezzuk/pincebol-lakas','/mi-intezzuk/telek-ellenorzes','/mi-intezzuk/szemelyes-hazajanlas','/biztonsag/vallalasaink','/biztonsag/atlathato-ar'];
const routes = process.env.EVERYDAY_SERVICE_ROUTES ? process.env.EVERYDAY_SERVICE_ROUTES.split(',').map(route => route.trim()).filter(Boolean) : canonicalRoutes;
const viewports = [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'desktop', width: 1440, height: 1000 },
];
const forbidden = ['látható karakter','önálló fejezet','szakmai kérdés','QA kötelez','NIM CMS','projektidővonal','döntési brief','konverziós réteg','hitelgarancia','automatikus jóváhagyás'];
const signatures = new Set();

function slug(route) { return route.replace(/^\//, '').replaceAll('/', '--'); }
fs.mkdirSync(screenshotRoot, { recursive: true });
fs.mkdirSync(renderedRoot, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROME_PATH || undefined });
  const contexts = new Map();
  const report = { base_url: baseUrl, generated_at: new Date().toISOString(), checks: [] };
  let failed = false;
  for (const route of routes) {
    for (const viewport of viewports) {
      let context = contexts.get(viewport.name);
      if (!context) {
        context = await browser.newContext({ viewport });
        if (previewRoot) {
          const basePath = new URL(baseUrl).pathname.replace(/\/$/, '');
          await context.route('**/*', async intercepted => {
            const requestUrl = new URL(intercepted.request().url());
            if (!requestUrl.pathname.startsWith(`${basePath}/`) && requestUrl.pathname !== basePath) return intercepted.continue();
            const relative = decodeURIComponent(requestUrl.pathname.slice(basePath.length)).replace(/^\/+/, '');
            let target = path.resolve(previewRoot, relative || 'index.html');
            if (!target.startsWith(previewRoot)) return intercepted.fulfill({ status: 403, body: 'Forbidden' });
            if (fs.existsSync(target) && fs.statSync(target).isDirectory()) target = path.join(target, 'index.html');
            if (!fs.existsSync(target)) return intercepted.fulfill({ status: 404, body: 'Not found' });
            return intercepted.fulfill({ path: target });
          });
        }
        contexts.set(viewport.name, context);
      }
      const page = await context.newPage();
      const consoleErrors = [], pageErrors = [], requestFailures = [], badResponses = [];
      page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
      page.on('pageerror', e => pageErrors.push(e.message));
      page.on('requestfailed', r => requestFailures.push(`${r.method()} ${r.url()} ${r.failure()?.errorText || ''}`));
      page.on('response', r => { if (r.status() >= 400 && r.url().startsWith(baseUrl)) badResponses.push(`${r.status()} ${r.url()}`); });
      const response = await page.goto(`${baseUrl}${route}`, { waitUntil: 'commit', timeout: 20000 });
      await page.waitForSelector('.service-page', { timeout: 30000 });
      await page.evaluate(async () => document.fonts.ready);
      await page.waitForTimeout(300);
      const dom = await page.evaluate(forbiddenPhrases => {
        const main = document.querySelector('main');
        const visibleText = main?.innerText || '';
        const documentWidth = document.documentElement.clientWidth;
        const outside = [...document.querySelectorAll('main *')].filter(el => {
          const rect = el.getBoundingClientRect();
          if (!(rect.width > 0 && (rect.left < -2 || rect.right > documentWidth + 2))) return false;
          let ancestor = el.parentElement;
          while (ancestor && ancestor !== document.body) {
            if (['auto','scroll','hidden','clip'].includes(getComputedStyle(ancestor).overflowX)) return false;
            ancestor = ancestor.parentElement;
          }
          return true;
        }).slice(0,20).map(el => ({ tag: el.tagName, className: el.className, text: (el.textContent || '').trim().slice(0,80) }));
        const clipped = [...document.querySelectorAll('main h1, main h2, main h3, main p, main dd, main summary, main .button')].filter(el => {
          const style = getComputedStyle(el), rect = el.getBoundingClientRect();
          if (!rect.width || !rect.height || style.visibility === 'hidden') return false;
          return (el.scrollWidth > el.clientWidth + 2 && ['hidden','clip'].includes(style.overflowX)) || (el.scrollHeight > el.clientHeight + 2 && ['hidden','clip'].includes(style.overflowY));
        }).slice(0,20).map(el => ({ tag: el.tagName, text: (el.textContent || '').trim().slice(0,100) }));
        const article = document.querySelector('.service-page');
        return {
          contentCharacters: (main?.textContent || '').replace(/\s+/g,' ').trim().length,
          servicePages: document.querySelectorAll('.service-page').length,
          faqItems: document.querySelectorAll('.service-faq details').length,
          layoutSignature: [...article.classList].find(name => name.startsWith('service-page--')),
          backgroundImage: getComputedStyle(document.querySelector('.service-hero__photo')).backgroundImage,
          forbidden: forbiddenPhrases.filter(phrase => visibleText.includes(phrase)),
          horizontalOverflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) > documentWidth + 2,
          outside, clipped,
        };
      }, forbidden);
      if (viewport.name === 'desktop') signatures.add(dom.layoutSignature);
      const check = { route, viewport: viewport.name, http_status: response?.status() || null, console_errors: consoleErrors, page_errors: pageErrors, request_failures: requestFailures, bad_responses: badResponses, ...dom };
      check.passed = check.http_status === 200 && check.servicePages === 1 && check.faqItems >= 25 && check.contentCharacters >= 12000 && check.backgroundImage !== 'none' && !check.horizontalOverflow && check.outside.length === 0 && check.clipped.length === 0 && check.forbidden.length === 0 && check.console_errors.length === 0 && check.page_errors.length === 0 && check.request_failures.length === 0 && check.bad_responses.length === 0;
      if (!check.passed) failed = true;
      report.checks.push(check);
      await page.screenshot({ path: path.join(screenshotRoot, `${slug(route)}--${viewport.name}.png`), fullPage: true, timeout: 120000 });
      if (viewport.name === 'desktop') fs.writeFileSync(path.join(renderedRoot, `${slug(route)}.html`), await page.content(), 'utf8');
      await page.close();
    }
  }
  report.layout_signatures = [...signatures];
  if (signatures.size !== routes.length) failed = true;
  report.passed = !failed;
  report.summary = { routes: routes.length, viewports: viewports.length, checks: report.checks.length, failures: report.checks.filter(c => !c.passed).length, unique_layouts: signatures.size };
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  await Promise.all([...contexts.values()].map(context => context.close()));
  await browser.close();
  console.log(JSON.stringify(report.summary));
  if (failed) process.exit(1);
})().catch(error => { console.error(error); process.exit(1); });
