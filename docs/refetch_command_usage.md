# Refetch Command Usage Guide

## Overview

The refetch command system allows you to re-scrape and update existing records in the database. This is useful when:
- Data is missing (e.g., `post_date IS NULL`)
- Data needs to be corrected
- New fields have been added to the scraper
- You want to update specific records

## Architecture

The system consists of:

1. **BaseScraper.refetch_single()** - Core method that refetches a single record
2. **BaseRefetchCommand** - Reusable Django management command base class
3. **App-specific commands** - Commands for each scraping app (e.g., `refetch_apartment_ads`)

## Available Commands

### refetch_apartment_ads

Refetch apartment rental and sale ads from ss.com.

```bash
python manage.py refetch_apartment_ads [OPTIONS]
```

## Command Options

### Required (one of):
- `--ids ID1 ID2 ...` - Refetch specific ad IDs
- `--filter EXPRESSION` - Filter records using Django query syntax

### Optional:
- `--deal-type {rent,sale}` - Limit to rent or sale ads only
- `--fields FIELD1,FIELD2,...` - Only update specific fields
- `--limit N` - Maximum number of records to process
- `--batch-size N` - Records per batch (default: 100)
- `--dry-run` - Preview changes without updating database

## Usage Examples

### Example 1: Fix Missing post_date Fields

Refetch all apartment rental ads where `post_date` is NULL:

```bash
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --deal-type rent
```

This will:
1. Find all rental ads with NULL post_date
2. Refetch each ad's detail page
3. Update: post_date, house_type, facilities, comment, seller

### Example 2: Dry Run First

Always test with `--dry-run` first to see what would be updated:

```bash
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --deal-type rent \
    --limit 10 \
    --dry-run
```

Output:
```
Processing RENT ads only

Filtering by: post_date__isnull=True
Found 716 record(s) to refetch
Fields to update: post_date, house_type, facilities, comment, seller

=== DRY RUN MODE - No changes will be made ===

  - ad123...: https://www.ss.com/msg/lv/...
  - ad456...: https://www.ss.com/msg/lv/...
  ... and 706 more
```

### Example 3: Refetch Specific IDs

Refetch specific ads by their ad_id:

```bash
python manage.py refetch_apartment_ads \
    --ids "tr_12345RigaCentrs..." "tr_67890Jurmala..." \
    --deal-type rent
```

### Example 4: Update Only Specific Fields

Only update `post_date` and `house_type` fields:

```bash
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --fields post_date,house_type \
    --deal-type rent
```

### Example 5: Process in Small Batches

Process records in batches of 50 with a limit:

```bash
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --deal-type rent \
    --limit 100 \
    --batch-size 50
```

### Example 6: Both Rent and Sale

Process both rental and sale ads (default behavior):

```bash
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True"
```

This will process rent ads first, then sale ads.

## Filter Syntax

The `--filter` option uses Django's query syntax:

### Null Checks
```bash
--filter "post_date__isnull=True"
--filter "house_type__isnull=False"
```

### Comparisons
```bash
--filter "size__lt=20"          # Less than
--filter "size__gt=100"         # Greater than
--filter "size__lte=50"         # Less than or equal
--filter "size__gte=30"         # Greater than or equal
```

### Exact Matches
```bash
--filter "district=Centrs"
--filter "rooms=3"
```

### String Operations
```bash
--filter "street_name__contains=Brivibas"
--filter "street_name__startswith=Kr"
```

## Default Update Fields

By default, `refetch_apartment_ads` updates these fields:
- `post_date` - When the ad was posted
- `house_type` - Type of building
- `facilities` - Available facilities
- `comment` - Ad description
- `seller` - Seller contact information

These are the fields that come from the detail page (enrichment data).

## Performance Considerations

1. **Rate Limiting**: The scraper includes built-in delays to avoid overwhelming ss.com
2. **Batch Processing**: Use `--batch-size` to control memory usage
3. **Limit Records**: Use `--limit` for testing or processing in chunks
4. **Dry Run First**: Always test with `--dry-run` before processing large batches

## Typical Workflow

1. **Identify the problem**:
   ```sql
   SELECT COUNT(*) FROM classified_ads_apartment_rent 
   WHERE post_date IS NULL;
   ```

2. **Dry run to preview**:
   ```bash
   python manage.py refetch_apartment_ads \
       --filter "post_date__isnull=True" \
       --deal-type rent \
       --limit 5 \
       --dry-run
   ```

