const pageState = {
  projects: [],
  projectOffset: 0,
  projectPageSize: 3
};

const pageElements = {
  statGrid: document.querySelector("#stat-grid"),
  portfolioGrid: document.querySelector("#portfolio-grid"),
  projectGrid: document.querySelector("#project-grid"),
  newsGrid: document.querySelector("#news-grid"),
  siteToast: document.querySelector("#site-toast"),
  menuToggle: document.querySelector(".menu-toggle"),
  navigation: document.querySelector("#site-navigation")
};

const HTML_ESCAPES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#039;"
};

// Egy menetben, karaktertérképből dolgozik: a láncolt replaceAll helyett
// nincs újra-escape ablak (Task60 hardening).
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => HTML_ESCAPES[character]);
}

function renderStats(stats) {
  pageElements.statGrid.innerHTML = stats
    .map((stat) => `
      <div class="stat-card">
        <strong>${escapeHtml(stat.value)}${escapeHtml(stat.suffix)}</strong>
        <span>${escapeHtml(stat.label)}</span>
      </div>
    `)
    .join("");
}

function renderPortfolio(items) {
  pageElements.portfolioGrid.innerHTML = items
    .map((item) => `
      <article class="portfolio-card" data-tone="${escapeHtml(item.tone)}" id="${escapeHtml(item.id)}">
        <span>${escapeHtml(item.index)}</span>
        <div class="portfolio-card-content">
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.description)}</p>
          <small>${escapeHtml(item.brands)}</small>
        </div>
      </article>
    `)
    .join("");
}

function visibleProjects() {
  const items = [];
  for (let index = 0; index < pageState.projectPageSize; index += 1) {
    items.push(pageState.projects[(pageState.projectOffset + index) % pageState.projects.length]);
  }
  return items;
}

function renderProjects() {
  pageElements.projectGrid.innerHTML = visibleProjects()
    .map((project) => `
      <figure class="project-card" id="${escapeHtml(project.id)}">
        <div class="project-visual" data-tone="${escapeHtml(project.tone)}" aria-hidden="true"></div>
        <figcaption>
          <span>${escapeHtml(project.category)}</span>
          <h3>${escapeHtml(project.name)}</h3>
          <div><span>${escapeHtml(project.location)}</span><span>${escapeHtml(project.year)}</span></div>
        </figcaption>
      </figure>
    `)
    .join("");
}

function renderNews(items) {
  pageElements.newsGrid.innerHTML = items
    .map((item) => `
      <a class="news-card" href="#contact" id="${escapeHtml(item.id)}">
        <div class="news-visual" data-tone="${escapeHtml(item.tone)}" aria-hidden="true"></div>
        <div class="news-card-content">
          <span>${escapeHtml(item.category)}</span>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.date)} · Minta tartalom</p>
        </div>
      </a>
    `)
    .join("");
}

function enableReviewMode(sections) {
  if (new URLSearchParams(window.location.search).get("review") !== "1") {
    return;
  }

  sections.forEach((sectionDefinition) => {
    const section = document.getElementById(sectionDefinition.id);
    if (!section) {
      return;
    }

    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "review-marker";
    marker.textContent = `#${sectionDefinition.id}`;
    marker.setAttribute("aria-label", `${sectionDefinition.label} kijelölése review-hoz`);

    marker.addEventListener("click", () => {
      document.querySelectorAll(".content-section").forEach((item) => item.classList.remove("is-review-selected"));
      section.classList.add("is-review-selected");
      window.parent.postMessage({
        type: "imperial:section-selected",
        sectionId: sectionDefinition.id,
        sectionLabel: sectionDefinition.label
      }, window.location.origin);
    });

    section.append(marker);
  });
}

function showSiteToast(message) {
  pageElements.siteToast.textContent = message;
  pageElements.siteToast.classList.add("is-visible");
  window.setTimeout(() => pageElements.siteToast.classList.remove("is-visible"), 2600);
}

async function initPage() {
  try {
    const response = await fetch("/assets/data/imperial-home.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    renderStats(data.stats);
    renderPortfolio(data.portfolio);
    pageState.projects = data.projects;
    renderProjects();
    renderNews(data.news);
    enableReviewMode(data.sections);
  } catch (error) {
    showSiteToast("A lokális tesztadatok nem tölthetők be.");
    console.error("Imperial prototype data loading failed", error);
  }
}

pageElements.menuToggle.addEventListener("click", () => {
  const open = pageElements.navigation.classList.toggle("is-open");
  pageElements.menuToggle.setAttribute("aria-expanded", String(open));
});

pageElements.navigation.addEventListener("click", () => {
  pageElements.navigation.classList.remove("is-open");
  pageElements.menuToggle.setAttribute("aria-expanded", "false");
});

document.querySelector("#project-prev").addEventListener("click", () => {
  pageState.projectOffset = (pageState.projectOffset - 1 + pageState.projects.length) % pageState.projects.length;
  renderProjects();
});

document.querySelector("#project-next").addEventListener("click", () => {
  pageState.projectOffset = (pageState.projectOffset + 1) % pageState.projects.length;
  renderProjects();
});

document.querySelector("#prototype-contact").addEventListener("click", () => {
  showSiteToast("Prototípus mód: adat nem került elküldésre.");
});

initPage();
