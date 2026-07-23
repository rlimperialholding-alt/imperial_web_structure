const state = {
  brands: [],
  currentBrand: "imperial",
  currentSection: {
    id: "hero",
    label: "Nyitó szekció"
  },
  reviews: [],
  device: "desktop"
};

const storageKey = "imperial-intelligence-reviews-v1";
const viewportConfig = {
  desktop: "1440 × 900",
  tablet: "834 × 1112",
  mobile: "390 × 844"
};

const elements = {
  brandSelect: document.querySelector("#brand-select"),
  brandStrip: document.querySelector("#brand-strip"),
  brandMetric: document.querySelector("#brand-metric"),
  navBrandCount: document.querySelector("#nav-brand-count"),
  sectionMetric: document.querySelector("#section-metric"),
  selectedBrandAvatar: document.querySelector("#selected-brand-avatar"),
  selectedBrandName: document.querySelector("#selected-brand-name"),
  selectedBrandStatus: document.querySelector("#selected-brand-status"),
  preview: document.querySelector("#site-preview"),
  previewStage: document.querySelector(".preview-stage"),
  previewAddress: document.querySelector("#preview-address"),
  viewportLabel: document.querySelector("#viewport-label"),
  openPreview: document.querySelector("#open-preview"),
  reviewPanel: document.querySelector("#review-panel"),
  workspace: document.querySelector("#preview-workspace"),
  toggleReview: document.querySelector("#toggle-review"),
  closeReview: document.querySelector("#close-review"),
  selectedSection: document.querySelector("#selected-section"),
  selectedSectionLabel: document.querySelector("#selected-section-label"),
  reviewForm: document.querySelector("#review-form"),
  reviewList: document.querySelector("#review-list"),
  reviewListCount: document.querySelector("#review-list-count"),
  reviewMetric: document.querySelector("#review-metric"),
  navReviewCount: document.querySelector("#nav-review-count"),
  toast: document.querySelector("#toast")
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function loadReviews() {
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || "[]");
    state.reviews = Array.isArray(stored) ? stored : [];
  } catch {
    state.reviews = [];
  }
}

function saveReviews() {
  localStorage.setItem(storageKey, JSON.stringify(state.reviews));
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("is-visible");
  window.setTimeout(() => elements.toast.classList.remove("is-visible"), 2400);
}

function renderBrands() {
  elements.brandSelect.innerHTML = state.brands
    .map((brand) => `<option value="${escapeHtml(brand.id)}">${escapeHtml(brand.name)}</option>`)
    .join("");

  elements.brandStrip.innerHTML = state.brands
    .map((brand) => `
      <button
        class="brand-card${brand.id === state.currentBrand ? " is-active" : ""}"
        type="button"
        role="listitem"
        data-brand="${escapeHtml(brand.id)}"
        style="--brand-accent: ${escapeHtml(brand.accent)}"
        aria-pressed="${brand.id === state.currentBrand}"
      >
        <span>${escapeHtml(brand.initials)}</span>
        <strong>${escapeHtml(brand.shortName)}</strong>
        <small>${brand.status === "active" ? "Aktív" : "Előkészítve"}</small>
      </button>
    `)
    .join("");

  elements.brandMetric.textContent = String(state.brands.length).padStart(2, "0");
  elements.navBrandCount.textContent = String(state.brands.length);
}

function setBrand(brandId) {
  const brand = state.brands.find((item) => item.id === brandId);
  if (!brand) {
    return;
  }

  state.currentBrand = brand.id;
  state.currentSection = brand.id === "imperial"
    ? { id: "hero", label: "Nyitó szekció" }
    : { id: "site-overview", label: `${brand.name} webhely áttekintése` };

  elements.brandSelect.value = brand.id;
  elements.selectedBrandAvatar.textContent = brand.initials;
  elements.selectedBrandAvatar.style.borderColor = brand.accent;
  elements.selectedBrandAvatar.style.color = brand.accent;
  elements.selectedBrandName.textContent = brand.name;
  elements.selectedBrandStatus.textContent = brand.statusLabel;
  elements.sectionMetric.textContent = String(brand.sectionCount).padStart(2, "0");
  elements.selectedSection.textContent = state.currentSection.id;
  elements.selectedSectionLabel.textContent = state.currentSection.label;

  const previewUrl = `/site-preview/${brand.id}/?review=1`;
  elements.preview.src = previewUrl;
  elements.openPreview.href = `/site-preview/${brand.id}/`;
  elements.previewAddress.textContent = `${brand.id}.localhost / home`;

  document.querySelectorAll(".brand-card").forEach((card) => {
    const active = card.dataset.brand === brand.id;
    card.classList.toggle("is-active", active);
    card.setAttribute("aria-pressed", String(active));
  });

  renderReviews();
}

