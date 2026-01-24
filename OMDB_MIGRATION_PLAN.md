# OMDb API Migration Plan for TV Programs Scraper

## Executive Summary

This document provides a detailed plan to migrate the TV Programs scraper from IMDb web scraping to the OMDb API. The migration will improve reliability, reduce scraping complexity, and provide structured data access.

---

## Current Implementation Analysis

### Data Flow
1. **Source**: Tet.lv TV program listings (provides Latvian titles, descriptions, times, channels)
2. **Enrichment**: IMDb web scraping (provides English titles, ratings, descriptions, images)
3. **Storage**: Django `Program` model in PostgreSQL database

### Current IMDb Scraping Process (`get_ratings` method)
1. Searches IMDb with URL-encoded query: `https://www.imdb.com/find/?q={query}`
2. Scrapes search results HTML to find first match
3. Follows link to program detail page
4. Extracts JSON-LD structured data from `<script type="application/ld+json">` tag
5. Parses JSON to extract: title, type, description, image, URL, content_rating, rating_value

### Issues with Current Approach
- ❌ Web scraping is fragile (breaks when HTML changes)
- ❌ Violates IMDb's terms of service
- ❌ Triggers bot detection (requires complex headers)
- ❌ Slow (multiple HTTP requests per program)
- ❌ No rate limiting control

---

## OMDb API Overview

### API Endpoint
```
http://www.omdbapi.com/?apikey={OMDB_KEY}&{parameters}
```

### Key Features
- ✅ Official API with structured JSON responses
- ✅ Free tier: 1,000 requests/day
- ✅ Search by title, IMDb ID, or year
- ✅ Returns ratings, plot, poster, type, etc.
- ✅ Reliable and fast

### API Parameters

#### Search by Title
```
?apikey={key}&t={title}&type={movie|series|episode}&y={year}
```

#### Search Query
```
?apikey={key}&s={search_term}&type={movie|series}&y={year}
```

### Response Fields (Relevant to Our Use Case)
```json
{
  "Title": "The Matrix",
  "Year": "1999",
  "Rated": "R",
  "Released": "31 Mar 1999",
  "Runtime": "136 min",
  "Genre": "Action, Sci-Fi",
  "Director": "Lana Wachowski, Lilly Wachowski",
  "Plot": "A computer hacker learns...",
  "Poster": "https://m.media-amazon.com/images/...",
  "Ratings": [
    {"Source": "Internet Movie Database", "Value": "8.7/10"},
    {"Source": "Rotten Tomatoes", "Value": "88%"}
  ],
  "imdbRating": "8.7",
  "imdbID": "tt0133093",
  "Type": "movie",
  "Response": "True"
}
```

---

## Migration Plan

### Phase 1: Add OMDb API Integration

#### Step 1.1: Update Settings
**File**: `industry_analyser/settings.py`

**Action**: OMDb API key is already added:
```python
OMDB_KEY = private_settings.get('OMDB_KEY')
```

**Status**: ✅ Complete

#### Step 1.2: Create OMDb API Client Method
**File**: `tv_programs/scraper.py`

**Action**: Replace `get_ratings()` method with `get_omdb_data()`

**New Method Signature**:
```python
def get_omdb_data(self, title, year=None, content_type=None):
    """
    Get program metadata from OMDb API.
    
    Args:
        title (str): Program title to search for
        year (str, optional): Release year for better matching
        content_type (str, optional): 'movie' or 'series'
    
    Returns:
        dict: Program metadata or None if not found
    """
```

**Implementation Details**:

1. **Import Django settings**:
   ```python
   from django.conf import settings
   ```

2. **Build API URL**:
   ```python
   base_url = "http://www.omdbapi.com/"
   params = {
       'apikey': settings.OMDB_KEY,
       't': title,  # Search by title
   }
   
   if year:
       params['y'] = year
   
   if content_type:
       params['type'] = content_type  # 'movie' or 'series'
   ```

3. **Make API Request**:
   ```python
   # Use existing self.make_request() or create new method
   response = self.make_request(base_url, params=params)
   ```

4. **Parse JSON Response**:
   ```python
   try:
       data = json.loads(response.data)
       
       if data.get('Response') == 'False':
           logger.info(f"OMDb: No results for '{title}': {data.get('Error')}")
           return None
       
       # Extract IMDb rating
       imdb_rating = data.get('imdbRating')
       if imdb_rating == 'N/A':
           imdb_rating = None
       
       return {
           'title': data.get('Title'),
           'type': data.get('Type'),  # 'movie', 'series', 'episode'
           'description': data.get('Plot'),
           'image': data.get('Poster') if data.get('Poster') != 'N/A' else None,
           'url': f"https://www.imdb.com/title/{data.get('imdbID')}/" if data.get('imdbID') else None,
           'content_rating': data.get('Rated'),  # 'PG', 'R', etc.
           'rating_value': imdb_rating,
           'published_date': data.get('Released'),
           'runtime': data.get('Runtime'),
           'genre': data.get('Genre'),
           'imdb_id': data.get('imdbID'),
       }
   except (json.JSONDecodeError, KeyError) as e:
       logger.error(f"Error parsing OMDb response: {e}")
       return None
   ```

