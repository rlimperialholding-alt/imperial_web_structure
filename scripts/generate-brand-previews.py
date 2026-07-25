#!/usr/bin/env python3
"""Generate standalone previews from the approved Drive website specifications."""

from __future__ import annotations

import html
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

BRANDS = {
    "danish-fabrik": {
        "name": "Danish Fabrik",
        "source_id": "1VAs7ftaGrf8JcoUGnmLv8J0FslQFfDSW",
        "eyebrow": "Északi minőség · favázas otthonok",
        "headline": "Nem érdemes másból építeni.",
        "lead": "Favázas könnyűszerkezetes otthonok – gyorsan, természetesen, precízen.",
        "trust": ["Északi minőség", "4–5 hónapos építés", "Alacsony rezsi"],
        "primary": "#183b56",
        "accent": "#c85c5c",
        "surface": "#f5f2ea",
        "hero_from": "#d8e8e2",
        "hero_to": "#7a9e9f",
        "values": [
            ("Gyere haza végre", "Természetközeli terek, nyugodt anyagok és valódi hygge-életérzés."),
            ("Gyors építés", "Tervezés, üzemi gyártás, szállítás és szerelés egy követhető folyamatban."),
            ("Energiatudatos", "Rétegrend, nyílászárók és gépészet egymásra hangolt rendszerként."),
        ],
        "collections": ["Nordic", "Modern", "Classic", "Funky", "Medi", "Business", "Bold"],
        "journey": ["Tervezés", "Gyártás", "Szállítás", "Összeszerelés", "Kulcsátadás"],
        "cta": "Kérek favázas házajánlatot",
    },
    "casa-moderna": {
        "name": "Casa Moderna",
        "source_id": "11We-v4bq7dw_LSktJPxGNsd0oyf3yGD1",
        "eyebrow": "Limitált kollekció · privát konzultáció",
        "headline": "Prémium otthonok, prémium ügyfeleknek.",
        "lead": "Exkluzív design, kézzel válogatott anyagok és személyre szabott projektélmény.",
        "trust": ["Prémium tervezés", "Válogatott anyagok", "Limitált kollekció"],
        "primary": "#221d1a",
        "accent": "#b7895c",
        "surface": "#f4eee8",
        "hero_from": "#d9c0aa",
        "hero_to": "#594235",
        "values": [
            ("Építészeti koncepció", "A telekhez, panorámához és életstílushoz igazított egyedi kompozíció."),
            ("Interior Universe", "Konyha, fürdő, nappali és háló egységes anyag- és hangulatrendszerben."),
            ("Concierge megvalósítás", "Anyagválasztás, mesterek és döntési pontok személyes koordinációja."),
        ],
        "collections": ["Prémium Villák", "Mediterrán Modern", "Minimal", "Art Deco", "Lakeside", "Urban Luxury"],
        "journey": ["Privát brief", "Koncepció", "Anyagkuráció", "Megvalósítás", "Átadás"],
        "cta": "Privát konzultációt kérek",
    },
    "everyday-homes": {
        "name": "Everyday Homes",
        "source_id": "1VZmftOSSK1ZZs1jePp7ZJKxErvELKKCF",
        "eyebrow": "Praktikus házak · érthető döntések",
        "headline": "Otthonok mindenkinek.",
        "lead": "Megfizethető, praktikus és energiatakarékos házak a mindennapokhoz.",
        "trust": ["Kedvező árak", "Okos alaprajzok", "Gyors kivitelezés"],
        "primary": "#173149",
        "accent": "#e19a3f",
        "surface": "#fff7e9",
        "hero_from": "#f8d99e",
        "hero_to": "#84aa8c",
        "values": [
            ("Megfizethető", "Alacsonyabb belépő ár és előre átlátható fenntartási szempontok."),
            ("Praktikus", "Jól bútorozható helyiségek és a családi rutinhoz igazított alaprajzok."),
            ("Gyors", "Kevesebb helyszíni bizonytalanság, rövidebb és követhetőbb építési idő."),
        ],
        "collections": ["Kis házak", "Családi házak", "Nagyobb házak", "Nyaralók", "Befektetési házak"],
        "journey": ["Igényfelmérés", "Házválasztás", "Pontosítás", "Kivitelezés", "Költözés"],
        "cta": "Kérek érthető ajánlatot",
    },
    "property-360": {
        "name": "Property 360",
        "source_id": "1bVAjyyycFcUl1qyGwU_XWWiti3rI1Hur",
        "eyebrow": "Telektől a kulcsátadásig",
        "headline": "Egy kézben a teljes projekt.",
        "lead": "Telekkeresés, tervezés, kivitelezés, belsőépítészet és kert egyetlen projektfolyamatban.",
        "trust": ["Teljes projektmenedzsment", "Telek + ház", "Rögzített döntési pontok"],
        "primary": "#102c3c",
        "accent": "#4e95ad",
        "surface": "#edf6f8",
        "hero_from": "#b9dce4",
        "hero_to": "#376979",
        "values": [
            ("Telek és beépíthetőség", "Telekkeresés, HÉSZ-ellenőrzés és a megvalósíthatóság korai vizsgálata."),
            ("Tervezés és kivitelezés", "Építész, szakágak és generálkivitelezés egy közös felelősségi térképen."),
            ("Költözésre kész átadás", "Belsőépítészet, kert, takarítás és utógondozás a projekt részeként."),
        ],
        "collections": ["Nordic", "Resort", "Minimal", "Jefferson", "Mediterranean", "Alpine", "Wellness Home", "Smart"],
        "journey": ["Telek", "Tervezés", "Engedélyezés", "Kivitelezés", "Berendezés", "Átadás"],
        "cta": "360° projektkonzultációt kérek",
    },
    "baufreund": {
        "name": "BauFreund",
        "source_id": "11jIKIOsmT6HAfWwm40OnSNoZW1Rztv7_",
        "eyebrow": "Családbarát tervezés · közvetlen csapat",
        "headline": "Otthon mindenkinek.",
        "lead": "Segítünk megtalálni és megépíteni első vagy következő családi otthonát.",
        "trust": ["Közvetlen csapat", "Elérhető árak", "Bővíthető alaprajzok"],
        "primary": "#213547",
        "accent": "#d4a72c",
        "surface": "#fff9e8",
        "hero_from": "#f5dfa2",
        "hero_to": "#88a87e",
        "values": [
            ("Egyszerű döntés", "Segítőkész szakértők és minden lépésnél érthető következő teendő."),
            ("Elérhető árak", "Összehasonlítható készültségi szintek, világos kizárások és tartalmak."),
            ("Családbarát", "Rugalmas alaprajzok, bővíthetőség és a változó élethelyzetek figyelembevétele."),
        ],
        "collections": ["Első otthonok", "Kis családi házak", "Nagyobb családi házak", "Praktikus házak", "Akciós ajánlatok"],
        "journey": ["Beszélgetés", "Házválasztás", "Finanszírozás", "Szerződés", "Kivitelezés", "Utógondozás"],
        "cta": "Beszélgessünk az otthonról",
    },
    "red-property": {
        "name": "RED Property",
        "source_id": "1o0sW9QmuVu6Hwl-B4StjRwOZyQkQtl28",
        "eyebrow": "Gyors otthon · rögzített tartalom",
        "headline": "Csodaszép házak gyorsan és elérhető áron.",
        "lead": "Standardizált tervek, hatékony kivitelezés és előre tisztázott műszaki tartalom.",
        "trust": ["Kedvező ár-érték", "3–4 hónapos célidő", "Letisztult alaprajzok"],
        "primary": "#241d22",
        "accent": "#d52f3e",
        "surface": "#fff0f1",
        "hero_from": "#f0a2aa",
        "hero_to": "#8a1723",
        "values": [
            ("Hatékony ár", "Ismételhető tervek és optimalizált anyaghasználat a kiszámíthatóbb költségért."),
            ("Gyors átadás", "Korán rögzített választások és rövidebb döntési ciklusok."),
            ("Biztonsági kapuk", "Ár, határidő és műszaki tartalom csak jóváhagyott feltételekkel válik ígéretté."),
        ],
        "collections": ["Olcsó házak", "Gyorsan építhető", "Kis család", "Nagy család", "Befektetési házak"],
        "journey": ["Modellválasztás", "Műszaki csomag", "Ajánlat", "Kivitelezés", "Átadás"],
        "cta": "Kérek feltételes ajánlatot",
    },
    "timberhaus": {
        "name": "TimberHaus",
        "source_id": "1ue19H61K7gNKdynpKovTN7ucsyK2qBBz",
        "eyebrow": "Smart & Efficient · favázas rendszer",
        "headline": "Fából mindent lehet.",
        "lead": "Természetes alapanyagok, intelligens megoldások és teljes döntéstámogatás.",
        "trust": ["Fenntartható faanyag", "Gyors építés", "Magas energiahatékonyság"],
        "primary": "#24352f",
        "accent": "#6f8e5e",
        "surface": "#eff3e9",
        "hero_from": "#bdd0a8",
        "hero_to": "#435b43",
        "values": [
            ("Smart & Efficient", "Rétegrend, energetika és okos funkciók egy közös teljesítményrendszerben."),
            ("Telekalkalmasság", "HÉSZ, geodézia, talaj és beépíthetőség ellenőrzése a házválasztás előtt."),
            ("Döntési központ", "Konfigurátor, árközpont, finanszírozás és ütemezés egy áttekinthető folyamatban."),
        ],
        "collections": ["Smart & Efficient", "Affordable Premium", "Optimized Living", "Smart Family Homes", "High-Value Homes"],
        "journey": ["Telekvizsgálat", "Konfiguráció", "Árközpont", "Finanszírozás", "Kivitelezés", "Energetikai kontroll"],
        "cta": "Belépek a döntési központba",
    },
}


