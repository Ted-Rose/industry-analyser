"""
Analyze the 'project' field in apartment ads to determine diversity and
standardization potential.
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'industry_analyser.settings')
django.setup()

from django.db.models import Count
from classified_ads.models import ApartmentForRent, ApartmentForSale


def analyze_project_field():
    """Analyze project field across apartment models."""
    
    print("=" * 80)
    print("PROJECT FIELD ANALYSIS")
    print("=" * 80)
    
    # Analyze ApartmentForRent
    print("\n### APARTMENTS FOR RENT ###\n")
    
    rent_total = ApartmentForRent.all_objects.count()
    rent_unique = ApartmentForRent.all_objects.values('project').distinct().count()
    rent_empty = ApartmentForRent.all_objects.filter(project='').count()
    
    print(f"Total records: {rent_total}")
    print(f"Unique project values: {rent_unique}")
    print(f"Empty project values: {rent_empty}")
    print(f"Diversity ratio: {rent_unique / rent_total if rent_total > 0 else 0:.2%}")
    
    print("\n--- Top 20 Most Common Project Values (Rent) ---")
    top_rent = (
        ApartmentForRent.all_objects
        .values('project')
        .annotate(count=Count('id'))
        .order_by('-count')[:20]
    )
    for i, item in enumerate(top_rent, 1):
        print(f"{i:2d}. '{item['project']}' - {item['count']} ads")
    
    # Analyze ApartmentForSale
    print("\n\n### APARTMENTS FOR SALE ###\n")
    
    sale_total = ApartmentForSale.all_objects.count()
    sale_unique = ApartmentForSale.all_objects.values('project').distinct().count()
    sale_empty = ApartmentForSale.all_objects.filter(project='').count()
    
    print(f"Total records: {sale_total}")
    print(f"Unique project values: {sale_unique}")
    print(f"Empty project values: {sale_empty}")
    print(f"Diversity ratio: {sale_unique / sale_total if sale_total > 0 else 0:.2%}")
    
    print("\n--- Top 20 Most Common Project Values (Sale) ---")
    top_sale = (
        ApartmentForSale.all_objects
        .values('project')
        .annotate(count=Count('id'))
        .order_by('-count')[:20]
    )
    for i, item in enumerate(top_sale, 1):
        print(f"{i:2d}. '{item['project']}' - {item['count']} ads")
    
    # Combined analysis
    print("\n\n### COMBINED ANALYSIS ###\n")
    
    combined_total = rent_total + sale_total
    
    # Get all unique project values from both tables
    all_projects = set()
    for item in ApartmentForRent.all_objects.values_list('project', flat=True).distinct():
        all_projects.add(item)
    for item in ApartmentForSale.all_objects.values_list('project', flat=True).distinct():
        all_projects.add(item)
    
    combined_unique = len(all_projects)
    
    print(f"Total records (rent + sale): {combined_total}")
    print(f"Unique project values (combined): {combined_unique}")
    print(f"Overall diversity ratio: {combined_unique / combined_total if combined_total > 0 else 0:.2%}")
    
    # Sample of unique values for pattern analysis
    print("\n--- Sample of Unique Project Values (first 30) ---")
    sample_projects = sorted(list(all_projects))[:30]
    for i, proj in enumerate(sample_projects, 1):
        print(f"{i:2d}. '{proj}'")
    
    print("\n" + "=" * 80)
    print("STANDARDIZATION RECOMMENDATIONS")
    print("=" * 80)
    
    if combined_unique / combined_total < 0.1:
        print("\n✓ LOW DIVERSITY - Good candidate for standardization")
        print("  Recommendation: Convert to ForeignKey with Project model")
    elif combined_unique / combined_total < 0.3:
        print("\n⚠ MODERATE DIVERSITY - Possible standardization with cleanup")
        print("  Recommendation: Analyze patterns, normalize similar values")
    else:
        print("\n✗ HIGH DIVERSITY - Difficult to standardize")
        print("  Recommendation: Keep as CharField, consider adding tags/categories")


if __name__ == '__main__':
    analyze_project_field()
