from django.db import models
from django.db.models import F, Q


class Product(models.Model):
    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)

    def __str__(self) -> str:
        return f"{self.sku} - {self.name}"


class Inventory(models.Model):
    product = models.OneToOneField(
        Product,
        on_delete=models.PROTECT,
        related_name="inventory",
    )
    total_quantity = models.PositiveBigIntegerField(default=0)
    allocated_quantity = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(allocated_quantity__lte=F("total_quantity")),
                name="inventory_allocated_lte_total",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product.sku}: {self.allocated_quantity}/{self.total_quantity}"


class StockMovement(models.Model):
    """One append-only entry in the stock ledger.

    Every change to an Inventory counter writes a row here in the same
    transaction. The deltas of all rows for an inventory add up to its
    counters, which `reconcile_stock` checks. Rows are never updated.
    """

    class Reason(models.TextChoices):
        OPENING_BALANCE = "opening_balance", "Opening balance"
        STOCK_ADDED = "stock_added", "Stock added"
        STOCK_REMOVED = "stock_removed", "Stock removed"
        RESERVED = "reserved", "Reserved"
        RELEASED = "released", "Released"

    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.PROTECT,
        related_name="movements",
    )
    total_delta = models.BigIntegerField(default=0)
    allocated_delta = models.BigIntegerField(default=0)
    reason = models.CharField(max_length=32, choices=Reason.choices)
    # A loose link to a reservation. It is not a foreign key, so the inventory
    # app does not depend on the reservations app (ADR-0002).
    reservation_public_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~(Q(total_delta=0) & Q(allocated_delta=0)),
                name="stockmovement_not_empty",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.reason}: total {self.total_delta:+}, "
            f"allocated {self.allocated_delta:+}"
        )
