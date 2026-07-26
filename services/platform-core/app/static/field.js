(() => {
  const pill = document.getElementById('connection-pill');
  const setConnection = () => {
    if (!pill) return;
    const online = navigator.onLine;
    pill.textContent = online ? 'Online · azonnali szinkron' : 'Offline · a piszkozat helyben marad';
    pill.classList.toggle('online', online);
    pill.classList.toggle('offline', !online);
  };
  setConnection();
  window.addEventListener('online', setConnection);
  window.addEventListener('offline', setConnection);

  const memoryStorage = new Map();
  const storage = {
    get(key) {
      try { return window.localStorage.getItem(key); }
      catch (_) { return memoryStorage.get(key) ?? null; }
    },
    set(key, value) {
      try { window.localStorage.setItem(key, value); }
      catch (_) { memoryStorage.set(key, value); }
    },
    remove(key) {
      try { window.localStorage.removeItem(key); }
      catch (_) { memoryStorage.delete(key); }
    }
  };

  let deviceId = storage.get('iip-field-device');
  if (!deviceId) {
    deviceId = `FIELD-${globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : Date.now()}`;
    storage.set('iip-field-device', deviceId);
  }
  document.querySelectorAll('.device-id').forEach(el => { el.value = deviceId; });

  document.querySelectorAll('.persist-form').forEach(form => {
    const key = `iip-draft-${form.dataset.draftKey}`;
    const status = form.querySelector('.draft-status');
    const saved = storage.get(key);
    if (saved) {
      try {
        const values = JSON.parse(saved);
        Object.entries(values).forEach(([name, value]) => {
          const field = form.elements.namedItem(name);
          if (field && !field.value) field.value = value;
        });
        if (status) status.textContent = 'Helyi piszkozat visszaállítva.';
      } catch (_) {}
    }
    const save = () => {
      const data = {};
      new FormData(form).forEach((value, name) => { if (name !== 'source_device_id') data[name] = value; });
      storage.set(key, JSON.stringify(data));
      if (status) status.textContent = `Piszkozat mentve: ${new Date().toLocaleTimeString('hu-HU', {hour:'2-digit', minute:'2-digit'})}`;
    };
    form.addEventListener('input', save);
    form.addEventListener('change', save);
    form.addEventListener('submit', () => storage.remove(key));
  });
})();
