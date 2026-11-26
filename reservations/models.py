import uuid

from django.db import models
from django.db.models import Q

from inventory.models import Inventory


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    # The integer primary key stays internal; clients only ever see public_id.
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    quantity = models.PositiveBigIntegerField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reference = models.CharField(max_length=255)
    # Empty means the client sent no key. Real keys must be unique.
    idempotency_key = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    # When a pending reservation stops holding stock. Null means it never
    # expires, which is how reservations made before expiry existed behave.
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="reservation_quantity_gt_zero",
            ),
            models.UniqueConstraint(
                fields=["idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="reservation_idempotency_key_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.public_id} ({self.status}): {self.quantity}"
