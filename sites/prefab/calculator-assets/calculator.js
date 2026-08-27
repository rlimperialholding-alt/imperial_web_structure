(() => {
  "use strict";

  const TECHNOLOGIES = Object.freeze({
    timber: {
      label: "Favázas könnyűszerkezet",
      netPricePerM2: 630000,
      baseSiteDays: 105,
      baseRisk: 3.0,
      marketFactor: 0.97,
      risks: [
        "Nedvességvédelem és párazárási részletek hibája érzékeny lehet.",
        "A kivitelezői minőség és a faanyag nedvességtartalma erősen befolyásol.",
        "Későbbi átalakítás előtt szerkezeti helyek ellenőrzése szükséges."
      ]
    },
    steel: {
      label: "Fémvázas könnyűszerkezet",
      netPricePerM2: 599500,
      baseSiteDays: 98,
      baseRisk: 3.1,
      marketFactor: 0.96,
      risks: [
        "Hőhidak és rétegrendi csomópontok hibás kialakítása komfortromlást okozhat.",
        "Korrózióvédelem és vágott élek helyszíni kezelése kritikus.",
        "A szakági áttörések előzetes koordinációja különösen fontos."
      ]
    },
    ytong: {
      label: "Ytong falazat",
      netPricePerM2: 659500,
      baseSiteDays: 140,
      baseRisk: 2.8,
      marketFactor: 0.99,
      risks: [
        "Repedésérzékeny csomópontoknál megfelelő áthidalás és hálózás kell.",
        "Nedvességtől védeni kell a falazatot a kivitelezés során.",
        "Nagy terhek rögzítéséhez rendszerazonos dübel és részletterv szükséges."
      ]
    },
    brick: {
      label: "Tégla falazat",
      netPricePerM2: 700000,
      baseSiteDays: 150,
      baseRisk: 2.7,
      marketFactor: 1.0,
      risks: [
        "Hosszabb helyszíni, időjárásnak kitett munkafolyamat.",
        "Sok egymásra épülő szakág miatt nagyobb az ütemezési szórás.",
        "Falazási pontatlanság és hőhidas csomópont helyszíni minőségkockázat."
      ]
    },
    sip: {
      label: "SIP panel",
      netPricePerM2: 610000,
      baseSiteDays: 88,
      baseRisk: 3.0,
      marketFactor: 0.95,
      risks: [
        "A légzárás és a panelkapcsolatok nedvességvédelme döntő.",
        "Gépészeti nyomvonalak és későbbi áttörések korán rögzítendők.",
        "Beszállítói rendszer- és szerelőcsapat-függőség jelentkezhet."
      ]
    },
    liapor: {
      label: "Liapor előregyártott agyagbeton",
      netPricePerM2: 760000,
      baseSiteDays: 100,
      baseRisk: 2.6,
      marketFactor: 1.0,
      risks: [
        "Daruzható, teherautóval biztonságosan megközelíthető telek szükséges.",
        "A gyártás előtt magas tervkészültség és korai döntészárás kell.",
        "Panelcsatlakozások és szakági áttörések gyártmánytervi koordinációt igényelnek."
      ]
    }
  });

  const QUALITY = Object.freeze({
    basic: { label: "alap", cost: 1.0, market: 0.94 },
    mid: { label: "közép", cost: 1.16, market: 1.0 },
    premium: { label: "prémium", cost: 1.31, market: 1.1 }
  });

  const REGIONS = Object.freeze({
    budapest: { label: "Budapest", build: 1.06, marketPerM2: 1450000, uncertainty: 0.12 },
    agglomeration: { label: "Budapesti agglomeráció / Pest", build: 1.04, marketPerM2: 1100000, uncertainty: 0.13 },
    balaton: { label: "Balaton / Velencei-tó prémium térség", build: 1.06, marketPerM2: 1250000, uncertainty: 0.15 },
    "major-city": { label: "kiemelt vármegyeszékhely", build: 1.03, marketPerM2: 1180000, uncertainty: 0.14 },
    "county-seat": { label: "egyéb vármegyeszékhely", build: 1.01, marketPerM2: 960000, uncertainty: 0.15 },
    town: { label: "egyéb város", build: 1.0, marketPerM2: 820000, uncertainty: 0.17 },
    village: { label: "község / vidéki térség", build: 1.02, marketPerM2: 670000, uncertainty: 0.2 }
  });

  const MODIFIERS = Object.freeze({
    storeys: {
      single: { cost: 1, time: 1 },
      double: { cost: 1.09, time: 1.08 }
    },
    terrain: {
      flat: { cost: 1, time: 1, risk: 0 },
      mild: { cost: 1.05, time: 1.14, risk: 0.25 },
      steep: { cost: 1.14, time: 1.38, risk: 0.7 }
    },
    access: {
      good: { cost: 1, time: 1, risk: 0 },
      limited: { cost: 1.04, time: 1.12, risk: 0.25 },
      hard: { cost: 1.1, time: 1.32, risk: 0.65 }
    },
    roof: {
      gable: { cost: 1, time: 1 },
      hip: { cost: 1.06, time: 1.12 },
      flat: { cost: 1.05, time: 1.18 },
      complex: { cost: 1.14, time: 1.32 }
    },
    foundation: {
      standard: { cost: 1, time: 1, risk: 0 },
      unknown: { cost: 1.06, time: 1.12, risk: 0.45 },
      water: { cost: 1.08, time: 1.12, risk: 0.5 },
      deep: { cost: 1.18, time: 1.35, risk: 0.65 }
    },
    utilities: {
      ready: { cost: 1, time: 1, risk: 0 },
      partial: { cost: 1.04, time: 1.12, risk: 0.15 },
      absent: { cost: 1.1, time: 1.35, risk: 0.4 }
    },
    mep: {
      standard: { cost: 1, time: 1 },
      enhanced: { cost: 1.08, time: 1.16 },
      complex: { cost: 1.15, time: 1.38 }
    },
    windows: {
      standard: { cost: 1, time: 1 },
      custom: { cost: 1.05, time: 1.16 }
    },
    season: {
      normal: { cost: 1, time: 1, risk: 0 },
      wet: { cost: 1.03, time: 1.16, risk: 0.15 },
      winter: { cost: 1.08, time: 1.36, risk: 0.35 }
    },
    changes: {
      low: { cost: 1, time: 1, risk: 0 },
      average: { cost: 1.04, time: 1.1, risk: 0.2 },
      high: { cost: 1.1, time: 1.28, risk: 0.6 }
    },
    design: {
      ready: { prepDays: 25, risk: 0 },
      concept: { prepDays: 55, risk: 0.2 },
      none: { prepDays: 90, risk: 0.5 }
    }
  });

  const LABELS = Object.freeze({
    storeys: { single: "földszintes", double: "kétszintes" },
    terrain: { flat: "sík", mild: "enyhén lejtős", steep: "erősen lejtős" },
    access: { good: "jól megközelíthető", limited: "korlátozott hozzáférésű", hard: "nehezen daruzható" },
    roof: { gable: "nyeregtető", hip: "kontyolt tető", flat: "lapostető", complex: "összetett magastető" }
  });

  const calculatorForm = document.querySelector("#calculator-form");
  const leadForm = document.querySelector("#lead-form");
  const results = document.querySelector("#results");
  const comparisonBody = document.querySelector("#comparison-body");
  const selectedTechHeading = document.querySelector("#selected-tech-heading");
  const resultSummary = document.querySelector("#result-summary");
  const editCalculation = document.querySelector("#edit-calculation");
  const calculationPayload = document.querySelector("#calculation-payload");
  const formStatus = document.querySelector("#form-status");
  const formFallbackNote = document.querySelector("#form-fallback-note");
  const config = window.PREFAB_CALCULATOR_CONFIG || {};

  const moneyFormatter = new Intl.NumberFormat("hu-HU", {
    style: "currency",
    currency: "HUF",
    maximumFractionDigits: 0
  });
  const numberFormatter = new Intl.NumberFormat("hu-HU", { maximumFractionDigits: 1 });

  let latestCalculation = null;

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function roundTo(value, step) {
    return Math.round(value / step) * step;
  }

  function areaFactor(area) {
    if (area < 80) return 1.08;
    if (area <= 120) return 1;
    if (area <= 180) return 0.97;
    return 0.95;
  }

  function marketAreaFactor(area) {
    if (area < 80) return 1.06;
    if (area > 220) return 0.9;
    if (area > 160) return 0.95;
    return 1;
  }

  function technologyLogistics(technologyKey, access) {
    if (technologyKey === "liapor") {
      if (access === "hard") return { cost: 1.05, time: 1.08, risk: 0.4 };
      if (access === "limited") return { cost: 1.02, time: 1.04, risk: 0.15 };
    }
    if (technologyKey === "sip" && access === "hard") {
      return { cost: 1.02, time: 1.04, risk: 0.15 };
    }
    return { cost: 1, time: 1, risk: 0 };
  }

  function uncertaintyFor(inputs, technologyKey) {
    let uncertainty = 0.08;
    if (inputs.design === "concept") uncertainty += 0.03;
    if (inputs.design === "none") uncertainty += 0.06;
    if (inputs.foundation === "unknown") uncertainty += 0.04;
    if (inputs.foundation === "deep" || inputs.foundation === "water") uncertainty += 0.03;
    if (inputs.access === "hard") uncertainty += 0.03;
    if (inputs.changes === "high") uncertainty += 0.05;
    if (technologyKey === "liapor" && inputs.access !== "good") uncertainty += 0.01;
    return clamp(uncertainty, 0.08, 0.24);
  }

  function calculateTechnology(technologyKey, inputs) {
    const tech = TECHNOLOGIES[technologyKey];
    const quality = QUALITY[inputs.quality];
    const region = REGIONS[inputs.region];
    const logistics = technologyLogistics(technologyKey, inputs.access);

    const costModifiers = [
      areaFactor(inputs.area),
      quality.cost,
      region.build,
      MODIFIERS.storeys[inputs.storeys].cost,
      MODIFIERS.terrain[inputs.terrain].cost,
      MODIFIERS.access[inputs.access].cost,
      MODIFIERS.roof[inputs.roof].cost,
      MODIFIERS.foundation[inputs.foundation].cost,
      MODIFIERS.utilities[inputs.utilities].cost,
      MODIFIERS.mep[inputs.mep].cost,
      MODIFIERS.windows[inputs.windows].cost,
      MODIFIERS.season[inputs.season].cost,
      MODIFIERS.changes[inputs.changes].cost,
      logistics.cost
    ];
    const costFactor = costModifiers.reduce(
      (total, modifier) => total + (modifier - 1),
      1
    );

    const netCost = roundTo(inputs.area * tech.netPricePerM2 * costFactor, 100000);
    const grossCost = roundTo(netCost * (1 + inputs.vat), 100000);
    const uncertainty = uncertaintyFor(inputs, technologyKey);
    const costLow = roundTo(netCost * (1 - uncertainty * 0.45), 100000);
    const costHigh = roundTo(netCost * (1 + uncertainty), 100000);

    const timeModifiers = [
      MODIFIERS.storeys[inputs.storeys].time,
      MODIFIERS.terrain[inputs.terrain].time,
      MODIFIERS.access[inputs.access].time,
      MODIFIERS.roof[inputs.roof].time,
      MODIFIERS.foundation[inputs.foundation].time,
      MODIFIERS.utilities[inputs.utilities].time,
      MODIFIERS.mep[inputs.mep].time,
      MODIFIERS.windows[inputs.windows].time,
      MODIFIERS.season[inputs.season].time,
      MODIFIERS.changes[inputs.changes].time,
      logistics.time
    ];
    const timeFactor = timeModifiers.reduce(
      (total, modifier) => total + (modifier - 1),
      1
    );

    const workDays = Math.round(
      tech.baseSiteDays * timeFactor + MODIFIERS.design[inputs.design].prepDays
    );
    const timeLow = Math.round(workDays * 0.9);
    const timeHigh = Math.round(workDays * 1.15);

    const riskScore = clamp(
      tech.baseRisk +
        MODIFIERS.terrain[inputs.terrain].risk +
        MODIFIERS.access[inputs.access].risk +
        MODIFIERS.foundation[inputs.foundation].risk +
        MODIFIERS.utilities[inputs.utilities].risk +
        MODIFIERS.season[inputs.season].risk +
        MODIFIERS.changes[inputs.changes].risk +
        MODIFIERS.design[inputs.design].risk +
        logistics.risk,
      1,
      5
    );

    const siteMarketFactor =
      (inputs.terrain === "steep" ? 0.92 : inputs.terrain === "mild" ? 0.98 : 1) *
      (inputs.access === "hard" ? 0.9 : inputs.access === "limited" ? 0.97 : 1);
    const buildingMarketValue = roundTo(
      inputs.area *
        region.marketPerM2 *
        quality.market *
        tech.marketFactor *
        marketAreaFactor(inputs.area) *
        siteMarketFactor,
      100000
    );
    const marketLow = roundTo(buildingMarketValue * (1 - region.uncertainty), 100000);
    const marketHigh = roundTo(buildingMarketValue * (1 + region.uncertainty), 100000);
    const totalMarketValue = buildingMarketValue + inputs.landValue;

    return {
      key: technologyKey,
      label: tech.label,
      netCost,
      grossCost,
      costLow,
      costHigh,
      uncertainty,
      workDays,
      timeLow,
      timeHigh,
      riskScore,
      riskLabel: riskLabel(riskScore),
      risks: tech.risks,
      buildingMarketValue,
      marketLow,
      marketHigh,
      totalMarketValue,
      valueCostRatio: buildingMarketValue / netCost
    };
  }

  function riskLabel(score) {
    if (score <= 2.4) return "alacsony";
    if (score <= 3.2) return "közepes";
    if (score <= 4) return "emelkedett";
    return "magas";
  }

  function readInputs() {
    const data = new FormData(calculatorForm);
    return {
      area: Number(data.get("area")),
      storeys: String(data.get("storeys")),
      technology: String(data.get("technology")),
      quality: String(data.get("quality")),
      vat: Number(data.get("vat")),
      landValue: Number(data.get("landValue") || 0) * 1000000,
      region: String(data.get("region")),
      terrain: String(data.get("terrain")),
      access: String(data.get("access")),
      roof: String(data.get("roof")),
      foundation: String(data.get("foundation")),
      utilities: String(data.get("utilities")),
      mep: String(data.get("mep")),
      windows: String(data.get("windows")),
      season: String(data.get("season")),
      design: String(data.get("design")),
      changes: String(data.get("changes"))
    };
  }

  function comparisonClasses(a, b, direction, tolerance) {
    const scale = Math.max(Math.abs(a), Math.abs(b), 1);
    if (Math.abs(a - b) / scale <= tolerance) {
      return ["is-neutral", "is-neutral"];
    }
    const aWins = direction === "lower" ? a < b : a > b;
    return aWins ? ["is-good", "is-bad"] : ["is-bad", "is-good"];
  }

  function formatMoney(value) {
    return moneyFormatter.format(roundTo(value, 100000));
  }

  function formatMillions(value) {
    return `${numberFormatter.format(value / 1000000)} M Ft`;
  }

  function formatDays(value) {
    const months = value / 21.7;
    return `${value} munkanap · kb. ${numberFormatter.format(months)} hónap`;
  }

  function differenceText(value, reference, unit, lowerIsBetter) {
    const difference = value - reference;
    const absolute = Math.abs(difference);
    if (Math.abs(difference) / Math.max(reference, 1) <= 0.02) {
      return "Nincs érdemi eltérés";
    }
    const favorable = lowerIsBetter ? difference < 0 : difference > 0;
    const direction = difference < 0 ? "kevesebb" : "több";
    const formatted =
      unit === "money" ? formatMillions(absolute) : `${Math.round(absolute)} munkanappal`;
    return `${formatted} ${direction}${favorable ? "" : ""}`;
  }

  function metricContent(value, detail, risks) {
    const fragment = document.createDocumentFragment();
    const strong = document.createElement("span");
    strong.className = "metric-value";
    strong.textContent = value;
    fragment.append(strong);

    if (detail) {
      const small = document.createElement("span");
      small.className = "metric-detail";
      small.textContent = detail;
      fragment.append(small);
    }

    if (risks?.length) {
      const list = document.createElement("ul");
      list.className = "risk-list";
      risks.forEach((risk) => {
        const item = document.createElement("li");
        item.textContent = risk;
        list.append(item);
      });
      fragment.append(list);
    }

    return fragment;
  }

  function addComparisonRow(label, selected, liapor, classes) {
    const row = document.createElement("tr");
    const heading = document.createElement("th");
    heading.scope = "row";
    heading.textContent = label;

    const selectedCell = document.createElement("td");
    selectedCell.className = classes[0];
    selectedCell.append(metricContent(selected.value, selected.detail, selected.risks));

    const liaporCell = document.createElement("td");
    liaporCell.className = classes[1];
    liaporCell.append(metricContent(liapor.value, liapor.detail, liapor.risks));

    row.append(heading, selectedCell, liaporCell);
    comparisonBody.append(row);
  }

  function buildRows(selected, liapor, inputs) {
    comparisonBody.replaceChildren();

    addComparisonRow(
      "Nettó kivitelezési becslés",
      {
        value: formatMoney(selected.netCost),
        detail: `${formatMoney(selected.netCost / inputs.area)} / m², azonos kulcsrakész műszaki tartalom`
      },
      {
        value: formatMoney(liapor.netCost),
        detail: `${formatMoney(liapor.netCost / inputs.area)} / m², azonos kulcsrakész műszaki tartalom`
      },
      comparisonClasses(selected.netCost, liapor.netCost, "lower", 0.02)
    );

    if (inputs.vat > 0) {
      addComparisonRow(
        `Bruttó összeg (${Math.round(inputs.vat * 100)}% áfa)`,
        { value: formatMoney(selected.grossCost), detail: "A kiválasztott áfakulccsal számolva" },
        { value: formatMoney(liapor.grossCost), detail: "A kiválasztott áfakulccsal számolva" },
        comparisonClasses(selected.grossCost, liapor.grossCost, "lower", 0.02)
      );
    }

    addComparisonRow(
      "Korai költségtartomány",
      {
        value: `${formatMillions(selected.costLow)} – ${formatMillions(selected.costHigh)}`,
        detail: `±${Math.round(selected.uncertainty * 100)}% felső bizonytalanság; nettó`
      },
      {
        value: `${formatMillions(liapor.costLow)} – ${formatMillions(liapor.costHigh)}`,
        detail: `±${Math.round(liapor.uncertainty * 100)}% felső bizonytalanság; nettó`
      },
      comparisonClasses(selected.netCost, liapor.netCost, "lower", 0.02)
    );

    addComparisonRow(
      "Teljes projektidő",
      {
        value: formatDays(selected.workDays),
        detail: `${selected.timeLow}–${selected.timeHigh} munkanapos becsült sáv, tervezéssel együtt`
      },
      {
        value: formatDays(liapor.workDays),
        detail: `${liapor.timeLow}–${liapor.timeHigh} munkanapos becsült sáv, tervezéssel együtt`
      },
      comparisonClasses(selected.workDays, liapor.workDays, "lower", 0.04)
    );

    const costDifferencePercent = Math.abs(
      ((selected.netCost - liapor.netCost) / liapor.netCost) * 100
    );
    addComparisonRow(
      "Költségeltérés a Liaporhoz képest",
      {
        value: differenceText(selected.netCost, liapor.netCost, "money", true),
        detail: `${numberFormatter.format(costDifferencePercent)}% eltérés az összehasonlítási alaphoz képest`
      },
      {
        value: "Összehasonlítási alap",
        detail: "A Liapor oszlop az azonos paraméterű referenciaprojekt."
      },
      comparisonClasses(selected.netCost, liapor.netCost, "lower", 0.02)
    );

    addComparisonRow(
      "Összesített kockázat",
      {
        value: `${selected.riskLabel} · ${numberFormatter.format(selected.riskScore)}/5`,
        detail: "Technológia, helyszín, tervkészültség és ütemezés együtt"
      },
      {
        value: `${liapor.riskLabel} · ${numberFormatter.format(liapor.riskScore)}/5`,
        detail: "Technológia, helyszín, tervkészültség és ütemezés együtt"
      },
      comparisonClasses(selected.riskScore, liapor.riskScore, "lower", 0.04)
    );

    addComparisonRow(
      "Kiemelt technológiai kockázatok",
      { value: "Fő ellenőrzési pontok", risks: selected.risks },
      { value: "Fő ellenőrzési pontok", risks: liapor.risks },
      ["is-neutral", "is-neutral"]
    );

    addComparisonRow(
      "Épület becsült piaci értéke",
      {
        value: formatMoney(selected.buildingMarketValue),
        detail: `${formatMillions(selected.marketLow)} – ${formatMillions(selected.marketHigh)} régiós sáv, telek nélkül`
      },
      {
        value: formatMoney(liapor.buildingMarketValue),
        detail: `${formatMillions(liapor.marketLow)} – ${formatMillions(liapor.marketHigh)} régiós sáv, telek nélkül`
      },
      comparisonClasses(selected.buildingMarketValue, liapor.buildingMarketValue, "higher", 0.03)
    );

    if (inputs.landValue > 0) {
      addComparisonRow(
        "Teljes ingatlanérték telekkel",
        {
          value: formatMoney(selected.totalMarketValue),
          detail: `${formatMoney(inputs.landValue)} megadott telekértékkel`
        },
        {
          value: formatMoney(liapor.totalMarketValue),
          detail: `${formatMoney(inputs.landValue)} megadott telekértékkel`
        },
        comparisonClasses(selected.totalMarketValue, liapor.totalMarketValue, "higher", 0.03)
      );
    }

    addComparisonRow(
      "Piaci érték / nettó építési költség",
      {
        value: `${numberFormatter.format(selected.valueCostRatio)}×`,
        detail: "Becsült épületérték osztva a nettó kivitelezési kerettel"
      },
      {
        value: `${numberFormatter.format(liapor.valueCostRatio)}×`,
        detail: "Becsült épületérték osztva a nettó kivitelezési kerettel"
      },
      comparisonClasses(selected.valueCostRatio, liapor.valueCostRatio, "higher", 0.03)
    );
  }

  function buildCalculationSummary(selected, liapor, inputs) {
    const vatText = inputs.vat > 0 ? `${Math.round(inputs.vat * 100)}% áfa` : "nettó";
    return [
      `Prefab technológiai kalkuláció – 2026. júliusi árbázis`,
      `Projekt: ${inputs.area} m², ${LABELS.storeys[inputs.storeys]}, ${QUALITY[inputs.quality].label} műszaki színvonal`,
      `Helyszín: ${REGIONS[inputs.region].label}; ${LABELS.terrain[inputs.terrain]} telek; ${LABELS.access[inputs.access]}; ${LABELS.roof[inputs.roof]}`,
      `Áfakezelés: ${vatText}`,
      ``,
      `${selected.label}:`,
      `- nettó kivitelezési becslés: ${formatMoney(selected.netCost)}`,
      `- teljes projektidő: ${selected.workDays} munkanap`,
      `- kockázat: ${selected.riskLabel} (${numberFormatter.format(selected.riskScore)}/5)`,
      `- épület becsült piaci értéke: ${formatMoney(selected.buildingMarketValue)}`,
      ``,
      `${liapor.label}:`,
      `- nettó kivitelezési becslés: ${formatMoney(liapor.netCost)}`,
      `- teljes projektidő: ${liapor.workDays} munkanap`,
      `- kockázat: ${liapor.riskLabel} (${numberFormatter.format(liapor.riskScore)}/5)`,
      `- épület becsült piaci értéke: ${formatMoney(liapor.buildingMarketValue)}`,
      ``,
      `Az eredmény tájékoztató becslés, nem ajánlat és nem hivatalos értékbecslés.`
    ].join("\n");
  }

  function renderCalculation(inputs) {
    const selected = calculateTechnology(inputs.technology, inputs);
    const liapor = calculateTechnology("liapor", inputs);
    latestCalculation = { inputs, selected, liapor };

    selectedTechHeading.textContent = selected.label;
    resultSummary.textContent =
      `${inputs.area} m²-es, ${LABELS.storeys[inputs.storeys]} ház · ` +
      `${REGIONS[inputs.region].label} · ${QUALITY[inputs.quality].label} színvonal`;
    buildRows(selected, liapor, inputs);
    calculationPayload.value = buildCalculationSummary(selected, liapor, inputs);
    results.hidden = false;
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  calculatorForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!calculatorForm.reportValidity()) return;
    renderCalculation(readInputs());
  });

  editCalculation.addEventListener("click", () => {
    calculatorForm.scrollIntoView({ behavior: "smooth", block: "start" });
    document.querySelector("#area").focus({ preventScroll: true });
  });

  function leadPayload() {
    const data = new FormData(leadForm);
    return {
      name: String(data.get("name") || "").trim(),
      phone: String(data.get("phone") || "").trim(),
      email: String(data.get("email") || "").trim(),
      consent: data.get("consent") === "on",
      calculation: calculationPayload.value || "A látogató még nem futtatott kalkulációt.",
      source: "prefab-technology-calculator",
      priceBase: "2026-07"
    };
  }

  function setFormStatus(message, isError = false) {
    formStatus.textContent = message;
    formStatus.classList.toggle("is-error", isError);
  }

  function openEmailFallback(payload) {
    const recipient = config.recipientEmail || "info@prefab.hu";
    const subject = `Díjmentes mérnöki konzultáció – ${payload.name}`;
    const body = [
      `Név: ${payload.name}`,
      `Telefonszám: ${payload.phone}`,
      `E-mail: ${payload.email}`,
      ``,
      payload.calculation
    ].join("\n");
    const mailto =
      `mailto:${encodeURIComponent(recipient)}?subject=${encodeURIComponent(subject)}` +
      `&body=${encodeURIComponent(body)}`;
    window.location.href = mailto;
    setFormStatus("A kitöltött levél megnyílt. Kérjük, a levelezőprogramban nyomd meg a Küldés gombot.");
  }

  leadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!leadForm.reportValidity()) return;
    if (leadForm.elements.website.value) return;

    const payload = leadPayload();
    const submitButton = leadForm.querySelector('button[type="submit"]');
    submitButton.disabled = true;
    setFormStatus("Küldés előkészítése…");

    try {
      if (!config.leadEndpoint) {
        openEmailFallback(payload);
        return;
      }

      const headers = { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" };
      if (config.csrfToken) headers["X-CSRF-Token"] = config.csrfToken;
      const response = await fetch(config.leadEndpoint, {
        method: "POST",
        credentials: "same-origin",
        headers,
        body: JSON.stringify(payload)
      });

      if (!response.ok) throw new Error("Lead endpoint rejected the request.");
      setFormStatus("Köszönjük! Az igényed megérkezett, hamarosan felvesszük veled a kapcsolatot.");
      leadForm.reset();
    } catch {
      setFormStatus("Az automatikus küldés most nem sikerült; megnyitjuk a kitöltött e-mailt.", true);
      openEmailFallback(payload);
    } finally {
      window.setTimeout(() => {
        submitButton.disabled = false;
      }, 1500);
    }
  });

  if (config.leadEndpoint) {
    formFallbackNote.hidden = true;
  }
})();
