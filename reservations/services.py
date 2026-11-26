from django.db import transaction

from inventory.models import Inventory
from inventory.services import allocate_stock
from reservations.models import Reservation


def reserve_stock(inventory: Inventory, quantity: int, reference: str) -> Reservation:
    """Hold `quantity` units and record who holds them, as one unit of work.

    The counter update and the reservation insert share a transaction, so
    either both happen or neither does.
    """
    with transaction.atomic():
        allocate_stock(inventory, quantity)
        return Reservation.objects.create(
            inventory=inventory,
            quantity=quantity,
            reference=reference,
        )
