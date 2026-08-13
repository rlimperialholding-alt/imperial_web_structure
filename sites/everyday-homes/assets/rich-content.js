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
  "/elso-sajat-otthon": { file: "../pages/101-elso-sajat-otthon.md", layout: "first-key-map", photo: "everyday-first-home-arrival-v1.png", primary: "/szamolok/havi-teher", introLimit: 2 },
  "/most-leszunk-csalad": { file: "../pages/102-most-leszunk-csalad.md", layout: "family-rhythm", photo: "everyday-expecting-family-nursery-v1.png", primary: "/kezdjuk-egyutt", introLimit: 1 },
  "/tobb-hely-a-csaladnak": { file: "../pages/103-tobb-hely-a-csaladnak.md", layout: "family-traffic", photo: "everyday-growing-family-zones-v1.png", primary: "/otthonvalaszto", introLimit: 1 },
  "/otthon-es-munka": { file: "../pages/104-otthon-es-munka.md", layout: "workday-switchboard", photo: "everyday-home-office-boundary-v1.png", primary: "/kezdjuk-egyutt", introLimit: 1 },
  "/kisebb-haz-konnyebb-elet": { file: "../pages/105-kisebb-haz-konnyebb-elet.md", layout: "lighter-life-balance", photo: "everyday-lighter-home-freedom-v1.png", primary: "/otthonvalaszto", introLimit: 1 },
  "/ket-generacio-egy-otthon": { file: "../pages/106-ket-generacio-egy-otthon.md", layout: "two-household-bridge", photo: "everyday-two-generations-courtyard-v1.png", primary: "/kezdjuk-egyutt", introLimit: 1 },
  "/kesobb-bovitheto-otthon": { file: "../pages/107-kesobb-bovitheto-otthon.md", layout: "phased-home-blueprint", photo: "everyday-expandable-home-plan-v1.png", primary: "/kezdjuk-egyutt", introLimit: 1 },
  "/szamolok/hazkoltseg": { file: "../pages/301-hazkoltseg.md", layout: "project-cost-ledger", photo: "everyday-house-cost-table-v1.png", primary: "/kezdjuk-egyutt", introLimit: 1 },
};

const INTERNAL_STOP = /^(?:\d+\.\s+)?(?:EGYEDI VIZUÁLIS ARCHETÍPUS|ÁLLÍTÁS- ÉS ADATKAPU|KAPUSTÁTUSZ|KIADÁSI STÁTUSZ|BELSŐ ELLENŐRZÉS)/i;
const DYNAMIC_PLACEHOLDER = /\[[^\]]+\]/g;
const EDITORIAL_FIELD_LINE = /^(?:Mezők?|Űrlapmezők|Típusházkártya|Otthonkártya|Összehasonlítási mezők|Kiinduló helyzet|A döntés fő oka|A telek fontos adottsága|A legfontosabb változtatás|Adatkezelési sor|Beküldés utáni üzenet|Fájlfeltöltés|Visszaigazoló üzenet):/i;
const PUBLIC_CONTROL_LINE = /^(?:Felső navigáció|Kiemelt gomb(?:szöveg)?|Elsődleges (?:gombszöveg|CTA)|Másodlagos (?:gombszöveg|CTA)|Bizalmi sor|gombszöveg|Szekció CTA|Találati összefoglaló|Válaszok|Súgó):/i;

