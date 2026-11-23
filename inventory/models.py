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
