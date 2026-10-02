from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    ApartmentForRent,
    ApartmentForRentSighting,
    ApartmentForSale,
    ApartmentForSaleSighting,
    ApartmentProperty,
    HouseForRent,
    HouseForRentSighting,
    HouseForSale,
    HouseForSaleSighting,
    HouseProperty,
    Project,
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


def _delete_if_orphan(prop):
    """Drop a property that no longer has any linked ads.

    Uses ``all_objects`` — hidden/misclassified ads still count as
    linked, otherwise their FK would be NULLed while their match
    status still says linked.
    """
    linked = (
        prop.rent_ads.model.all_objects.filter(property=prop).exists()
        or prop.sale_ads.model.all_objects.filter(property=prop).exists()
    )
    if not linked:
        prop.delete()


class PropertyLinkActionsMixin:
    """Review-queue actions shared by the four ad admins."""

    actions = [
        'confirm_property_link',
        'reject_property_candidate',
        'create_new_property',
        'unlink_property',
    ]

    @admin.action(description='Confirm candidate property link')
    def confirm_property_link(self, request, queryset):
        linked = 0
        for ad in queryset.filter(
            property_match_status='candidate',
            candidate_property__isnull=False,
        ).select_related('candidate_property'):
            prop = ad.candidate_property
            old_prop = ad.property if ad.property_id else None
            ad.property = prop
            ad.candidate_property = None
            ad.property_match_status = 'manual'
            ad.save(update_fields=[
                'property', 'candidate_property',
                'property_match_status',
            ])
            prop.refresh_from_ads()
            if old_prop and old_prop.pk != prop.pk:
                old_prop.refresh_from_ads()
                _delete_if_orphan(old_prop)
            linked += 1
        self.message_user(
            request, f'Confirmed {linked} property link(s).'
        )

    @admin.action(description='Reject candidate property')
    def reject_property_candidate(self, request, queryset):
        updated = queryset.filter(
            property_match_status='candidate',
        ).update(
            candidate_property=None,
            property_match_status='manual',
        )
        self.message_user(
            request,
            f'Rejected {updated} candidate(s). The ad stays unlinked '
            '(match status "manual") — use "Create new property" to '
            'link it to a fresh property.',
        )

    @admin.action(description='Create new property from ad')
    def create_new_property(self, request, queryset):
        prop_model = queryset.model._meta.get_field(
            'property'
        ).remote_field.model
        created = 0
        for ad in queryset.filter(
            property__isnull=True,
        ).select_related('region'):
            prop = prop_model.from_ad(ad)
            prop.save()
            prop._linked_ads_cache = [ad]
            ad.candidate_property = None
            ad.property = prop
            ad.property_match_status = 'manual'
            ad.save(update_fields=[
                'property', 'candidate_property',
                'property_match_status',
            ])
            created += 1
        self.message_user(
            request, f'Created {created} new propertie(s).'
        )

    @admin.action(description='Unlink property (back to unmatched)')
    def unlink_property(self, request, queryset):
        unlinked = 0
        for ad in queryset.filter(
            property__isnull=False,
        ).select_related('property'):
            old_prop = ad.property
            ad.property = None
            ad.candidate_property = None
            ad.property_match_status = 'unmatched'
            ad.property_match_score = None
            ad.save(update_fields=[
                'property', 'candidate_property',
                'property_match_status', 'property_match_score',
            ])
            old_prop.refresh_from_ads()
            _delete_if_orphan(old_prop)
            unlinked += 1
        self.message_user(
            request, f'Unlinked {unlinked} ad(s).'
        )


@admin.register(ApartmentForRent)
class ApartmentForRentAdmin(PropertyLinkActionsMixin, admin.ModelAdmin):
    list_display = [
        'region_name',
        'district',
        'rooms',
        'size',
        'floor',
        'project_raw',
        'project',
        'monthly_price',
        'monthly_price_per_sqm',
        'is_sale_misclassified',
        'post_date',
        'seller',
        'days_active',
        'property_match_status',
    ]
    list_filter = [
        'is_sale_misclassified',
        'property_match_status',
        'region',
        'district',
        'project',
    ]
    list_editable = ['is_sale_misclassified']
    search_fields = [
        'district',
        'street_name',
        'project_raw',
        'project__name',
        'seller__phone',
    ]
    ordering = ['-post_date']
    raw_id_fields = ['property', 'candidate_property']
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
class ApartmentForSaleAdmin(PropertyLinkActionsMixin, admin.ModelAdmin):
    list_display = [
        'region_name',
        'district',
        'rooms',
        'size',
        'floor',
        'project_raw',
        'project',
        'total_price',
        'price_per_sqm',
        'post_date',
        'seller',
        'days_active',
        'property_match_status',
    ]
    list_filter = [
        'property_match_status',
        'region',
        'district',
        'project',
    ]
    search_fields = [
        'district',
        'street_name',
        'project_raw',
        'project__name',
        'seller__phone',
    ]
    ordering = ['-post_date']
    raw_id_fields = ['property', 'candidate_property']
    readonly_fields = ['first_seen', 'last_seen', 'days_active']
    inlines = [ApartmentForSaleSightingInline]

    def get_queryset(self, request):
        """Use unfiltered manager so all records are visible in Admin."""
        return self.model.all_objects.get_queryset()

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
class HouseForRentAdmin(PropertyLinkActionsMixin, admin.ModelAdmin):
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
        'property_match_status',
    ]
    list_filter = ['property_match_status', 'region', 'district']
    search_fields = [
        'district',
        'street_name',
        'seller__phone',
    ]
    ordering = ['-post_date']
    raw_id_fields = ['property', 'candidate_property']
    readonly_fields = ['first_seen', 'last_seen', 'days_active']
    inlines = [HouseForRentSightingInline]

    def get_queryset(self, request):
        """Use unfiltered manager so all records are visible in Admin."""
        return self.model.all_objects.get_queryset()

    @admin.display(description='Days active')
    def days_active(self, obj):
        return obj.days_active