#### Step 1.3: Update `initiate_resource()` Method
**File**: `tv_programs/scraper.py`

**Current Flow**:
```python
def initiate_resource(self, resource_link):
    # Gets IMDb data via get_ratings()
    imdb_search_results = self.get_ratings(...)
```

**New Flow**:
```python
def initiate_resource(self, resource_link):
    # Extract title from Tet.lv data
    title_lv = resource_link.find(class_="tet-font__headline--s").text.strip()
    
    # Translate to English for better OMDb matching
    title_eng = translate_lv_to_eng(title_lv)
    
    # Try to get data from OMDb
    omdb_data = self.get_omdb_data(title_eng, content_type='movie')
    
    # If no results, try without content_type filter
    if not omdb_data:
        omdb_data = self.get_omdb_data(title_eng)
    
    # Validate and return
    return self.validate_and_return(resource_link, omdb_data)
```

#### Step 1.4: Update `process_item()` Method
**File**: `tv_programs/scraper.py`

**Changes Required**:
- Method signature already accepts `imdb_program` (rename to `omdb_data` for clarity)
- The data structure returned by OMDb is similar to current IMDb scraping
- No major changes needed, just ensure field mapping is correct

**Field Mapping**:
```python
{
    "title_lv": title_lv,  # From Tet.lv
    "title_eng": omdb_data["title"],  # From OMDb
    "description_lv": description_lv,  # From Tet.lv
    "description_eng": omdb_data["description"],  # From OMDb (Plot field)
    "image": omdb_data.get("image") or tet_image_url,  # Prefer OMDb poster
    "url": omdb_data["url"],  # IMDb URL from OMDb
    "content_rating": omdb_data.get("content_rating"),  # PG rating
    "rating_value": omdb_data.get("rating_value"),  # IMDb rating
    "published_date": omdb_data.get("published_date"),
    "type": omdb_data.get("type"),
    "match_ratio": combined_match_ratio
}
```

---

### Phase 2: Improve Search Accuracy

#### Step 2.1: Add Year Extraction
**Goal**: Extract release year from Tet.lv data to improve OMDb matching

**Implementation**:
```python
# In initiate_resource() or process_item()
# Look for year in title or description
year_match = re.search(r'\b(19\d{2}|20\d{2})\b', title_lv)
year = year_match.group(1) if year_match else None

omdb_data = self.get_omdb_data(title_eng, year=year, content_type='movie')
```

#### Step 2.2: Implement Fallback Search
**Goal**: If exact title match fails, try search endpoint

**Implementation**:
```python
def get_omdb_data(self, title, year=None, content_type=None):
    # First try: Direct title match
    data = self._omdb_request(t=title, y=year, type=content_type)
    
    if data:
        return data
    
    # Second try: Search and pick best match
    search_results = self._omdb_search(s=title, type=content_type)
    
    if search_results and len(search_results) > 0:
        # Get full details for first result
        best_match = search_results[0]
        return self._omdb_request(i=best_match['imdbID'])
    
    return None

def _omdb_search(self, s, type=None):
    """Search OMDb and return list of results"""
    params = {'apikey': settings.OMDB_KEY, 's': s}
    if type:
        params['type'] = type
    
    response = self.make_request("http://www.omdbapi.com/", params=params)
    data = json.loads(response.data)
    
    if data.get('Response') == 'True':
        return data.get('Search', [])
    
    return []
```

#### Step 2.3: Add Rate Limiting
**Goal**: Respect OMDb's 1,000 requests/day limit

**Implementation**:
```python
import time

class TVProgramScraper(BaseScraper):
    def __init__(self, config=None):
        super().__init__(config)
        self.omdb_request_count = 0
        self.omdb_request_limit = 1000  # Daily limit
        self.last_omdb_request_time = 0
        self.min_request_interval = 0.1  # 100ms between requests
    
    def get_omdb_data(self, title, year=None, content_type=None):
        # Check rate limit
        if self.omdb_request_count >= self.omdb_request_limit:
            logger.warning("OMDb daily request limit reached")
            return None
        
        # Throttle requests
        time_since_last = time.time() - self.last_omdb_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
        
        # Make request
        data = self._omdb_request(...)
        
        # Update counters
        self.omdb_request_count += 1
        self.last_omdb_request_time = time.time()
        
        logger.info(f"OMDb requests: {self.omdb_request_count}/{self.omdb_request_limit}")
        
        return data
```

