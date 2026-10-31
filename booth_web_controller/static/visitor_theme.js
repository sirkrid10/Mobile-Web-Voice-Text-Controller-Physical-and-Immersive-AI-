'use strict';

globalThis.initVisitorTheme = function (btnThemeToggle) {
  function applyTheme(theme) {
    const bodyEl = typeof document !== 'undefined' ? document.body : null;
    const rootEl = typeof document !== 'undefined' ? document.documentElement : null;
    if (bodyEl && bodyEl.setAttribute) {
      if (theme === 'dark') {
        bodyEl.setAttribute('data-theme', 'dark');
        if (rootEl && rootEl.style) rootEl.style.colorScheme = 'dark';
      } else if (bodyEl.removeAttribute) {
        bodyEl.removeAttribute('data-theme');
        if (rootEl && rootEl.style) rootEl.style.colorScheme = 'only light';
      }
    }
  }

  function initTheme() {
    try {
      const savedTheme = typeof localStorage !== 'undefined' ? localStorage.getItem('theme') : null;
      // Start in the cyberpunk theme; keep the visitor's saved preference.
      const initialTheme = savedTheme || 'dark';
      applyTheme(initialTheme);
    } catch (e) {}

    if (btnThemeToggle) {
      btnThemeToggle.addEventListener('click', () => {
        const bodyEl = typeof document !== 'undefined' ? document.body : null;
        const isDark = bodyEl && bodyEl.getAttribute && bodyEl.getAttribute('data-theme') === 'dark';
        const newTheme = isDark ? 'light' : 'dark';
        applyTheme(newTheme);
        try {
          if (typeof localStorage !== 'undefined') localStorage.setItem('theme', newTheme);
        } catch (e) {}
      });
    }
  }

  initTheme();
};
