const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.EVERYDAY_PREVIEW_URL || 'http://127.0.0.1:18084/site-preview/everyday-homes';
const previewRoot = path.resolve(process.env.EVERYDAY_PREVIEW_ROOT || path.join(__dirname, '..'));
const routes = (process.env.EVERYDAY_RICH_ROUTES || '/,/otthonvalaszto,/keretbol-otthon,/igy-lesz-egyszeru,/kozelrol,/elso-lepesek,/a-fontos-kerdesek,/kezdjuk-egyutt').split(',');
const viewports = [{name:'mobile',width:390,height:844},{name:'tablet',width:768,height:1024},{name:'desktop',width:1440,height:1000}];
const screenshotRoot = path.join(__dirname, 'screenshots', 'rich-pages');
const reportPath = path.join(__dirname, 'rich-pages-report.json');
const forbidden = ['látható karakter','önálló fejezet','QA kötelez','NIM CMS','belső ellenőrzés','kiadási státusz'];
fs.mkdirSync(screenshotRoot, {recursive:true});

function slug(route) { return route === '/' ? 'kezdolap' : route.slice(1).replaceAll('/','--'); }

(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROME_PATH || undefined});
  const report = {generated_at:new Date().toISOString(), checks:[]};
  const signatures = new Set();
  let failed = false;
  for (const route of routes) for (const viewport of viewports) {
    const context = await browser.newContext({viewport});
    const basePath = new URL(baseUrl).pathname.replace(/\/$/, '');
    await context.route('**/*', async intercepted => {
      const requestUrl = new URL(intercepted.request().url());
      if (!requestUrl.pathname.startsWith(basePath)) return intercepted.continue();
      const relative = decodeURIComponent(requestUrl.pathname.slice(basePath.length)).replace(/^\/+/, '');
      let target = path.resolve(previewRoot, relative || 'index.html');
      if (!target.startsWith(previewRoot)) return intercepted.fulfill({status:403,body:'Forbidden'});
      if (fs.existsSync(target) && fs.statSync(target).isDirectory()) target = path.join(target,'index.html');
      if (!fs.existsSync(target)) return intercepted.fulfill({status:404,body:'Not found'});
      return intercepted.fulfill({path:target});
    });
    const page = await context.newPage();
    const consoleErrors=[], pageErrors=[], requestFailures=[], badResponses=[];
    page.on('console', m => { if (m.type()==='error') consoleErrors.push(m.text()); });
    page.on('pageerror', e => pageErrors.push(e.message));
    page.on('requestfailed', r => requestFailures.push(`${r.method()} ${r.url()} ${r.failure()?.errorText||''}`));
    page.on('response', r => { if (r.status()>=400 && r.url().startsWith(baseUrl)) badResponses.push(`${r.status()} ${r.url()}`); });
    const response = await page.goto(`${baseUrl}${route==='/'?'':route}`, {waitUntil:'commit',timeout:20000});
    await page.waitForSelector('.rich-page', {timeout:30000});
    await page.evaluate(async () => document.fonts.ready);
    const dom = await page.evaluate(forbiddenPhrases => {
      const main=document.querySelector('main'), article=document.querySelector('.rich-page');
      const visible=main?.innerText||'', width=document.documentElement.clientWidth;
      const outside=[...document.querySelectorAll('main *')].filter(el=>{ const r=el.getBoundingClientRect(); if(!(r.width>0&&(r.left<-2||r.right>width+2))) return false; let a=el.parentElement; while(a&&a!==document.body){ if(['auto','scroll','hidden','clip'].includes(getComputedStyle(a).overflowX)) return false; a=a.parentElement; } return true; }).slice(0,20).map(el=>({tag:el.tagName,text:(el.textContent||'').trim().slice(0,80)}));
      const clipped=[...document.querySelectorAll('main h1,main h2,main h3,main p,main summary,main .button')].filter(el=>{const s=getComputedStyle(el),r=el.getBoundingClientRect(); return r.width&&r.height&&((el.scrollWidth>el.clientWidth+2&&['hidden','clip'].includes(s.overflowX))||(el.scrollHeight>el.clientHeight+2&&['hidden','clip'].includes(s.overflowY)));}).slice(0,20).map(el=>({tag:el.tagName,text:(el.textContent||'').trim().slice(0,80)}));
      return {contentCharacters:(main?.textContent||'').replace(/\s+/g,' ').trim().length, faqItems:document.querySelectorAll('.rich-faq').length, visuals:document.querySelectorAll('.rich-hero__image,.explain-visual,.secondary-visual').length, layoutSignature:[...article.classList].find(x=>x.startsWith('rich-page--')), forbidden:forbiddenPhrases.filter(x=>visible.includes(x)), horizontalOverflow:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)>width+2, outside, clipped};
    }, forbidden);
    if(viewport.name==='desktop') signatures.add(dom.layoutSignature);
    const check={route,viewport:viewport.name,http_status:response?.status()||null,console_errors:consoleErrors,page_errors:pageErrors,request_failures:requestFailures,bad_responses:badResponses,...dom};
    check.passed=check.http_status===200&&check.contentCharacters>=12000&&check.faqItems>=25&&check.visuals>=3&&!check.horizontalOverflow&&!check.outside.length&&!check.clipped.length&&!check.forbidden.length&&!check.console_errors.length&&!check.page_errors.length&&!check.request_failures.length&&!check.bad_responses.length;
    if(!check.passed) failed=true;
    report.checks.push(check);
    await page.screenshot({path:path.join(screenshotRoot,`${slug(route)}--${viewport.name}.png`),fullPage:true,timeout:120000});
    await context.close();
  }
  report.layout_signatures=[...signatures]; report.summary={routes:routes.length,checks:report.checks.length,failures:report.checks.filter(x=>!x.passed).length,unique_layouts:signatures.size}; report.passed=!failed&&signatures.size===routes.length;
  fs.writeFileSync(reportPath,JSON.stringify(report,null,2)+'\n');
  await browser.close(); console.log(JSON.stringify(report.summary)); if(!report.passed) process.exit(1);
})().catch(error=>{console.error(error);process.exit(1);});
