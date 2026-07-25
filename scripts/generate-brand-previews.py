#!/usr/bin/env python3
"""Build source-aligned, brand-specific previews from the approved Drive masters.

The Drive markdown files contain several separately specified pages.  Earlier
versions collapsed each file into one generic homepage.  This generator keeps
every H2 page as its own preview and gives page types and brands distinct
composition, copy, navigation and visual assets.
"""

from __future__ import annotations

import hashlib
import html
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FONT_SOURCE = ROOT / "sites" / "danish-fabrik" / "assets" / "fonts" / "inter-latin.woff2"


@dataclass(frozen=True)
class Brand:
    key: str
    name: str
    source_id: str
    guide_id: str
    tagline: str
    hero: str
    positioning: str
    primary_cta: str
    secondary_cta: str
    primary: str
    accent: str
    secondary: str
    surface: str
    ink: str
    display_font: str
    body_font: str
    character: str
    output_subdir: str = ""


BRANDS = (
    Brand(
        "imperial",
        "Imperial Holding",
        "1FS_rHRKBarfzOWCzMT56e0QSwnoIRbuk",
        "1VkZsQzZ2wSXiAAwCNZi71EdVBfkkfRM2MCpuUCAFuio",
        "Csodálatos otthonok megfizethető áron.",
        "Nyugodt építkezés. Szabad választás.",
        "Csoportszintű biztonság, teljes választék és egy kézben vezetett otthonteremtés.",
        "Kérek mérnöki konzultációt",
        "Megnézem a hozzám illő házakat",
        "#152A3A",
        "#D4A54B",
        "#607D8B",
        "#F4F1EA",
        "#17232C",
        "Playfair Display",
        "Inter",
        "institutional",
        "consumer",
    ),
    Brand(
        "bautica",
        "Bautica",
        "11p3lBYwZvoiWK2kAHNnrJex_aKwQYImE",
        "1vnsM34aDMY7EDKlktzVPKEA3YdemgLqUYpEsHnH4y4I",
        "Értünk hozzá. Az építés tudománya.",
        "A tervtől az átadásig ugyanaz a mérnöki gondolkodás.",
        "Személyes mérnöki figyelem és végig követhető szakmai kontroll.",
        "Kérek helyszíni felmérést",
        "Küldd el a terved",
        "#173C57",
        "#F0B323",
        "#2D7A78",
        "#EEF4F5",
        "#13242D",
        "IBM Plex Sans",
        "Source Serif 4",
        "engineering",
        "consumer",
    ),
    Brand(
        "prefab",
        "Prefab",
        "1I4B8E3LfK2POc5yGmh9XD_ZO6GFaJZLW",
        "19YvNQlOHO0L0Aoy-cWtAEImo2cHST6kaEfxv_Yv6amc",
        "Építőipar 2.0. Nincsenek kérdőjelek. Betonbiztos építkezés.",
        "Nem kell elhinnie. Végig ellenőrizheti.",
        "Üzemi pontosságú, ellenőrizhető előregyártott masszívház-rendszer.",
        "Kérek tételes mérnöki ajánlatot",
        "Megnézem a gyártási folyamatot",
        "#202A33",
        "#00A7C4",
        "#B8C0C7",
        "#F1F4F5",
        "#111820",
        "Bahnschrift",
        "Inter",
        "industrial",
        "consumer",
    ),
    Brand(
        "danish-fabrik",
        "Danish Fabrik",
        "1VAs7ftaGrf8JcoUGnmLv8J0FslQFfDSW",
        "1_mXGnbwMH3jFl0LL6r_ADDSIXV1OomjH4kMDQp4eKK0",
        "Nem érdemes másból építeni.",
        "Gyere haza végre.",
        "Gyors, világos és energiahatékony skandináv favázas otthonteremtés.",
        "Kérek gyors költségbecslést",
        "Mutasd a Danish házakat",
        "#234B5C",
        "#F4C95D",
        "#7BB4A5",
        "#F6F4EE",
        "#1E3138",
        "Montserrat",
        "Lora",
        "hygge",
    ),
    Brand(
        "casa-moderna",
        "Casa Moderna",
        "11We-v4bq7dw_LSktJPxGNsd0oyf3yGD1",
        "10JPg2WoVMajzErERN8It-QNm3GDHJ36g6d2DHi_IKBc",
        "Nem csak megérkezik. Hazatér.",
        "Az otthon, amelyben minden részlet Önre válaszol.",
        "Prémium építészeti, enteriőr- és concierge projektélmény.",
        "Privát konzultációt kérek",
        "Megismerem a kollekciót",
        "#191816",
        "#B79A6B",
        "#8E8A82",
        "#F5F1E9",
        "#181715",
        "Cormorant Garamond",
        "Inter",
        "editorial",
    ),
    Brand(
        "everyday-homes",
        "Everyday Homes",
        "1VZmftOSSK1ZZs1jePp7ZJKxErvELKKCF",
        "19DL0k4Cl-HHHylak9xfc9C0QYDXDJd60_zRu06fCdS4",
        "Otthon – egyszerűen.",
        "Minden négyzetméternek dolga van.",
        "Praktikus, fenntartható, könnyen finanszírozható otthonok.",
        "Kérek egyszerű költségbecslést",
        "Megnézem a 80–100 m²-es otthonokat",
        "#376C76",
        "#F3B563",
        "#8EAD96",
        "#F6F3EA",
        "#25383C",
        "DM Sans",
        "Source Serif 4",
        "practical",
    ),
    Brand(
        "property-360",
        "Property360",
        "1bVAjyyycFcUl1qyGwU_XWWiti3rI1Hur",
        "14B2BEJNvNjUpgMpkBhuRVoEbQ3hn9oTsV5D6Ptc6WGU",
        "Kattints és költözz!",
        "Ön dönt. Mi mindent megszervezünk.",
        "Telektől a bútorozott átadásig egyetlen felelős projektút.",
        "Kérek teljes projekttervet",
        "Megnézem a 360° csomagot",
        "#123B4A",
        "#29C3B2",
        "#567780",
        "#EDF6F5",
        "#17272C",
        "Manrope",
        "Spectral",
        "service-map",
    ),
    Brand(
        "baufreund",
        "BauFreund",
        "11jIKIOsmT6HAfWwm40OnSNoZW1Rztv7_",
        "120-i4EHv_OrWXwSMUZad-gUFzXGby84UGfjXus8EyVo",
        "BauFreund. Az építő barát.",
        "Nem kell mindent tudnod az építkezésről. Nekünk igen.",
        "Közérthető, barátságos és független segítség az építési döntésekhez.",
        "Kérek egy őszinte költségbecslést",
        "Kérdezek az építő baráttól",
        "#245B49",
        "#F2A541",
        "#6FA88B",
        "#FFF7E8",
        "#1D3028",
        "Nunito Sans",
        "Merriweather",
        "friendly",
    ),
    Brand(
        "red-property",
        "RED Property",
        "1o0sW9QmuVu6Hwl-B4StjRwOZyQkQtl28",
        "192fP7Y6r_WT8za8cxv-DR81-pPuasuP2HrNdowNurQk",
        "Típusházak a leggyorsabban és a legjobb árakon!",
        "Ház. Ár. Határidő. Egy képernyőn.",
        "Ár- és időelső, gyorsan összehasonlítható típusterv-ajánlati rendszer.",
        "Kérem a gyorsajánlatot",
        "Mutasd az akciós házakat",
        "#C91F32",
        "#FFD400",
        "#222222",
        "#F7F7F7",
        "#141414",
        "Archivo Black",
        "Inter",
        "direct",
    ),
    Brand(
        "timberhaus",
        "TimberHaus",
        "1ue19H61K7gNKdynpKovTN7ucsyK2qBBz",
        "1Lkf65qqksfbMSeIBszXpYNhKCVe36Qu5cGzEoFcJPus",
        "Fából mindent lehet.",
        "Faépítés, minden rétegében átláthatóan.",
        "Nyitott, összehasonlítható és épületfizikailag transzparens faépítés.",
        "Kérek döntéstámogató konzultációt",
        "Összehasonlítom a rendszereket",
        "#244734",
        "#C98A4A",
        "#6C8B73",
        "#F3F0E7",
        "#1C2D23",
        "Roboto Slab",
        "Inter",
        "technical-natural",
    ),
)


