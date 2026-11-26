from dataclasses import dataclass

from django.db.models import Sum
from django.db.models.functions import Coalesce

from inventory.models import Inventory


@dataclass(frozen=True)
class Discrepancy:
    """An inventory whose counters do not match the sum of its ledger rows."""

    inventory_id: int
    sku: str
    total_quantity: int
    ledger_total: int
    allocated_quantity: int
    ledger_allocated: int


def find_discrepancies() -> list[Discrepancy]:
    inventories = Inventory.objects.select_related("product").annotate(
        ledger_total=Coalesce(Sum("movements__total_delta"), 0),
        ledger_allocated=Coalesce(Sum("movements__allocated_delta"), 0),
    )

    return [
        Discrepancy(
            inventory_id=inventory.pk,
            sku=inventory.product.sku,
            total_quantity=inventory.total_quantity,
            ledger_total=inventory.ledger_total,
            allocated_quantity=inventory.allocated_quantity,
            ledger_allocated=inventory.ledger_allocated,
        )
        for inventory in inventories
        if inventory.total_quantity != inventory.ledger_total
        or inventory.allocated_quantity != inventory.ledger_allocated
    ]
