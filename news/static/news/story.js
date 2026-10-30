// Inline story reader for /news/: a click on .story-toggle
// fetches /news/story/<pk>/fragment/ into the sibling
// .story-slot; .story-switch links inside an injected
// fragment swap the outlet without a page load. Delegated
// handlers survive fragment re-injection. No JS = the toggle
// button simply does nothing.
(function () {
  'use strict';

  function loadFragment(url, slot) {
    fetch(url)
      .then(function (response) {
        if (!response.ok) {
          throw new Error('HTTP ' + response.status);
        }
        return response.text();
      })
      .then(function (html) {
        slot.innerHTML = html;
        slot.dataset.loaded = '1';
        slot.hidden = false;
      })
      .catch(function () {
        slot.innerHTML =
          '<p class="muted">Neizdevās ielādēt stāstu.</p>';
        slot.hidden = false;
      });
  }

  document.addEventListener('click', function (event) {
    var toggle = event.target.closest('.story-toggle');
    if (toggle) {
      var slot =
        toggle.parentElement.querySelector('.story-slot');
      if (!slot) {
        return;
      }
      if (!slot.hidden) {
        slot.hidden = true; // re-click collapses
      } else if (slot.dataset.loaded) {
        slot.hidden = false;
      } else {
        loadFragment(
          '/news/story/' + toggle.dataset.story + '/fragment/',
          slot
        );
      }
      return;
    }
    var link = event.target.closest('a.story-switch');
    if (link) {
      var host = link.closest('.story-slot');
      if (host) {
        event.preventDefault();
        loadFragment(link.href, host);
      }
    }
  });
})();
