from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from inventory.models import Inventory

router = Router(tags=["inventory"])


class InventoryOut(Schema):
    sku: str
    total_quantity: int
    allocated_quantity: int
    available_quantity: int


@router.get("/products/{sku}/inventory", response=InventoryOut)
def get_inventory(request, sku: str):
    inventory = get_object_or_404(
        Inventory.objects.select_related("product"), product__sku=sku
    )
    return InventoryOut(
        sku=inventory.product.sku,
        total_quantity=inventory.total_quantity,
        allocated_quantity=inventory.allocated_quantity,
        available_quantity=inventory.total_quantity - inventory.allocated_quantity,
    )
