# Refetch Command - Quick Start

## What Is This?

A reusable command-line tool to re-scrape and update existing database records. Perfect for fixing missing or incorrect data.

## Quick Start

### 1. Run Migrations (REQUIRED FIRST)

```bash
python manage.py migrate classified_ads
```

### 2. Fix Your 716 NULL post_date Records

```bash
# Preview what will be updated (dry run)
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --deal-type rent \
    --limit 10 \
    --dry-run

# Process all records
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --deal-type rent
```

This will:
- Find all rental ads with NULL post_date
- Refetch each ad's detail page from ss.com
- Update: post_date, house_type, facilities, comment, seller
- Process in batches of 100
- Take ~12-15 minutes for 716 records

## Common Commands

### Fix missing data
```bash
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --deal-type rent
```

### Refetch specific IDs
```bash
python manage.py refetch_apartment_ads \
    --ids "ad123" "ad456" \
    --deal-type rent
```

### Update only specific fields
```bash
python manage.py refetch_apartment_ads \
    --filter "house_type__isnull=True" \
    --fields house_type,facilities \
    --deal-type rent
```

### Process in small batches
```bash
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --limit 100 \
    --batch-size 50 \
    --deal-type rent
```

## All Options

```
--filter EXPRESSION      # Django filter (e.g., "post_date__isnull=True")
--ids ID1 ID2 ...       # Specific ad IDs to refetch
--deal-type {rent,sale} # Limit to rent or sale ads
--fields FIELD1,FIELD2  # Only update these fields
--limit N               # Maximum records to process
--batch-size N          # Records per batch (default: 100)
--dry-run               # Preview without making changes
```

## Works With All Scraping Apps

The same system works for:
- Apartment ads (implemented)
- House ads (easy to add)
- Blog posts (easy to add)
- TV programs (easy to add)
- Any future scrapers (easy to add)

## Documentation

- **Usage Guide**: `docs/refetch_command_usage.md` - Detailed examples and syntax
- **Implementation**: `docs/refetch_implementation.md` - How it works, extending to other apps

## Typical Workflow

1. **Identify problem**: Run SQL query to find bad data
2. **Dry run**: Test with `--dry-run --limit 5`
3. **Small batch**: Process 50-100 records first
4. **Verify**: Check database to confirm updates
5. **Full run**: Process all remaining records

## Example: Your Current Issue

```bash
# 1. Check the problem
psql -c "SELECT COUNT(*) FROM classified_ads_apartment_rent 
         WHERE post_date IS NULL;"
# Result: 716

# 2. Dry run to preview
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --deal-type rent \
    --limit 5 \
    --dry-run

# 3. Process a small batch
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --deal-type rent \
    --limit 50

# 4. Verify it worked
psql -c "SELECT COUNT(*) FROM classified_ads_apartment_rent 
         WHERE post_date IS NULL;"
# Should be less than 716

# 5. Process the rest
python manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --deal-type rent
```

## Safety Features

✅ **Dry run mode** - Preview changes without updating  
✅ **Batch processing** - Efficient database updates  
✅ **Error handling** - Continues on failures, reports errors  
✅ **Rate limiting** - Won't overwhelm ss.com servers  
✅ **Selective updates** - Only update specified fields  

## Quick Scripts

### Pre-made Shell Script (Easiest!)

A ready-to-use script is available for your specific use case:

```bash
# Dry run (preview only)
./scripts/refetch_null_post_dates.sh

# Process 50 test records
./scripts/refetch_null_post_dates.sh test

# Process all records
./scripts/refetch_null_post_dates.sh full
```

The script handles your 716 null post_date records with safety checks and colored output.

## Debugging with VS Code

### Option 1: Terminal with Variables (Easiest)

Run the command in the terminal and set variables as needed:

```bash
# Set filter as variable for easy modification
FILTER="post_date__isnull=True"
LIMIT=10

python manage.py refetch_apartment_ads \
    --filter "$FILTER" \
    --deal-type rent \
    --limit $LIMIT \
    --dry-run
```

### Option 2: VS Code Debugger

Create `.vscode/launch.json` in your project root:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Refetch: Dry Run (10 records)",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/manage.py",
            "args": [
                "refetch_apartment_ads",
                "--filter", "post_date__isnull=True",
                "--deal-type", "rent",
                "--limit", "10",
                "--dry-run"
            ],
            "django": true,
            "justMyCode": false,
            "console": "integratedTerminal"
        },
        {
            "name": "Refetch: Process 50 records",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/manage.py",
            "args": [
                "refetch_apartment_ads",
                "--filter", "post_date__isnull=True",
                "--deal-type", "rent",
                "--limit", "50"
            ],
            "django": true,
            "justMyCode": false,
            "console": "integratedTerminal"
        },
        {
            "name": "Refetch: Specific IDs",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/manage.py",
            "args": [
                "refetch_apartment_ads",
                "--ids", "ad123", "ad456",
                "--deal-type", "rent"
            ],
            "django": true,
            "justMyCode": false,
            "console": "integratedTerminal"
        },
        {
            "name": "Refetch: Custom Filter",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/manage.py",
            "args": [
                "refetch_apartment_ads",
                "--filter", "house_type__isnull=True",
                "--fields", "house_type,facilities",
                "--deal-type", "rent",
                "--limit", "20"
            ],
            "django": true,
            "justMyCode": false,
            "console": "integratedTerminal"
        }
    ]
}
```

**To use**:
1. Open VS Code
2. Press `F5` or go to Run → Start Debugging
3. Select the configuration you want from the dropdown
4. Set breakpoints in the code as needed

**Tip**: Edit the `args` array in the configuration to change filters, limits, etc.

### Option 3: Python Debugger in Terminal

```bash
# Run with Python debugger
python -m pdb manage.py refetch_apartment_ads \
    --filter "post_date__isnull=True" \
    --deal-type rent \
    --limit 10 \
    --dry-run
```

## Need Help?

See the full documentation:
- `docs/refetch_command_usage.md` - All examples and options
- `docs/refetch_implementation.md` - Technical details

Or run:
```bash
python manage.py refetch_apartment_ads --help
```
