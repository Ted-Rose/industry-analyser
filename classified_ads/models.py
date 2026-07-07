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


class ClassifiedAd(models.Model):
    DEAL_RENT = 'RENT'
    DEAL_SELL = 'SELL'
    DEAL_TYPE_CHOICES = [
        (DEAL_RENT, 'Rent'),
        (DEAL_SELL, 'Sell'),
    ]

    ad_id = models.CharField(max_length=255, unique=True)
    deal_type = models.CharField(
        max_length=10, choices=DEAL_TYPE_CHOICES
    )
    comment = models.TextField(blank=True)
    link = models.URLField(max_length=500)
    region = models.ForeignKey(
        'Region',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ads',
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
    post_date = models.DateTimeField(null=True)
    seller = models.ForeignKey(
        'Seller',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ads',
    )
    price_per_sqm = models.FloatField()
    alt_price_per_sqm = models.FloatField()
    total_price = models.FloatField()
    alt_price = models.FloatField()
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    @property
    def days_active(self):
        return self.sightings.count()

    def __str__(self):
        return (
            f"{self.deal_type} | {self.district} | "
            f"{self.rooms}rm | {self.size}m² | €{self.total_price}"
        )


class ClassifiedAdSighting(models.Model):
    ad = models.ForeignKey(
        ClassifiedAd,
        on_delete=models.CASCADE,
        related_name='sightings',
    )
    seen_on = models.DateField()

    class Meta:
        unique_together = [('ad', 'seen_on')]

    def __str__(self):
        return f"{self.ad.ad_id} seen on {self.seen_on}"
