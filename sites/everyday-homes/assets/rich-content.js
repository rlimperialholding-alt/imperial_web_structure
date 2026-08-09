const RICH_SOURCE_MAP = {
  "/": { file: "01-kezdolap.md", layout: "family-editorial", photo: "everyday-first-home-planning-v2.png", primary: "/otthonvalaszto" },
  "/otthonvalaszto": { file: "02-otthonvalaszto.md", layout: "chooser-mosaic", photo: "everyday-young-family.jpg", primary: "/keretbol-otthon" },
  "/keretbol-otthon": { file: "04-keretbol-otthon.md", layout: "family-ledger", photo: "everyday-budget-consultation-v2.png", primary: "/szamolok/teljes-projektkeret" },
  "/igy-lesz-egyszeru": { file: "05-igy-lesz-egyszeru.md", layout: "guided-journey", photo: "everyday-guided-building-process-v2.png", primary: "/kezdjuk-egyutt" },
  "/kozelrol": { file: "06-kozelrol.md", layout: "proof-gallery", photo: "everyday-real-home-visit-v2.png", primary: "/kozelrol/elkeszult-otthonok" },
  "/elso-lepesek": { file: "07-tudastar.md", layout: "knowledge-magazine", photo: "everyday-young-family.jpg", primary: "/a-fontos-kerdesek" },
  "/a-fontos-kerdesek": { file: "08-gyik.md", layout: "question-wall", photo: "everyday-mother-child.jpg", primary: "/kezdjuk-egyutt" },
  "/kezdjuk-egyutt": { file: "09-kapcsolat.md", layout: "conversation-room", photo: "everyday-warm-generations.jpg", primary: "/otthonvalaszto" },
  "/kell-egy-otthon-mindenkinek": { file: "../pages/10-kuldetesunk.md", layout: "mission-manifesto", photo: "everyday-mission-family-v1.png", primary: "/otthonvalaszto" },
  "/garanciak-es-utogondozas": { file: "../pages/11-garanciak-es-utogondozas.md", layout: "care-protocol", photo: "everyday-aftercare-inspection-v1.png", primary: "/biztonsag/atadas-utan" },
  "/elso-lepesek-hirlevel": { file: "../pages/12-hirlevel.md", layout: "letter-lab", photo: "everyday-newsletter-planning-v1.png", primary: "/elso-lepesek" },
  "/karrier": { file: "../pages/13-karrier.md", layout: "maker-workshop", photo: "everyday-career-team-v1.png", primary: "/karrier" },
  "/sajto": { file: "../pages/14-sajto.md", layout: "press-desk", photo: "everyday-press-interview-v1.png", primary: "/sajto" },
};

const INTERNAL_STOP = /^(?:\d+\.\s+)?(?:EGYEDI VIZUÁLIS ARCHETÍPUS|ÁLLÍTÁS- ÉS ADATKAPU|KAPUSTÁTUSZ|KIADÁSI STÁTUSZ|BELSŐ ELLENŐRZÉS)/i;
const DYNAMIC_PLACEHOLDER = /\[[^\]]+\]/g;
const EDITORIAL_FIELD_LINE = /^(?:Mezők?|Űrlapmezők|Típusházkártya|Otthonkártya|Összehasonlítási mezők|Kiinduló helyzet|A döntés fő oka|A telek fontos adottsága|A legfontosabb változtatás|Adatkezelési sor|Beküldés utáni üzenet|Fájlfeltöltés|Visszaigazoló üzenet):/i;

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
    if (/^Szerkesztői szabály:/i.test(line) || EDITORIAL_FIELD_LINE.test(line)) continue;
    const withoutPlaceholder = line.replace(DYNAMIC_PLACEHOLDER, "").replace(/\s{2,}/g, " ").trim();
    if (withoutPlaceholder.length >= 24) cleaned.push(withoutPlaceholder);
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
  if (layout === "mission-manifesto") {
    return `<figure class="explain-visual explain-visual--mission"><figcaption>Az otthon nem a tervrajznál kezdődik</figcaption><div class="mission-orbit"><strong>A család élete</strong>${safe.map((label, index) => `<span style="--orbit:${index}">${label}</span>`).join("")}</div></figure>`;
  }
  if (layout === "care-protocol") {
    return `<figure class="explain-visual explain-visual--care"><figcaption>Egy kérdés útja a jelzéstől a lezárásig</figcaption><ol class="care-track"><li><b>01</b><span>Jelzés</span></li><li><b>02</b><span>Azonosítás</span></li><li><b>03</b><span>Vizsgálat</span></li><li><b>04</b><span>Intézkedés</span></li><li><b>05</b><span>Visszajelzés</span></li></ol></figure>`;
  }
  if (layout === "letter-lab") {
    return `<figure class="explain-visual explain-visual--letters"><figcaption>Nem mindegy, melyik levél érkezik meg ma</figcaption><div class="mail-stack">${safe.map((label, index) => `<article><small>0${index + 1}</small><strong>${label}</strong><span>Egy válasz. Egy következő lépés.</span></article>`).join("")}</div></figure>`;
  }
  if (layout === "maker-workshop") {
    return `<figure class="explain-visual explain-visual--workshop"><figcaption>A munkád mindig valaki más munkáját készíti elő</figcaption><div class="handoff-plan"><span>Megértem</span><i></i><span>Elkészítem</span><i></i><span>Ellenőrzöm</span><i></i><strong>Átadom</strong></div></figure>`;
  }
  if (layout === "press-desk") {
    return `<figure class="explain-visual explain-visual--press"><figcaption>Állításból közölhető információ</figcaption><div class="fact-desk"><span>Forrás</span><span>Dátum</span><span>Feltétel</span><span>Módszer</span><strong>Ellenőrzött mondat</strong></div></figure>`;
  }
  return `<figure class="explain-visual explain-visual--home"><figcaption>Az otthonhoz vezető döntések</figcaption><svg viewBox="0 0 800 360" role="img" aria-label="Döntési útvonal"><path d="M80 270 L220 130 L360 245 L520 90 L720 220"/><circle cx="80" cy="270" r="24"/><circle cx="220" cy="130" r="24"/><circle cx="360" cy="245" r="24"/><circle cx="520" cy="90" r="24"/><circle cx="720" cy="220" r="24"/></svg><div class="visual-labels">${safe.map(label => `<span>${label}</span>`).join("")}</div></figure>`;
}

