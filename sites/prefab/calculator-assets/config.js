/**
 * Staging alapbeállítás.
 *
 * Éles integrációkor a leadEndpoint értéke egy same-origin, CSRF-védett
 * végpont legyen, amely JSON POST kérést fogad és szerveroldalon küldi el az
 * üzenetet az info@prefab.hu címre. Üres végpont esetén biztonságos mailto
 * fallback indul.
 */
window.PREFAB_CALCULATOR_CONFIG = Object.freeze({
  leadEndpoint: "",
  privacyPolicyUrl: "https://prefab.hu/privacy-policy",
  recipientEmail: "info@prefab.hu"
});