function cleanPublicLines(source) {
  let text = source.replace(/\r/g, "");
  const marker = text.indexOf("NYILVÁNOS OLDALSZÖVEG");
  if (marker < 0) throw new Error("A forrásból hiányzik a nyilvános tartalom egyértelmű kezdőjelölője.");
  text = text.slice(marker + "NYILVÁNOS OLDALSZÖVEG".length);
  const lines = text.split("\n");
  const cleaned = [];
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (INTERNAL_STOP.test(line) || /^Kiadási státusz:/i.test(line) || /^SZERKESZTŐI(?:\s+ÉS)?/i.test(line)) break;
    if (!line) { cleaned.push(""); continue; }
    if (/^Szerkesztői szabály:/i.test(line) || EDITORIAL_FIELD_LINE.test(line) || PUBLIC_CONTROL_LINE.test(line)) continue;
    if (/^(?:EVERYDAY HOMES|META|Meta title|Meta description|FELSŐ NAVIGÁCIÓ|FOOTER)$/i.test(line)) continue;
    const withoutPlaceholder = line.replace(DYNAMIC_PLACEHOLDER, "").replace(/\s{2,}/g, " ").trim();
    if (/^\+\s*ÁFA[.,]?$/i.test(withoutPlaceholder)) continue;
    if (withoutPlaceholder && (withoutPlaceholder.length >= 24 || withoutPlaceholder === "HERO" || isDisplayHeading(withoutPlaceholder) || /^\d+\.\s+\S/.test(withoutPlaceholder))) cleaned.push(withoutPlaceholder);
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
  if (layout === "first-key-map") {
    return `<figure class="explain-visual explain-visual--first-key"><figcaption>Négy zárat nyitunk ki az első kulcs előtt</figcaption><div class="first-key-path"><span><b>01</b>Miért költöznétek?</span><span><b>02</b>Mi fér bele biztonságosan?</span><span><b>03</b>Hol lehet megépíteni?</span><span><b>04</b>Melyik otthon szolgál benneteket?</span><strong aria-label="A döntés eredménye">Első saját kulcs</strong></div></figure>`;
  }
  if (layout === "family-rhythm") {
    return `<figure class="explain-visual explain-visual--family-rhythm"><figcaption>Egy nap ritmusa mutatja meg, milyen térre lesz szükségetek</figcaption><div class="rhythm-wheel"><span><b>06</b>Ébredés és készülődés</span><span><b>10</b>Otthoni munka és gondozás</span><span><b>16</b>Érkezés, játék, kert</span><span><b>21</b>Fürdés és elcsendesedés</span><strong>Nyugodtabb családi nap</strong></div></figure>`;
  }
  if (layout === "family-traffic") {
    return `<figure class="explain-visual explain-visual--family-traffic"><figcaption>Nem a szobaszámot növeljük. A napi ütközéseket oldjuk fel.</figcaption><div class="traffic-map"><ol><li><b>07:10</b><span>fürdő</span><i></i><span>öltözés</span><i></i><span>indulás</span></li><li><b>16:30</b><span>érkezés</span><i></i><span>tanulás</span><i></i><span>játék</span></li><li><b>20:15</b><span>vacsora</span><i></i><span>fürdés</span><i></i><span>csend</span></li></ol><strong>Kevesebb keresztezés. Több együtt töltött idő.</strong></div></figure>`;
  }
  if (layout === "workday-switchboard") {
    return `<figure class="explain-visual explain-visual--workday"><figcaption>A munkanapnak legyen kezdete, ritmusa és vége</figcaption><div class="workday-console"><span><b>08:00</b><i>FÓKUSZ</i>ajtó becsukva</span><span><b>10:30</b><i>HÍVÁS</i>csendes háttér</span><span><b>13:00</b><i>SZÜNET</i>kilépés a munkatérből</span><span><b>17:00</b><i>LEZÁRÁS</i>eszközök a helyükön</span><strong><i></i>Otthon mód</strong></div></figure>`;
  }
  if (layout === "lighter-life-balance") {
    return `<figure class="explain-visual explain-visual--lighter-life"><figcaption>Nem egyszerűen kisebb lesz. Más kerül a mérleg két oldalára.</figcaption><div class="life-balance"><section><small>AMIBŐL KEVESEBB</small><span>Takarítás</span><span>Lépcső</span><span>Fűtött üres tér</span><span>Kerti kötelesség</span></section><i><b></b></i><section><small>AMIBŐL TÖBB</small><span>Szabad idő</span><span>Könnyű közlekedés</span><span>Használt, szeretett terek</span><span>Család és hobbi</span></section></div></figure>`;
  }
  if (layout === "two-household-bridge") {
    return `<figure class="explain-visual explain-visual--two-households"><figcaption>A közelség nem közös nappalit jelent, hanem jól megválasztott kapcsolatokat</figcaption><div class="household-bridge"><section><small>ELSŐ OTTHON</small><span>Saját bejárat</span><span>Saját napirend</span><span>Saját vendégek</span></section><div><b>KÖZÖS UDVAR</b><i></i><strong>Segítség, amikor szükség van rá</strong></div><section><small>MÁSODIK OTTHON</small><span>Saját fürdő</span><span>Saját konyha</span><span>Saját csend</span></section></div></figure>`;
  }
  if (layout === "phased-home-blueprint") {
    return `<figure class="explain-visual explain-visual--phased-home"><figcaption>A bővítés nem a második építkezésnél kezdődik</figcaption><ol class="phase-track"><li><b>01</b><strong>Végállapot</strong><span>Előbb a teljes ház helye és logikája készül el.</span></li><li><b>02</b><strong>Első otthon</strong><span>Önálló, kényelmes, azonnal beköltözhető.</span></li><li><b>03</b><strong>Előkészítés</strong><span>Csatlakozások, kapacitás és szabad építési út.</span></li><li><b>04</b><strong>Folytatás</strong><span>Új tér, kevés bontás, rendezett átmenet.</span></li></ol></figure>`;
  }
  if (layout === "project-cost-ledger") {
    return `<figure class="explain-visual explain-visual--cost-ledger"><figcaption>A teljes projekt három külön keretből áll össze</figcaption><div class="cost-rings"><section><b>01</b><strong>A ház</strong><span>rögzített műszaki tartalom</span></section><section><b>02</b><strong>A helyszín</strong><span>telek, közmű, előkészítés</span></section><section><b>03</b><strong>A biztonság</strong><span>külön kezelt tartalék</span></section><p>Az összegek nem cserélhetik fel egymást.</p></div></figure>`;
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
    "first-key-map": `<figure class="secondary-visual secondary-visual--three-doors"><figcaption>Három lakhatási út, háromféle következmény</figcaption><div><article><small>Albérlet</small><strong>Rugalmas kezdet</strong><span>Nincs építési projekt, de nincs saját ingatlan sem.</span></article><article><small>Kész lakás vagy ház</small><strong>Gyorsabban birtokba vehető</strong><span>Az adottságokhoz alkalmazkodtok.</span></article><article><small>Saját építés</small><strong>A saját életre alakítható</strong><span>Több előkészítés, előre rendezhető döntések.</span></article></div></figure>`,
    "family-rhythm": `<figure class="secondary-visual secondary-visual--safety-home"><figcaption>A nyugodt otthon hat figyelmesen tervezett pontja</figcaption><div><span>Bejárat<br><b>szabad út</b></span><span>Tároló<br><b>kéznél van</b></span><span>Konyha<br><b>átlátható</b></span><span>Fürdő<br><b>segítő hely</b></span><span>Hálók<br><b>csendes rend</b></span><span>Kert<br><b>biztonságos kijárat</b></span></div></figure>`,
    "family-traffic": `<figure class="secondary-visual secondary-visual--useful-space"><figcaption>A hasznos hely nem mindig újabb szoba</figcaption><div><strong>Jól bútorozható hálók</strong><span>Tanulósarok</span><span>Második mosdó</span><span>Bejárati tárolás</span><span>Csendes visszavonulás</span><span>Kertre nyíló közös tér</span></div></figure>`,
    "workday-switchboard": `<figure class="secondary-visual secondary-visual--sound-shield"><figcaption>A csend útja a forrástól a koncentrációig</figcaption><div><span>Zajos családi tér</span><span>Jó helyiségkapcsolat</span><span>Fal + ajtó + tömítés</span><span>Belső hangelnyelés</span><strong>Érthető beszéd. Nyugodt figyelem.</strong></div></figure>`,
    "lighter-life-balance": `<figure class="secondary-visual secondary-visual--time-return"><figcaption>Mit kezdtek azzal az idővel, amit a ház visszaad?</figcaption><div><span><b>Hétfő</b>nem a javítással indul</span><span><b>Szerda</b>jut idő a saját dolgokra</span><span><b>Szombat</b>a kert öröm, nem műszak</span><strong>Vasárnap<br>együtt vagytok</strong></div></figure>`,
    "two-household-bridge": `<figure class="secondary-visual secondary-visual--family-agreement"><figcaption>Négy mondat, amelyet még a falak előtt érdemes kimondani</figcaption><div><article><b>01</b><span>Miben maradunk önállók?</span></article><article><b>02</b><span>Mit használunk együtt?</span></article><article><b>03</b><span>Mikor számítunk egymásra?</span></article><article><b>04</b><span>Mi változhat később?</span></article></div></figure>`,
    "phased-home-blueprint": `<figure class="secondary-visual secondary-visual--future-layers"><figcaption>Amit ma kell rögzíteni, és amit ráértek később kiválasztani</figcaption><div><section><small>MOST DŐL EL</small><span>hely a telken</span><span>tartószerkezeti rend</span><span>tető és víz útja</span><span>gépészeti csatlakozás</span></section><section><small>KÉSŐBB VÁLASZTHATÓ</small><span>pontos funkció</span><span>belső színek</span><span>bútorozás</span><span>indítás időpontja</span></section></div></figure>`,
    "project-cost-ledger": `<figure class="secondary-visual secondary-visual--known-unknown"><figcaption>A jó kalkuláció nem rejti el a bizonytalanságot</figcaption><div><span><small>RÖGZÍTETT</small>műszaki tartalom</span><span><small>BECSÜLT</small>helyszíni tétel</span><span><small>VIZSGÁLANDÓ</small>nyitott adat</span><strong><small>ELKÜLÖNÍTETT</small>biztonsági tartalék</strong></div></figure>`,
  };
  return visuals[layout] || "";
}

