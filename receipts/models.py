"""Receipt data model.

Follows project conventions: explicit ``db_table``/``unique_together``,
``DecimalField`` for money, ``logging.getLogger('receipts')``. PDF bytes
are never stored — ``Receipt.source_ref`` (sha256 of the PDF) is the
idempotency key.
"""

from django.conf import settings
from django.db import models


class Store(models.Model):
    chain = models.CharField(max_length=50)        # 'rimi', 'maxima'
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=300, blank=True)
    vat_number = models.CharField(max_length=30, blank=True)

    class Meta:
        db_table = 'receipts_store'
        unique_together = (('chain', 'name'),)

    def __str__(self):
        return f'{self.chain}: {self.name}'


class Receipt(models.Model):
    PARSED = 'parsed'
    TOTAL_MISMATCH = 'total_mismatch'
    PARSE_ERROR = 'parse_error'
    PARSE_STATUS_CHOICES = (
        (PARSED, 'Parsed'),
        (TOTAL_MISMATCH, 'Total mismatch'),
        (PARSE_ERROR, 'Parse error'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='receipts',
    )
    store = models.ForeignKey(
        Store, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='receipts',
    )
    purchased_at = models.DateTimeField(null=True, blank=True)
    document_number = models.CharField(max_length=50, blank=True)
    # Fiscal/Fb number ('FB numurs: ... #03642429') — distinct from
    # Dok. Nr.; e-receipt filenames '<kase>-<docnr>' carry this.
    fb_number = models.CharField(max_length=30, blank=True)
    register_number = models.CharField(max_length=20, blank=True)
    total = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default='EUR')
    payment_method = models.CharField(max_length=50, blank=True)
    total_discount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)
    # Provenance — no PDF is ever stored.
    source = models.CharField(max_length=30, default='imap')
    source_ref = models.CharField(max_length=64)   # sha256(pdf)
    source_filename = models.CharField(max_length=255, blank=True)
    message_id = models.CharField(max_length=255, blank=True)
    raw_text = models.TextField(blank=True)  # model output / text layer
    parse_status = models.CharField(
        max_length=20, default=PARSED,
        choices=PARSE_STATUS_CHOICES)
    parse_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'receipts_receipt'
        # sha256 of the PDF is the idempotency key — the same file
        # forwarded twice yields identical bytes, so re-syncs and
        # double-processing are safe.
        unique_together = (('user', 'source_ref'),)

    def __str__(self):
        return (
            f'{self.purchased_at or "?"} '
            f'{self.store or "?"} {self.total} {self.currency}'
        )


class Category(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='receipt_categories',
    )
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='children',
    )

    class Meta:
        db_table = 'receipts_category'
        unique_together = (('user', 'name'),)
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class CategoryRule(models.Model):
    CONTAINS = 'contains'
    EQUALS = 'equals'
    STARTS_WITH = 'starts_with'
    ENDS_WITH = 'ends_with'
    MATCH_TYPES = (
        (CONTAINS, 'Contains'),
        (EQUALS, 'Equals'),
        (STARTS_WITH, 'Starts with'),
        (ENDS_WITH, 'Ends with'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='receipt_category_rules',
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE,
        related_name='rules',
    )
    pattern = models.CharField(max_length=200)
    match_type = models.CharField(
        max_length=20, choices=MATCH_TYPES, default=CONTAINS)
    priority = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    # Applied to ReceiptItem.raw_name, case-insensitive, ordered
    # (priority, pk); the first matching rule wins.

    class Meta:
        db_table = 'receipts_category_rule'

    def __str__(self):
        return f'{self.match_type} "{self.pattern}" → {self.category}'


class Product(models.Model):
    """Canonical product across receipts (global, not per-user)."""
    name = models.CharField(max_length=300, unique=True)
    brand = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = 'receipts_product'

    def __str__(self):
        return self.name


class ReceiptItem(models.Model):
    receipt = models.ForeignKey(
        Receipt, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(
        Product, null=True, blank=True, on_delete=models.SET_NULL)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL)
    raw_name = models.CharField(max_length=300)
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    unit = models.CharField(max_length=10, blank=True)  # 'gab'|'kg'
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True)
    discount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    vat_class = models.CharField(max_length=2, blank=True)  # A/C/F
    vat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True)
    is_fee = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField()

    class Meta:
        db_table = 'receipts_receipt_item'

    def __str__(self):
        return f'{self.raw_name} x{self.quantity} = {self.total}'
