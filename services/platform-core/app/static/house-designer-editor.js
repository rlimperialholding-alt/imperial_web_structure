(() => {
  "use strict";

  const runtime = document.getElementById("hd-editor-runtime");
  if (!runtime) return;

  const sessionId = runtime.dataset.sessionId;
  const scopeKey = runtime.dataset.offlineScope;
  const csrfToken = runtime.dataset.csrfToken;
  const commandUrl = `/api/v1/house-designer/sessions/${encodeURIComponent(sessionId)}/commands`;
  const htmlCommandPath = `/house-designer/sessions/${sessionId}/commands`;
  const forms = Array.from(
    document.querySelectorAll(`form.hd-command[action="${htmlCommandPath}"]`),
  );
  const statusBox = document.getElementById("hd-save-status");
  const statusText = statusBox?.querySelector("span");
  const statusDetail = statusBox?.querySelector("small");
  const conflictBox = document.getElementById("hd-conflict");
  const conflictMessage = document.getElementById("hd-conflict-message");
  const reloadButton = document.getElementById("hd-conflict-reload");
  const discardButton = document.getElementById("hd-conflict-discard");
  const autosaveTimers = new WeakMap();
  let operationChain = Promise.resolve();
  let databasePromise;
  let cryptoKeyPromise;

  const commandFields = {
    set_footprint: ["levelId", "widthMm", "depthMm"],
    add_level: ["levelType"],
    remove_level: ["levelId"],
    add_room: [
      "levelId", "roomId", "name", "function", "xMm", "yMm", "widthMm", "depthMm",
    ],
    move_room: ["levelId", "roomId", "xMm", "yMm"],
    resize_room: ["levelId", "roomId", "widthMm", "depthMm"],
    remove_room: ["levelId", "roomId"],
    set_room_function: ["levelId", "roomId", "name", "function"],
    set_roof: ["levelId", "roofType", "pitchDeg"],
    set_north: ["northAngleDeg"],
    set_site: ["municipalityCode", "postalCode", "city", "address", "parcelNumber"],
    set_configuration: [
      "constructionTechnology", "completionLevel", "roofType", "foundationType", "slabType",
      "stairType", "technicalPackage",
    ],
    restore_revision: ["targetRevisionId"],
  };
  const integerFields = new Set([
    "widthMm", "depthMm", "xMm", "yMm", "pitchDeg", "northAngleDeg",
  ]);

  class EditorError extends Error {
    constructor(code, message, { transient = false, conflict = false } = {}) {
      super(message);
      this.code = code;
      this.transient = transient;
      this.conflict = conflict;
    }
  }

  function setStatus(state, message, detail = "") {
    if (!statusBox || !statusText || !statusDetail) return;
    statusBox.dataset.state = state;
    statusText.textContent = message;
    statusDetail.textContent = detail;
  }

  function showConflict(message) {
    if (conflictMessage) conflictMessage.textContent = message;
    if (conflictBox) conflictBox.hidden = false;
    setStatus(
      "error",
      "Mentési konfliktus – felhasználói döntés szükséges.",
      "A helyi függő módosításokat a rendszer nem írja rá automatikusan az új szerververzióra.",
    );
  }

  function hideConflict() {
    if (conflictBox) conflictBox.hidden = true;
  }

  function requestResult(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("IndexedDB request failed"));
    });
  }

  function transactionDone(transaction) {
    return new Promise((resolve, reject) => {
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error || new Error("IndexedDB failed"));
      transaction.onabort = () => reject(transaction.error || new Error("IndexedDB aborted"));
    });
  }

  function openDatabase() {
    if (databasePromise) return databasePromise;
    databasePromise = new Promise((resolve, reject) => {
      const request = indexedDB.open("imperial-house-designer-v1", 1);
      request.onupgradeneeded = () => {
        const database = request.result;
        if (!database.objectStoreNames.contains("keys")) {
          database.createObjectStore("keys", { keyPath: "id" });
        }
        if (!database.objectStoreNames.contains("pending")) {
          database.createObjectStore("pending", { keyPath: "id" });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("IndexedDB unavailable"));
      request.onblocked = () => reject(new Error("IndexedDB upgrade blocked"));
    });
    return databasePromise;
  }

  async function getCryptoKey() {
    if (cryptoKeyPromise) return cryptoKeyPromise;
    cryptoKeyPromise = (async () => {
      const database = await openDatabase();
      let transaction = database.transaction("keys", "readonly");
      let completed = transactionDone(transaction);
      let stored = await requestResult(transaction.objectStore("keys").get("pending-aes-gcm"));
      await completed;
      if (stored?.key) return stored.key;

      const key = await crypto.subtle.generateKey(
        { name: "AES-GCM", length: 256 },
        false,
        ["encrypt", "decrypt"],
      );
      transaction = database.transaction("keys", "readwrite");
      completed = transactionDone(transaction);
      try {
        transaction.objectStore("keys").add({ id: "pending-aes-gcm", key });
        await completed;
        return key;
      } catch (error) {
        if (error?.name !== "ConstraintError") throw error;
        transaction = database.transaction("keys", "readonly");
        completed = transactionDone(transaction);
        stored = await requestResult(transaction.objectStore("keys").get("pending-aes-gcm"));
        await completed;
        if (!stored?.key) throw error;
        return stored.key;
      }
    })();
    return cryptoKeyPromise;
  }

  async function encryptEnvelope(envelope) {
    const key = await getCryptoKey();
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const plaintext = new TextEncoder().encode(JSON.stringify(envelope));
    const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, plaintext);
    return {
      id: crypto.randomUUID(),
      createdAt: envelope.queuedAt,
      iv,
      ciphertext,
    };
  }

  async function decryptRecord(record) {
    const key = await getCryptoKey();
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: record.iv },
      key,
      record.ciphertext,
    );
    return JSON.parse(new TextDecoder().decode(plaintext));
  }

  async function allPendingRecords() {
    const database = await openDatabase();
    const transaction = database.transaction("pending", "readonly");
    const completed = transactionDone(transaction);
    const rows = await requestResult(transaction.objectStore("pending").getAll());
    await completed;
    return rows.sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  }

  async function scopedPending() {
    const result = [];
    for (const record of await allPendingRecords()) {
      let envelope;
      try {
        envelope = await decryptRecord(record);
      } catch (error) {
        throw new EditorError(
          "pending_decryption_failed",
          "A titkosított helyi mentési sor nem olvasható; az adatot nem töröltük.",
        );
      }
      if (envelope.scopeKey === scopeKey && envelope.sessionId === sessionId) {
        result.push({ record, envelope });
      }
    }
    return result;
  }

  async function deletePending(ids) {
    if (!ids.length) return;
    const database = await openDatabase();
    const transaction = database.transaction("pending", "readwrite");
    const completed = transactionDone(transaction);
    const store = transaction.objectStore("pending");
    ids.forEach((id) => store.delete(id));
    await completed;
  }

  async function queueEnvelope(envelope) {
    let superseded = [];
    if (envelope.source === "autosave") {
      superseded = (await scopedPending())
        .filter(({ envelope: row }) => (
          row.source === "autosave" && row.commandType === envelope.commandType
        ))
        .map(({ record }) => record.id);
    }
    const encrypted = await encryptEnvelope(envelope);
    const database = await openDatabase();
    const transaction = database.transaction("pending", "readwrite");
    const completed = transactionDone(transaction);
    transaction.objectStore("pending").add(encrypted);
    await completed;
    await deletePending(superseded);
  }

  function formPayload(form, commandType) {
    const allowed = commandFields[commandType];
    if (!allowed) throw new EditorError("unknown_command", "Ismeretlen szerkesztési művelet.");
    const formData = new FormData(form);
    const payload = {};
    for (const name of allowed) {
      const raw = formData.get(name);
      if (raw === null || String(raw).trim() === "") continue;
      payload[name] = integerFields.has(name) ? Number(raw) : String(raw).trim();
      if (integerFields.has(name) && !Number.isInteger(payload[name])) {
        throw new EditorError("invalid_number", `Hibás egész szám: ${name}.`);
      }
    }
    return payload;
  }

  function envelopeFromForm(form, source) {
    const commandType = form.elements.command_type.value;
    return {
      version: 1,
      scopeKey,
      sessionId,
      commandId: form.elements.command_id.value || crypto.randomUUID(),
      commandType,
      payload: formPayload(form, commandType),
      changeSummary: form.elements.change_summary?.value || "",
      baseRevisionId: runtime.dataset.revisionId,
      baseRevisionNo: Number(runtime.dataset.revisionNo),
      baseCanonicalSha256: runtime.dataset.canonicalSha256,
      source,
      queuedAt: new Date().toISOString(),
    };
  }

  function errorMessage(body, fallback) {
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail.message === "string") return detail.message;
    return fallback;
  }

  async function sendEnvelope(envelope) {
    let response;
    try {
      response = await fetch(commandUrl, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
          "Idempotency-Key": envelope.commandId,
          "If-Match": envelope.baseCanonicalSha256,
        },
        body: JSON.stringify({
          baseRevisionId: envelope.baseRevisionId,
          commandType: envelope.commandType,
          payload: envelope.payload,
          changeSummary: envelope.changeSummary,
        }),
      });
    } catch (error) {
      throw new EditorError("network_error", "A szerver nem érhető el.", { transient: true });
    }

    let body = null;
    try {
      body = await response.json();
    } catch (error) {
      body = null;
    }
    if (!response.ok) {
      const code = body?.detail?.code || `http_${response.status}`;
      throw new EditorError(
        code,
        errorMessage(body, `A mentés sikertelen (${response.status}).`),
        {
          transient: response.status === 502 || response.status === 503 || response.status === 504,
          conflict: response.status === 409,
        },
      );
    }
    if (!body?.revision?.revisionId || !body?.revision?.canonicalSha256) {
      throw new EditorError("invalid_response", "A szerver hiányos mentési választ adott.");
    }
    return body;
  }

  function acceptServerState(design) {
    runtime.dataset.revisionId = design.revision.revisionId;
    runtime.dataset.revisionNo = String(design.revision.revisionNo);
    runtime.dataset.canonicalSha256 = design.revision.canonicalSha256;
    for (const form of forms) {
      form.elements.base_revision_id.value = design.revision.revisionId;
      form.elements.base_canonical_sha256.value = design.revision.canonicalSha256;
      form.elements.command_id.value = crypto.randomUUID();
    }
  }

  async function pendingCountStatus() {
    const count = (await scopedPending()).length;
    if (count) {
      setStatus(
        "pending",
        `${count} titkosított módosítás helyben várakozik.`,
        "A sor az internetkapcsolat visszatérésekor ugyanazzal az idempotencia-azonosítóval folytatódik.",
      );
    } else {
      setStatus("saved", "Minden módosítás mentve.", "Nincs függő helyi mentés.");
    }
    return count;
  }

  async function flushQueuedInner() {
    const pending = await scopedPending();
    if (!pending.length || !navigator.onLine) {
      await pendingCountStatus();
      return { processed: false, reload: false };
    }

    let currentRevisionId = runtime.dataset.revisionId;
    let currentRevisionNo = Number(runtime.dataset.revisionNo);
    let currentSha = runtime.dataset.canonicalSha256;
    const acceptedBases = new Set([`${currentRevisionId}|${currentSha}`]);
    let processed = false;
    let reload = false;

    for (let index = 0; index < pending.length; index += 1) {
      const { record, envelope } = pending[index];
      const queuedBase = `${envelope.baseRevisionId}|${envelope.baseCanonicalSha256}`;
      if (!acceptedBases.has(queuedBase)) {
        showConflict(
          "A függő módosítás másik tervverzióból indult. A rendszer nem egyesíti automatikusan a két változatot.",
        );
        return { processed, reload: false };
      }

      const rebased = {
        ...envelope,
        baseRevisionId: currentRevisionId,
        baseRevisionNo: currentRevisionNo,
        baseCanonicalSha256: currentSha,
      };
      setStatus("pending", "Függő módosítások biztonságos mentése…", `${index + 1}/${pending.length}`);
      let design;
      try {
        design = await sendEnvelope(rebased);
      } catch (error) {
        if (error.conflict) {
          showConflict(error.message);
          return { processed, reload: false };
        }
        if (error.transient) {
          await pendingCountStatus();
          return { processed, reload: false };
        }
        throw error;
      }

      await deletePending([record.id]);
      processed = true;
      reload ||= envelope.source === "explicit";
      const previousBase = `${currentRevisionId}|${currentSha}`;
      currentRevisionId = design.revision.revisionId;
      currentRevisionNo = Number(design.revision.revisionNo);
      currentSha = design.revision.canonicalSha256;
      acceptedBases.add(previousBase);
      acceptedBases.add(`${currentRevisionId}|${currentSha}`);
      acceptServerState(design);

      if (currentRevisionNo !== rebased.baseRevisionNo + 1 && index + 1 < pending.length) {
        showConflict(
          "Az első függő parancs visszaigazolása közben további szerververzió jelent meg. A hátralévő módosításokat nem alkalmaztuk automatikusan.",
        );
        return { processed, reload: false };
      }
    }
    hideConflict();
    await pendingCountStatus();
    return { processed, reload };
  }

  function runSerial(action) {
    operationChain = operationChain.then(action, action);
    return operationChain.catch((error) => {
      setStatus("error", "A módosítás nincs elmentve.", error.message || "Ismeretlen hiba.");
    });
  }

  async function saveForm(form, source) {
    if (!form.reportValidity()) return;
    let envelope;
    try {
      envelope = envelopeFromForm(form, source);
    } catch (error) {
      setStatus("error", "A módosítás nincs elmentve.", error.message);
      return;
    }

    const pending = await scopedPending();
    if (!navigator.onLine || pending.length) {
      await queueEnvelope(envelope);
      await pendingCountStatus();
      if (navigator.onLine) {
        const result = await flushQueuedInner();
        if (result.reload) window.location.reload();
      }
      return;
    }

    setStatus("pending", source === "autosave" ? "Automatikus mentés…" : "Mentés…", "");
    try {
      const design = await sendEnvelope(envelope);
      acceptServerState(design);
      hideConflict();
      setStatus("saved", "Minden módosítás mentve.", `Aktuális tervverzió: v${design.revision.revisionNo}.`);
      if (source === "explicit") window.location.reload();
    } catch (error) {
      if (error.conflict) {
        showConflict(error.message);
        return;
      }
      if (error.transient) {
        await queueEnvelope(envelope);
        await pendingCountStatus();
        return;
      }
      throw error;
    }
  }

  const supported = Boolean(
    window.indexedDB
      && window.crypto?.subtle
      && window.crypto?.randomUUID
      && window.TextEncoder
      && window.TextDecoder,
  );
  if (!supported) {
    setStatus(
      "error",
      "A titkosított helyi mentés ebben a böngészőben nem támogatott.",
      "Online mentéshez használható a gomb; hálózati hiba esetén a rendszer nem tárol tervadatot titkosítatlanul.",
    );
    return;
  }

  for (const form of forms) {
    form.addEventListener("submit", (event) => {
      if (event.defaultPrevented) return;
      event.preventDefault();
      const timer = autosaveTimers.get(form);
      if (timer) clearTimeout(timer);
      runSerial(() => saveForm(form, "explicit"));
    });
    if (form.hasAttribute("data-hd-autosave")) {
      const schedule = () => {
        const existing = autosaveTimers.get(form);
        if (existing) clearTimeout(existing);
        setStatus("pending", "Módosítás vár mentésre…", "Az automatikus mentés legfeljebb 1,2 másodpercen belül indul.");
        autosaveTimers.set(
          form,
          setTimeout(() => {
            autosaveTimers.delete(form);
            runSerial(() => saveForm(form, "autosave"));
          }, 1200),
        );
      };
      form.addEventListener("input", schedule);
      form.addEventListener("change", schedule);
    }
  }

  window.addEventListener("online", () => {
    runSerial(async () => {
      const result = await flushQueuedInner();
      if (result.reload) window.location.reload();
    });
  });
  window.addEventListener("offline", () => {
    setStatus("pending", "Nincs hálózati kapcsolat.", "A következő módosítás csak titkosítva, helyben kerül sorba.");
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "hidden") return;
    for (const form of forms.filter((item) => item.hasAttribute("data-hd-autosave"))) {
      const timer = autosaveTimers.get(form);
      if (!timer) continue;
      clearTimeout(timer);
      autosaveTimers.delete(form);
      runSerial(() => saveForm(form, "autosave"));
    }
  });

  reloadButton?.addEventListener("click", () => window.location.reload());
  discardButton?.addEventListener("click", () => {
    if (!window.confirm("Biztosan elveti ennek a tervnek az összes helyi függő módosítását?")) return;
    runSerial(async () => {
      const ids = (await scopedPending()).map(({ record }) => record.id);
      await deletePending(ids);
      window.location.reload();
    });
  });

  runSerial(async () => {
    await getCryptoKey();
    const result = await flushQueuedInner();
    if (result.reload) window.location.reload();
  });
})();
