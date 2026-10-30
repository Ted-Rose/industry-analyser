# News story reader — preference-ordered inline RSS reader

Status: implemented on `feat/news-story-reader`.

Clicking a digest headline on `/news/` expands it inline and
shows the RSS result (title, lead, image) from the reader's
favorite covering outlet. Authenticated users rank news
sources; the ranking decides which outlet's item is shown,
falling back through the rest by `importance_weight`.

## Context (current state)

- `NewsArticle.lead` holds the RSS `<description>` (HTML
  stripped); `image_url` comes from `<enclosure>`. No full
  article body is stored anywhere — display the lead only.
- A "wrap-up" is a `NewsDigestItem` → `NewsStory` → confirmed
  `NewsArticle` members (one per outlet). Confirmed =
  `story_match_status in CONFIRMED_MATCH_STATUSES`
  (`'auto'`/`'manual'`); `'candidate'` members are
  admin-review material — never eligible for display.
- `digest_list.html` renders all digests with an `<ol>` of
  `item.headline` — plain text today, no click target.
- Pages are public; auth exists (LOGIN_URL='/admin/login/').
  Anonymous readers get the default ordering; only
  authenticated users get the preference form.
- Per-user convention (copy from fetcher/models.py
  `CompanyPreference`): `settings.AUTH_USER_MODEL` FK +
  `unique_together` + explicit `db_table`.
- No MEDIA/FileField infra exists in the project — the audio
  table below stores a `file_path` string only; no file
  serving is implemented yet.

## 1. Models (news/models.py)

```python
class NewsSourcePreference(models.Model):
    """A user's ranked favorite news outlets — rank 1 is tried
    first when picking which member article a story shows."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='news_source_preferences',
    )
    source = models.ForeignKey(
        NewsSource,
        on_delete=models.CASCADE,
        related_name='user_preferences',
    )
    rank = models.PositiveSmallIntegerField()

    class Meta:
        db_table = 'news_source_preference'
        unique_together = (('user', 'source'),)
        ordering = ('rank',)


class NewsArticleAudio(models.Model):
    """Audio seam for a future TTS feature — one rendered
    narration of an article's spoken text per engine+voice.
    No generator exists yet; the table and endpoint are the
    contract it will fill."""
    STATUSES = [
        ('pending', 'Pending'),
        ('ready', 'Ready'),
        ('failed', 'Failed'),
    ]
    article = models.ForeignKey(
        NewsArticle, on_delete=models.CASCADE,
        related_name='audio',
    )
    engine = models.CharField(max_length=32)
    voice = models.CharField(max_length=64, blank=True)
    text = models.TextField()
    text_sha256 = models.CharField(max_length=64)
    status = models.CharField(
        max_length=8, choices=STATUSES,
        default='pending', db_index=True,
    )
    file_path = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'news_article_audio'
        unique_together = (('article', 'engine', 'voice'),)
```

Generate the migration with `python manage.py makemigrations
news` and commit the file. Do NOT run `migrate` — the default
DATABASE_URL is production.

## 2. Ordering helpers (news/preferences.py)

```python
def ordered_sources(user):
    """Enabled NewsSource list: user's preferred sources first
    by rank asc, then the rest by importance_weight desc, pk
    as final tie-break — deterministic. Anonymous or a user
    with no prefs collapses to the weight ordering."""

def ordered_story_articles(story, user):
    """The story's confirmed member articles sorted by their
    source's position in ordered_sources(user). Index 0 is
    'the favorite that covered it' — or the best
    non-favorite when no favorite did."""
```

## 3. Views + urls (news/views.py, news/urls.py)

Function-based views, `app_name = 'news'` already set.

1. `story_fragment` — `GET /news/story/<int:pk>/fragment/`
   (`name='story-fragment'`). Renders the partial template
   `news/_story_card.html` (not a full page). Context:
   `story`, `article` (chosen), `other_articles` (the
   remaining confirmed members, same ordering).
   - Default pick: `ordered_story_articles(story,
     request.user)[0]`; 404 when the story has no confirmed
     members.
   - `?source=<slug>` override: use that source's confirmed
     member when present; when absent, silently fall back to
     the default pick (no 404 — a stale switcher link should
     still show something).
