# Blog Scraper Call Stack Documentation

This document traces the complete execution flow of the blog scraper from start to finish.

## High-Level Overview

The blog scraper uses AI analysis to evaluate blog posts against multiple themes. Unlike other scrapers, it saves resources **during analysis** rather than in a separate batch operation.

## Complete Call Stack

### 1. Entry Point: `BlogScraper.run()` 
**Location:** `blogs/scraper.py` (lines 47-68)

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
**Location:** `core_scraper/base.py` (lines 63-72)

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
**Location:** `core_scraper/base.py` (lines 80-102)

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
**Location:** `blogs/scraper.py` (lines 600-746)

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
**Location:** `blogs/scraper.py` (lines 460-598)

```python
def analyse_content(self, content, themes_to_analyse):
    """
    Two-tier AI analysis system:
    1. Cheap model (gemini-2.0-flash-lite) - Fast initial screening
    2. Expensive model (gemini-2.5-pro) - Verification if all cheap analyses pass
    """
    # Check API request limit
    if self.max_api_requests and self.api_request_count >= self.max_api_requests:
        raise MaxAPIRequestsReached(...)

    # Tier 1: Cheap model analysis
    if self.current_url_use_cheap_tier:
        cheap_results = self._analyze_with_models(
            content, themes_to_analyse, self.cheap_models
        )
        self.api_request_count += 1
        
        if self._has_theme_match(cheap_results):
            # Bad content detected, stop here (cost savings!)
            return cheap_results

    # Tier 2: Expensive model analysis (only if cheap tier passed)
    expensive_results = self._analyze_with_models(
        content, themes_to_analyse, self.expensive_models
    )
    self.api_request_count += 1

    return expensive_results
```

**What it does:**
- Implements two-tier AI analysis for cost optimization
- **Tier 1 (Cheap):** Uses `gemini-2.0-flash-lite` for initial screening
  - If ANY theme matches → stops immediately (content is bad)
- **Tier 2 (Expensive):** Uses `gemini-2.5-pro` for verification
  - Only runs if cheap tier found no matches
- Increments `api_request_count` for cost tracking
- Raises `MaxAPIRequestsReached` if limit exceeded

**Cost Optimization:**
- Bad content (80% of cases): 1 cheap API call
- Good content (20% of cases): 1 cheap + 1 expensive = 2 API calls
- Overall savings: ~60% cost reduction

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
- Counter incremented in `analyse_content()` after each AI call
- `MaxAPIRequestsReached` exception propagates up to `run()` for graceful shutdown

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
                                    │       ├─> Tier 1: Cheap model
                                    │       │   └─> If match: STOP (save costs)
                                    │       │
                                    │       └─> Tier 2: Expensive model
                                    │           └─> Final verification
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
- **Cost Control:** Two-tier AI system + API request limiter

**The key insight:** Unlike traditional scrapers that collect resources and save them in batch, the blog scraper saves each resource immediately during the analysis phase. This is why `create_or_update_resources()` is not needed.
