from django.db.models import F

from inventory.models import Inventory


class StockError(Exception):
    """Base class for stock operation errors."""


class InvalidQuantity(StockError, ValueError):
    """The quantity is not a positive integer."""


class InsufficientStock(StockError):
    """The operation would leave less stock than is already allocated."""


def _validate_quantity(quantity: int) -> None:
    # bool is a subclass of int, so True would otherwise pass as 1
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise InvalidQuantity(f"Quantity must be an integer, got {quantity!r}")
    if quantity <= 0:
        raise InvalidQuantity(f"Quantity must be positive, got {quantity}")


def add_stock(inventory: Inventory, quantity: int) -> None:
    _validate_quantity(quantity)

    updated = Inventory.objects.filter(pk=inventory.pk).update(
        total_quantity=F("total_quantity") + quantity
    )
    if updated == 0:
        raise Inventory.DoesNotExist(f"Inventory {inventory.pk} does not exist")

    inventory.refresh_from_db()


def remove_stock(inventory: Inventory, quantity: int) -> None:
    # validate quantity
    _validate_quantity(quantity)

    # perform a conditional database update
    updated = Inventory.objects.filter(
        pk=inventory.pk,
        total_quantity__gte=F("allocated_quantity") + quantity,
    ).update(total_quantity=F("total_quantity") - quantity)

    # handle unsuccessful update
    if updated == 0:
        inventory.refresh_from_db()

        available = inventory.total_quantity - inventory.allocated_quantity

        raise InsufficientStock(
            f"Cannot remove {quantity} units: "
            f"only {available} are unallocated "
            f"(total {inventory.total_quantity}, "
            f"allocated {inventory.allocated_quantity})."
        )

    inventory.refresh_from_db()