2. `article_audio` — `GET /news/article/<int:pk>/audio/`
   (`name='article-audio'`). Seam only: look up a
   `status='ready'` `NewsArticleAudio` for the article and
   FileResponse its `file_path` if it exists on disk;
   otherwise `Http404`. Effectively always 404 today — the
   URL contract is what matters.
3. `preferences` — `GET|POST /news/preferences/`
   (`name='preferences'`), `@login_required`.
   - GET: `news/preferences.html` — every enabled source as a
     checkbox + rank number input, prefilled from the user's
     rows.
   - POST: take checked sources ordered by their submitted
     rank (ties by input order); delete the user's existing
     rows and bulk_create rank 1..N. Ignore unknown or
     disabled slugs. Redirect back to the same page.

## 4. Templates + JS

- `news/templates/news/_story_card.html` — partial: source
  name, article title, `lead` paragraph, `<img>` with
  `loading="lazy"` when `image_url`, `published_at`, a
  "Lasīt oriģinālu" anchor to `article.link`, and the outlet
  switcher (`other_articles` → links to the fragment URL
  with `?source=<slug>`, class `story-switch`). Audio slot:
  a `ready` `article.audio` row → `<audio controls>` pointing
  at `news:article-audio`; otherwise a disabled
  "Klausīties" button. No `|safe` on feed content.
- `news/templates/news/preferences.html` — extends
  `news/base.html`; the checkbox+rank form above plus a
  short explanation.
- `news/templates/news/digest_list.html` — each
  `<li>{{ item.headline }}</li>` becomes
  `<li><button type="button" class="story-toggle"
  data-story="{{ item.story.pk }}">{{ item.headline }}</button>
  <div class="story-slot" hidden></div></li>`.
- `news/templates/news/base.html` — `{% load static %}` +
  `<script src="{% static 'news/story.js' %}" defer>`;
  header nav: `request.user.is_authenticated` → link to
  `news:preferences`; anonymous → muted "Log in to rank
  portals" link to `news:preferences` (login_required
  redirects to the admin login with ?next).
- `news/static/news/story.js` — ~30 lines vanilla JS:
  delegated click on `.story-toggle` → fetch
  `/news/story/<pk>/fragment/`, inject the HTML into the
  sibling `.story-slot`, unhide; re-click collapses.
  Delegated click on `.story-switch` inside injected
  fragments → preventDefault, fetch, re-inject. No-JS
  fallback: nothing breaks — the button just does nothing;
  optionally degrade the button to a link to the digest
  detail page.
- Minor CSS in base.html for `.story-toggle` (link-like
  button), `.story-slot`, `.story-card img {max-width:100%}`.

## 5. Admin (news/admin.py)

Register `NewsSourcePreference` (list_display
`user`/`rank`/`source`, `list_filter` on source) and
`NewsArticleAudio` (list_display `article`/`engine`/`status`,
readonly_fields on `text`/`error` — it's machine-written).

## 6. Tests (news/tests.py)

Follow existing test style. Cover:
- `ordered_sources`: anonymous → weight order; with prefs →
  preferred first by rank; a preferred-but-disabled source
  drops out.
- `ordered_story_articles`: a 'candidate' member never wins;
  fallback to non-favorite ordering.
- `story_fragment`: 200 renders the preferred article;
  `?source=` override; unknown slug falls back; no confirmed
  members → 404.
- `preferences`: anonymous GET → login redirect; POST writes
  rows in submitted rank order; second POST replaces.
- `article_audio`: 404 for an article without a ready row.

## Verify

    python manage.py makemigrations news   # commit the files
    python manage.py check
    DATABASE_URL=sqlite:///db.sqlite3 python manage.py test news

Never run `migrate`/`sqlmigrate`/bare `test` — .env's
DATABASE_URL is production.

## Out of scope (the audio seam is shaped for these)

- TTS generation: future `news.tts` AIJobSpec via
  `ai_providers.client.JobClient` (cost caps + AIRequest
  logging for free); Latvian engines: Google Cloud TTS
  lv-LV or Gemini TTS.
- File storage: Cloud Run fs is ephemeral — generated audio
  eventually wants GCS via django-storages or generate-
  on-demand with the table as cache.
- Pagination of the digest list; digest_detail reuse of the
  expandable toggle (optional, trivial).
