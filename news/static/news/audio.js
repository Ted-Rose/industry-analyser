// Digest audio player for /news/: each item's headline and
// description are synthesized on demand via GET /news/audio/
// (gTTS -> GCS signed URL). On page load the newest digest's
// clips pre-warm through a bounded resolve pool so playback
// feels instant; content-addressed clips make revisits ~free.
// Delegated click handlers match story.js style. When the
// bucket is unconfigured (local dev), the first 502 stops the
// fan-out, unhides the "Audio unavailable" note and buttons
// degrade to an error state on click. No JS = buttons inert.
(function () {
  'use strict';

  var ENDPOINT = '/news/audio/';
  var POOL_SIZE = 3;
  var MAX_TEXT = 2300;

  var cache = {};        // clip key -> Promise<audio_url>
  var poolQueue = [];    // pending resolve jobs
  var poolActive = 0;
  var audioDown = false; // a 502 stopped the pre-warm fan-out
  var clipSeq = 0;
  var playQueue = [];
  var clipToken = 0;   // bumps per dequeued clip
  var player = new Audio();

  // djb2 hex — the server re-hashes anyway, so this only keeps
  // filenames distinct for bucket browsing.
  function hashText(s) {
    var h = 5381;
    for (var i = 0; i < s.length; i += 1) {
      h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
    }
    return h.toString(16);
  }

  function fetchAudio(text, kind) {
    var clipped = text.slice(0, MAX_TEXT);
    var qs = '?text=' + encodeURIComponent(clipped) +
      '&filename=' + encodeURIComponent(
        kind + '-' + hashText(clipped)
      );
    return fetch(ENDPOINT + qs).then(function (response) {
      if (!response.ok) {
        var err = new Error('HTTP ' + response.status);
        err.status = response.status;
        throw err;
      }
      return response.json();
    }).then(function (data) {
      return data.audio_url;
    });
  }

  // One cache entry per clip key guarantees one request per
  // clip; only successes stay cached so a click can retry.
  function ensureAudio(key, text, kind) {
    if (!cache[key]) {
      cache[key] = fetchAudio(text, kind).catch(function (err) {
        delete cache[key];
        throw err;
      });
    }
    return cache[key];
  }

  function pump() {
    while (poolActive < POOL_SIZE && poolQueue.length) {
      var job = poolQueue.shift();
      poolActive += 1;
      ensureAudio(job.key, job.text, job.kind).then(
        function (url) {
          job.resolve(url);
          poolActive -= 1;
          pump();
        },
        function (err) {
          job.reject(err);
          poolActive -= 1;
          pump();
        }
      );
    }
  }

  function resolveClip(key, text, kind, warm) {
    return new Promise(function (resolve, reject) {
      poolQueue.push({
        key: key, text: text, kind: kind, warm: !!warm,
        resolve: resolve, reject: reject
      });
      pump();
    });
  }

  // A 502 means the pipeline is down (e.g. GCS_AUDIO_BUCKET
  // unset) — cancel the remaining warm jobs instead of
  // hammering the endpoint. Real clicks still go through.
  function cancelWarm() {
    audioDown = true;
    poolQueue = poolQueue.filter(function (job) {
      if (job.warm) {
        job.resolve(null);
        return false;
      }
      return true;
    });
    var note = document.querySelector('.audio-note');
    if (note) {
      note.textContent = 'Audio unavailable';
      note.hidden = false;
    }
  }

  function warmClip(key, text, kind) {
    if (audioDown) {
      return Promise.resolve(null);
    }
    var p = resolveClip(key, text, kind, true);
    p.catch(function (err) {
      if (!audioDown && err && err.status === 502) {
        cancelWarm();
      }
    });
    return p;
  }

  function clipId(btn) {
    if (!btn.dataset.clipId) {
      clipSeq += 1;
      btn.dataset.clipId = 'c' + clipSeq;
    }
    return btn.dataset.clipId;
  }

  // One item = title clip then description clip (skipped when
  // the story carries no representative lead).
  function buttonJobs(btn) {
    var id = clipId(btn);
    var jobs = [
      {key: id + '|t', text: btn.dataset.title, kind: 't'}
    ];
    if (btn.dataset.desc) {
      jobs.push({key: id + '|d', text: btn.dataset.desc, kind: 'd'});
    }
    return jobs;
  }

  function setState(btn, state) {
    if (state) {
      btn.dataset.state = state;
    } else {
      delete btn.dataset.state;
    }
  }

  function stopButton() {
    return document.querySelector('.audio-stop');
  }

  // A failing clip trips BOTH the play() rejection and the
  // element 'error' event — only the callback carrying the
  // current clip's token advances, so one failure consumes
  // exactly one queue entry.
  function clipFailed(token) {
    if (token !== clipToken) {
      return;
    }
    playNext();
  }

  function playNext() {
    var url = playQueue.shift();
    if (!url) {
      var stop = stopButton();
      if (stop) {
        stop.hidden = true;
      }
      return;
    }
    clipToken += 1;
    var token = clipToken;
    player.src = url;
    var played = player.play();
    if (played && played.catch) {
      played.catch(function () {
        clipFailed(token);
      });
    }
  }

  function stopPlayback() {
    playQueue = [];
    player.pause();
    player.removeAttribute('src');
    player.load();
    var stop = stopButton();
    if (stop) {
      stop.hidden = true;
    }
  }

  // A play click replaces the current queue: resolve every
  // clip through the pool, drop failures, play in order.
  function startPlayback(jobs, btn) {
    if (!jobs.length) {
      return;
    }
    setState(btn, 'loading');
    stopPlayback();
    Promise.allSettled(jobs.map(function (job) {
      return resolveClip(job.key, job.text, job.kind);
    })).then(function (results) {
      var urls = [];
      results.forEach(function (r) {
        if (r.status === 'fulfilled' && r.value) {
          urls.push(r.value);
        }
      });
      if (!urls.length) {
        setState(btn, 'error');
        return;
      }
      setState(btn, null);
      playQueue = urls;
      var stop = stopButton();
      if (stop) {
        stop.hidden = false;
      }
      playNext();
    });
  }

  function jobsUnder(root) {
    var jobs = [];
    root.querySelectorAll('[data-audio-item]').forEach(
      function (btn) {
        jobs = jobs.concat(buttonJobs(btn));
      }
    );
    return jobs;
  }

  player.addEventListener('ended', playNext);
  player.addEventListener('error', function () {
    clipFailed(clipToken);
  });

  document.addEventListener('click', function (event) {
    var item = event.target.closest('[data-audio-item]');
    if (item) {
      startPlayback(buttonJobs(item), item);
      return;
    }
    var date = event.target.closest('[data-audio-date]');
    if (date) {
      var section = date.closest('.digest');
      if (section) {
        startPlayback(jobsUnder(section), date);
      }
      return;
    }
    var all = event.target.closest('[data-audio-all]');
    if (all) {
      startPlayback(jobsUnder(document), all);
      return;
    }
    if (event.target.closest('.audio-stop')) {
      stopPlayback();
      document.querySelectorAll('.audio-btn[data-state]').forEach(
        function (btn) {
          setState(btn, null);
        }
      );
    }
  });

  // Pre-warm: enqueue title+desc resolve jobs for the newest
  // digest only (no playback) — satisfies "generate on visit"
  // without blocking render.
  document.addEventListener('DOMContentLoaded', function () {
    var newest = document.querySelector('[data-audio-newest]');
    if (!newest) {
      return;
    }
    newest.querySelectorAll('[data-audio-item]').forEach(
      function (btn) {
        buttonJobs(btn).forEach(function (job) {
          warmClip(job.key, job.text, job.kind);
        });
      }
    );
  });
})();
