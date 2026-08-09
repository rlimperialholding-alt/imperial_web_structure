const RICH_SOURCE_MAP = {
  "/": { file: "01-kezdolap.md", layout: "family-editorial", photo: "everyday-first-home-planning-v2.png", primary: "/otthonvalaszto" },
  "/otthonvalaszto": { file: "02-otthonvalaszto.md", layout: "chooser-mosaic", photo: "everyday-young-family.jpg", primary: "/keretbol-otthon" },
  "/keretbol-otthon": { file: "04-keretbol-otthon.md", layout: "family-ledger", photo: "everyday-budget-consultation-v2.png", primary: "/szamolok/teljes-projektkeret" },
  "/igy-lesz-egyszeru": { file: "05-igy-lesz-egyszeru.md", layout: "guided-journey", photo: "everyday-guided-building-process-v2.png", primary: "/kezdjuk-egyutt" },
  "/kozelrol": { file: "06-kozelrol.md", layout: "proof-gallery", photo: "everyday-real-home-visit-v2.png", primary: "/kozelrol/elkeszult-otthonok" },
  "/elso-lepesek": { file: "07-tudastar.md", layout: "knowledge-magazine", photo: "everyday-young-family.jpg", primary: "/a-fontos-kerdesek" },
  "/a-fontos-kerdesek": { file: "08-gyik.md", layout: "question-wall", photo: "everyday-mother-child.jpg", primary: "/kezdjuk-egyutt" },
  "/kezdjuk-egyutt": { file: "09-kapcsolat.md", layout: "conversation-room", photo: "everyday-warm-generations.jpg", primary: "/otthonvalaszto" },
};

const INTERNAL_STOP = /^(?:\d+\.\s+)?(?:EGYEDI VIZUÁLIS ARCHETÍPUS|ÁLLÍTÁS- ÉS ADATKAPU|KAPUSTÁTUSZ|KIADÁSI STÁTUSZ|BELSŐ ELLENŐRZÉS)/i;
const DYNAMIC_PLACEHOLDER = /\[[^\]]+(?:SZÜKSÉGES|JÓVÁHAGYOTT|AKTÍV|ELLENŐRZÖTT|HÁZNÉV|ÁR|MEZŐ|HELYSZÍN|IDŐ)[^\]]*\]/gi;

function cleanPublicLines(source) {
  let text = source.replace(/\r/g, "");
  const marker = text.indexOf("NYILVÁNOS OLDALSZÖVEG");
  if (marker >= 0) text = text.slice(marker + "NYILVÁNOS OLDALSZÖVEG".length);
  const lines = text.split("\n");
  const cleaned = [];
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (INTERNAL_STOP.test(line) || /^Kiadási státusz:/i.test(line)) break;
    if (!line) { cleaned.push(""); continue; }
    if (/^(?:Szerkesztői szabály|Mezők|Űrlapmezők|Típusházkártya|Összehasonlítási mezők):/i.test(line)) continue;
    const withoutPlaceholder = line.replace(DYNAMIC_PLACEHOLDER, "").replace(/\s{2,}/g, " ").trim();
    if (withoutPlaceholder) cleaned.push(withoutPlaceholder);
  }
  return cleaned;
}

function isDisplayHeading(line) {
  if (!line || line.length > 130 || line.includes(":")) return false;
  const letters = line.match(/[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]/g) || [];
  if (!letters.length) return false;
  const upper = line.toLocaleUpperCase("hu-HU");
  return line === upper && !/^EVERYDAY HOMES$/.test(line);
}

function parsePublicSource(source) {
  const lines = cleanPublicLines(source);
  const heroIndex = lines.findIndex(line => line === "HERO");
  const working = lines.slice(heroIndex >= 0 ? heroIndex + 1 : 0);
  const titleIndex = working.findIndex(line => line && !/^(?:EVERYDAY HOMES|Elsődleges|Másodlagos|Bizalmi sor)/i.test(line));
  const title = working[titleIndex] || "Everyday Homes";
  const heroText = [];
  const sections = [];
  let current = null;
  for (let index = titleIndex + 1; index < working.length; index += 1) {
    const line = working[index];
    if (!line) continue;
    if (/^(?:Elsődleges|Másodlagos)?\s*(?:gomb|gombszöveg|CTA):/i.test(line) || /^Bizalmi sor:/i.test(line) || /^Kiemelt gomb:/i.test(line)) continue;
    if (isDisplayHeading(line) || /^\d+\.\s+\S/.test(line)) {
      current = { title: line.replace(/^\d+\.\s+/, ""), blocks: [] };
      sections.push(current);
      continue;
    }
    if (!current) heroText.push(line);
    else current.blocks.push(line);
  }
  return { title, heroText, sections };
}

