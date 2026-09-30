# Blog Scraper Call Stack Documentation

This document traces the complete execution flow of the blog scraper from start to finish.

## High-Level Overview

The blog scraper uses AI analysis to evaluate blog posts against multiple themes. Unlike other scrapers, it saves resources **during analysis** rather than in a separate batch operation.

## Complete Call Stack

### 1. Entry Point: `BlogScraper.run()` 
**Location:** `blogs/scraper.py` (lines 63-83)

```python
def run(self):
    """Override run to handle API request limit."""
    try:
        for search_url in self.get_search_urls():
            # TODO: Blog scrapper will return empty list - fix logic gap
            self.scrape_portal(search_url)
    except MaxAPIRequestsReached:
        # Logs summary and exits gracefully
        ...
```

**What it does:**
- Iterates through all search URLs (blog listing pages)
- Calls `scrape_portal()` for each URL
- Handles `MaxAPIRequestsReached` exception for cost control
- **Note:** Does NOT call `create_or_update_resources()` because resources are saved during analysis

---

### 2. `BaseScraper.scrape_portal(search_url)`
**Location:** `core_scraper/base.py` (lines 66-80)

```python
def scrape_portal(self, search_url):
    search_results = self.make_request(search_url)
    parsed_results = self.parse_results(search_response)

    if not parsed_results:
        return

    pruned_results = self.remove_redundant_results(parsed_results)

    return self.extract_resources(pruned_results)
```

**What it does:**
- Makes HTTP request to the listing page
- Parses HTML to extract blog post links
- Removes duplicates
- Calls `extract_resources()` to process each link
- **Returns:** Empty list (when `ai_analysis=True`)

---

### 3. `BaseScraper.extract_resources(search_results)`
**Location:** `core_scraper/base.py` (lines 88-107)

```python
def extract_resources(self, search_results) -> List[Model]:
    if self.enrich_search_results:
        resources = []
        for result in search_results:
            enriched_result = self.enrich_result(result)

            if not enriched_result:
                self.excluded_resources.append(result)
                continue

            if self.ai_analysis:
                self.analyse_and_save_resource(enriched_result, result)
            else:
                resource = self.initiate_resource(enriched_result)
                resources.append(resource)

                if len(resources) >= 2:
                    break

        # TODO: Blog scrapper will return empty list - fix logic gap
        return resources
    else:
        return self.initiate_resources(search_results)
```

**What it does:**
- For each blog post link in the listing:
  - Calls `enrich_result()` to fetch the full blog post page
  - Since `self.ai_analysis = True` (set in `BlogScraper.__init__`):
    - Calls `analyse_and_save_resource()` **← Resources saved here!**
    - Does NOT append to `resources` list
- **Returns:** Empty list (because `ai_analysis=True`)
- **Note:** This is why `create_or_update_resources()` is never needed

---

### 4. `BlogScraper.analyse_and_save_resource(http_response, url)`
**Location:** `blogs/scraper.py` (lines 382-528)

```python
def analyse_and_save_resource(self, http_response, url):
    """Analyzes a page against missing themes and saves the results."""
    page_data = self.extract_resource(url, http_response)

    # 1. Get or create the Page
    page, created = Page.objects.get_or_create(
        url=page_data['url'],
        defaults={'title': page_data.get('title', 'No Title Found')}
    )
    if created:
        logger.info("Created new page: %s", page.title)

    # 1.5 Update content characteristics
    page.has_video = page_data.get('has_video', False)
    page.video_count = page_data.get('video_count', 0)
    page.image_count = page_data.get('image_count', 0)
    page.text_length = page_data.get('text_length', 0)
    page.save()  # ← Page object saved to database here!

    # Check if media-heavy and skip AI if so
    if page.is_media_heavy:
        # Mark as kid_unfriendly without AI analysis
        ...
        return page

    # 2. Determine which themes need analysis
    # (checks existing PageAnalysis records)
    ...

    # 3. Call the AI for analysis on the missing themes
    analysis_json = self.analyse_content(
        page_data['content'], themes_to_analyse
    )

    # 4. Save the new analysis results
    for theme_name, results in analysis_json.items():
        theme = Theme.objects.get(name=theme_name)
        PageAnalysis.objects.update_or_create(  # ← Analysis saved here!
            page=page,
            theme=theme,
            defaults={
                'confidence_score': results.get('confidence_score'),
                'reasoning_summary': results.get('reasoning_summary'),
                'theme_match': results.get(theme_name),
                'model': results.get('model'),
                'model_tier': results.get('model_tier', 'expensive')
            }
        )

    return page
```

