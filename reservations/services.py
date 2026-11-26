from django.db import transaction

from inventory.models import Inventory
from inventory.services import allocate_stock, release_stock
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


class InvalidTransition(Exception):
    """The reservation is not in a state that allows this change."""


# The single source of truth for the lifecycle: from-state -> allowed to-states.
Status = Reservation.Status
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Status.PENDING: {Status.CONFIRMED, Status.CANCELLED},
    Status.CONFIRMED: {Status.CANCELLED},
    Status.CANCELLED: set(),
}


def _transition(reservation: Reservation, to_status: str) -> None:
    allowed_from = [
        from_status
        for from_status, targets in ALLOWED_TRANSITIONS.items()
        if to_status in targets
    ]

    # One conditional UPDATE: the state check and the write are the same
    # statement, so of two competing requests only one can match.
    updated = Reservation.objects.filter(
        pk=reservation.pk, status__in=allowed_from
    ).update(status=to_status)

    if updated == 0:
        if not Reservation.objects.filter(pk=reservation.pk).exists():
            raise Reservation.DoesNotExist(
                f"Reservation {reservation.pk} does not exist"
            )

        reservation.refresh_from_db()
        raise InvalidTransition(
            f"Cannot move a {reservation.status} reservation to {to_status}."
        )

    reservation.refresh_from_db()


def confirm_reservation(reservation: Reservation) -> None:
    _transition(reservation, Status.CONFIRMED)


def cancel_reservation(reservation: Reservation) -> None:
    """Cancel a reservation and give its stock back, as one unit of work.

    The status change claims the cancellation first. Only the request that wins
    it goes on to release the stock, so stock is released at most once.
    """
    with transaction.atomic():
        _transition(reservation, Status.CANCELLED)
        release_stock(reservation.inventory, reservation.quantity)
