from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Region(models.Model):
    CATEGORY_CHOICES = [
        ('APARTMENT', 'Apartment'),
        ('HOUSE', 'House'),
        ('PHONE', 'Phone'),
        ('HOUSEHOLD', 'Household Items'),
    ]

    name = models.CharField(max_length=255)
    url = models.URLField(max_length=500, unique=True)
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='APARTMENT',
    )
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='sub_regions',
    )
    scrape_enabled = models.BooleanField(default=False)
    order_id = models.CharField(max_length=50, default='1')

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class Seller(models.Model):
    phone = models.CharField(max_length=50, blank=True)
    contact_id = models.CharField(max_length=500, blank=True)

    def __str__(self):
        return self.phone or self.contact_id


PROPERTY_MATCH_STATUS_CHOICES = [
    ('unmatched', 'Unmatched'),
    ('auto', 'Auto-linked'),
    ('candidate', 'Pending review'),
    ('manual', 'Manually linked'),
]

# Fields copied onto a property from its "best" linked ad by
# BaseProperty.refresh_from_ads(). Concrete subclasses extend this.
BASE_PROPERTY_CANONICAL_FIELDS = (
    'region_id', 'district', 'street_name', 'street_no',
)


def _ad_completeness(ad):
    """Count of non-empty optional fields, used to pick the best ad."""
    filled = 0
    for field in (
        'apartment_no', 'project_id', 'house_type', 'facilities',
        'land_area_sqm', 'comment', 'post_date', 'seller_id',
    ):
        if getattr(ad, field, None) not in (None, ''):
            filled += 1
    return filled


class BaseProperty(models.Model):
    """Canonical physical unit that one or more ads may refer to."""

    region = models.ForeignKey(
        'Region',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='%(class)s_properties',
    )
    district = models.CharField(max_length=255)
    street_name = models.CharField(max_length=255)
    street_no = models.CharField(max_length=50, blank=True)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()

    CANONICAL_FIELDS = BASE_PROPERTY_CANONICAL_FIELDS

    class Meta:
        abstract = True

    def iter_linked_ads(self):
        """Yield every linked ad (rent and sale).

        Uses the ``_linked_ads_cache`` list when present so unsaved
        properties (dry-run matching) behave like saved ones.
        """
        cached = getattr(self, '_linked_ads_cache', None)
        if cached is not None:
            yield from cached
            return
        if self.pk is None:
            return
        # all_objects: hidden/misclassified ads still belong to the
        # property (matching + days_on_market need them).
        yield from self.rent_ads.model.all_objects.filter(property=self)
        yield from self.sale_ads.model.all_objects.filter(property=self)

    def linked_ads(self):
        return list(self.iter_linked_ads())

    def note_linked_ad(self, ad):
        """Track a freshly linked ad in the in-memory cache, if any."""
        cache = getattr(self, '_linked_ads_cache', None)
        if cache is not None:
            cache.append(ad)

    def discard_linked_ad(self, ad):
        """Drop an ad from the in-memory cache, if any."""
        cache = getattr(self, '_linked_ads_cache', None)
        if cache is not None:
            cache[:] = [a for a in cache if a.pk != ad.pk]

    @property
    def days_on_market(self):
        """Distinct days the unit was seen across all linked ads."""
        seen = set()
        for ad in self.iter_linked_ads():
            for sighting in ad.sightings.all():
                seen.add(sighting.seen_on)
        return len(seen)

    @classmethod
    def from_ad(cls, ad):
        """Build an unsaved property seeded from a single ad."""
        prop = cls(first_seen=ad.first_seen, last_seen=ad.last_seen)
        for field in cls.CANONICAL_FIELDS:
            setattr(prop, field, prop._canonical_value(ad, field))
        prop._linked_ads_cache = [ad]
        return prop

    def _canonical_value(self, ad, field):
        value = getattr(ad, field)
        if field == 'street_no':
            from .property_matcher import normalize_street_no
            return normalize_street_no(value)
        # Block lookups filter on stripped values — keep stored
        # canonical strings clean so they always match.
        if isinstance(value, str):
            return value.strip()
        return value

    def refresh_from_ads(self, save=True):
        """Recompute canonical fields and first/last seen from ads.

        Canonical attributes come from the "best" linked ad (most
        sightings, tie-break most complete); first_seen/last_seen are
        the min/max across all linked ads.
        """
        ads = self.linked_ads()
        if not ads:
            return
        best = max(
            ads,
            key=lambda a: (a.days_active, _ad_completeness(a)),
        )
        for field in self.CANONICAL_FIELDS:
            setattr(self, field, self._canonical_value(best, field))
        self.first_seen = min(a.first_seen for a in ads)
        self.last_seen = max(a.last_seen for a in ads)
        if save and self.pk:
            self.save()


