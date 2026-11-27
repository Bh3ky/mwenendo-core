from django.contrib import admin

from core.admin import ReadOnlyModelAdmin
from reservations.models import Reservation


@admin.register(Reservation)
class ReservationAdmin(ReadOnlyModelAdmin):
    list_display = (
        "public_id",
        "inventory",
        "quantity",
        "status",
        "reference",
        "expires_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("public_id", "reference", "inventory__product__sku")
    date_hierarchy = "created_at"
