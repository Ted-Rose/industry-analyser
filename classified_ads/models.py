from django.db import models


class Region(models.Model):
    name = models.CharField(max_length=255)
    url = models.URLField(max_length=500, unique=True)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='sub_regions',
    )
    scrape_enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Seller(models.Model):
    phone = models.CharField(max_length=50, blank=True)
    contact_id = models.CharField(max_length=500, blank=True)

    def __str__(self):
        return self.phone or self.contact_id


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
    rooms = models.IntegerField()
    size = models.FloatField(help_text='Square metres')
    floor = models.IntegerField()
    max_floor = models.IntegerField()
    project = models.CharField(max_length=255)
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

    class Meta:
        abstract = True

    @property
    def days_active(self):
        return self.sightings.count()


class CleanRentalManager(models.Manager):
    """Manager that excludes misclassified for-sale ads."""
    def get_queryset(self):
        return super().get_queryset().filter(
            is_sale_misclassified=False
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
