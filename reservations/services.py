import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from inventory.models import Inventory
from inventory.services import allocate_stock, release_stock
from reservations.models import Reservation
from reservations.tasks import schedule_expiry

logger = logging.getLogger(__name__)


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
            ttl = timedelta(minutes=settings.RESERVATION_TTL_MINUTES)
            allocate_stock(inventory, quantity, reservation_public_id=public_id)
            reservation = Reservation.objects.create(
                public_id=public_id,
                expires_at=timezone.now() + ttl,
                inventory=inventory,
                quantity=quantity,
                reference=reference,
                idempotency_key=idempotency_key,
            )
            # Runs only once the transaction commits, so the task can never
            # fire before the reservation exists. The periodic sweep is the
            # safety net if scheduling fails.
            schedule_expiry(reservation.public_id, ttl + timedelta(seconds=1))
            return reservation
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
    Status.PENDING: {Status.CONFIRMED, Status.CANCELLED, Status.EXPIRED},
    Status.CONFIRMED: {Status.CANCELLED},
    Status.CANCELLED: set(),
    Status.EXPIRED: set(),
}


def _allowed_from(to_status: str) -> list[str]:
    return [
        from_status
        for from_status, targets in ALLOWED_TRANSITIONS.items()
        if to_status in targets
    ]


def _not_overdue() -> Q:
    return Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())


def _transition(
    reservation: Reservation, to_status: str, only_if: Q | None = None
) -> None:
    conditions = Q(pk=reservation.pk, status__in=_allowed_from(to_status))
    if only_if is not None:
        conditions &= only_if

    # One conditional UPDATE: the state check and the write are the same
    # statement, so of two competing requests only one can match.
    updated = Reservation.objects.filter(conditions).update(status=to_status)

    if updated == 0:
        if not Reservation.objects.filter(pk=reservation.pk).exists():
            raise Reservation.DoesNotExist(
                f"Reservation {reservation.pk} does not exist"
            )

        reservation.refresh_from_db()
        if only_if is not None and reservation.status == Status.PENDING:
            raise InvalidTransition(
                "The reservation has expired and can no longer be confirmed."
            )
        raise InvalidTransition(
            f"Cannot move a {reservation.status} reservation to {to_status}."
        )

    reservation.refresh_from_db()


def confirm_reservation(reservation: Reservation) -> None:
    # A pending reservation past its deadline cannot be confirmed, even in the
    # moments before the expiry task gets to it.
    _transition(reservation, Status.CONFIRMED, only_if=_not_overdue())


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


def expire_reservation(reservation: Reservation) -> bool:
    """Expire one overdue pending reservation and give its stock back.

    Returns True if this call expired it, False if there was nothing to do
    (already confirmed, cancelled or expired, or not due yet). Safe to repeat,
    and of two competing calls only one releases the stock.
    """
    with transaction.atomic():
        updated = Reservation.objects.filter(
            pk=reservation.pk,
            status__in=_allowed_from(Status.EXPIRED),
            expires_at__lte=timezone.now(),
        ).update(status=Status.EXPIRED)

        if updated == 0:
            return False

        reservation.refresh_from_db()
        release_stock(
            reservation.inventory,
            reservation.quantity,
            reservation_public_id=reservation.public_id,
        )
        return True


SWEEP_BATCH_SIZE = 500


def expire_overdue_reservations(limit: int = SWEEP_BATCH_SIZE) -> int:
    """Expire every overdue pending reservation, up to `limit`. Returns how many.

    The safety net behind the per-reservation tasks. One bad reservation is
    logged and skipped, so it cannot block the rest.
    """
    overdue = (
        Reservation.objects.filter(
            status__in=_allowed_from(Status.EXPIRED), expires_at__lte=timezone.now()
        )
        .select_related("inventory")
        .order_by("expires_at")[:limit]
    )

    expired = 0
    for reservation in list(overdue):
        try:
            if expire_reservation(reservation):
                expired += 1
        except Exception:
            logger.exception("Could not expire reservation %s", reservation.public_id)
    return expired