class ApartmentProperty(BaseProperty):
    apartment_no = models.CharField(
        max_length=50,
        blank=True,
        help_text='Apartment/unit number within the building'
    )
    rooms = models.IntegerField()
    size = models.FloatField(help_text='Square metres')
    floor = models.IntegerField()
    max_floor = models.IntegerField()
    project = models.ForeignKey(
        'Project',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='apartment_properties',
    )

    CANONICAL_FIELDS = BASE_PROPERTY_CANONICAL_FIELDS + (
        'apartment_no', 'rooms', 'size', 'floor', 'max_floor',
        'project_id',
    )

    class Meta:
        db_table = 'classified_ads_apartment_property'
        verbose_name = 'Apartment Property'
        verbose_name_plural = 'Apartment Properties'
        indexes = [
            models.Index(
                fields=['district', 'street_no'],
                name='ca_apt_prop_block_idx',
            ),
        ]

    def __str__(self):
        addr = f'{self.street_name} {self.street_no}'.strip()
        if self.apartment_no:
            addr += f', apt {self.apartment_no}'
        return (
            f'{self.district} | {addr} | '
            f'{self.rooms}rm | {self.size}m²'
        )


class HouseProperty(BaseProperty):
    rooms = models.IntegerField()
    size = models.FloatField(help_text='House floor area m²')
    floors = models.IntegerField(help_text='Total number of storeys')
    land_area_sqm = models.FloatField(
        null=True,
        blank=True,
        help_text='Plot area in m²',
    )

    CANONICAL_FIELDS = BASE_PROPERTY_CANONICAL_FIELDS + (
        'rooms', 'size', 'floors', 'land_area_sqm',
    )

    class Meta:
        db_table = 'classified_ads_house_property'
        verbose_name = 'House Property'
        verbose_name_plural = 'House Properties'
        indexes = [
            models.Index(
                fields=['district', 'street_no'],
                name='ca_house_prop_block_idx',
            ),
        ]

    def __str__(self):
        addr = f'{self.street_name} {self.street_no}'.strip()
        return (
            f'{self.district} | {addr} | '
            f'{self.rooms}rm | {self.size}m²'
        )