function approvedBrandProofMarkup(path) {
  if (path !== "/otthonvalaszto") return "";
  const proofs = [
    ["Nem kell egyedül végignéznetek mindent", "Személyes tanácsadónk az élethelyzetetekből, a lehetőségeitekből és a valódi igényeitekből indul ki. Nem egy végtelen katalógust küld, hanem megmutatja, mely otthonokat érdemes először közelebbről megnéznetek."],
    ["Több mint 300 típustervből lehet szűkíteni", "A nagy választék akkor érték, ha nem nektek kell benne elveszni. A méret, a helyiségek, a telek, a keret és a költözési cél alapján rövidebb listát készítünk, amelyen minden háznak világos oka van."],
    ["Akár 30 m²-es otthon is szóba jöhet", "A saját ház nem kötelezően nagy. Pályakezdőknek, egyedülállóknak, pároknak vagy könnyebben fenntartható otthont keresőknek a kis alapterület is lehet teljes értékű, szerethető megoldás."],
    ["Minden élethelyzetre külön megoldást keresünk", "Első otthon, növekvő család, otthoni munka, két generáció vagy későbbi bővítés: nem ugyanazt a házat ajánljuk mindenkinek. A jó választás a hétköznapjaitokból következik."],
    ["Több mint 70 felépített ház tapasztalata", "Egy alaprajz képernyőn sok mindent ígérhet. Az elkészült házaknál viszont már látszik, hogyan működik a tér, mennyire követhető a kivitelezés, és milyen kérdéseket érdemes még a döntés előtt feltenni."],
    ["Összeszokott, saját fizikai állomány", "A jó tervet a helyszínen is következetesen kell megvalósítani. A régóta együtt dolgozó csapat, az ismert munkarend és a dokumentált ellenőrzés csökkenti annak kockázatát, hogy minden munkafázisnál újra kelljen kezdeni az egyeztetést."],
    ["Standardizált, informatikailag támogatott folyamat", "A típusterv, az előre rendezett döntések és a követhető feladatok nem személytelenné teszik az építkezést. Éppen ellenkezőleg: kevesebb idő megy el keresgélésre, félreértésre és újratervezésre."],
    ["Erős vállalások, átlátható feltételek", "Az ár, a határidő és a műszaki tartalom csak együtt értelmezhető. A döntés előtt megmutatjuk, mi rögzített, mi függ a telektől, hol van még választásotok, és mely kérdéshez kell további vizsgálat."],
    ["Egy építkezésnek nem kell bonyolultnak lennie", "A házválasztás, a tervezés, a finanszírozási segítség és a generálkivitelezés nem négy külön történet. Ha a feladatok sorrendje és felelőse az elején látszik, nektek nem kell minden szakág között közvetítenetek."],
    ["Házak, amelyekhez egy fizetés is elég lehet", "A megfizethetőség nem pusztán alacsonyabb induló árat jelent. A jól kihasznált alapterület, a tervezhető műszaki tartalom, a fenntartható üzemeltetés és a teljes projektkeret együtt mutatja meg, melyik otthon vállalható hosszú távon."],
  ];
  return `<section class="approved-proof" aria-labelledby="approved-proof-title"><header><p class="eyebrow">Miért könnyebb így választani?</p><h2 id="approved-proof-title">Nem több alaprajz kell. Hanem néhány valóban jó lehetőség.</h2><p>Az Otthonválasztó a jóváhagyott Everyday Homes-állításokra épül: széles kínálatból személyes szűkítés, érthető összehasonlítás és olyan következő lépés, amelyet már nem találomra tesztek meg.</p></header><div>${proofs.map(([title, copy], index) => `<article><span>${String(index + 1).padStart(2, "0")}</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(copy)}</p></article>`).join("")}</div><footer><div><strong>Van már telketek?</strong><span>Megnézzük, milyen otthon illik rá.</span><a class="button" href="${href('/mi-intezzuk/telek-ellenorzes')}" data-route>Telekellenőrzést kérek</a></div><div><strong>Előbb a keretet tisztáznátok?</strong><span>Mutatunk egy biztonságos kiindulópontot.</span><a class="button button--secondary" href="${href('/keretbol-otthon')}" data-route>Előbb számolok</a></div><div><strong>Inkább beszélnétek valakivel?</strong><span>Személyes tanácsadónk segít leszűkíteni a lehetőségeket.</span><a class="button" href="${href('/kezdjuk-egyutt')}" data-route>Beszéljünk róla</a></div></footer></section>`;
}