function secondaryDiagramMarkup(layout) {
  const visuals = {
    "family-editorial": `<figure class="secondary-visual secondary-visual--rooms"><figcaption>Egy nap az otthonban</figcaption><div><span>Reggel</span><b>Közös tér</b><span>Délután</span><b>Saját sarok</b><span>Este</span></div></figure>`,
    "chooser-mosaic": `<figure class="secondary-visual secondary-visual--filter"><figcaption>A választás szűkül, az indok tisztul</figcaption><div><i>Élethelyzet</i><i>Telek</i><i>Keret</i><strong>Nekünk való</strong></div></figure>`,
    "family-ledger": `<figure class="secondary-visual secondary-visual--reserve"><figcaption>A biztonsági tartalék nem maradék</figcaption><div><span>Ház</span><span>Telek és külső munkák</span><strong>Megőrzött tartalék</strong></div></figure>`,
    "guided-journey": `<figure class="secondary-visual secondary-visual--calendar"><figcaption>A döntéseknek is van időpontjuk</figcaption><div>${["Most", "Következő", "Előkészítve", "Lezárva"].map((x, i) => `<span style="--step:${i}">${x}</span>`).join("")}</div></figure>`,
    "proof-gallery": `<figure class="secondary-visual secondary-visual--lenses"><figcaption>Ugyanaz a ház négy bizonyítékkal</figcaption><div><span>Fotó</span><span>Helyszín</span><span>Műszaki adat</span><span>Családi tapasztalat</span></div></figure>`,
    "knowledge-magazine": `<figure class="secondary-visual secondary-visual--reading"><figcaption>A jó kérdésből használható jegyzet lesz</figcaption><div><b>?</b><span>Mi változik?</span><span>Mit kell mérni?</span><span>Ki tud felelni?</span></div></figure>`,
    "question-wall": `<figure class="secondary-visual secondary-visual--answers"><figcaption>Nem minden válasz ugyanaz a mondat</figcaption><div><span>Ár → számítás</span><span>Telek → vizsgálat</span><span>Technika → mérnök</span><span>Szerződés → dokumentum</span></div></figure>`,
    "conversation-room": `<figure class="secondary-visual secondary-visual--meeting"><figcaption>Így érkeztek felkészülten a beszélgetésre</figcaption><div><span>Kérdés</span><span>Dokumentum</span><span>Elképzelés</span><strong>Következő lépés</strong></div></figure>`,
    "mission-manifesto": `<figure class="secondary-visual secondary-visual--promise"><figcaption>A küldetés a hétköznapokban mérhető</figcaption><div><span>Érthető választás</span><span>Vállalható keret</span><span>Követhető út</span><strong>Jól használható otthon</strong></div></figure>`,
    "care-protocol": `<figure class="secondary-visual secondary-visual--seasons"><figcaption>Az első év négy ellenőrzési nézőpontja</figcaption><div><span>Tavasz<br><b>víz útja</b></span><span>Nyár<br><b>hő és árnyék</b></span><span>Ősz<br><b>felkészítés</b></span><span>Tél<br><b>pára és komfort</b></span></div></figure>`,
    "letter-lab": `<figure class="secondary-visual secondary-visual--inbox"><figcaption>A postafiók nem tartalomraktár</figcaption><div><span>Megérkezik</span><span>Elolvasható</span><span>Elvégezhető</span><strong>Hasznos döntés</strong></div></figure>`,
    "maker-workshop": `<figure class="secondary-visual secondary-visual--responsibility"><figcaption>A felelősség nem áll meg a saját feladat végén</figcaption><div><span>Bemenet</span><i></i><span>Munka</span><i></i><span>Ellenőrzés</span><i></i><strong>Másik ember biztos kezdése</strong></div></figure>`,
    "press-desk": `<figure class="secondary-visual secondary-visual--citation"><figcaption>Az idézhető szám teljes névjegye</figcaption><dl><dt>Mit mér?</dt><dd>Jelentés</dd><dt>Mikor?</dt><dd>Dátum</dd><dt>Hogyan?</dt><dd>Módszer</dd><dt>Honnan?</dt><dd>Forrás</dd></dl></figure>`,
  };
  return visuals[layout] || "";
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
      ${secondaryDiagramMarkup(config.layout)}
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