CSS = r"""@font-face{font-family:BrandSans;src:url("./fonts/inter-latin.woff2") format("woff2");font-style:normal;font-weight:100 900;font-display:swap}
:root{--primary:#000;--accent:#999;--secondary:#777;--surface:#f4f4f4;--ink:#111;--display:BrandSans;--body:BrandSans;font-family:var(--body),system-ui,sans-serif;color:var(--ink);background:#fff;font-synthesis:none}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;line-height:1.62;background:#fff;color:var(--ink)}a{color:inherit}.shell{width:min(1240px,calc(100% - 2rem));margin:auto}
.skip{position:absolute;left:-9999px}.skip:focus{left:1rem;top:1rem;z-index:100;background:#fff;padding:.7rem}
.header{position:sticky;top:0;z-index:30;border-bottom:1px solid color-mix(in srgb,var(--ink) 14%,transparent);background:color-mix(in srgb,#fff 92%,transparent);backdrop-filter:blur(18px)}
.nav{display:flex;align-items:center;gap:1rem;min-height:76px}.brand{display:flex;align-items:center;gap:.7rem;text-decoration:none;font-family:var(--display);font-weight:900;letter-spacing:-.03em}.brand img{width:38px;height:38px}.navlinks{display:flex;gap:.25rem;margin-left:auto;overflow:auto;scrollbar-width:none}.navlinks a{white-space:nowrap;text-decoration:none;font-size:.8rem;font-weight:800;padding:.6rem .75rem;border-radius:999px}.navlinks a[aria-current=page],.navlinks a:hover{background:var(--surface)}.menu{display:none;margin-left:auto;border:1px solid #ccd4d7;border-radius:999px;padding:.55rem .8rem;background:#fff;font:inherit;font-weight:850}
.hero{position:relative;overflow:hidden;padding:clamp(4rem,9vw,8.5rem) 0;background:linear-gradient(145deg,var(--surface),#fff 65%)}.hero-grid{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(300px,.95fr);gap:clamp(2rem,6vw,7rem);align-items:center}.eyebrow{font-size:.74rem;font-weight:950;letter-spacing:.14em;text-transform:uppercase;color:var(--primary)}h1,h2,h3{font-family:var(--display),BrandSans,sans-serif}h1{max-width:14ch;margin:.6rem 0 1.2rem;font-size:clamp(2.8rem,6.4vw,6.7rem);line-height:.94;letter-spacing:-.055em}h2{margin:.5rem 0 1.2rem;font-size:clamp(2rem,4vw,4rem);line-height:1.02;letter-spacing:-.04em}h3{font-size:1.35rem;line-height:1.15}.lead{max-width:45rem;font-size:clamp(1.08rem,2vw,1.35rem);color:color-mix(in srgb,var(--ink) 72%,#fff)}.tagline{font-family:var(--display);font-weight:900;color:var(--primary)}
.hero-visual{position:relative}.hero-visual img{display:block;width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:clamp(4px,3vw,36px);box-shadow:0 28px 80px color-mix(in srgb,var(--primary) 25%,transparent)}.hero-visual::after{content:"";position:absolute;inset:auto -6% -8% 32%;height:38%;border-radius:999px;background:var(--accent);opacity:.18;filter:blur(28px)}
.actions{display:flex;flex-wrap:wrap;gap:.7rem;margin-top:2rem}.button{display:inline-flex;align-items:center;justify-content:center;min-height:52px;padding:.8rem 1.2rem;border:1px solid var(--primary);border-radius:999px;background:var(--primary);color:#fff;text-decoration:none;font-weight:900}.button.secondary{background:transparent;color:var(--primary)}.source-state{display:inline-flex;margin-top:1.2rem;padding:.4rem .65rem;border:1px solid color-mix(in srgb,var(--ink) 16%,transparent);border-radius:999px;font-size:.72rem;font-weight:800;background:#fff}
.section{padding:clamp(4rem,8vw,7rem) 0}.section.soft{background:var(--surface)}.intro{max-width:760px}.blocks{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:1rem;margin-top:2.5rem}.block{grid-column:span 4;min-height:250px;padding:clamp(1.3rem,2vw,2rem);border:1px solid color-mix(in srgb,var(--ink) 12%,transparent);border-radius:24px;background:#fff;box-shadow:0 14px 45px color-mix(in srgb,var(--ink) 8%,transparent)}.block:nth-child(5n+1){grid-column:span 7}.block:nth-child(5n+2){grid-column:span 5}.block-kicker{font-size:.72rem;letter-spacing:.13em;text-transform:uppercase;font-weight:950;color:var(--primary)}.block p{margin-bottom:0;color:color-mix(in srgb,var(--ink) 78%,#fff)}.chips{display:flex;flex-wrap:wrap;gap:.6rem;margin-top:1rem}.chip{padding:.5rem .75rem;background:var(--surface);border-radius:999px;font-size:.78rem;font-weight:850}
.layout-process .blocks{display:flex;flex-direction:column;max-width:920px;margin-left:auto}.layout-process .block{position:relative;min-height:0;margin-left:4rem;border-left:5px solid var(--accent)}.layout-process .block::before{content:attr(data-step);position:absolute;left:-4.6rem;top:1rem;width:42px;height:42px;display:grid;place-items:center;border-radius:50%;background:var(--primary);color:#fff;font-weight:950}
.layout-editorial .hero-grid{grid-template-columns:.8fr 1.2fr}.layout-editorial .hero-visual{order:-1}.layout-editorial .blocks{gap:2.5rem}.layout-editorial .block{grid-column:span 6;border:0;border-radius:0;box-shadow:none;border-top:1px solid var(--ink);padding:2rem 0}.layout-editorial .block:nth-child(3n){grid-column:3/span 8}
.layout-collection .blocks .block{grid-column:span 6;min-height:320px}.layout-collection .blocks .block:nth-child(3n){grid-column:span 12;display:grid;grid-template-columns:.4fr .6fr;gap:2rem;align-items:center;background:var(--primary);color:#fff}.layout-collection .blocks .block:nth-child(3n) p{color:#fff}
.layout-technical .hero{background:repeating-linear-gradient(90deg,var(--surface) 0,var(--surface) calc(8.333% - 1px),color-mix(in srgb,var(--primary) 11%,transparent) calc(8.333% - 1px),color-mix(in srgb,var(--primary) 11%,transparent) 8.333%)}.layout-technical .block{border-radius:6px;box-shadow:none;border-top:5px solid var(--primary)}.layout-technical .blocks .block:nth-child(even){transform:translateY(2.2rem)}
.layout-direct h1{text-transform:uppercase;max-width:11ch}.layout-direct .hero{border-bottom:14px solid var(--accent)}.layout-direct .block{border:3px solid var(--ink);border-radius:0;box-shadow:8px 8px 0 var(--accent)}.layout-direct .button{border-radius:4px;text-transform:uppercase}
.layout-friendly .block{border-radius:34px 10px 34px 10px}.layout-friendly .hero-visual img{border-radius:45% 12px 45% 12px}.layout-practical .blocks{grid-template-columns:repeat(2,1fr)}.layout-practical .block{grid-column:auto!important;min-height:220px}.layout-service-map .blocks{border-radius:50%;background:radial-gradient(circle,var(--surface),transparent 68%);padding:3rem}.layout-service-map .block{grid-column:span 6;min-height:210px}.layout-hygge .hero-visual img{border-radius:48% 48% 12px 12px}.layout-hygge .block{border:0;background:color-mix(in srgb,var(--surface) 72%,#fff);box-shadow:none}
.decision{padding:clamp(3rem,6vw,5rem) 0;background:var(--primary);color:#fff}.decision-grid{display:grid;grid-template-columns:1fr auto;gap:2rem;align-items:center}.decision .button{background:var(--accent);border-color:var(--accent);color:var(--ink)}.decision p{max-width:62rem}.footer{padding:3rem 0;background:var(--ink);color:#fff}.footer-grid{display:flex;align-items:flex-end;justify-content:space-between;gap:2rem}.footer p{max-width:60rem;margin:.4rem 0}.legal{font-size:.76rem;color:color-mix(in srgb,#fff 67%,transparent)}
@media(max-width:900px){.navlinks{display:none;position:absolute;top:76px;left:0;right:0;padding:1rem;background:#fff;border-bottom:1px solid #ddd;flex-direction:column}.navlinks.open{display:flex}.menu{display:block}.hero-grid,.layout-editorial .hero-grid{grid-template-columns:1fr}.layout-editorial .hero-visual{order:initial}.block,.block:nth-child(n),.layout-collection .blocks .block:nth-child(n),.layout-service-map .block{grid-column:span 12}.layout-technical .blocks .block:nth-child(even){transform:none}.decision-grid{grid-template-columns:1fr}.layout-service-map .blocks{padding:0;background:none}}
@media(max-width:620px){.shell{width:min(100% - 1.25rem,1240px)}.hero{padding:3rem 0}.hero-visual img{border-radius:16px}.blocks,.layout-practical .blocks{display:flex;flex-direction:column}.block{min-height:0}.layout-process .block{margin-left:3rem}.layout-process .block::before{left:-3.6rem}.layout-collection .blocks .block:nth-child(3n){display:block}.footer-grid{display:block}}
"""