function sectionMarkup(section, sectionIndex) {
  const blocks = [];
  let currentQuestion = null;
  for (const line of section.blocks) {
    if (line.endsWith("?") && line.length < 190) {
      currentQuestion = { question: line, answers: [] };
      blocks.push(currentQuestion);
    } else if (currentQuestion) {
      currentQuestion.answers.push(line);
    } else {
      blocks.push({ paragraph: line });
    }
  }
  const content = blocks.map((block, index) => {
    if (block.question) {
      return `<details class="rich-faq" ${sectionIndex === 0 && index === 0 ? "open" : ""}><summary>${escapeHtml(block.question)}</summary><div>${block.answers.map(answer => `<p>${escapeHtml(answer)}</p>`).join("")}</div></details>`;
    }
    return `<p class="rich-copy">${escapeHtml(block.paragraph)}</p>`;
  }).join("");
  return `<section class="rich-section rich-section--${(sectionIndex % 5) + 1}"><div class="rich-section__number">${String(sectionIndex + 1).padStart(2, "0")}</div><div class="rich-section__body"><h2>${escapeHtml(section.title)}</h2>${content}</div></section>`;
}

function diagramMarkup(layout, sections) {
  const labels = sections.slice(0, 4).map(section => section.title.replace(/^\d+\.\s+/, ""));
  while (labels.length < 4) labels.push(["Döntés", "Rend", "Biztonság", "Otthon"][labels.length]);
  const safe = labels.map(label => escapeHtml(label.length > 34 ? `${label.slice(0, 31)}…` : label));
  if (layout === "family-ledger") {
    return `<figure class="explain-visual explain-visual--ledger"><figcaption>A teljes döntés négy sora</figcaption><div class="ledger-bars">${safe.map((label, index) => `<div><span style="--bar:${68 + index * 8}%"></span><strong>${label}</strong></div>`).join("")}</div></figure>`;
  }
  if (layout === "guided-journey") {
    return `<figure class="explain-visual explain-visual--journey"><figcaption>A következő döntés mindig látható</figcaption><ol>${safe.map((label, index) => `<li><b>${index + 1}</b><span>${label}</span></li>`).join("")}</ol></figure>`;
  }
  if (layout === "question-wall") {
    return `<figure class="explain-visual explain-visual--questions"><figcaption>A döntés négy nézőpontja</figcaption><div>${safe.map(label => `<span>${label}</span>`).join("")}</div></figure>`;
  }
  if (layout === "proof-gallery") {
    return `<figure class="explain-visual explain-visual--proof"><figcaption>Ígéretből ellenőrizhető tapasztalat</figcaption><div class="proof-lens"><span>Megnézem</span><span>Megkérdezem</span><span>Összevetem</span><strong>Döntök</strong></div></figure>`;
  }
  if (layout === "knowledge-magazine") {
    return `<figure class="explain-visual explain-visual--compass"><figcaption>Nem több információ kell. Jobb sorrend.</figcaption><div class="compass"><span>${safe[0]}</span><span>${safe[1]}</span><strong>Érthető döntés</strong><span>${safe[2]}</span><span>${safe[3]}</span></div></figure>`;
  }
  if (layout === "conversation-room") {
    return `<figure class="explain-visual explain-visual--conversation"><figcaption>Onnan indulunk, ahol most tartotok</figcaption><div class="speech-flow"><span>Elmondjátok</span><span>Rákérdezünk</span><span>Tisztázzuk</span><strong>Következő lépés</strong></div></figure>`;
  }
  if (layout === "chooser-mosaic") {
    return `<figure class="explain-visual explain-visual--mosaic"><figcaption>Négy válasz szűkíti a választást</figcaption><div>${safe.map((label, index) => `<span style="--i:${index}">${label}</span>`).join("")}</div></figure>`;
  }
  return `<figure class="explain-visual explain-visual--home"><figcaption>Az otthonhoz vezető döntések</figcaption><svg viewBox="0 0 800 360" role="img" aria-label="Döntési útvonal"><path d="M80 270 L220 130 L360 245 L520 90 L720 220"/><circle cx="80" cy="270" r="24"/><circle cx="220" cy="130" r="24"/><circle cx="360" cy="245" r="24"/><circle cx="520" cy="90" r="24"/><circle cx="720" cy="220" r="24"/></svg><div class="visual-labels">${safe.map(label => `<span>${label}</span>`).join("")}</div></figure>`;
}