function conversionEvidenceMarkup(path) {
  if (path === "/") return `<section class="home-evidence"><header><p class="eyebrow">Hétköznapi árak. Csodálatos otthonok.</p><h2>Ne egy építkezést próbáljatok túlélni. Egy otthont válasszatok magatoknak.</h2><p>Az Everyday Homes azért dolgozik, hogy a családi ház ne távoli, bonyolult vagy kiszámíthatatlan terv legyen. A típustervek, a személyes tanácsadás és az előre rendezett kivitelezési folyamat ugyanazt a célt szolgálja: gyorsabban lássátok, mi illik hozzátok, mit tudtok biztonságosan vállalni, és mi történik a következő lépésben.</p></header><div><article><b>01</b><h3>Nem négyzetmétert adunk el</h3><p>Nektek nem szakági rövidítésekre és végeláthatatlan választékra van szükségetek, hanem olyan otthonra, amelyben jó reggel elindulni és jó este hazatérni. Ezért az első kérdésünk nem az, milyen falazatot választanátok, hanem az, hogyan éltek most, és min szeretnétek változtatni.</p></article><article><b>02</b><h3>A nagy választékból rövid lista lesz</h3><p>Több mint 300 típusterv között könnyű elveszni. Személyes tanácsadónk a család helyzete, a telek, a vállalható keret, a szobák és a költözési cél alapján néhány valóban indokolható lehetőséget mutat. Így nem ötven alaprajzot kell összehasonlítanotok, hanem három jó választást.</p></article><article><b>03</b><h3>A megfizethetőség a teljes képet jelenti</h3><p>Egy kedvezőnek tűnő házár önmagában kevés. Meg kell férnie mellette a telek előkészítésének, a külső munkáknak, a finanszírozásnak és az életeteknek is. A ház méretét, műszaki tartalmát és fenntartását együtt nézzük, mert csak így derül ki, melyik megoldás marad hosszú távon is kényelmes.</p></article><article><b>04</b><h3>Előre látható út a beköltözésig</h3><p>A standardizált, informatikailag támogatott folyamat nem személytelenséget jelent. Azt jelenti, hogy a feladatoknak sorrendjük, felelősük és ellenőrizhető állapotuk van. Nektek nem kell a résztvevők között közvetítenetek: mindig tudjátok, hol tart a közös munka.</p></article><article><b>05</b><h3>Tapasztalat, amely a helyszínen is számít</h3><p>Több mint 70 elkészült ház, saját eszközök és régóta együtt dolgozó fizikai állomány áll a tervek mögött. Ez annak alapja, hogy a tervből következetesen megépített otthon legyen, a részletek pedig ne minden munkafázisnál kezdődjenek elölről.</p></article><article><b>06</b><h3>Egyszerű szerződés, érthető vállalások</h3><p>Az ár, a határidő és a műszaki tartalom csak együtt értelmezhető. Még a döntés előtt megmutatjuk, mi rögzíthető, mi függ a telektől, mi választható, és mi nincs benne az adott összegben. A cél egy olyan megállapodás, amelyhez később is vissza lehet nyúlni.</p></article></div><footer><strong>Kezdjük azzal, ami most a legfontosabb nektek.</strong><div class="actions"><a class="button" href="${href('/otthonvalaszto')}" data-route>Otthont választok</a><a class="button button--secondary" href="${href('/szamolok/teljes-projektkeret')}" data-route>Előbb számolok</a><a class="text-link" href="${href('/kezdjuk-egyutt')}" data-route>Beszéljünk</a></div></footer></section>`;
  if (path === "/keretbol-otthon") return `<section class="budget-confidence"><header><p class="eyebrow">A teljes projekt legyen vállalható</p><h2>A jó keret megmutatja, hol marad biztonságban a család.</h2><p>Nem abból indulunk ki, mekkora hitelt lehet elméletben felvenni. Előbb különválasztjuk a házat, a helyszínhez kötődő munkákat, a finanszírozás költségeit és a megőrzendő tartalékot. Csak ezután érdemes házméretet vagy műszaki csomagot választani.</p></header><div class="budget-confidence__path"><article><b>1</b><div><h3>A biztos adatokkal kezdünk</h3><p>A rendelkezésre álló saját forrás, a vállalható havi teher, a telek megléte és a kívánt költözési idő adja a kiindulópontot. A bizonytalan bevételt, a még el nem adott ingatlan teljes várható árát vagy egy nem igazolt támogatást nem kezelünk készpénzként. Így a terv már az első számításnál a valós helyzetetekhez igazodik.</p></div></article><article><b>2</b><div><h3>A ház mellé odatesszük a helyszínt</h3><p>A típusterv ára az adott műszaki tartalomra, sík telekre és normál talajviszonyokra számított alapozásra vonatkozik. A tereprendezés, közműkapcsolatok, kerítés, térburkolat, kert és egyedi telekadottság külön tétel lehet. Nem rejtjük őket későbbi apró betűbe: már a kerettervezésnél saját soron jelennek meg.</p></div></article><article><b>3</b><div><h3>Külön helyet kap a tartalék</h3><p>A biztonsági tartalék nem a kivitelezőnek félretett, biztosan elkölthető pénz. A család védelmét szolgálja arra az esetre, ha a telekről új adat derül ki vagy a költözés körül jelentkezik váratlan kiadás. Ha a ház csak a teljes tartalék felélésével fér bele, kisebb vagy más műszaki megoldást keresünk.</p></div></article><article><b>4</b><div><h3>Azonos feltételeket hasonlítunk</h3><p>Két ajánlat csak akkor vethető össze, ha ugyanazt a készültségi szintet, alapozási feltételt, gépészetet, burkolati keretet és külső munkát tartalmazza. Az összehasonlítás ezért nem egyetlen végösszegre épül. Soronként láthatóvá tesszük, mi van benne, mi választható és mi igényel további vizsgálatot.</p></div></article></div><aside><div><small>Ha a keret feszes</small><strong>Kevesebb alapterület, jobb kihasználás</strong><p>A jól bútorozható alaprajz gyakran többet ad néhány rosszul használható plusz négyzetméternél. A kisebb ház az építés és a fenntartás költségét is mérsékelheti.</p></div><div><small>Ha az idő a fontos</small><strong>Változtatás nélküli típusterv</strong><p>A típusterv tervezése akkor része az árnak, ha nem kértek módosítást. Ezzel használható ki legjobban a standardizált megoldások ár- és időelőnye.</p></div><div><small>Ha a hosszú táv számít</small><strong>Fenntartás a döntés részeként</strong><p>A gépészet, a hőszigetelés és a ház mérete nemcsak a kivitelezési árat alakítja. Megmutatjuk, hogyan hathatnak a későbbi energia- és karbantartási költségekre.</p></div></aside><footer><h3>Mekkora otthon fér bele úgy, hogy az életetekre is maradjon?</h3><div class="actions"><a class="button" href="${href('/szamolok/teljes-projektkeret')}" data-route>Kiszámolom</a><a class="button button--secondary" href="${href('/kezdjuk-egyutt')}" data-route>Átbeszéljük</a><a class="text-link" href="${href('/otthonvalaszto')}" data-route>Házat választok</a></div></footer></section>`;
  if (path === "/kozelrol") return `<section class="proof-visit"><p class="eyebrow">Nézzetek a szép képek mögé</p><h2>Egy elkészült otthonban öt perc alatt többet tudhattok meg, mint száz látványtervből.</h2><p>Referencia-látogatáskor ne csak azt nézzétek, tetszik-e a ház. Figyeljétek meg, hogyan érkezik meg a fény a nappaliba, elfér-e két ember a közlekedőkben, kézre áll-e a konyha, van-e valódi helye a kabátoknak, a mosásnak és a mindennapi rendetlenségnek. Kérdezzetek rá arra is, mi változott az eredeti tervhez képest, hogyan lehetett követni a kivitelezést, és melyik döntést hozná meg másképp a család.</p><p>Az Everyday Homes bemutatott történetei nem díszletként szolgálnak. Az a céljuk, hogy ellenőrizhető tapasztalatot adjanak a döntésetekhez: teljes házképpel, megnevezett alaprajzzal, valódi használati helyzetekkel és olyan részletekkel, amelyekből kiderül, miért működik az adott otthon. Ha szeretnétek, személyesen is megmutatunk egy elkészült vagy épülő házat, és mérnökünknek a helyszínen tehetitek fel a szakmai kérdéseiteket.</p><div class="actions"><a class="button" href="${href('/kozelrol/elkeszult-otthonok')}" data-route>Elkészült otthonokat nézek</a><a class="button button--secondary" href="${href('/kezdjuk-egyutt')}" data-route>Helyszíni látogatást kérek</a></div></section>`;
  if (path === "/elso-lepesek") return `<section class="first-step-pulse"><strong>Ha ma csak három dolgot tisztáztok:</strong><span>mekkora otthon szolgálja a hétköznapjaitokat,</span><span>mekkora teljes projektkeret marad biztonságos,</span><span>és mit enged a telek.</span><a class="button" href="${href('/kezdjuk-egyutt')}" data-route>Segítséget kérek az első lépéshez</a></section>`;
  return "";
}