CSS = """@font-face{font-family:InterPreview;src:url("./fonts/inter-latin.woff2") format("woff2");font-style:normal;font-weight:100 900;font-display:swap}
:root{font-family:InterPreview,system-ui,sans-serif;color:var(--ink);background:var(--surface);font-synthesis:none}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#fff;color:var(--ink);line-height:1.6}a{color:inherit}
.container{width:min(1180px,calc(100% - 2rem));margin:auto}.site-header{position:sticky;top:0;z-index:20;border-bottom:1px solid color-mix(in srgb,var(--ink) 12%,transparent);background:color-mix(in srgb,#fff 92%,transparent);backdrop-filter:blur(16px)}
.nav{min-height:76px;display:flex;align-items:center;gap:2rem}.brand{display:flex;align-items:center;gap:.75rem;font-weight:900;text-decoration:none;letter-spacing:-.03em}.brand img{width:38px;height:38px}.nav-links{margin-left:auto;display:flex;gap:1.4rem}.nav-links a{text-decoration:none;font-size:.92rem;font-weight:750}.menu{display:none;margin-left:auto;border:1px solid #ccd4d7;border-radius:999px;padding:.55rem .8rem;background:#fff;font:inherit;font-weight:800}
.hero{overflow:hidden;background:linear-gradient(145deg,var(--surface),#fff 58%);padding:clamp(4rem,9vw,8.5rem) 0}.hero-grid{display:grid;grid-template-columns:1.02fr .98fr;gap:clamp(2rem,6vw,6rem);align-items:center}.eyebrow{text-transform:uppercase;letter-spacing:.14em;font-size:.75rem;font-weight:900;color:var(--accent)}h1{max-width:12ch;margin:.7rem 0 1.3rem;font-size:clamp(3rem,7vw,6.5rem);line-height:.92;letter-spacing:-.065em}h2{margin:.6rem 0 1.2rem;font-size:clamp(2rem,4vw,3.8rem);line-height:1.02;letter-spacing:-.045em}.lead{max-width:44rem;font-size:clamp(1.08rem,2vw,1.35rem);color:color-mix(in srgb,var(--ink) 70%,#fff)}.actions{display:flex;flex-wrap:wrap;gap:.75rem;margin-top:2rem}.button{display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:.75rem 1.2rem;border:1px solid var(--primary);border-radius:999px;background:var(--primary);color:#fff;font-weight:850;text-decoration:none}.button.secondary{background:transparent;color:var(--primary)}
.hero-art{position:relative}.hero-art>img{display:block;width:100%;aspect-ratio:4/3;border-radius:32px;box-shadow:0 30px 70px color-mix(in srgb,var(--primary) 24%,transparent);object-fit:cover}.trust{display:flex;flex-wrap:wrap;gap:.55rem;margin-top:1.5rem}.trust span{padding:.45rem .7rem;border:1px solid color-mix(in srgb,var(--ink) 15%,transparent);border-radius:999px;background:#fff;font-size:.78rem;font-weight:800}
section{padding:clamp(4rem,8vw,7rem) 0}.intro{max-width:720px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-top:2.5rem}.card{min-height:260px;padding:1.6rem;border:1px solid color-mix(in srgb,var(--ink) 12%,transparent);border-radius:24px;background:#fff;box-shadow:0 12px 40px color-mix(in srgb,var(--ink) 8%,transparent)}.card b{display:block;color:var(--accent);font-size:.78rem;letter-spacing:.12em;text-transform:uppercase}.card h3{font-size:1.35rem;line-height:1.15}.soft{background:var(--surface)}.chips{display:flex;flex-wrap:wrap;gap:.75rem;margin-top:2rem}.chip{padding:1rem 1.2rem;border-radius:18px;background:#fff;border:1px solid color-mix(in srgb,var(--ink) 12%,transparent);font-weight:850}
.journey{counter-reset:step;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.8rem;margin-top:2.5rem}.journey div{counter-increment:step;padding:1.25rem;border-left:3px solid var(--accent);background:var(--surface);font-weight:850}.journey div:before{content:"0" counter(step);display:block;margin-bottom:.55rem;color:var(--accent);font-size:.76rem;letter-spacing:.12em}
.cta{border-radius:32px;background:var(--primary);color:#fff;padding:clamp(2rem,6vw,5rem)}.cta h2{max-width:16ch}.cta p{max-width:44rem;color:color-mix(in srgb,#fff 75%,transparent)}form{display:grid;grid-template-columns:1fr 1fr;gap:.8rem;margin-top:2rem}label{font-size:.8rem;font-weight:800}input,select,textarea{width:100%;margin-top:.3rem;border:1px solid color-mix(in srgb,#fff 35%,transparent);border-radius:12px;padding:.85rem;background:#fff;color:var(--ink);font:inherit}textarea{min-height:115px;resize:vertical}.full{grid-column:1/-1}.submit{border:0;background:var(--accent);cursor:pointer}.form-note{font-size:.76rem;color:color-mix(in srgb,#fff 72%,transparent)}
footer{padding:2rem 0;background:color-mix(in srgb,var(--primary) 92%,#000);color:#fff}.footer-row{display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap;font-size:.82rem}
@media(max-width:820px){.hero-grid{grid-template-columns:1fr}.grid{grid-template-columns:1fr}.nav-links{display:none;position:absolute;top:76px;left:0;right:0;padding:1rem;background:#fff;border-bottom:1px solid #ddd;flex-direction:column}.nav-links.is-open{display:flex}.menu{display:block}form{grid-template-columns:1fr}.full{grid-column:auto}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
"""


