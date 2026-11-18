"use strict";
/*
 * Light / dark / system theme selection and motion preference.
 * Only the viewer's display preferences are persisted (never tokens).
 */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.StudioTheme = api;
})(typeof self !== "undefined" ? self : this, function (root) {
  const THEME_KEY = "studio.theme";
  const MOTION_KEY = "studio.flowAnimation";
  const CHOICES = ["light", "dark", "system"];

  function storage() {
    try { return root.localStorage || null; } catch { return null; }
  }

  function read(key, fallback) {
    try { const value = storage()?.getItem(key); return value === null || value === undefined ? fallback : value; }
    catch { return fallback; }
  }

  function write(key, value) {
    try { storage()?.setItem(key, value); } catch { /* storage unavailable: preference is per-session */ }
  }

  function systemPrefersDark() {
    try { return Boolean(root.matchMedia && root.matchMedia("(prefers-color-scheme: dark)").matches); }
    catch { return false; }
  }

  function prefersReducedMotion() {
    try { return Boolean(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches); }
    catch { return false; }
  }

  function resolve(choice, prefersDark) {
    if (choice === "light" || choice === "dark") return choice;
    return prefersDark ? "dark" : "light";
  }

  function preference() {
    const value = read(THEME_KEY, "system");
    return CHOICES.includes(value) ? value : "system";
  }

  function apply(choice) {
    const doc = root.document;
    const resolved = resolve(choice, systemPrefersDark());
    if (doc) {
      doc.documentElement.dataset.theme = resolved;
      doc.documentElement.dataset.themePreference = choice;
      doc.documentElement.style.colorScheme = resolved;
    }
    return resolved;
  }

  function setPreference(choice) {
    const value = CHOICES.includes(choice) ? choice : "system";
    write(THEME_KEY, value);
    return apply(value);
  }

  function animationEnabled() {
    return read(MOTION_KEY, "on") !== "off" && !prefersReducedMotion();
  }

  function setAnimation(enabled) { write(MOTION_KEY, enabled ? "on" : "off"); }
  function animationPreference() { return read(MOTION_KEY, "on") !== "off"; }

  function watchSystem(callback) {
    try {
      const query = root.matchMedia("(prefers-color-scheme: dark)");
      query.addEventListener("change", () => { if (preference() === "system") callback(apply("system")); });
    } catch { /* matchMedia unavailable */ }
  }

  // Apply as early as possible to avoid a flash of the wrong theme.
  if (root.document) apply(preference());

  return {
    THEME_KEY, MOTION_KEY, CHOICES, resolve, preference, setPreference, apply,
    animationEnabled, animationPreference, setAnimation, prefersReducedMotion, watchSystem,
  };
});