JS = r"""const menu=document.querySelector('[data-menu]');const nav=document.querySelector('[data-nav]');
if(menu&&nav){menu.addEventListener('click',()=>{const open=nav.classList.toggle('open');menu.setAttribute('aria-expanded',String(open));});}
if(new URLSearchParams(location.search).get('review')==='1'){document.querySelectorAll('a[href]').forEach(a=>{const raw=a.getAttribute('href');if(!raw||raw.startsWith('#')||/^(mailto:|tel:|https?:)/.test(raw))return;const u=new URL(raw,location.href);u.searchParams.set('review','1');a.href=u.pathname+u.search+u.hash;});}
document.querySelectorAll('form[data-preview-form]').forEach(form=>form.addEventListener('submit',event=>{event.preventDefault();form.querySelector('[data-form-state]').textContent='Preview mód: az adatokat nem küldtük el.';}));"""


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    replacements = {
        "kezdolap": "index",
        "kapcsolat-ajanlatkeres": "kapcsolat",
        "kapcsolat": "kapcsolat",
    }
    return replacements.get(value, value)


def parse_pages(source: str) -> list[tuple[str, list[tuple[str, str]]]]:
    pages: list[tuple[str, list[tuple[str, str]]]] = []
    title: str | None = None
    blocks: list[tuple[str, str]] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        text = " ".join(item.strip() for item in paragraph if item.strip()).strip()
        if text:
            blocks.append(("Oldalösszefoglaló", text))
        paragraph = []

    def flush_page() -> None:
        if title is None:
            return
        flush_paragraph()
        pages.append((title, blocks.copy()))
        blocks.clear()

    for raw in source.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            flush_page()
            title = line[3:].strip()
            continue
        if title is None or not line:
            if paragraph:
                flush_paragraph()
            continue
        bullet = re.match(r"^-\s+\*\*(.+?)\*\*:\s*(.*)$", line)
        if bullet:
            flush_paragraph()
            blocks.append((bullet.group(1).strip(), bullet.group(2).strip()))
        elif line.startswith("- "):
            flush_paragraph()
            blocks.append(("Részlet", line[2:].strip()))
        else:
            paragraph.append(line)
    flush_page()
    return pages