async function renderRichSourcePage(path) {
  const config = RICH_SOURCE_MAP[path];
  if (!config) return false;
  const response = await fetch(`${BASE}/sources/drive/${config.file}`);
  if (!response.ok) throw new Error(`A forrásszöveg nem tölthető be: ${config.file}`);
  const parsed = parsePublicSource(await response.text());
  const extensions = globalThis.RICH_CONTENT_EXTENSIONS?.[path] || [];
  parsed.sections.push(...extensions.map(section => ({
    title: section.title,
    blocks: section.blocks.slice(),
  })));
  const canonical = pages[path];
  const intro = parsed.heroText.slice(0, config.introLimit || 3).join(" ");
  const faqCount = parsed.sections.reduce((sum, section) => sum + section.blocks.filter(line => line.endsWith("?")).length, 0);
  const bodyChars = parsed.sections.reduce((sum, section) => sum + section.title.length + section.blocks.join(" ").length, 0);
  const main = document.querySelector("main");
  document.title = `${canonical.eyebrow} | Everyday Homes`;
  main.innerHTML = `
    <article class="rich-page rich-page--${config.layout}" data-body-characters="${bodyChars}" data-faq-count="${faqCount}">
      <section class="rich-hero">
        <div class="rich-hero__image" style="background-image:url('${BASE}/assets/photos/${config.photo}')" role="img" aria-label="${escapeHtml(canonical.eyebrow)} – Everyday Homes élethelyzet"></div>
        <div class="rich-hero__copy"><span class="hero__tag">Otthon – egyszerűen.</span><p class="eyebrow">${escapeHtml(canonical.eyebrow)}</p><h1>${escapeHtml(parsed.title)}</h1><p class="lede">${escapeHtml(intro)}</p><div class="actions"><a class="button" href="${href(config.primary)}" data-route>${escapeHtml(canonical.primary?.[0] || "Megnézem a következő lépést")}</a><a class="button button--secondary" href="${href('/kezdjuk-egyutt')}" data-route>Személyes segítséget kérek</a><a class="text-link" href="${href('/szamolok/hazkoltseg')}" data-route>Mennyibe kerülhet a ház?</a></div></div>
      </section>
      <div class="trust-strip"><span>Több mint 300 típusterv</span><span>Személyes tanácsadás</span><span>Több mint 70 elkészült ház</span><span>Átlátható feltételek</span></div>
      ${diagramMarkup(config.layout, parsed.sections)}
      <div class="rich-sections">${parsed.sections.map(sectionMarkup).join("")}</div>
      ${approvedBrandProofMarkup(path)}
      ${conversionEvidenceMarkup(path)}
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