function setDevice(device) {
  state.device = device;
  elements.previewStage.dataset.device = device;
  elements.viewportLabel.textContent = viewportConfig[device];

  document.querySelectorAll(".device-button").forEach((button) => {
    const active = button.dataset.device === device;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function renderReviews() {
  const brandReviews = state.reviews.filter((review) => review.brandId === state.currentBrand);
  const total = state.reviews.length;

  elements.reviewMetric.textContent = String(total).padStart(2, "0");
  elements.navReviewCount.textContent = String(total);
  elements.reviewListCount.textContent = `${brandReviews.length} elem`;

  if (brandReviews.length === 0) {
    elements.reviewList.innerHTML = `
      <div class="review-empty">
        Még nincs megjegyzés ehhez a márkához. Kattints az Imperial preview egyik szekciójára, majd rögzíts review elemet.
      </div>
    `;
    return;
  }

  elements.reviewList.innerHTML = brandReviews
    .slice()
    .reverse()
    .map((review) => `
      <article class="review-item">
        <header>
          <strong>${escapeHtml(review.title)}</strong>
          <span class="review-priority">${escapeHtml(review.priorityLabel)}</span>
        </header>
        <p>${escapeHtml(review.comment)}</p>
        <footer>
          <span>#${escapeHtml(review.sectionId)} · ${escapeHtml(review.createdAtLabel)}</span>
          <button class="review-item-delete" type="button" data-review-id="${escapeHtml(review.id)}" title="Megjegyzés törlése">×</button>
        </footer>
      </article>
    `)
    .join("");
}

function addReview(formData) {
  const priorityLabels = {
    low: "Alacsony",
    normal: "Normál",
    high: "Magas"
  };
  const now = new Date();

  state.reviews.push({
    id: `review-${now.getTime()}`,
    brandId: state.currentBrand,
    sectionId: state.currentSection.id,
    sectionLabel: state.currentSection.label,
    title: formData.get("title").trim(),
    comment: formData.get("comment").trim(),
    priority: formData.get("priority"),
    priorityLabel: priorityLabels[formData.get("priority")] || "Normál",
    createdAt: now.toISOString(),
    createdAtLabel: new Intl.DateTimeFormat("hu-HU", {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    }).format(now)
  });

  saveReviews();
  renderReviews();
  elements.reviewForm.reset();
  showToast("A review megjegyzés lokálisan elmentve.");
}

function exportReviews() {
  const payload = {
    exportedAt: new Date().toISOString(),
    environment: "local-prototype",
    containsCustomerData: false,
    reviews: state.reviews
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `imperial-review-${new Date().toISOString().slice(0, 10)}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
  showToast("A review lista JSON-ként exportálva.");
}

function toggleReviewPanel(forceOpen) {
  const shouldOpen = typeof forceOpen === "boolean"
    ? forceOpen
    : elements.workspace.classList.contains("review-collapsed");
  elements.workspace.classList.toggle("review-collapsed", !shouldOpen);
  elements.toggleReview.setAttribute("aria-expanded", String(shouldOpen));
}

async function init() {
  loadReviews();
  renderReviews();

  try {
    const response = await fetch("/data/brands.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    state.brands = data.brands;
    renderBrands();
    setBrand(state.currentBrand);
  } catch (error) {
    showToast("A márkaadatok nem tölthetők be.");
    console.error("Brand data loading failed", error);
  }
}

elements.brandSelect.addEventListener("change", (event) => setBrand(event.target.value));

elements.brandStrip.addEventListener("click", (event) => {
  const button = event.target.closest("[data-brand]");
  if (button) {
    setBrand(button.dataset.brand);
  }
});

document.querySelector(".device-switcher").addEventListener("click", (event) => {
  const button = event.target.closest("[data-device]");
  if (button) {
    setDevice(button.dataset.device);
  }
});

document.querySelector("#refresh-preview").addEventListener("click", () => {
  elements.preview.src = elements.preview.src;
  showToast("A preview újratöltve.");
});

elements.reviewForm.addEventListener("submit", (event) => {
  event.preventDefault();
  addReview(new FormData(event.currentTarget));
});

elements.reviewList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-review-id]");
  if (!button) {
    return;
  }
  state.reviews = state.reviews.filter((review) => review.id !== button.dataset.reviewId);
  saveReviews();
  renderReviews();
  showToast("A review megjegyzés törölve.");
});

document.querySelector("#export-reviews").addEventListener("click", exportReviews);

document.querySelector("#clear-reviews").addEventListener("click", () => {
  state.reviews = [];
  saveReviews();
  renderReviews();
  showToast("A lokális review lista kiürítve.");
});

elements.toggleReview.addEventListener("click", () => toggleReviewPanel());
elements.closeReview.addEventListener("click", () => toggleReviewPanel(false));

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin || event.data?.type !== "imperial:section-selected") {
    return;
  }
  state.currentSection = {
    id: event.data.sectionId,
    label: event.data.sectionLabel
  };
  elements.selectedSection.textContent = state.currentSection.id;
  elements.selectedSectionLabel.textContent = state.currentSection.label;
  toggleReviewPanel(true);
});

init();
