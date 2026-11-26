import uuid

from django.db import IntegrityError, transaction

from inventory.models import Inventory
from inventory.services import allocate_stock, release_stock
from reservations.models import Reservation


class IdempotencyKeyReused(Exception):
    """The key was already used for a different request."""


def _replay(
    existing: Reservation, inventory: Inventory, quantity: int, reference: str
) -> Reservation:
    same_request = (existing.inventory_id, existing.quantity, existing.reference) == (
        inventory.pk,
        quantity,
        reference,
    )
    if not same_request:
        raise IdempotencyKeyReused(
            "This idempotency key was already used for a different request."
        )
    return existing


def reserve_stock(
    inventory: Inventory,
    quantity: int,
    reference: str,
    idempotency_key: str = "",
) -> Reservation:
    """Hold `quantity` units and record who holds them, as one unit of work.

    The counter update and the reservation insert share a transaction, so
    either both happen or neither does.

    With an idempotency key, repeating the same request returns the original
    reservation instead of holding more stock. Reusing the key for a different
    request raises IdempotencyKeyReused.
    """
    if idempotency_key:
        existing = Reservation.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return _replay(existing, inventory, quantity, reference)

    try:
        with transaction.atomic():
            public_id = uuid.uuid4()
            allocate_stock(inventory, quantity, reservation_public_id=public_id)
            return Reservation.objects.create(
                public_id=public_id,
                inventory=inventory,
                quantity=quantity,
                reference=reference,
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        # Two requests with the same key can both miss the lookup above. The
        # unique constraint lets only one insert win, and the loser's stock
        # allocation was rolled back with its transaction. Return the winner's.
        if idempotency_key:
            existing = Reservation.objects.filter(
                idempotency_key=idempotency_key
            ).first()
            if existing is not None:
                inventory.refresh_from_db()
                return _replay(existing, inventory, quantity, reference)
        raise


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
        release_stock(
            reservation.inventory,
            reservation.quantity,
            reservation_public_id=reservation.public_id,
        )
