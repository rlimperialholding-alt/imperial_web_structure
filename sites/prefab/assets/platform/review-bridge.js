(() => {
  const params = new URLSearchParams(window.location.search);
  const reviewMode = params.get("review") === "1";

  if (!reviewMode) {
    return;
  }

  document.documentElement.classList.add("review-mode");

  const previewMatch = window.location.pathname.match(/^\/site-preview\/([^/]+)(?:\/|$)/);
  const previewBrand = previewMatch?.[1] || null;

  document.querySelectorAll("a[href]").forEach((anchor) => {
    const rawHref = anchor.getAttribute("href")?.trim();

    if (!rawHref || rawHref.startsWith("#")) {
      return;
    }

    let target;
    try {
      target = new URL(rawHref, window.location.href);
    } catch {
      return;
    }

    if (target.origin !== window.location.origin) {
      return;
    }

    if (previewBrand && !target.pathname.startsWith(`/site-preview/${previewBrand}/`)) {
      target.pathname = `/site-preview/${previewBrand}${target.pathname.startsWith("/") ? "" : "/"}${target.pathname}`;
    }

    target.searchParams.set("review", "1");
    anchor.href = `${target.pathname}${target.search}${target.hash}`;
  });

  const pageSlug = window.location.pathname
    .replace(/^\/site-preview\/[^/]+\//, "")
    .replace(/\/?index\.html$/, "")
    .replace(/\.html$/, "")
    .replace(/[^a-z0-9]+/gi, "-")
    .replace(/^-|-$/g, "") || "home";

  const candidates = Array.from(document.querySelectorAll(
    "[data-review-section], body > header, main > header, main > section, body > section, body > main, body > footer"
  ));

  const usedIds = new Set();

  candidates.forEach((element, index) => {
    let sectionId = element.id || element.dataset.reviewSection;

    if (!sectionId || usedIds.has(sectionId)) {
      sectionId = `${pageSlug}-${element.tagName.toLowerCase()}-${String(index + 1).padStart(2, "0")}`;
    }

    element.id = sectionId;
    element.dataset.reviewSection = sectionId;
    element.classList.add("review-section");
    usedIds.add(sectionId);
  });

  function sectionLabel(element) {
    const heading = element.querySelector("h1, h2, h3");
    return heading?.textContent?.trim().replace(/\s+/g, " ").slice(0, 100)
      || element.getAttribute("aria-label")
      || element.dataset.reviewSection
      || "Tartalmi szekció";
  }

  function selectSection(element) {
    document.querySelectorAll(".review-section.is-review-selected").forEach((item) => {
      item.classList.remove("is-review-selected");
    });

    element.classList.add("is-review-selected");
    window.parent.postMessage({
      type: "imperial:section-selected",
      sectionId: element.dataset.reviewSection,
      sectionLabel: sectionLabel(element),
      pagePath: window.location.pathname
    }, window.location.origin);
  }

  document.addEventListener("click", (event) => {
    const section = event.target.closest(".review-section");
    if (section) {
      selectSection(section);
    }
  }, true);

  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const notice = document.createElement("div");
      notice.className = "review-form-notice";
      notice.textContent = "Tesztmód: az űrlap nem továbbít adatot.";
      document.body.appendChild(notice);
      window.setTimeout(() => notice.remove(), 2600);
    });
  });

  if (candidates[0]) {
    selectSection(candidates[0]);
  }
})();
