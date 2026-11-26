from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError
from pydantic import Field

from inventory.models import Inventory
from inventory.services import InsufficientStock, add_stock, remove_stock

router = Router(tags=["inventory"])


class InventoryOut(Schema):
    sku: str
    total_quantity: int
    allocated_quantity: int
    available_quantity: int


class StockChangeIn(Schema):
    quantity: int = Field(gt=0, strict=True)


def _get_inventory_or_404(sku: str) -> Inventory:
    return get_object_or_404(
        Inventory.objects.select_related("product"), product__sku=sku
    )


def _to_out(inventory: Inventory) -> InventoryOut:
    return InventoryOut(
        sku=inventory.product.sku,
        total_quantity=inventory.total_quantity,
        allocated_quantity=inventory.allocated_quantity,
        available_quantity=inventory.total_quantity - inventory.allocated_quantity,
    )


@router.get("/products/{sku}/inventory", response=InventoryOut)
def get_inventory(request, sku: str):
    return _to_out(_get_inventory_or_404(sku))


@router.post("/products/{sku}/inventory/add", response=InventoryOut)
def add_inventory(request, sku: str, payload: StockChangeIn):
    inventory = _get_inventory_or_404(sku)

    try:
        add_stock(inventory, payload.quantity)
    except Inventory.DoesNotExist as exc:
        raise HttpError(404, "Not Found") from exc
    return _to_out(inventory)


@router.post("/products/{sku}/inventory/remove", response=InventoryOut)
def remove_inventory(request, sku: str, payload: StockChangeIn):
    inventory = _get_inventory_or_404(sku)

    try:
        remove_stock(inventory, payload.quantity)
    except InsufficientStock as exc:
        raise HttpError(409, str(exc)) from exc
    except Inventory.DoesNotExist as exc:
        raise HttpError(404, "Not Found") from exc

    return _to_out(inventory)
