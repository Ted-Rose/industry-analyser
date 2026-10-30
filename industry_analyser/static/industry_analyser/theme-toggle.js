/* Dependency-free theme toggle for Django-rendered pages
   (landing, news) — mirrors frontend/src/shared/theme.ts:
   localStorage['theme'] = 'auto'|'light'|'dark' (the same key
   Django 5.2 admin uses), `.dark` class + data-theme on <html>,
   and the dual theme-color metas emitted by _theme_head.html.
   Clicking any [data-theme-toggle] button cycles
   auto → light → dark and stamps 'Theme: <mode>' on it. */
(function () {
  'use strict';

  var COLORS = { light: '#ffffff', dark: '#18181b' };
  var ORDER = ['auto', 'light', 'dark'];
  var DARK_QUERY = '(prefers-color-scheme: dark)';

  function stored() {
    try {
      var t = localStorage.getItem('theme');
      return ORDER.indexOf(t) !== -1 ? t : 'auto';
    } catch (e) {
      return 'auto';
    }
  }

  function isDark(theme) {
    return (
      theme === 'dark' ||
      (theme === 'auto' && window.matchMedia(DARK_QUERY).matches)
    );
  }

  function syncMetas(theme, dark) {
    var metas = document.querySelectorAll(
      'meta[name="theme-color"]'
    );
    for (var i = 0; i < metas.length; i += 1) {
      if (theme === 'auto') {
        var scheme = i === 0 ? 'light' : 'dark';
        metas[i].media = '(prefers-color-scheme: ' + scheme + ')';
        metas[i].content = COLORS[scheme];
      } else {
        metas[i].content = dark ? COLORS.dark : COLORS.light;
        metas[i].media = i === 0 ? 'all' : 'not all';
      }
    }
  }

  /* Stamp the label without wiping a nested icon: a
     [data-theme-label] child wins, otherwise the first text
     node is rewritten (or appended when the button holds only
     elements). */
  function labelButton(button, text) {
    button.setAttribute('aria-label', text);
    var label = button.querySelector('[data-theme-label]');
    if (label) {
      label.textContent = text;
      return;
    }
    for (var i = 0; i < button.childNodes.length; i += 1) {
      if (button.childNodes[i].nodeType === Node.TEXT_NODE) {
        button.childNodes[i].nodeValue = text;
        return;
      }
    }
    button.appendChild(document.createTextNode(text));
  }

  function apply(theme) {
    var dark = isDark(theme);
    var root = document.documentElement;
    root.classList.toggle('dark', dark);
    root.dataset.theme = theme;
    syncMetas(theme, dark);
    var buttons = document.querySelectorAll('[data-theme-toggle]');
    for (var i = 0; i < buttons.length; i += 1) {
      labelButton(buttons[i], 'Theme: ' + theme);
    }
  }

  function setTheme(theme) {
    try {
      localStorage.setItem('theme', theme);
    } catch (e) {
      /* Storage can be unavailable — apply anyway. */
    }
    apply(theme);
  }

  document.addEventListener('click', function (event) {
    var target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    if (target.closest('[data-theme-toggle]')) {
      var next = ORDER[(ORDER.indexOf(stored()) + 1) %
        ORDER.length];
      setTheme(next);
    }
  });

  window
    .matchMedia(DARK_QUERY)
    .addEventListener('change', function () {
      if (stored() === 'auto') {
        apply('auto');
      }
    });

  window.addEventListener('storage', function (event) {
    if (event.key === 'theme' || event.key === null) {
      apply(stored());
    }
  });

  apply(stored());
})();
