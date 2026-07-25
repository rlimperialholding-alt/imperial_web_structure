import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

test.setTimeout(120_000);

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const catalog = JSON.parse(
  fs.readFileSync(
    path.join(repository, "sites", "_portal", "data", "artifacts.json"),
    "utf8"
  )
);
const viewports = {
  desktop: { width: 1440, height: 900 },
  tablet: { width: 834, height: 1112 },
  mobile: { width: 390, height: 844 }
};

const catalogPages = Object.entries(catalog.brands).flatMap(([brand, entry]) =>
  entry.pages.map((page, index) => ({ brand, index, ...page }))
);

function pageSlug(page) {
  const value = page.path
    .replace(/^\/|\/$/g, "")
    .replace(/\.html$/i, "")
    .replace(/[^a-z0-9]+/gi, "-")
    .replace(/^-|-$/g, "");
  return value || "home";
}

function previewRoute(page) {
  const normalized = page.path.startsWith("/") ? page.path : `/${page.path}`;
  const route = normalized === "/"
    ? `/site-preview/${page.brand}/`
    : `/site-preview/${page.brand}${normalized}`;
  return `${route}${route.includes("?") ? "&" : "?"}review=1`;
}

test.describe("website preview catalog", () => {
  test("the catalog contains every registered screen", async () => {
    expect(catalogPages).toHaveLength(131);
    expect(Object.keys(catalog.brands)).toHaveLength(12);
  });

  for (const pageEntry of catalogPages) {
    for (const [viewportName, viewport] of Object.entries(viewports)) {
      test(`${pageEntry.brand} ${pageEntry.path} · ${viewportName}`, async ({
        page
      }) => {
        const browserErrors = [];
        const failedRequests = [];

        await page.setViewportSize(viewport);
        page.on("console", (message) => {
          if (message.type() === "error") {
            browserErrors.push(`console: ${message.text()}`);
          }
        });
        page.on("pageerror", (error) => {
          browserErrors.push(`pageerror: ${error.message}`);
        });
        page.on("request", (request) => {
          const url = new URL(request.url());
          if (
            ["http:", "https:"].includes(url.protocol)
            && !["127.0.0.1", "localhost"].includes(url.hostname)
          ) {
            failedRequests.push(`external request: ${request.url()}`);
          }
        });
        page.on("requestfailed", (request) => {
          failedRequests.push(
            `request failed: ${request.url()} · ${request.failure()?.errorText || "unknown"}`
          );
        });
        page.on("response", (response) => {
          if (response.status() >= 400) {
            failedRequests.push(
              `HTTP ${response.status()}: ${response.url()}`
            );
          }
        });

        const response = await page.goto(previewRoute(pageEntry), {
          waitUntil: "domcontentloaded"
        });
        expect(response?.status()).toBe(200);
        await page.waitForTimeout(350);
        await page.evaluate(() => document.fonts.ready);
        await expect(page.locator("body")).toBeVisible();

        const screenshotDirectory = path.join(
          repository,
          "artifacts",
          "website-previews",
          pageEntry.brand,
          `${String(pageEntry.index + 1).padStart(2, "0")}-${pageSlug(pageEntry)}`
        );
        fs.mkdirSync(screenshotDirectory, { recursive: true });
        await page.screenshot({
          path: path.join(screenshotDirectory, `${viewportName}.jpg`),
          fullPage: true,
          animations: "disabled",
          type: "jpeg",
          quality: 80
        });

        const diagnostics = await page.evaluate(({ brand, kind }) => {
          const normalizeCopy = (value) =>
            value
              .toLocaleLowerCase("hu")
              .replace(/\s+/g, " ")
              .replace(/[^\p{L}\p{N}%+–-]+/gu, " ")
              .trim();
          const images = Array.from(document.images);
          const brokenImages = images
            .filter((image) => !image.complete || image.naturalWidth === 0)
            .map((image) => image.currentSrc || image.src);
          const localNavigationWithoutReview = Array.from(
            document.querySelectorAll("a[href]")
          )
            .map((anchor) => anchor.href)
            .filter((href) => {
              const target = new URL(href, location.href);
              return (
                target.origin === location.origin
                && !target.hash
                && target.pathname.startsWith(
                  `/site-preview/${location.pathname.split("/")[2]}/`
                )
                && target.searchParams.get("review") !== "1"
              );
            });
          const viewportWidth = document.documentElement.clientWidth;
          const copyCounts = new Map();
          Array.from(
            document.querySelectorAll("main h1,main h2,main h3,main p,main li,main summary")
          ).forEach((element) => {
            const normalized = normalizeCopy(element.textContent || "");
            if (
              normalized.length >= 90
              && !normalized.includes("preview nem küld adatot")
              && !normalized.includes("drive-forráshoz igazított")
            ) {
              copyCounts.set(normalized, (copyCounts.get(normalized) || 0) + 1);
            }
          });
          const duplicateVisibleBlocks = Array.from(copyCounts.entries())
            .filter(([, count]) => count > 1)
            .map(([text, count]) => ({ text, count }));
          const foreignBrandMarkers = brand === "prefab"
            ? ["imperial holding", "imperialholding.hu", "bautica", "csodálatos otthonok"]
                .filter((marker) => document.body.innerText.toLowerCase().includes(marker))
            : [];
          const overflowingElements = Array.from(document.querySelectorAll("*"))
            .map((element) => {
              const bounds = element.getBoundingClientRect();
              return {
                selector: [
                  element.tagName.toLowerCase(),
                  element.id ? `#${element.id}` : "",
                  ...Array.from(element.classList).map((name) => `.${name}`)
                ].join(""),
                left: Math.round(bounds.left),
                right: Math.round(bounds.right),
                width: Math.round(bounds.width)
              };
            })
            .filter(({ left, right }) => left < -2 || right > viewportWidth + 2)
            .slice(0, 20);
          return {
            title: document.title.trim(),
            text: document.body.innerText,
            brokenImages,
            localNavigationWithoutReview,
            duplicateVisibleBlocks,
            foreignBrandMarkers,
            sourceMetadata: kind === "drive-source-page"
              ? {
                  sourceId: document.querySelector('meta[name="source-id"]')?.content,
                  guideId: document.querySelector('meta[name="brand-guide-id"]')?.content,
                  status: document.querySelector('meta[name="content-status"]')?.content
                }
              : null,
            overflowingElements,
            viewportWidth,
            scrollWidth: document.documentElement.scrollWidth
          };
        }, { brand: pageEntry.brand, kind: pageEntry.kind });

        expect(diagnostics.title).not.toBe("");
        expect(diagnostics.text.toLowerCase()).not.toContain("helyőrző");
        expect(diagnostics.text.toLowerCase()).not.toContain("placeholder");
        expect(diagnostics.brokenImages).toEqual([]);
        expect(diagnostics.localNavigationWithoutReview).toEqual([]);
        expect(diagnostics.duplicateVisibleBlocks).toEqual([]);
        expect(diagnostics.foreignBrandMarkers).toEqual([]);
        if (pageEntry.kind === "drive-source-page") {
          expect(diagnostics.sourceMetadata?.sourceId).toBeTruthy();
          expect(diagnostics.sourceMetadata?.guideId).toBeTruthy();
          expect(diagnostics.sourceMetadata?.status).toBe("source-aligned-preview");
        }
        expect(
          diagnostics.scrollWidth,
          `Overflowing elements: ${JSON.stringify(diagnostics.overflowingElements)}`
        ).toBeLessThanOrEqual(
          diagnostics.viewportWidth + 2
        );
        expect(browserErrors).toEqual([]);
        expect(failedRequests).toEqual([]);
      });
    }
  }
});
