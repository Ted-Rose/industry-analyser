from django.contrib import admin

from .models import (
    Category,
    CategoryRule,
    Product,
    Receipt,
    ReceiptItem,
    Store,
)


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'chain', 'address', 'vat_number')
    list_filter = ('chain',)
    search_fields = ('name', 'address', 'vat_number')


class ReceiptItemInline(admin.TabularInline):
    model = ReceiptItem
    extra = 0
    fields = (
        'position', 'raw_name', 'quantity', 'unit', 'unit_price',
        'discount', 'total', 'vat_class', 'is_fee', 'category',
        'product',
    )
    readonly_fields = ('position',)
    ordering = ('position',)


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        'purchased_at', 'store', 'total', 'currency',
        'parse_status', 'source_filename', 'created_at',
    )
    list_filter = ('parse_status', 'store__chain', 'source')
    search_fields = (
        'document_number', 'register_number', 'raw_text',
        'source_filename', 'source_ref',
    )
    readonly_fields = (
        'source', 'source_ref', 'source_filename', 'message_id',
        'raw_text', 'parse_error', 'created_at',
    )
    list_select_related = ('store', 'user')
    inlines = (ReceiptItemInline,)
    date_hierarchy = 'purchased_at'


class CategoryRuleInline(admin.TabularInline):
    model = CategoryRule
    extra = 0
    fields = (
        'pattern', 'match_type', 'priority', 'is_active',
    )
    ordering = ('priority', 'pk')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'parent')
    list_filter = ('user',)
    search_fields = ('name',)
    inlines = (CategoryRuleInline,)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'brand')
    search_fields = ('name', 'brand')