class BaseApartmentAd(models.Model):
    ad_id = models.CharField(max_length=255, unique=True)
    comment = models.TextField(blank=True)
    link = models.URLField(max_length=500)
    region = models.ForeignKey(
        'Region',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='%(class)s_ads',
    )
    region_name = models.CharField(max_length=255, blank=True)
    district = models.CharField(max_length=255)
    street_name = models.CharField(max_length=255)
    street_no = models.CharField(max_length=50, blank=True)
    apartment_no = models.CharField(
        max_length=50,
        blank=True,
        help_text='Apartment/unit number within the building'
    )
    rooms = models.IntegerField()
    size = models.FloatField(help_text='Square metres')
    floor = models.IntegerField()
    max_floor = models.IntegerField()
    project_raw = models.CharField(
        max_length=255,
        blank=True,
        help_text='Original project value from source'
    )
    project = models.ForeignKey(
        'Project',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='%(class)s_ads',
        help_text='Standardized project type'
    )
    house_type = models.CharField(max_length=255, blank=True)
    facilities = models.CharField(max_length=500, blank=True)
    post_date = models.DateTimeField(null=True)
    seller = models.ForeignKey(
        'Seller',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='%(class)s_ads',
    )
    price_per_sqm = models.FloatField()
    total_price = models.FloatField()
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    is_hidden = models.BooleanField(default=False)
    property_match_status = models.CharField(
        max_length=20,
        choices=PROPERTY_MATCH_STATUS_CHOICES,
        default='unmatched',
        db_index=True,
    )
    property_match_score = models.FloatField(null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def days_active(self):
        return self.sightings.count()


class VisibleApartmentManager(models.Manager):
    """Manager that excludes hidden apartment ads."""
    def get_queryset(self):
        return super().get_queryset().filter(is_hidden=False)


class CleanRentalManager(models.Manager):
    """Manager that excludes misclassified for-sale ads and hidden ads."""
    def get_queryset(self):
        return super().get_queryset().filter(
            is_sale_misclassified=False,
            is_hidden=False
        )


class ApartmentForRent(BaseApartmentAd):
    monthly_price = models.FloatField()
    monthly_price_per_sqm = models.FloatField()
    total_price_120m = models.FloatField()
    price_per_sqm_120m = models.FloatField()
    is_sale_misclassified = models.BooleanField(
        default=False,
        help_text=(
            'True if this rental ad is actually a for-sale listing '
            'posted in the wrong category'
        )
    )
    property = models.ForeignKey(
        ApartmentProperty,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='rent_ads',
        help_text='Canonical property this ad is linked to',
    )
    candidate_property = models.ForeignKey(
        ApartmentProperty,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        help_text='Proposed property link awaiting review',
    )

    objects = CleanRentalManager()
    all_objects = models.Manager()

    class Meta:
        db_table = 'classified_ads_apartment_rent'
        verbose_name = 'Apartment for Rent'
        verbose_name_plural = 'Apartments for Rent'

    def __str__(self):
        return (
            f"RENT | {self.district} | "
            f"{self.rooms}rm | {self.size}m² | €{self.monthly_price}/mo"
        )


class ApartmentForSale(BaseApartmentAd):
    property = models.ForeignKey(
        ApartmentProperty,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sale_ads',
        help_text='Canonical property this ad is linked to',
    )
    candidate_property = models.ForeignKey(
        ApartmentProperty,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        help_text='Proposed property link awaiting review',
    )

    objects = VisibleApartmentManager()
    all_objects = models.Manager()

    class Meta:
        db_table = 'classified_ads_apartment_sale'
        verbose_name = 'Apartment for Sale'
        verbose_name_plural = 'Apartments for Sale'

    def __str__(self):
        return (
            f"SALE | {self.district} | "
            f"{self.rooms}rm | {self.size}m² | €{self.total_price}"
        )


class ApartmentForRentSighting(models.Model):
    ad = models.ForeignKey(
        ApartmentForRent,
        on_delete=models.CASCADE,
        related_name='sightings',
    )
    seen_on = models.DateField()

    class Meta:
        unique_together = [('ad', 'seen_on')]
        db_table = 'classified_ads_apartment_rent_sighting'

    def __str__(self):
        return f"{self.ad.ad_id} seen on {self.seen_on}"


class ApartmentForSaleSighting(models.Model):
    ad = models.ForeignKey(
        ApartmentForSale,
        on_delete=models.CASCADE,
        related_name='sightings',
    )
    seen_on = models.DateField()

    class Meta:
        unique_together = [('ad', 'seen_on')]
        db_table = 'classified_ads_apartment_sale_sighting'

    def __str__(self):
        return f"{self.ad.ad_id} seen on {self.seen_on}"


class VisibleHouseManager(models.Manager):
    """Manager that excludes hidden house ads."""
    def get_queryset(self):
        return super().get_queryset().filter(is_hidden=False)


class BaseHouseAd(models.Model):
    ad_id = models.CharField(max_length=255, unique=True)
    comment = models.TextField(blank=True)
    link = models.URLField(max_length=500)
    region = models.ForeignKey(
        'Region',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='%(class)s_ads',
    )
    region_name = models.CharField(max_length=255, blank=True)
    district = models.CharField(max_length=255)
    street_name = models.CharField(max_length=255)
    street_no = models.CharField(max_length=50, blank=True)
    rooms = models.IntegerField()
    size = models.FloatField(help_text='House floor area m²')
    floors = models.IntegerField(help_text='Total number of storeys')
    land_area_sqm = models.FloatField(
        null=True,
        blank=True,
        help_text='Plot area in m²',
    )
    post_date = models.DateTimeField(null=True)
    seller = models.ForeignKey(
        'Seller',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='%(class)s_ads',
    )
    price_per_sqm = models.FloatField()
    total_price = models.FloatField()
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    is_hidden = models.BooleanField(default=False)
    property_match_status = models.CharField(
        max_length=20,
        choices=PROPERTY_MATCH_STATUS_CHOICES,
        default='unmatched',
        db_index=True,
    )
    property_match_score = models.FloatField(null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def days_active(self):
        return self.sightings.count()


class HouseForRent(BaseHouseAd):
    monthly_price = models.FloatField()
    monthly_price_per_sqm = models.FloatField()
    total_price_120m = models.FloatField()
    price_per_sqm_120m = models.FloatField()
    property = models.ForeignKey(
        HouseProperty,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='rent_ads',
        help_text='Canonical property this ad is linked to',
    )
    candidate_property = models.ForeignKey(
        HouseProperty,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        help_text='Proposed property link awaiting review',
    )

    objects = VisibleHouseManager()
    all_objects = models.Manager()

    class Meta:
        db_table = 'classified_ads_house_rent'
        verbose_name = 'House for Rent'
        verbose_name_plural = 'Houses for Rent'

    def __str__(self):
        return (
            f"RENT | {self.district} | "
            f"{self.rooms}rm | {self.size}m² | €{self.monthly_price}/mo"
        )


class HouseForSale(BaseHouseAd):
    property = models.ForeignKey(
        HouseProperty,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sale_ads',
        help_text='Canonical property this ad is linked to',
    )
    candidate_property = models.ForeignKey(
        HouseProperty,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        help_text='Proposed property link awaiting review',
    )

    objects = VisibleHouseManager()
    all_objects = models.Manager()

    class Meta:
        db_table = 'classified_ads_house_sale'
        verbose_name = 'House for Sale'
        verbose_name_plural = 'Houses for Sale'

    def __str__(self):
        return (
            f"SALE | {self.district} | "
            f"{self.rooms}rm | {self.size}m² | €{self.total_price}"
        )


class HouseForRentSighting(models.Model):
    ad = models.ForeignKey(
        HouseForRent,
        on_delete=models.CASCADE,
        related_name='sightings',
    )
    seen_on = models.DateField()

    class Meta:
        unique_together = [('ad', 'seen_on')]
        db_table = 'classified_ads_house_rent_sighting'

    def __str__(self):
        return f"{self.ad.ad_id} seen on {self.seen_on}"


class HouseForSaleSighting(models.Model):
    ad = models.ForeignKey(
        HouseForSale,
        on_delete=models.CASCADE,
        related_name='sightings',
    )
    seen_on = models.DateField()

    class Meta:
        unique_together = [('ad', 'seen_on')]
        db_table = 'classified_ads_house_sale_sighting'

    def __str__(self):
        return f"{self.ad.ad_id} seen on {self.seen_on}"