JS = """document.addEventListener("DOMContentLoaded",()=>{document.querySelectorAll("[data-year]").forEach((node)=>{node.textContent=String(new Date().getFullYear())});const menu=document.querySelector("[data-menu]");const links=document.querySelector("[data-nav]");menu?.addEventListener("click",()=>{const open=links.classList.toggle("is-open");menu.setAttribute("aria-expanded",String(open))});document.querySelectorAll("form").forEach((form)=>form.addEventListener("submit",(event)=>{event.preventDefault();const note=form.querySelector("[data-form-note]");if(note)note.textContent="Tesztüzem: az űrlap nem továbbít adatot."}))});
"""


def cards(values: list[tuple[str, str]]) -> str:
    return "\n".join(
        f'<article class="card"><b>0{index}</b><h3>{html.escape(title)}</h3>'
        f"<p>{html.escape(text)}</p></article>"
        for index, (title, text) in enumerate(values, 1)
    )


def render_page(slug: str, data: dict) -> str:
    trusts = "".join(f"<span>{html.escape(item)}</span>" for item in data["trust"])
    collections = "".join(
        f'<div class="chip">{html.escape(item)}</div>' for item in data["collections"]
    )
    journey = "".join(f"<div>{html.escape(item)}</div>" for item in data["journey"])
    name = html.escape(data["name"])
    return f"""<!doctype html>
<html lang="hu" style="--primary:{data['primary']};--accent:{data['accent']};--surface:{data['surface']};--ink:{data['primary']}">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="robots" content="noindex,nofollow">
    <meta name="description" content="{html.escape(data['lead'])}">
    <title>{name} · tesztüzemi weboldal</title>
    <link rel="icon" href="/site-preview/{slug}/assets/icons/mark.svg" type="image/svg+xml">
    <link rel="stylesheet" href="/site-preview/{slug}/assets/site.css">
    <link rel="stylesheet" href="/site-preview/{slug}/assets/platform/review-bridge.css">
    <script src="/site-preview/{slug}/assets/site.js" defer></script>
    <script src="/site-preview/{slug}/assets/platform/review-bridge.js" defer></script>
  </head>
  <body data-source-id="{data['source_id']}">
    <header class="site-header">
      <nav class="container nav" aria-label="Fő navigáció">
        <a class="brand" href="#top"><img src="/site-preview/{slug}/assets/icons/mark.svg" alt=""><span>{name}</span></a>
        <button class="menu" type="button" data-menu aria-expanded="false">Menü</button>
        <div class="nav-links" data-nav>
          <a href="#miert">Miért {name}?</a><a href="#kollekciok">Kollekciók</a>
          <a href="#folyamat">Folyamat</a><a href="#kapcsolat">Kapcsolat</a>
        </div>
      </nav>
    </header>
    <main id="top">
      <section class="hero">
        <div class="container hero-grid">
          <div>
            <div class="eyebrow">{html.escape(data['eyebrow'])}</div>
            <h1>{html.escape(data['headline'])}</h1>
            <p class="lead">{html.escape(data['lead'])}</p>
            <div class="actions"><a class="button" href="#kollekciok">Felfedezem</a><a class="button secondary" href="#kapcsolat">{html.escape(data['cta'])}</a></div>
            <div class="trust">{trusts}</div>
          </div>
          <figure class="hero-art"><img src="/site-preview/{slug}/assets/images/hero.svg" alt="{name} építészeti látvány"></figure>
        </div>
      </section>
      <section id="miert">
        <div class="container"><div class="intro"><div class="eyebrow">Márkaspecifikus ajánlat</div><h2>A döntéshez szükséges lényeg, egy helyen.</h2><p class="lead">A Drive-ban jóváhagyott weboldali specifikáció alapján összeállított, önállóan tesztelhető képernyő.</p></div><div class="grid">{cards(data['values'])}</div></div>
      </section>
      <section class="soft" id="kollekciok">
        <div class="container"><div class="eyebrow">Választható irányok</div><h2>Találja meg a saját élethelyzetéhez illő megoldást.</h2><div class="chips">{collections}</div></div>
      </section>
      <section id="folyamat">
        <div class="container"><div class="eyebrow">Átlátható folyamat</div><h2>A briefből dokumentált átadás.</h2><div class="journey">{journey}</div></div>
      </section>
      <section id="kapcsolat">
        <div class="container"><div class="cta"><div class="eyebrow">Következő lépés</div><h2>{html.escape(data['cta'])}</h2><p>Adja meg a projekt legfontosabb adatait. Tesztüzemben az űrlap semmilyen adatot nem továbbít.</p>
          <form><label>Név<input name="name" autocomplete="name"></label><label>E-mail<input type="email" name="email" autocomplete="email"></label><label>Projekt típusa<select name="project"><option>Új otthon</option><option>Telek + ház</option><option>Egyedi projekt</option></select></label><label>Tervezett helyszín<input name="location"></label><label class="full">Rövid projektbrief<textarea name="message"></textarea></label><div class="full actions"><button class="button submit" type="submit">{html.escape(data['cta'])}</button><span class="form-note" data-form-note>Tesztüzem · nincs adattovábbítás</span></div></form>
        </div></div>
      </section>
    </main>
    <footer><div class="container footer-row"><strong>{name}</strong><span>© <span data-year></span> · lokális, noindex tesztpreview</span></div></footer>
  </body>
</html>
"""


