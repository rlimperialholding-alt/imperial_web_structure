#!/usr/bin/env node
/**
 * check-package-age.mjs — érvényesített 7 napos package-age supply-chain küszöb.
 *
 * A Semgrep `npm-missing-minimum-release-age` szabály által megkövetelt
 * telepítés-oldali korhatár valós, futó implementációja. A nem támogatott
 * `minimum-release-age=7` npm .npmrc kulcs (semmilyen npm parancs nem
 * érvényesíti) HELYETT ez a szkript a package-lock.json minden registry-ből
 * feloldott, nem dev csomagjának publikálási idejét ellenőrzi a registry
 * packument `time` térképe alapján, és fail-closed leáll, ha bármely verzió
 * fiatalabb a küszöbnél, ha a publikálási idő nem bizonyítható, vagy ha a
 * registry nem érhető el.
 *
 * Futás: a Quality workflow `itep-core` jobjának dedikált lépése
 * (`node scripts/check-package-age.mjs`) minden npm ci után, hálózattal;
 * lokálisan `npm run check:package-age`. A szkript az imperial-sales-crm
 * projekt azonos logikájú, tesztelt példányával byte-azonos (Task61).
 *
 * A szkript nem módosít semmit; kimenete csak a küszöbsértő vagy nem
 * bizonyítható csomagok listája (secretmentes).
 */

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

export const DEFAULT_MIN_RELEASE_AGE_DAYS = 7;
const DAY_MS = 24 * 60 * 60 * 1000;

/** A lockfile minden érintett csomagjának név/verzió kigyűjtése. */
export function collectLockedPackages(lock, { includeDev = false } = {}) {
  const packages = new Map();
  for (const [key, entry] of Object.entries(lock.packages ?? {})) {
    const marker = "node_modules/";
    const markerIndex = key.lastIndexOf(marker);
    if (markerIndex < 0 || !entry?.version) continue;
    if (entry.link || entry.resolved?.startsWith("file:")) continue;
    if (!includeDev && (entry.dev || entry.devOptional)) continue;
    // Nested beágyazásoknál (a/b/node_modules/c) a csomagnév az utolsó szegmens.
    const name = key.slice(markerIndex + marker.length);
    const version = entry.version;
    if (!packages.has(`${name}@${version}`)) {
      packages.set(`${name}@${version}`, { name, version });
    }
  }
  return [...packages.values()].sort((a, b) =>
    `${a.name}@${a.version}`.localeCompare(`${b.name}@${b.version}`),
  );
}

/** A packument `time` térképéből a verzió publikálási időpontja (ISO), vagy null. */
export function extractPublishTime(packument, version) {
  return packument?.time?.[version] ?? null;
}

/**
 * A küszöböt sértő (vagy nem bizonyítható korú) csomagok listája.
 * Fail-closed: a hiányzó `time` bejegyzés is sértésnek számít.
 */
export function findTooYoung({ packages, packuments, nowMs, minAgeDays }) {
  const floorMs = minAgeDays * DAY_MS;
  const tooYoung = [];
  for (const { name, version } of packages) {
    const packument = packuments.get(name);
    if (!packument) {
      tooYoung.push({
        name,
        version,
        reason: "registry evidence unavailable",
        publishedAt: null,
      });
      continue;
    }
    const publishedAt = extractPublishTime(packument, version);
    if (!publishedAt) {
      tooYoung.push({
        name,
        version,
        reason: "publish time not provable from the registry packument",
        publishedAt: null,
      });
      continue;
    }
    const publishedMs = Date.parse(publishedAt);
    if (!Number.isFinite(publishedMs)) {
      tooYoung.push({
        name,
        version,
        reason: `unparsable publish time: ${publishedAt}`,
        publishedAt,
      });
      continue;
    }
    const ageMs = nowMs - publishedMs;
    if (ageMs < floorMs) {
      tooYoung.push({
        name,
        version,
        reason: `age ${Math.floor(ageMs / DAY_MS)}d < ${minAgeDays}d floor`,
        publishedAt,
      });
    }
  }
  return tooYoung;
}

/** Registry packument lekérés (a scoped névben a `/` karakter %2F-ként kódolt).

A teljes (nem abbreviated/corgi) packument kell: csak az tartalmazza a
verziónkénti `time` publikálási időpontokat. */
export async function fetchPackument(name, registryUrl, fetchImpl) {
  const url = `${registryUrl.replace(/\/$/, "")}/${name.replace("/", "%2F")}`;
  const response = await fetchImpl(url, {
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`registry HTTP ${response.status} for ${name} (${url})`);
  }
  return response.json();
}

/**
 * A fő folyamat. Visszatérési kód: 0 = minden csomag a küszöb felett,
 * 1 = küszöbsértés vagy nem bizonyítható kor, 2 = használati hiba.
 * A `fetchImpl` és `nowMs` injektálható (offline tesztek számára).
 */
export async function runPackageAgeCheck({
  argv = [],
  fetchImpl = (...args) => fetch(...args),
  nowMs = Date.now(),
  lockfilePath = "package-lock.json",
  registryUrl = "https://registry.npmjs.org",
  stdout = console.log,
  stderr = console.error,
} = {}) {
  const args = [...argv];
  let includeDev = false;
  let minAgeDays = DEFAULT_MIN_RELEASE_AGE_DAYS;
  while (args.length > 0) {
    const arg = args.shift();
    if (arg === "--include-dev") includeDev = true;
    else if (arg === "--min-age-days") {
      const next = args.shift();
      if (!next) return 2;
      const parsed = Number.parseInt(next, 10);
      if (!Number.isInteger(parsed) || parsed < 1) return 2;
      minAgeDays = parsed;
    } else return 2;
  }

  let lock;
  try {
    lock = JSON.parse(await readFile(lockfilePath, "utf8"));
  } catch (error) {
    stderr(`check-package-age: cannot read lockfile ${lockfilePath}: ${error.message}`);
    return 1;
  }
  const packages = collectLockedPackages(lock, { includeDev });
  if (packages.length === 0) {
    stderr("check-package-age: no registry-resolved lockfile packages to verify");
    return 1;
  }

  const packuments = new Map();
  for (const { name } of packages) {
    if (packuments.has(name)) continue;
    try {
      packuments.set(name, await fetchPackument(name, registryUrl, fetchImpl));
    } catch (error) {
      stderr(`check-package-age: ${error.message} (floor is fail-closed; rerun the check)`);
      return 1;
    }
  }

  const tooYoung = findTooYoung({ packages, packuments, nowMs, minAgeDays });
  if (tooYoung.length > 0) {
    stderr(
      `check-package-age: ${tooYoung.length} package(s) violate the ${minAgeDays}-day release-age floor:`,
    );
    for (const item of tooYoung) {
      stderr(
        `  ${item.name}@${item.version} — ${item.reason}` +
          (item.publishedAt ? ` (published ${item.publishedAt})` : ""),
      );
    }
    return 1;
  }
  stdout(
    `check-package-age: ${packages.length} locked package(s) verified at or above the ${minAgeDays}-day release-age floor`,
  );
  return 0;
}

const isDirectRun =
  typeof process.argv[1] === "string" &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href;

if (isDirectRun) {
  process.exitCode = await runPackageAgeCheck({ argv: process.argv.slice(2) });
}