def quoted_headline(text: str) -> str | None:
    match = re.search(r'[„"]([^”"]{8,120})[”"]', text)
    if match:
        return match.group(1).strip().rstrip(".") + "."
    return None


def page_layout(brand: Brand, title: str, index: int) -> str:
    text = title.lower()
    if any(word in text for word in ("folyamat", "journey", "hogyan épít")):
        return "process"
    if any(word in text for word in ("lista", "kollekció", "házaink", "akciós")):
        return "collection"
    if any(word in text for word in ("technológ", "döntési", "műszaki", "finansz")):
        return "technical"
    if any(word in text for word in ("tudás", "blog", "inspiráció", "referencia")):
        return "editorial"
    if any(word in text for word in ("kapcsolat", "ajánlat", "konzultáció")):
        return "service-map"
    if brand.character in {"editorial", "direct", "friendly", "practical", "service-map", "hygge"}:
        return brand.character
    return ("technical", "collection", "editorial")[index % 3]


def page_headline(brand: Brand, title: str, blocks: list[tuple[str, str]], index: int) -> str:
    if index == 0:
        return brand.hero
    for block_title, text in blocks:
        if "hero" in block_title.lower():
            headline = quoted_headline(text)
            if headline:
                return headline
    endings = (
        "Érthető döntés, a következő lépésig.",
        "Minden fontos szempont egy helyen.",
        "A részletek, amelyek valóban számítanak.",
    )
    return f"{title}. {endings[index % len(endings)]}"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def split_chips(value: str) -> tuple[str, list[str]]:
    parts = [clean_text(item.strip(' „”"')) for item in re.split(r"\s*[•→;]\s*|,\s+(?=[A-ZÁÉÍÓÖŐÚÜŰ])", value)]
    parts = [item for item in parts if 2 < len(item) < 54]
    if len(parts) >= 3:
        return value, parts[:8]
    return value, []


