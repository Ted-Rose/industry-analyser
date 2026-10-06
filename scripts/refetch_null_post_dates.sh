#!/bin/bash
# Script to refetch apartment ads with null post_date
# Usage: ./scripts/refetch_null_post_dates.sh [dry-run|test|full]

set -e  # Exit on error

# Configuration
FILTER="post_date__isnull=True"
DEAL_TYPE="rent"
FIELDS="post_date,house_type,facilities,comment,seller"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

MODE="${1:-dry-run}"

case "$MODE" in
    dry-run)
        echo -e "${YELLOW}Running in DRY RUN mode (no changes)${NC}"
        python manage.py refetch_apartment_ads \
            --filter "$FILTER" \
            --deal-type "$DEAL_TYPE" \
            --fields "$FIELDS" \
            --limit 10 \
            --dry-run
        ;;
    
    test)
        echo -e "${YELLOW}Processing 50 test records${NC}"
        python manage.py refetch_apartment_ads \
            --filter "$FILTER" \
            --deal-type "$DEAL_TYPE" \
            --fields "$FIELDS" \
            --limit 50
        
        echo -e "${GREEN}Test complete! Check the results.${NC}"
        ;;
    
    full)
        echo -e "${YELLOW}Processing ALL records with null post_date${NC}"
        read -p "Are you sure? This will process all matching records. (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            python manage.py refetch_apartment_ads \
                --filter "$FILTER" \
                --deal-type "$DEAL_TYPE" \
                --fields "$FIELDS"
            
            echo -e "${GREEN}Refetch complete!${NC}"
        else
            echo "Cancelled."
            exit 1
        fi
        ;;
    
    *)
        echo "Usage: $0 [dry-run|test|full]"
        echo ""
        echo "Modes:"
        echo "  dry-run  - Preview 10 records without making changes (default)"
        echo "  test     - Process 50 records to verify it works"
        echo "  full     - Process all records with null post_date"
        echo ""
        echo "Examples:"
        echo "  $0              # Dry run (preview only)"
        echo "  $0 dry-run      # Same as above"
        echo "  $0 test         # Process 50 records"
        echo "  $0 full         # Process all records"
        exit 1
        ;;
esac