**What it does:**
1. **Extracts page data** (title, content, images, videos, etc.)
2. **Creates or gets the `Page` object** using `Page.objects.get_or_create()`
3. **Saves the `Page` object** with `page.save()` ← **DATABASE WRITE #1**
4. **Checks if media-heavy** (videos or many images with little text)
   - If yes: marks as `kid_unfriendly` and skips AI analysis
5. **Determines which themes need analysis** (skips already-analyzed themes)
6. **Calls AI analysis** via `analyse_content()`
7. **Saves `PageAnalysis` results** using `update_or_create()` ← **DATABASE WRITE #2**

**Database Operations:**
- `Page.objects.get_or_create()` - Creates or retrieves Page
- `page.save()` - Saves/updates Page with content metadata
- `PageAnalysis.objects.update_or_create()` - Saves AI analysis results (one per theme)

---

### 5. `BlogScraper.analyse_content(content, themes_to_analyse)`
**Location:** `blogs/scraper.py`

```python
def analyse_content(self, article_content, themes_to_analyse):
    """Delegates to ThemeAnalyzer (blogs/analyzer.py)."""
    use_cheap = getattr(self, 'current_url_use_cheap_tier', True)
    return self._analyzer.analyse(
        article_content, themes_to_analyse, use_cheap_tier=use_cheap
    )
```

**What it does:**
- Thin wrapper around `ThemeAnalyzer.analyse()` (built in
  `__init__` with a `GeminiDirectBackend` and the
  `load_theme_prompt` prompt loader)
- Implements two-tier AI analysis for cost optimization:
  - **Tier 1 (Cheap):** `gemini-2.5-flash-lite` — after the first
    theme yields a parsed result, returns; if it matched → stop
    (content is bad)
  - **Tier 2 (Expensive):** `gemini-2.5-pro` — runs over all themes,
    stops at the first match; only runs when the cheap pass found no
    match or `use_cheap_tier` is off for the URL
- The per-theme loop (prompt load → backend call → JSON cleanup →
  early exits) lives in `ThemeAnalyzer._analyse_role()`
- The Gemini model lists, retries, request-cap check and prompt
  assembly (`instructions + "\n\n---\n\n" + content`) live in
  `GeminiDirectBackend.generate()` (`blogs/ai_backends.py`)
- Raises `MaxAPIRequestsReached` (from `blogs/ai_backends.py`,
  re-exported here) if the limit is exceeded

**Cost Optimization:**
- Bad content: 1 cheap API call
- Good content: 1 cheap + 1 expensive per theme until a match

---

### 6. `GeminiDirectBackend.generate(...)`
**Location:** `blogs/ai_backends.py`

```python
def generate(self, template_key, template_text, input_text, role):
    full_prompt = template_text + "\n\n---\n\n" + input_text
    client = genai.Client(api_key=self.api_key)
    for model_name in MODELS_BY_ROLE[role]:
        for attempt in range(RETRIES_PER_MODEL):
            self._check_cap()          # may raise MaxAPIRequestsReached
            self.counter.count += 1    # every attempt sent counts
            response = client.models.generate_content(...)
            # prompt_feedback / candidate finish_reason blocks ->
            #   AnalyzerResponse(blocked=True)
            # empty text / errors -> retry, then next model
    return AnalyzerResponse(text=..., model_name=...)  # or None
```

**What it does:**
- Temporary `AnalyzerBackend` (PR-3); replaced by `JobClientBackend`
  in PR-6
- `MODELS_BY_ROLE` holds the model lists that used to be hardcoded
  in `analyse_content` (`cheap`/`expensive`)
- Shares an `APIRequestCounter` with the scraper so the cap counts
  **every attempt sent** (including failed calls) and
  `scraper.api_request_count` still works for the run summary
