// Light or dark. Follows the device until the officer chooses, then remembers.
const KEY = "rahsaaf-theme";

export function currentTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem(KEY);
  } catch {
    // Storage can be blocked; fall back to the device setting.
  }
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
}

export function saveTheme(theme) {
  applyTheme(theme);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Not remembered, but still applied for this visit.
  }
}
