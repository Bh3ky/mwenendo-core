import logging
from datetime import timedelta

from celery import shared_task
from django.db import OperationalError, transaction

logger = logging.getLogger(__name__)

# Task bodies import the services inside the function: the services import this
# module to schedule expiry, so importing them here would be circular.


@shared_task(
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_kwargs={"max_retries": 5},
)
def expire_reservation_task(public_id: str) -> bool:
    """Expire one reservation. Safe to run twice or too early: it then does nothing."""
    from reservations.models import Reservation
    from reservations.services import expire_reservation

    reservation = (
        Reservation.objects.select_related("inventory")
        .filter(public_id=public_id)
        .first()
    )
    if reservation is None:
        return False
    return expire_reservation(reservation)


@shared_task
def expire_overdue_reservations() -> int:
    """The periodic sweep. Run by Celery beat every minute."""
    from reservations.services import expire_overdue_reservations as sweep

    return sweep()


def schedule_expiry(public_id, delay: timedelta) -> None:
    """Queue the expiry task for after the current transaction commits."""

    def send() -> None:
        try:
            expire_reservation_task.apply_async(
                args=[str(public_id)], countdown=delay.total_seconds()
            )
        except Exception:
            # The reservation is already committed. If the broker is down, the
            # periodic sweep will expire it instead.
            logger.exception(
                "Could not schedule expiry for reservation %s; "
                "the periodic sweep will handle it.",
                public_id,
            )

    transaction.on_commit(send)
