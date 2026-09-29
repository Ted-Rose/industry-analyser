-- SQL Queries for Validating Apartment Sightings
-- Purpose: Check for duplicate sightings (same ad_id and seen_on date)
-- Date: 2026-09-02

-- ============================================================================
-- 1. Check for duplicate RENT sightings
-- ============================================================================
-- This query finds any (ad_id, seen_on) combinations that appear more than once

SELECT 
    ad_id,
    seen_on,
    COUNT(*) as duplicate_count
FROM classified_ads_apartment_rent_sighting
GROUP BY ad_id, seen_on
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC, seen_on DESC;

-- Expected result: 0 rows (no duplicates)


-- ============================================================================
-- 2. Check for duplicate SALE sightings
-- ============================================================================

SELECT 
    ad_id,
    seen_on,
    COUNT(*) as duplicate_count
FROM classified_ads_apartment_sale_sighting
GROUP BY ad_id, seen_on
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC, seen_on DESC;

-- Expected result: 0 rows (no duplicates)


-- ============================================================================
-- 3. Verify UNIQUE constraints exist
-- ============================================================================

-- Check rent sightings table constraints
SELECT 
    tc.constraint_name,
    tc.constraint_type,
    STRING_AGG(kcu.column_name, ', ' ORDER BY kcu.ordinal_position) as columns
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu 
    ON tc.constraint_name = kcu.constraint_name
WHERE tc.table_name = 'classified_ads_apartment_rent_sighting'
    AND tc.constraint_type = 'UNIQUE'
GROUP BY tc.constraint_name, tc.constraint_type;

-- Expected: classified_ads_apartment_ad_id_seen_on_87e94e92_uniq on (ad_id, seen_on)


-- Check sale sightings table constraints
SELECT 
    tc.constraint_name,
    tc.constraint_type,
    STRING_AGG(kcu.column_name, ', ' ORDER BY kcu.ordinal_position) as columns
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu 
    ON tc.constraint_name = kcu.constraint_name
WHERE tc.table_name = 'classified_ads_apartment_sale_sighting'
    AND tc.constraint_type = 'UNIQUE'
GROUP BY tc.constraint_name, tc.constraint_type;

-- Expected: classified_ads_apartment_ad_id_seen_on_ca1b7176_uniq on (ad_id, seen_on)


-- ============================================================================
-- 4. Summary statistics
-- ============================================================================

-- Total sightings count
SELECT 
    'Rent Sightings' as type,
    COUNT(*) as total_records,
    COUNT(DISTINCT ad_id) as unique_ads,
    COUNT(DISTINCT seen_on) as unique_dates,
    MIN(seen_on) as first_sighting,
    MAX(seen_on) as last_sighting
FROM classified_ads_apartment_rent_sighting

UNION ALL

SELECT 
    'Sale Sightings' as type,
    COUNT(*) as total_records,
    COUNT(DISTINCT ad_id) as unique_ads,
    COUNT(DISTINCT seen_on) as unique_dates,
    MIN(seen_on) as first_sighting,
    MAX(seen_on) as last_sighting
FROM classified_ads_apartment_sale_sighting;


-- ============================================================================
-- 5. Daily sighting counts (last 30 days)
-- ============================================================================

SELECT 
    seen_on,
    COUNT(*) as rent_sightings
FROM classified_ads_apartment_rent_sighting
WHERE seen_on >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY seen_on
ORDER BY seen_on DESC
LIMIT 30;


-- ============================================================================
-- 6. Find ads with most sightings (most active listings)
-- ============================================================================

SELECT 
    s.ad_id,
    a.district,
    a.rooms,
    a.size,
    COUNT(*) as total_sightings,
    MIN(s.seen_on) as first_seen,
    MAX(s.seen_on) as last_seen,
    (MAX(s.seen_on) - MIN(s.seen_on) + 1) as days_active
FROM classified_ads_apartment_rent_sighting s
JOIN classified_ads_apartment_rent a ON s.ad_id = a.id
GROUP BY s.ad_id, a.district, a.rooms, a.size
ORDER BY total_sightings DESC
LIMIT 10;


-- ============================================================================
-- 7. Check for any sightings today
-- ============================================================================

SELECT 
    'Rent' as type,
    COUNT(*) as sightings_today
FROM classified_ads_apartment_rent_sighting
WHERE seen_on = CURRENT_DATE

UNION ALL

SELECT 
    'Sale' as type,
    COUNT(*) as sightings_today
FROM classified_ads_apartment_sale_sighting
WHERE seen_on = CURRENT_DATE;


-- ============================================================================
-- 8. Detailed duplicate check with ad information (if any exist)
-- ============================================================================

-- This query shows full details if duplicates are found
SELECT 
    s.id as sighting_id,
    s.ad_id,
    s.seen_on,
    a.district,
    a.street_name,
    a.rooms,
    a.size,
    a.total_price
FROM classified_ads_apartment_rent_sighting s
JOIN classified_ads_apartment_rent a ON s.ad_id = a.id
WHERE (s.ad_id, s.seen_on) IN (
    SELECT ad_id, seen_on
    FROM classified_ads_apartment_rent_sighting
    GROUP BY ad_id, seen_on
    HAVING COUNT(*) > 1
)
ORDER BY s.ad_id, s.seen_on, s.id;

-- Expected result: 0 rows


-- ============================================================================
-- NOTES
-- ============================================================================
-- 
-- The apartment_scraper.py prevents duplicates through:
-- 
-- 1. Database UNIQUE constraint on (ad_id, seen_on)
-- 2. Django's bulk_create() with ignore_conflicts=True
-- 3. Proper implementation in _write_sightings() method
-- 
-- If duplicates are found, check:
-- - Database constraints are properly applied
-- - Migration files are up to date
-- - _write_sightings() is using ignore_conflicts=True
-- 
-- ============================================================================