---

### Phase 3: Testing and Validation

#### Step 3.1: Unit Tests
**File**: `tv_programs/tests/test_omdb_integration.py`

**Test Cases**:
1. Test successful OMDb API call
2. Test handling of "Response: False"
3. Test rate limiting
4. Test fallback search
5. Test field mapping to Program model

#### Step 3.2: Integration Testing
**Process**:
1. Run scraper on small dataset (1-2 channels, 1 day)
2. Verify data quality:
   - Check that ratings are populated
   - Verify image URLs are valid
   - Confirm English titles are correct
3. Compare results with old IMDb scraping method

#### Step 3.3: Performance Testing
**Metrics to Track**:
- API response time
- Success rate (% of programs found)
- Match quality (title/description similarity)
- Total scraping time

---

### Phase 4: Deployment

#### Step 4.1: Update Environment Variables
**Vercel Environment Variables**:
```
OMDB_KEY = a4404098
```

**Local Development** (`private_settings.json`):
```json
{
  "OMDB_KEY": "a4404098"
}
```

#### Step 4.2: Database Migration
**No schema changes required** - all existing fields in `Program` model are compatible.

#### Step 4.3: Rollout Strategy
1. Deploy to staging/preview environment
2. Run scraper and monitor logs
3. Verify data quality in database
4. Deploy to production
5. Monitor for 24 hours

---

## Implementation Checklist

### Code Changes
- [ ] Add `get_omdb_data()` method to replace `get_ratings()`
- [ ] Update `initiate_resource()` to call OMDb API
- [ ] Add rate limiting logic
- [ ] Add fallback search functionality
- [ ] Update logging messages
- [ ] Remove old IMDb scraping code (after validation)

### Testing
- [ ] Write unit tests for OMDb integration
- [ ] Test with sample data
- [ ] Verify field mapping
- [ ] Test rate limiting
- [ ] Test error handling

### Documentation
- [ ] Update code comments
- [ ] Document OMDb API usage
- [ ] Add troubleshooting guide

### Deployment
- [ ] Set OMDB_KEY environment variable
- [ ] Deploy to staging
- [ ] Validate results
- [ ] Deploy to production

---

## Expected Benefits

### Reliability
- ✅ Official API vs. fragile web scraping
- ✅ Structured JSON responses
- ✅ No bot detection issues

### Performance
- ✅ Single API call vs. multiple page scrapes
- ✅ Faster response times
- ✅ Predictable rate limits

### Maintainability
- ✅ No HTML parsing complexity
- ✅ Stable API contract
- ✅ Better error handling

### Data Quality
- ✅ Consistent data format
- ✅ More metadata available (genre, runtime, etc.)
- ✅ Official IMDb ratings

---

## Risks and Mitigation

### Risk 1: API Rate Limits
**Impact**: 1,000 requests/day may not be enough for all channels

**Mitigation**:
- Implement smart caching (don't re-fetch known programs)
- Prioritize movie channels
- Consider upgrading to paid tier if needed

### Risk 2: Title Matching Accuracy
**Impact**: Latvian → English translation may not match OMDb titles

**Mitigation**:
- Use fuzzy matching with SequenceMatcher
- Implement fallback search
- Add year filtering for better accuracy

### Risk 3: Missing Data
**Impact**: Some programs may not be in OMDb database

**Mitigation**:
- Log missing programs for manual review
- Keep Tet.lv data even if OMDb lookup fails
- Consider hybrid approach (OMDb + fallback to IMDb scraping)

---

## Success Criteria

1. **Functionality**: 90%+ of programs successfully enriched with OMDb data
2. **Performance**: Average API response time < 500ms
3. **Reliability**: Zero bot detection errors
4. **Data Quality**: IMDb ratings populated for 80%+ of movies
5. **Compliance**: No terms of service violations

---

## Timeline

- **Phase 1** (Code Implementation): 4-6 hours
- **Phase 2** (Improvements): 2-3 hours
- **Phase 3** (Testing): 2-3 hours
- **Phase 4** (Deployment): 1-2 hours

**Total Estimated Time**: 9-14 hours

---

## Next Steps for Gemini 2.5

1. Review this plan thoroughly
2. Implement Phase 1 changes to `tv_programs/scraper.py`
3. Test with a small dataset
4. Report results and any issues encountered
5. Proceed with Phases 2-4 based on initial results

---

**Document Version**: 1.0  
**Created**: 2026-01-24  
**Author**: Development Team  
**Status**: Ready for Implementation