3. **Process a small batch**:
   ```bash
   python manage.py refetch_apartment_ads \
       --filter "post_date__isnull=True" \
       --deal-type rent \
       --limit 50
   ```

4. **Verify results**:
   ```sql
   SELECT COUNT(*) FROM classified_ads_apartment_rent 
   WHERE post_date IS NULL;
   ```

5. **Process remaining records**:
   ```bash
   python manage.py refetch_apartment_ads \
       --filter "post_date__isnull=True" \
       --deal-type rent
   ```

## Extending to Other Apps

To create a refetch command for other scraping apps:

1. **Implement `_parse_detail_for_refetch()` in your scraper**:
   ```python
   def _parse_detail_for_refetch(self, response):
       """Return dict of fields to update."""
       return {
           'field1': value1,
           'field2': value2,
       }
   ```

2. **Create app-specific command**:
   ```python
   from core_scraper.management.commands.base_refetch import (
       BaseRefetchCommand
   )
   
   class Command(BaseRefetchCommand):
       def get_model(self):
           return YourModel
       
       def get_scraper_class(self):
           return YourScraper
       
       def get_default_update_fields(self):
           return ['field1', 'field2']
   ```

## Debugging

### VS Code Debugger Setup

A `.vscode/launch.json` file has been created with pre-configured debug configurations:

1. **Refetch: Dry Run (10 records)** - Test with 10 records in dry-run mode
2. **Refetch: Process 50 records** - Process a small batch
3. **Refetch: Specific IDs** - Debug specific ad IDs
4. **Refetch: Custom Filter** - Customize filter and fields

**To use**:
1. Open the project in VS Code
2. Press `F5` or click Run → Start Debugging
3. Select a configuration from the dropdown
4. Set breakpoints in the code:
   - `core_scraper/management/commands/base_refetch.py` - Command logic
   - `core_scraper/base.py` - Refetch method
   - `classified_ads/apartment_scraper.py` - Parsing logic

**To customize**:
Edit `.vscode/launch.json` and modify the `args` array:

```json
"args": [
    "refetch_apartment_ads",
    "--filter", "YOUR_FILTER_HERE",
    "--deal-type", "rent",
    "--limit", "10"
]
```

### Terminal with Variables (Quick & Easy)

Use shell variables for easy testing:

```bash
# Define your parameters
FILTER="post_date__isnull=True"
DEAL_TYPE="rent"
LIMIT=10

# Dry run
python manage.py refetch_apartment_ads \
    --filter "$FILTER" \
    --deal-type "$DEAL_TYPE" \
    --limit $LIMIT \
    --dry-run

# Real run (just remove --dry-run)
python manage.py refetch_apartment_ads \
    --filter "$FILTER" \
    --deal-type "$DEAL_TYPE" \
    --limit $LIMIT
```

**Benefits**:
- Easy to change parameters
- No need to edit code
- Can save as shell script for reuse

### Python Debugger (pdb)

For quick debugging without VS Code:

```bash
python -m pdb manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --limit 5 \
    --dry-run
```

Common pdb commands:
- `n` - Next line
- `s` - Step into function
- `c` - Continue
- `p variable_name` - Print variable
- `l` - List code around current line
- `b line_number` - Set breakpoint

### Useful Breakpoint Locations

**To debug filter parsing**:
- File: `core_scraper/management/commands/base_refetch.py`
- Line: `parse_filter()` method

**To debug refetch logic**:
- File: `core_scraper/base.py`
- Line: `refetch_single()` method

**To debug parsing**:
- File: `classified_ads/apartment_scraper.py`
- Line: `_parse_detail_for_refetch()` method

**To debug batch updates**:
- File: `core_scraper/management/commands/base_refetch.py`
- Line: Inside the `for record in queryset` loop

## Troubleshooting

### "No records found matching criteria"
- Check your filter syntax
- Verify the field names exist in the model
- Try without `--limit` to see total count

### "Failed to refetch: ad_id"
- The ad may have been deleted from ss.com
- Network issues
- Check logs for details

### Database errors
- Ensure migrations are up to date: `python manage.py migrate`
- Check that all fields in `--fields` exist in the database

## Migration Requirement

**IMPORTANT**: Before using the refetch command, ensure your database is up to date:

```bash
# Check for pending migrations
python manage.py showmigrations classified_ads

# Apply migrations if needed
python manage.py migrate classified_ads
```

If you see unapplied migrations (marked with `[ ]`), run the migrate command first.