- Detects both prompt-level blocks (`prompt_feedback.block_reason`)
  and candidate-level safety finishes (`finish_reason` in
  `{SAFETY, PROHIBITED_CONTENT, BLOCKLIST, SPII}`)
- Non-retryable API errors (400/401/403/404) skip retries and move
  to the next model

---

## Key Architectural Points

### Why `create_or_update_resources()` is Not Needed

1. **`ai_analysis = True`** in `BlogScraper.__init__`
2. When `ai_analysis=True`, `extract_resources()` calls `analyse_and_save_resource()` directly
3. `analyse_and_save_resource()` saves the `Page` object immediately (line 617)
4. `extract_resources()` returns an empty list (line 99 in base.py)
5. Therefore, `create_or_update_resources()` would receive an empty list

### Database Writes Happen in Two Places

1. **`Page` objects:** Saved in `analyse_and_save_resource()` at line 605-617
2. **`PageAnalysis` objects:** Saved in `analyse_and_save_resource()` at line 726-736

### API Request Limiting

- Configured via `max_api_requests` in `config.yaml`
- Held in a shared `APIRequestCounter` (`blogs/ai_backends.py`);
  `GeminiDirectBackend` increments it for **every attempt sent**
  (successful, blocked or failed)
- `scraper.api_request_count` is a property over that counter, so
  `run()` still logs the total in the cap-reached summary
- `MaxAPIRequestsReached` (defined in `blogs/ai_backends.py`,
  imported by `blogs/scraper.py`) propagates up to `run()` for
  graceful shutdown

### Per-URL Tier Configuration

- URLs can specify `use_cheap_tier: true/false` in config
- Allows skipping cheap tier for high-quality sources
- Optimizes costs based on content source quality

---

## Flow Diagram

```
BlogScraper.run()
    │
    ├─> get_search_urls() [yields listing URLs]
    │
    └─> BaseScraper.scrape_portal(url)
            │
            ├─> make_request(url) [fetch listing page]
            ├─> parse_results() [extract blog post links]
            ├─> remove_redundant_results() [dedupe]
            │
            └─> BaseScraper.extract_resources(links)
                    │
                    └─> FOR EACH link:
                            │
                            ├─> enrich_result(link) [fetch full blog post]
                            │
                            └─> BlogScraper.analyse_and_save_resource()
                                    │
                                    ├─> extract_resource() [parse HTML]
                                    │
                                    ├─> Page.objects.get_or_create() ← DB WRITE
                                    ├─> page.save() ← DB WRITE
                                    │
                                    ├─> Check if media-heavy
                                    │   └─> If yes: mark kid_unfriendly, skip AI
                                    │
                                    ├─> Determine themes to analyze
                                    │
                                    ├─> analyse_content(content, themes)
                                    │       │
                                    │       └─> ThemeAnalyzer.analyse()
                                    │           (blogs/analyzer.py)
                                    │               │
                                    │               ├─> Tier 1 'cheap':
                                    │               │   prompt_loader ->
                                    │               │   GeminiDirectBackend
                                    │               │   .generate() ->
                                    │               │   genai API
                                    │               │   └─> return after 1st
                                    │               │       parsed theme;
                                    │               │       match -> STOP
                                    │               │
                                    │               └─> Tier 2 'expensive':
                                    │                   all themes, STOP at
                                    │                   first match
                                    │
                                    └─> FOR EACH theme result:
                                            │
                                            └─> PageAnalysis.objects.update_or_create() ← DB WRITE
```

---

## Summary

- **Entry:** `BlogScraper.run()`
- **Main Loop:** Iterates through listing URLs
- **Resource Processing:** Each blog post is analyzed and saved immediately
- **Database Writes:** Happen during analysis, not in batch
- **Return Value:** Empty list (by design when `ai_analysis=True`)
- **Cost Control:** Two-tier AI system (`ThemeAnalyzer` +
  `GeminiDirectBackend`) + shared `APIRequestCounter` limiter

**The key insight:** Unlike traditional scrapers that collect resources and save them in batch, the blog scraper saves each resource immediately during the analysis phase. This is why `create_or_update_resources()` is not needed.
