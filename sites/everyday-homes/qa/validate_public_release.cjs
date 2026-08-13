const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.EVERYDAY_PREVIEW_URL || 'http://127.0.0.1:18084/site-preview/everyday-homes';
const previewRoot = path.resolve(process.env.EVERYDAY_PREVIEW_ROOT || path.join(__dirname, '..'));
const pageMap = JSON.parse(fs.readFileSync(path.join(previewRoot, 'data', 'page-map.json'), 'utf8'));
const routes = process.env.EVERYDAY_PUBLIC_ROUTES
  ? process.env.EVERYDAY_PUBLIC_ROUTES.split(',')
  : pageMap.groups.flatMap(group => group.pages.map(page => page[1]));
const nimRoutes = new Set(pageMap.groups.find(group => group.name === 'Nekünk való házak')?.pages.map(page => page[1]) || []);
nimRoutes.add('/otthonok/minta');
const legalRoutes = new Set(['/adatkezeles', '/impresszum', '/sutik', '/akadalymentesseg']);
const forbidden = [
  /kapujegyz/i, /kapustátusz/i, /márkaelkülönítési/i, /információs architektúra/i,
  /szerkesztési előnézet/i, /részletes forrásoldal/i, /távoli tesztkörnyezet/i,
  /jóváhagyásra váró/i, /nem publikálható/i, /publication_allowed/i,
  /review_required/i, /review-required/i, /kiadási kapu/i, /adat- és kiadási kapu/i,
  /szerkesztői (?:szabály|megjegyzés|állapot)/i, /komponensátadás/i,
  /javasolt pageid/i, /EH-HU-\d/i, /az összes aloldal/i, /látható karakter/i,
  /önálló fejezet/i, /QA kötelez/i, /NIM CMS/i, /forrásbetöltési hiba/i,
  /tesztoldal/i, /tesztkörnyezet/i, /tartalmi előnézet/i,
];
const viewports = [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'desktop', width: 1440, height: 1000 },
];

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROME_PATH || undefined });
  const failures = [];
  const results = [];
  for (const route of routes) {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport });
      const basePath = new URL(baseUrl).pathname.replace(/\/$/, '');
      await context.route('**/*', async intercepted => {
        const requestUrl = new URL(intercepted.request().url());
        if (!requestUrl.pathname.startsWith(basePath)) return intercepted.continue();
        const relative = decodeURIComponent(requestUrl.pathname.slice(basePath.length)).replace(/^\/+/, '');
        let target = path.resolve(previewRoot, relative || 'index.html');
        if (!target.startsWith(previewRoot)) return intercepted.fulfill({ status: 403, body: 'Forbidden' });
        if (fs.existsSync(target) && fs.statSync(target).isDirectory()) target = path.join(target, 'index.html');
        if (!fs.existsSync(target)) return intercepted.fulfill({ status: 404, body: 'Not found' });
        return intercepted.fulfill({ path: target });
      });
      const page = await context.newPage();
      const consoleErrors = [];
      const requestFailures = [];
      page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
      page.on('requestfailed', request => requestFailures.push(`${request.method()} ${request.url()}`));
      const response = await page.goto(`${baseUrl}${route === '/' ? '' : route}`, { waitUntil: 'networkidle', timeout: 30000 });
      await page.evaluate(async () => document.fonts.ready);
      const data = await page.evaluate(({ forbiddenSources, isNim, isLegal }) => {
        const main = document.querySelector('main');
        const visible = main?.innerText || '';
        const h1 = main?.querySelector('h1');
        const width = document.documentElement.clientWidth;
        const h1Style = h1 ? getComputedStyle(h1) : null;
        const badOverflow = [...document.querySelectorAll('main *')].filter(element => {
          const rect = element.getBoundingClientRect();
          if (!(rect.width > 0 && (rect.left < -2 || rect.right > width + 2))) return false;
          let parent = element.parentElement;
          while (parent && parent !== document.body) {
            if (['auto','scroll','hidden','clip'].includes(getComputedStyle(parent).overflowX)) return false;
            parent = parent.parentElement;
          }
          return true;
        }).slice(0, 8).map(element => (element.textContent || '').trim().slice(0, 80));
        const hero = main?.querySelector('.hero,.rich-hero,.service-hero,.technology-hero,.decision-hero');
        const heroActions = hero?.querySelectorAll('.actions a').length || 0;
        const allActions = main?.querySelectorAll('a.button,.actions a').length || 0;
        const visuals = main?.querySelectorAll('[role="img"],figure,svg,.service-journey,.service-proof,.technology-body section,.decision-body section').length || 0;
        return {
          visibleCharacters: visible.replace(/\s+/g, ' ').trim().length,
          forbidden: forbiddenSources.filter(source => new RegExp(source, 'i').test(visible)),
          heading: h1?.textContent?.trim() || '',
          headingFontSize: h1Style ? parseFloat(h1Style.fontSize) : 0,
          headingWordBreak: h1Style?.wordBreak,
          headingOverflowWrap: h1Style?.overflowWrap,
          headingOverflow: h1 ? h1.getBoundingClientRect().right > width + 2 : true,
          horizontalOverflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) > width + 2,
          badOverflow,
          heroActions,
          allActions,
          visuals,
          hasDirectory: !!document.querySelector('.page-directory,.page-directory-toggle'),
          navGroups: document.querySelectorAll('.nav-group').length,
          isNim,
          isLegal,
        };
      }, { forbiddenSources: forbidden.map(regex => regex.source), isNim: nimRoutes.has(route), isLegal: legalRoutes.has(route) });
      const maxHeading = viewport.name === 'mobile' ? 54 : viewport.name === 'tablet' ? 68 : 84;
      const reasons = [];
      if (response?.status() !== 200) reasons.push(`HTTP ${response?.status()}`);
      if (consoleErrors.length) reasons.push(`console: ${consoleErrors.join(' | ')}`);
      if (requestFailures.length) reasons.push(`network: ${requestFailures.join(' | ')}`);
      if (data.forbidden.length) reasons.push(`belső szöveg: ${data.forbidden.join(', ')}`);
      if (!data.heading) reasons.push('nincs H1');
      if (data.headingFontSize > maxHeading) reasons.push(`túl nagy H1: ${data.headingFontSize}px`);
      if (data.headingOverflow || data.horizontalOverflow || data.badOverflow.length) reasons.push('tördelési vagy túlcsordulási hiba');
      if (data.headingWordBreak !== 'normal' || data.headingOverflowWrap === 'anywhere') reasons.push('szóközi törés engedélyezett');
      if (data.hasDirectory) reasons.push('régi összes-aloldal panel jelen van');
      if (data.navGroups < 6) reasons.push('hiányos ügyfélbarát főmenü');
      if (!data.isLegal && !data.isNim && data.heroActions < 2) reasons.push(`kevés hero CTA: ${data.heroActions}`);
      if (!data.isLegal && !data.isNim && data.allActions < 3) reasons.push(`kevés oldal-CTA: ${data.allActions}`);
      if (!data.isLegal && !data.isNim && data.visuals < 3) reasons.push(`kevés vizuális magyarázat: ${data.visuals}`);
      const entry = { route, viewport: viewport.name, ...data, reasons };
      results.push(entry);
      if (reasons.length) failures.push(entry);
      await context.close();
    }
  }
  const report = { generated_at: new Date().toISOString(), routes: routes.length, checks: results.length, failures: failures.length, results };
  fs.writeFileSync(path.join(__dirname, 'public-release-report.json'), `${JSON.stringify(report, null, 2)}\n`);
  await browser.close();
  console.log(JSON.stringify({ routes: report.routes, checks: report.checks, failures: report.failures }));
  if (failures.length) process.exit(1);
})().catch(error => { console.error(error); process.exit(1); });
