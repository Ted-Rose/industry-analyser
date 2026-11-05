// Auto-submit the /news/ digest filter form when the anchor
// date or period changes. Progressive enhancement only — the
// form's "Rādīt" submit button keeps it fully functional with
// JS disabled, so no showPicker() tricks are needed.
(function () {
  'use strict';

  var form = document.querySelector('form.digest-filter');
  if (!form) {
    return;
  }
  form.addEventListener('change', function () {
    form.submit();
  });
})();
