import uuid

from django.db import transaction
from django.db.models import F

from inventory.models import Inventory, StockMovement


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


def _record_movement(
    inventory: Inventory,
    reason: str,
    *,
    total_delta: int = 0,
    allocated_delta: int = 0,
    reservation_public_id: uuid.UUID | None = None,
) -> None:
    StockMovement.objects.create(
        inventory_id=inventory.pk,
        reason=reason,
        total_delta=total_delta,
        allocated_delta=allocated_delta,
        reservation_public_id=reservation_public_id,
    )


# Each operation changes the counter and writes its ledger row in one
# transaction, so the counters and the ledger can never disagree.


def add_stock(inventory: Inventory, quantity: int) -> None:
    _validate_quantity(quantity)

    with transaction.atomic():
        updated = Inventory.objects.filter(pk=inventory.pk).update(
            total_quantity=F("total_quantity") + quantity
        )
        if updated == 0:
            raise Inventory.DoesNotExist(f"Inventory {inventory.pk} does not exist")

        _record_movement(
            inventory, StockMovement.Reason.STOCK_ADDED, total_delta=quantity
        )

    inventory.refresh_from_db()


def remove_stock(inventory: Inventory, quantity: int) -> None:
    # validate quantity
    _validate_quantity(quantity)

    with transaction.atomic():
        # perform a conditional database update
        updated = Inventory.objects.filter(
            pk=inventory.pk,
            total_quantity__gte=F("allocated_quantity") + quantity,
        ).update(total_quantity=F("total_quantity") - quantity)

        # handle unsuccessful update
        if updated == 0:
            # a deleted row is a different failure from insufficient stock
            if not Inventory.objects.filter(pk=inventory.pk).exists():
                raise Inventory.DoesNotExist(f"Inventory {inventory.pk} does not exist")

            inventory.refresh_from_db()

            available = inventory.total_quantity - inventory.allocated_quantity

            raise InsufficientStock(
                f"Cannot remove {quantity} units: "
                f"only {available} are unallocated "
                f"(total {inventory.total_quantity}, "
                f"allocated {inventory.allocated_quantity})."
            )

        _record_movement(
            inventory, StockMovement.Reason.STOCK_REMOVED, total_delta=-quantity
        )

    inventory.refresh_from_db()


def allocate_stock(
    inventory: Inventory,
    quantity: int,
    reservation_public_id: uuid.UUID | None = None,
) -> None:
    _validate_quantity(quantity)

    with transaction.atomic():
        # One conditional UPDATE: the check and the write happen in the same
        # statement, so two requests cannot both claim the last units.
        updated = Inventory.objects.filter(
            pk=inventory.pk,
            total_quantity__gte=F("allocated_quantity") + quantity,
        ).update(allocated_quantity=F("allocated_quantity") + quantity)

        if updated == 0:
            if not Inventory.objects.filter(pk=inventory.pk).exists():
                raise Inventory.DoesNotExist(f"Inventory {inventory.pk} does not exist")

            inventory.refresh_from_db()

            available = inventory.total_quantity - inventory.allocated_quantity

            raise InsufficientStock(
                f"Cannot allocate {quantity} units: "
                f"only {available} are unallocated "
                f"(total {inventory.total_quantity}, "
                f"allocated {inventory.allocated_quantity})."
            )

        _record_movement(
            inventory,
            StockMovement.Reason.RESERVED,
            allocated_delta=quantity,
            reservation_public_id=reservation_public_id,
        )

    inventory.refresh_from_db()


def release_stock(
    inventory: Inventory,
    quantity: int,
    reservation_public_id: uuid.UUID | None = None,
) -> None:
    _validate_quantity(quantity)

    with transaction.atomic():
        # Never release more than is allocated: the counter must not go negative.
        updated = Inventory.objects.filter(
            pk=inventory.pk,
            allocated_quantity__gte=quantity,
        ).update(allocated_quantity=F("allocated_quantity") - quantity)

        if updated == 0:
            if not Inventory.objects.filter(pk=inventory.pk).exists():
                raise Inventory.DoesNotExist(f"Inventory {inventory.pk} does not exist")

            inventory.refresh_from_db()

            raise StockError(
                f"Cannot release {quantity} units: "
                f"only {inventory.allocated_quantity} are allocated."
            )

        _record_movement(
            inventory,
            StockMovement.Reason.RELEASED,
            allocated_delta=-quantity,
            reservation_public_id=reservation_public_id,
        )

    inventory.refresh_from_db()
