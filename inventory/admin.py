from django.contrib import admin

from core.admin import ReadOnlyModelAdmin
from inventory.models import Inventory, Product, StockMovement


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name")
    search_fields = ("sku", "name")


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ("product", "total_quantity", "allocated_quantity")
    search_fields = ("product__sku", "product__name")

    # The counters are read-only here on purpose. Changing them in the admin
    # would skip the ledger and break reconciliation (ADR-0011), so stock changes
    # only through the services: the API, or the "Add 10 units" button on /demo/.
    # A new inventory starts at zero.
    readonly_fields = ("total_quantity", "allocated_quantity")

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        # Once it exists, an inventory stays attached to its product.
        return (*fields, "product") if obj else fields


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyModelAdmin):
    list_display = (
        "created_at",
        "inventory",
        "reason",
        "total_delta",
        "allocated_delta",
        "reservation_public_id",
    )
    list_filter = ("reason",)
    search_fields = ("inventory__product__sku", "reservation_public_id")
    date_hierarchy = "created_at"
