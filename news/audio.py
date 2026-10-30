"""Digest-item audio — gTTS synthesis uploaded to GCS under a
content-addressed name, played back through a 7-day v4 signed
URL (docs/plans/news_audio_plan.md).

Stateless by design: the blob name derives from the spoken
text, so repeat requests dedup on ``blob.exists()`` and no
database rows are needed. ``GCS_AUDIO_BUCKET`` unset disables
the feature (AudioGenerationError -> 502 from the view)."""
import hashlib
import logging
import os
import re
import tempfile
from datetime import timedelta

import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage
from google.oauth2 import service_account
from gtts import gTTS
from gtts.lang import tts_langs
from langdetect import (
    DetectorFactory,
    LangDetectException,
    detect_langs,
)

from django.conf import settings

logger = logging.getLogger('news')

# langdetect is probabilistic — a fixed seed keeps the pick
# stable across processes and retries.
DetectorFactory.seed = 0

# Only these voices are synthesized; a stronger non-whitelist
# guess still loses to a whitelisted one.
_LANGUAGES = {'lv', 'en'}
_DEFAULT_LANG = 'lv'
_MAX_TEXT_CHARS = 5000
_GCS_SCOPE = 'https://www.googleapis.com/auth/devstorage.read_write'


class AudioGenerationError(Exception):
    """Pipeline failure (auth, synthesis, upload, signing) —
    the view maps it to 502; bad input stays ValueError/400."""


def _sanitize(text):
    """Strip constructs gTTS would read aloud awkwardly: URLs
    become 'web link', decoration runs are dropped, whitespace
    collapses. Runs before language detection."""
    text = re.sub(r'https?://\S+', 'web link', text)
    text = re.sub(r'[-_~=*]{2,}', '', text)
    return ' '.join(text.split())


def _detect_lang(text):
    """Whitelist argmax over detect_langs() guesses — NOT
    detect()'s global winner: a Latvian lead can guess a
    related language first while 'lv' still outranks 'en'."""
    try:
        guesses = detect_langs(text)
    except LangDetectException:
        return _DEFAULT_LANG
    hits = [g for g in guesses if g.lang in _LANGUAGES]
    if not hits:
        return _DEFAULT_LANG
    return max(hits, key=lambda g: g.prob).lang


def _blob_name(text, lang, filename):
    """audio/<name>.mp3 — content-addressed on the spoken text
    so identical clips dedup. The optional filename prefix only
    aids bucket browsing; the sha suffix is the dedup key."""
    digest = hashlib.sha256(f'{lang}:{text}'.encode()).hexdigest()[:16]
    if filename:
        safe = re.sub(r'[^A-Za-z0-9._-]+', '-', filename)
        safe = safe.strip('-.')[:80]
        if safe:
            return f'audio/{safe}-{digest}.mp3'
    return f'audio/{digest}.mp3'


def text_to_audio(text, lang=None, filename=None):
    """Synthesize ``text`` to an mp3 in the GCS audio bucket
    and return a 7-day v4 signed GET URL for it.

    ``lang`` pins the gTTS voice; ``None`` auto-detects within
    the {'lv', 'en'} whitelist. ``filename`` optionally prefixes
    the object name for bucket browsing. Existing blobs are
    re-signed, never re-synthesized (dedup + retry safety).

    Raises ValueError on bad input and AudioGenerationError on
    any pipeline failure."""
    if not isinstance(text, str) or not text:
        raise ValueError('text is required')
    if len(text) > _MAX_TEXT_CHARS:
        raise ValueError('text is too long')
    if filename is not None and not isinstance(filename, str):
        raise ValueError('filename must be a string')
    clean = _sanitize(text)
    if not clean:
        raise ValueError('text has no speakable content')
    if lang is None:
        lang = _detect_lang(clean)
    elif not isinstance(lang, str):
        raise ValueError('lang must be a string')
    elif lang not in tts_langs():
        # Region tags like 'lv-LV' are not gTTS keys — a
        # supported base language speaks with its plain voice.
        base = lang.split('-')[0]
        if base in tts_langs():
            lang = base
        else:
            raise ValueError(f'unsupported lang: {lang}')
    bucket_name = settings.GCS_AUDIO_BUCKET
    if not bucket_name:
        raise AudioGenerationError('GCS storage not configured')
    blob_name = _blob_name(clean, lang, filename)
    try:
        credentials, _ = google.auth.default(scopes=[_GCS_SCOPE])
        credentials.refresh(Request())
        client = storage.Client(credentials=credentials)
        blob = client.bucket(bucket_name).blob(blob_name)
        if not blob.exists():
            with tempfile.NamedTemporaryFile(
                suffix='.mp3', delete=False
            ) as tmp:
                path = tmp.name
            try:
                gTTS(text=clean, lang=lang).save(path)
                blob.upload_from_filename(
                    path, content_type='audio/mpeg', timeout=30
                )
            finally:
                os.unlink(path)
        sign_kwargs = {}
        if not isinstance(credentials, service_account.Credentials):
            # Metadata-server creds (Cloud Run) cannot sign
            # locally — generate_signed_url must go through the
            # IAM signBlob API instead. User ADC creds carry no
            # service_account_email to impersonate.
            email = getattr(
                credentials, 'service_account_email', None
            )
            if not email:
                raise AudioGenerationError(
                    'credentials cannot sign URLs: no '
                    'service_account_email'
                )
            sign_kwargs = {
                'service_account_email': email,
                'access_token': credentials.token,
            }
        return blob.generate_signed_url(
            version='v4',
            expiration=timedelta(days=7),
            method='GET',
            **sign_kwargs,
        )
    except Exception as exc:
        raise AudioGenerationError(str(exc)) from exc