def relative_link(current_index: int, target_slug: str) -> str:
    if current_index == 0:
        return "index.html" if target_slug == "index" else f"pages/{target_slug}.html"
    return "../index.html" if target_slug == "index" else f"{target_slug}.html"


def svg_for(brand: Brand, slug: str, index: int) -> str:
    digest = hashlib.sha256(f"{brand.key}:{slug}".encode()).digest()
    x1, y1 = 80 + digest[0] % 220, 70 + digest[1] % 150
    x2, y2 = 420 + digest[2] % 280, 230 + digest[3] % 210
    radius = 90 + digest[4] % 120
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 680" role="img" aria-labelledby="t d">
<title id="t">{html.escape(brand.name)} – {html.escape(slug)}</title><desc id="d">Márkaspecifikus absztrakt építészeti kompozíció.</desc>
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{brand.surface}"/><stop offset="1" stop-color="{brand.secondary}"/></linearGradient><pattern id="p" width="{36 + index % 5 * 8}" height="{36 + index % 5 * 8}" patternUnits="userSpaceOnUse"><path d="M0 0H36V36" fill="none" stroke="{brand.primary}" stroke-opacity=".12"/></pattern></defs>
<rect width="900" height="680" fill="url(#g)"/><rect width="900" height="680" fill="url(#p)"/>
<circle cx="{x1}" cy="{y1}" r="{radius}" fill="{brand.accent}" opacity=".88"/><path d="M80 570L{x2} {y2}L820 570Z" fill="{brand.primary}" opacity=".92"/>
<path d="M160 570V330L430 {150 + index * 9 % 120}L720 330V570" fill="{brand.surface}" stroke="{brand.ink}" stroke-width="10"/>
<rect x="{260 + index * 19 % 120}" y="390" width="150" height="180" fill="{brand.secondary}"/><rect x="500" y="370" width="130" height="100" fill="{brand.accent}" opacity=".76"/>
</svg>"""


def render_blocks(blocks: list[tuple[str, str]]) -> str:
    if not blocks:
        blocks = [("Döntési fókusz", "A részletes oldalstruktúra a jóváhagyott márkaforrás következő kiadásában egészül ki.")]
    rendered = []
    for index, (title, text) in enumerate(blocks, start=1):
        text, chips = split_chips(clean_text(text))
        chip_html = "".join(f'<span class="chip">{html.escape(chip)}</span>' for chip in chips)
        rendered.append(
            f'<article class="block" data-step="{index:02d}">'
            f'<span class="block-kicker">{index:02d} · {html.escape(title)}</span>'
            f"<h3>{html.escape(title)}</h3><p>{html.escape(text)}</p>"
            f'{f"<div class=chips>{chip_html}</div>" if chip_html else ""}</article>'
        )
    return "".join(rendered)


def render_page(
    brand: Brand,
    pages: list[tuple[str, list[tuple[str, str]]]],
    index: int,
    title: str,
    blocks: list[tuple[str, str]],
) -> str:
    slug = "index" if index == 0 else slugify(title)
    layout = page_layout(brand, title, index)
    headline = page_headline(brand, title, blocks, index)
    visual = f"assets/visuals/{slug}.svg" if index == 0 else f"../assets/visuals/{slug}.svg"
    css = "assets/site.css" if index == 0 else "../assets/site.css"
    js = "assets/site.js" if index == 0 else "../assets/site.js"
    logo = "assets/logo.svg" if index == 0 else "../assets/logo.svg"
    bridge_css = "/site-preview/{}/assets/platform/review-bridge.css".format(brand.key)
    bridge_js = "/site-preview/{}/assets/platform/review-bridge.js".format(brand.key)
    nav = []
    for page_index, (page_title, _) in enumerate(pages):
        target = "index" if page_index == 0 else slugify(page_title)
        nav.append(
            f'<a href="{relative_link(index, target)}"'
            f'{" aria-current=page" if target == slug else ""}>{html.escape(page_title)}</a>'
        )
    lead = (
        f"{brand.positioning} A {title.lower()} célja, hogy a látogató "
        "egyértelmű szempontokkal jusson el a következő megalapozott döntésig."
    )
    return f"""<!doctype html>