async function renderRichSourcePage(path) {
  const config = RICH_SOURCE_MAP[path];
  if (!config) return false;
  const response = await fetch(`${BASE}/sources/drive/${config.file}`);
  if (!response.ok) throw new Error(`A forrásszöveg nem tölthető be: ${config.file}`);
  const parsed = parsePublicSource(await response.text());
  const canonical = pages[path];
  const intro = parsed.heroText.slice(0, 3).join(" ");
  const faqCount = parsed.sections.reduce((sum, section) => sum + section.blocks.filter(line => line.endsWith("?")).length, 0);
  const bodyChars = parsed.sections.reduce((sum, section) => sum + section.title.length + section.blocks.join(" ").length, 0);
  const main = document.querySelector("main");
  document.title = `${canonical.eyebrow} | Everyday Homes staging`;
  main.innerHTML = `
    <article class="rich-page rich-page--${config.layout}" data-page-id="${escapeHtml(canonical.id)}" data-release-state="review-required" data-body-characters="${bodyChars}" data-faq-count="${faqCount}">
      <section class="rich-hero">
        <div class="rich-hero__image" style="background-image:url('${BASE}/assets/photos/${config.photo}')" role="img" aria-label="${escapeHtml(canonical.eyebrow)} – Everyday Homes élethelyzet"></div>
        <div class="rich-hero__copy"><span class="hero__tag">${escapeHtml(canonical.id)} · részletes forrásoldal</span><p class="eyebrow">${escapeHtml(canonical.eyebrow)}</p><h1>${escapeHtml(parsed.title)}</h1><p class="lede">${escapeHtml(intro)}</p><div class="actions"><a class="button" href="${href(config.primary)}" data-route>${escapeHtml(canonical.primary?.[0] || "Megnézem a következő lépést")}</a></div></div>
      </section>
      <div class="rich-metrics" aria-label="Szerkesztési készültség"><span><strong>${bodyChars.toLocaleString("hu-HU")}</strong> látható karakter</span><span><strong>${parsed.sections.length}</strong> önálló fejezet</span><span><strong>${faqCount}</strong> szakmai kérdés</span><span><strong>3×</strong> QA kötelező</span></div>
      ${diagramMarkup(config.layout, parsed.sections)}
      <div class="rich-sections">${parsed.sections.map(sectionMarkup).join("")}</div>
      <section class="rich-closing"><div><p class="eyebrow">Otthon – egyszerűen.</p><h2>${escapeHtml(canonical.title)}</h2></div><a class="button" href="${href(config.primary)}" data-route>${escapeHtml(canonical.primary?.[0] || "Tovább")}</a></section>
    </article>`;
  setCurrent(path);
  bindRoutes();
  return true;
}

async function upgradeCurrentPage() {
  const path = normalizePath();
  if (!RICH_SOURCE_MAP[path]) return;
  try {
    await renderRichSourcePage(path);
  } catch (error) {
    document.querySelector("main")?.insertAdjacentHTML("afterbegin", `<p class="status-note"><strong>Forrásbetöltési hiba:</strong> ${escapeHtml(error.message)}</p>`);
  }
}

const originalNavigate = navigate;
navigate = function richNavigate(path, replace = false) {
  originalNavigate(path, replace);
  upgradeCurrentPage();
};

window.addEventListener("popstate", upgradeCurrentPage);
upgradeCurrentPage();