def hero_svg(data: dict) -> str:
    name = html.escape(data["name"])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 900" role="img" aria-labelledby="title desc">
<title id="title">{name} építészeti illusztráció</title><desc id="desc">Helyben tárolt, márkaspecifikus absztrakt házillusztráció.</desc>
<defs><linearGradient id="sky" x2="1" y2="1"><stop stop-color="{data['hero_from']}"/><stop offset="1" stop-color="{data['hero_to']}"/></linearGradient><linearGradient id="glass" x2="0" y2="1"><stop stop-color="#fff" stop-opacity=".88"/><stop offset="1" stop-color="#fff" stop-opacity=".34"/></linearGradient></defs>
<rect width="1200" height="900" fill="url(#sky)"/><circle cx="965" cy="165" r="88" fill="#fff" opacity=".54"/><path d="M0 680 230 520l210 86 260-218 500 318v194H0Z" fill="{data['primary']}" opacity=".18"/>
<path d="M165 705V454l328-194 319 194v251Z" fill="#f8f5ef"/><path d="m126 470 367-226 357 226-38 54-319-190-328 190Z" fill="{data['primary']}"/>
<rect x="247" y="475" width="176" height="230" rx="3" fill="url(#glass)"/><rect x="545" y="443" width="176" height="262" rx="3" fill="url(#glass)"/><rect x="739" y="536" width="73" height="169" fill="{data['accent']}"/>
<path d="M0 706h1200v194H0Z" fill="{data['surface']}"/><path d="M80 770c210-74 358 74 566-4s318-24 474 26" fill="none" stroke="{data['accent']}" stroke-width="16" stroke-linecap="round" opacity=".55"/>
</svg>"""


def mark_svg(data: dict) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="18" fill="{data['primary']}"/><path d="M13 34 32 18l19 16v17H38V38H26v13H13Z" fill="{data['surface']}"/><path d="m32 18 19 16" fill="none" stroke="{data['accent']}" stroke-width="5" stroke-linecap="round"/></svg>"""


def main() -> None:
    for slug, data in BRANDS.items():
        site = ROOT / "sites" / slug
        assets = site / "assets"
        (assets / "images").mkdir(parents=True, exist_ok=True)
        (assets / "icons").mkdir(parents=True, exist_ok=True)
        (assets / "fonts").mkdir(parents=True, exist_ok=True)
        (site / "index.html").write_text(render_page(slug, data), encoding="utf-8")
        (assets / "site.css").write_text(CSS, encoding="utf-8")
        (assets / "site.js").write_text(JS, encoding="utf-8")
        (assets / "images" / "hero.svg").write_text(hero_svg(data), encoding="utf-8")
        (assets / "icons" / "mark.svg").write_text(mark_svg(data), encoding="utf-8")
        print(f"generated {slug}")


if __name__ == "__main__":
    main()