<html lang="hu" data-brand="{brand.key}" data-layout="{layout}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <meta name="description" content="{html.escape(lead, quote=True)}">
  <meta name="source-id" content="{brand.source_id}">
  <meta name="brand-guide-id" content="{brand.guide_id}">
  <meta name="content-status" content="source-aligned-preview">
  <title>{html.escape(title)} | {html.escape(brand.name)}</title>
  <link rel="stylesheet" href="{css}">
  <link rel="stylesheet" href="{bridge_css}">
  <style>:root{{--primary:{brand.primary};--accent:{brand.accent};--secondary:{brand.secondary};--surface:{brand.surface};--ink:{brand.ink};--display:"{brand.display_font}",BrandSans;--body:"{brand.body_font}",BrandSans}}</style>
</head>
<body class="layout-{layout} page-{slug}">
  <a class="skip" href="#tartalom">Ugrás a tartalomhoz</a>
  <header class="header"><div class="shell nav">
    <a class="brand" href="{relative_link(index, 'index')}"><img src="{logo}" alt=""><span>{html.escape(brand.name)}</span></a>
    <button class="menu" type="button" data-menu aria-controls="site-nav" aria-expanded="false">Menü</button>
    <nav class="navlinks" id="site-nav" data-nav aria-label="Fő navigáció">{''.join(nav)}</nav>
  </div></header>
  <main id="tartalom">
    <section class="hero"><div class="shell hero-grid">
      <div>
        <div class="eyebrow">{html.escape(brand.character)} · {html.escape(title)}</div>
        <h1>{html.escape(headline)}</h1>
        <p class="lead">{html.escape(lead)}</p>
        <p class="tagline">{html.escape(brand.tagline)}</p>
        <div class="actions"><a class="button" href="#kovetkezo-lepes">{html.escape(brand.primary_cta)}</a><a class="button secondary" href="{relative_link(index, 'index')}">{html.escape(brand.secondary_cta)}</a></div>
        <span class="source-state">Drive-forráshoz igazított tesztoldal · publikálás nélkül</span>
      </div>
      <figure class="hero-visual"><img src="{visual}" alt="{html.escape(title)} – {html.escape(brand.name)} vizuális koncepció"></figure>
    </div></section>
    <section class="section"><div class="shell">
      <div class="intro"><span class="eyebrow">Oldalspecifikus döntési út</span><h2>{html.escape(title)}</h2><p>{html.escape(brand.positioning)}</p></div>
      <div class="blocks">{render_blocks(blocks)}</div>
    </div></section>
    <section class="decision" id="kovetkezo-lepes"><div class="shell decision-grid">
      <div><span class="eyebrow">Következő emberi döntés</span><h2>{html.escape(brand.primary_cta)}</h2><p>A preview nem küld adatot és nem tesz ajánlatot. Ár, határidő, garancia vagy szerződéses vállalás csak jóváhagyott evidence- és ajánlati rekord alapján jelenhet meg élesben.</p></div>
      <a class="button" href="{relative_link(index, 'kapcsolat')}">{html.escape(brand.primary_cta)}</a>
    </div></section>
  </main>
  <footer class="footer"><div class="shell footer-grid"><div><strong>{html.escape(brand.name)}</strong><p>{html.escape(brand.tagline)}</p><p class="legal">Forrás: {brand.source_id} · arculati kézikönyv: {brand.guide_id} · noindex preview.</p></div><a href="{relative_link(index, 'index')}">Oldaltérkép</a></div></footer>
  <script src="{js}" defer></script><script src="{bridge_js}" defer></script>
