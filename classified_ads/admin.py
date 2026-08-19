from django.contrib import admin

from .models import (
    ApartmentForRent,
    ApartmentForRentSighting,
    ApartmentForSale,
    ApartmentForSaleSighting,
    HouseForRent,
    HouseForRentSighting,
    HouseForSale,
    HouseForSaleSighting,
    Region,
    Seller,
)


class ApartmentForRentSightingInline(admin.TabularInline):
    model = ApartmentForRentSighting
    extra = 0
    readonly_fields = ['seen_on']
    can_delete = False
    ordering = ['-seen_on']


class ApartmentForSaleSightingInline(admin.TabularInline):
    model = ApartmentForSaleSighting
    extra = 0
    readonly_fields = ['seen_on']
    can_delete = False
    ordering = ['-seen_on']


class HouseForRentSightingInline(admin.TabularInline):
    model = HouseForRentSighting
    extra = 0
    readonly_fields = ['seen_on']
    can_delete = False
    ordering = ['-seen_on']


class HouseForSaleSightingInline(admin.TabularInline):
    model = HouseForSaleSighting
    extra = 0
    readonly_fields = ['seen_on']
    can_delete = False
    ordering = ['-seen_on']


@admin.register(ApartmentForRent)
class ApartmentForRentAdmin(admin.ModelAdmin):
    list_display = [
        'region_name',
        'district',
        'rooms',
        'size',
        'floor',
        'project',
        'monthly_price',
        'monthly_price_per_sqm',
        'is_sale_misclassified',
        'post_date',
        'seller',
        'days_active',
    ]
    list_filter = ['is_sale_misclassified', 'region', 'district', 'project']
    list_editable = ['is_sale_misclassified']
    search_fields = [
        'district',
        'street_name',
        'project',
        'seller__phone',
    ]
    ordering = ['-post_date']
    readonly_fields = ['first_seen', 'last_seen', 'days_active']
    inlines = [ApartmentForRentSightingInline]
    show_full_result_count = False

    def get_queryset(self, request):
        """Use unfiltered manager so all records are visible in Admin."""
        return self.model.all_objects.get_queryset()

    @admin.display(description='Days active')
    def days_active(self, obj):
        return obj.days_active


@admin.register(ApartmentForSale)
class ApartmentForSaleAdmin(admin.ModelAdmin):
    list_display = [
        'region_name',
        'district',
        'rooms',
        'size',
        'floor',
        'project',
        'total_price',
        'price_per_sqm',
        'post_date',
        'seller',
        'days_active',
    ]
    list_filter = ['region', 'district', 'project']
    search_fields = [
        'district',
        'street_name',
        'project',
        'seller__phone',
    ]
    ordering = ['-post_date']
    readonly_fields = ['first_seen', 'last_seen', 'days_active']
    inlines = [ApartmentForSaleSightingInline]

    @admin.display(description='Days active')
    def days_active(self, obj):
        return obj.days_active


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'parent', 'url', 'scrape_enabled']
    list_filter = ['category', 'scrape_enabled', 'parent']
    list_editable = ['scrape_enabled']
    search_fields = ['name', 'url']


@admin.register(HouseForRent)
class HouseForRentAdmin(admin.ModelAdmin):
    list_display = [
        'region_name',
        'district',
        'rooms',
        'size',
        'floors',
        'land_area_sqm',
        'monthly_price',
        'monthly_price_per_sqm',
        'post_date',
        'seller',
        'days_active',
    ]
    list_filter = ['region', 'district']
    search_fields = [
        'district',
        'street_name',
        'seller__phone',
    ]
    ordering = ['-post_date']
    readonly_fields = ['first_seen', 'last_seen', 'days_active']
    inlines = [HouseForRentSightingInline]

    @admin.display(description='Days active')
    def days_active(self, obj):
        return obj.days_active


@admin.register(HouseForSale)
class HouseForSaleAdmin(admin.ModelAdmin):
    list_display = [
        'region_name',
        'district',
        'rooms',
        'size',
        'floors',
        'land_area_sqm',
        'total_price',
        'price_per_sqm',
        'post_date',
        'seller',
        'days_active',
    ]
    list_filter = ['region', 'district']
    search_fields = [
        'district',
        'street_name',
        'seller__phone',
    ]
    ordering = ['-post_date']
    readonly_fields = ['first_seen', 'last_seen', 'days_active']
    inlines = [HouseForSaleSightingInline]

    @admin.display(description='Days active')
    def days_active(self, obj):
        return obj.days_active


@admin.register(Seller)
class SellerAdmin(admin.ModelAdmin):
    list_display = ['phone', 'contact_id']
    search_fields = ['phone', 'contact_id']