@admin.register(HouseForSale)
class HouseForSaleAdmin(PropertyLinkActionsMixin, admin.ModelAdmin):
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
        'property_match_status',
    ]
    list_filter = ['property_match_status', 'region', 'district']
    search_fields = [
        'district',
        'street_name',
        'seller__phone',
    ]
    ordering = ['-post_date']
    raw_id_fields = ['property', 'candidate_property']
    readonly_fields = ['first_seen', 'last_seen', 'days_active']
    inlines = [HouseForSaleSightingInline]

    def get_queryset(self, request):
        """Use unfiltered manager so all records are visible in Admin."""
        return self.model.all_objects.get_queryset()

    @admin.display(description='Days active')
    def days_active(self, obj):
        return obj.days_active


class _LinkedAdInline(admin.TabularInline):
    """Read-only inline of ads linked to a property (fk_name=property)."""
    extra = 0
    can_delete = False
    fk_name = 'property'
    fields = [
        'admin_link',
        'property_match_status',
        'property_match_score',
        'first_seen',
        'last_seen',
    ]
    readonly_fields = fields

    def get_queryset(self, request):
        return self.model.all_objects.get_queryset()

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ApartmentRentAdInline(_LinkedAdInline):
    model = ApartmentForRent
    fields = _LinkedAdInline.fields + ['monthly_price']
    readonly_fields = fields

    @admin.display(description='Ad')
    def admin_link(self, obj):
        url = reverse(
            'admin:classified_ads_apartmentforrent_change', args=[obj.pk]
        )
        return format_html('<a href="{}">{}</a>', url, obj)


class ApartmentSaleAdInline(_LinkedAdInline):
    model = ApartmentForSale
    fields = _LinkedAdInline.fields + ['total_price']
    readonly_fields = fields

    @admin.display(description='Ad')
    def admin_link(self, obj):
        url = reverse(
            'admin:classified_ads_apartmentforsale_change', args=[obj.pk]
        )
        return format_html('<a href="{}">{}</a>', url, obj)


class HouseRentAdInline(_LinkedAdInline):
    model = HouseForRent
    fields = _LinkedAdInline.fields + ['monthly_price']
    readonly_fields = fields

    @admin.display(description='Ad')
    def admin_link(self, obj):
        url = reverse(
            'admin:classified_ads_houseforrent_change', args=[obj.pk]
        )
        return format_html('<a href="{}">{}</a>', url, obj)


class HouseSaleAdInline(_LinkedAdInline):
    model = HouseForSale
    fields = _LinkedAdInline.fields + ['total_price']
    readonly_fields = fields

    @admin.display(description='Ad')
    def admin_link(self, obj):
        url = reverse(
            'admin:classified_ads_houseforsale_change', args=[obj.pk]
        )
        return format_html('<a href="{}">{}</a>', url, obj)


@admin.register(ApartmentProperty)
class ApartmentPropertyAdmin(admin.ModelAdmin):
    list_display = [
        'district',
        'street_name',
        'street_no',
        'apartment_no',
        'rooms',
        'size',
        'floor',
        'rent_ad_count',
        'sale_ad_count',
        'first_seen',
        'last_seen',
    ]
    list_filter = ['region', 'project']
    search_fields = ['district', 'street_name', 'street_no']
    readonly_fields = ['first_seen', 'last_seen', 'days_on_market']
    inlines = [ApartmentRentAdInline, ApartmentSaleAdInline]
    show_full_result_count = False

    @admin.display(description='Rent ads')
    def rent_ad_count(self, obj):
        return obj.rent_ads.model.all_objects.filter(
            property=obj
        ).count()

    @admin.display(description='Sale ads')
    def sale_ad_count(self, obj):
        return obj.sale_ads.model.all_objects.filter(
            property=obj
        ).count()


@admin.register(HouseProperty)
class HousePropertyAdmin(admin.ModelAdmin):
    list_display = [
        'district',
        'street_name',
        'street_no',
        'rooms',
        'size',
        'floors',
        'rent_ad_count',
        'sale_ad_count',
        'first_seen',
        'last_seen',
    ]
    list_filter = ['region']
    search_fields = ['district', 'street_name', 'street_no']
    readonly_fields = ['first_seen', 'last_seen', 'days_on_market']
    inlines = [HouseRentAdInline, HouseSaleAdInline]
    show_full_result_count = False

    @admin.display(description='Rent ads')
    def rent_ad_count(self, obj):
        return obj.rent_ads.model.all_objects.filter(
            property=obj
        ).count()

    @admin.display(description='Sale ads')
    def sale_ad_count(self, obj):
        return obj.sale_ads.model.all_objects.filter(
            property=obj
        ).count()


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'description']
    search_fields = ['name', 'description']


@admin.register(Seller)
class SellerAdmin(admin.ModelAdmin):
    list_display = ['phone', 'contact_id']
    search_fields = ['phone', 'contact_id']