</body></html>
"""


def logo_svg(brand: Brand) -> str:
    initials = "".join(part[0] for part in brand.name.split())[:2].upper()
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" role="img" aria-label="{html.escape(brand.name)}">
<rect width="80" height="80" rx="20" fill="{brand.primary}"/><path d="M14 58L40 18L66 58Z" fill="{brand.accent}" opacity=".9"/>
<text x="40" y="55" text-anchor="middle" font-family="Arial,sans-serif" font-size="24" font-weight="900" fill="{brand.surface}">{initials}</text></svg>"""


def generate_brand(brand: Brand) -> int:
    site_root = ROOT / "sites" / brand.key
    root = site_root / brand.output_subdir if brand.output_subdir else site_root
    source_path = site_root / "source" / "website-spec.md"
    pages = parse_pages(source_path.read_text(encoding="utf-8"))
    if not pages:
        raise RuntimeError(f"No pages found in {source_path}")
    assets = root / "assets"
    fonts = assets / "fonts"
    visuals = assets / "visuals"
    pages_dir = root / "pages"
    assets.mkdir(parents=True, exist_ok=True)
    fonts.mkdir(parents=True, exist_ok=True)
    visuals.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    font_target = fonts / "inter-latin.woff2"
    if FONT_SOURCE.resolve() != font_target.resolve():
        shutil.copyfile(FONT_SOURCE, font_target)
    (assets / "site.css").write_text(CSS, encoding="utf-8")
    (assets / "site.js").write_text(JS, encoding="utf-8")
    (assets / "logo.svg").write_text(logo_svg(brand), encoding="utf-8")
    for index, (title, blocks) in enumerate(pages):
        slug = "index" if index == 0 else slugify(title)
        output = root / "index.html" if index == 0 else pages_dir / f"{slug}.html"
        output.write_text(render_page(brand, pages, index, title, blocks), encoding="utf-8")
        (visuals / f"{slug}.svg").write_text(svg_for(brand, slug, index), encoding="utf-8")
    return len(pages)


def main() -> None:
    total = 0
    for brand in BRANDS:
        count = generate_brand(brand)
        total += count
        print(f"{brand.key}: {count} source-aligned pages")
    print(f"generated {total} source-aligned previews")


if __name__ == "__main__":
    main()
