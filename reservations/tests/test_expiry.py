import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from config.celery import app
from inventory.models import StockMovement
from inventory.tests.factories import InventoryFactory
from reservations import services
from reservations.models import Reservation
from reservations.services import (
    InvalidTransition,
    confirm_reservation,
    expire_overdue_reservations,
    expire_reservation,
    reserve_stock,
)
from reservations.tasks import expire_reservation_task
from reservations.tests.factories import ReservationFactory

Status = Reservation.Status


def _overdue():
    return timezone.now() - timedelta(minutes=1)


def _later():
    return timezone.now() + timedelta(minutes=10)


@pytest.mark.django_db
def test_reserving_sets_expires_at_from_the_ttl():
    inventory = InventoryFactory(total_quantity=10)
    before = timezone.now()

    reservation = reserve_stock(inventory, 1, "order-1")

    ttl = timedelta(minutes=settings.RESERVATION_TTL_MINUTES)
    assert before + ttl <= reservation.expires_at <= timezone.now() + ttl


@pytest.mark.django_db
def test_reserving_schedules_expiry_once_the_transaction_commits(
    django_capture_on_commit_callbacks, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        "reservations.tasks.expire_reservation_task.apply_async",
        lambda args, countdown: calls.append((args, countdown)),
    )
    inventory = InventoryFactory(total_quantity=10)

    with django_capture_on_commit_callbacks(execute=True):
        reservation = reserve_stock(inventory, 1, "order-1")
        assert calls == []  # nothing is sent before the commit

    ttl_seconds = settings.RESERVATION_TTL_MINUTES * 60
    assert calls == [([str(reservation.public_id)], ttl_seconds + 1)]


@pytest.mark.django_db
def test_a_scheduling_failure_does_not_break_the_reservation(
    django_capture_on_commit_callbacks, monkeypatch
):
    def broker_down(args, countdown):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(
        "reservations.tasks.expire_reservation_task.apply_async", broker_down
    )
    inventory = InventoryFactory(total_quantity=10)

    with django_capture_on_commit_callbacks(execute=True):
        reserve_stock(inventory, 1, "order-1")

    assert Reservation.objects.count() == 1


@pytest.mark.django_db
def test_expiring_a_due_reservation_releases_its_stock():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=5)
    reservation = ReservationFactory(
        inventory=inventory, quantity=3, expires_at=_overdue()
    )

    assert expire_reservation(reservation) is True

    inventory.refresh_from_db()
    assert reservation.status == Status.EXPIRED
    assert inventory.allocated_quantity == 2
    assert StockMovement.objects.filter(
        reservation_public_id=reservation.public_id,
        reason=StockMovement.Reason.RELEASED,
    ).exists()


@pytest.mark.django_db
def test_a_reservation_that_is_not_due_is_left_alone():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=5)
    reservation = ReservationFactory(
        inventory=inventory, quantity=3, expires_at=_later()
    )

    assert expire_reservation(reservation) is False

    inventory.refresh_from_db()
    reservation.refresh_from_db()
    assert reservation.status == Status.PENDING
    assert inventory.allocated_quantity == 5


@pytest.mark.django_db
def test_a_reservation_with_no_deadline_never_expires():
    reservation = ReservationFactory(expires_at=None)

    assert expire_reservation(reservation) is False
    assert expire_overdue_reservations() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("status", [Status.CONFIRMED, Status.CANCELLED, Status.EXPIRED])
def test_only_pending_reservations_expire(status):
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=5)
    reservation = ReservationFactory(
        inventory=inventory, quantity=3, status=status, expires_at=_overdue()
    )

    assert expire_reservation(reservation) is False

    inventory.refresh_from_db()
    reservation.refresh_from_db()
    assert reservation.status == status
    assert inventory.allocated_quantity == 5


@pytest.mark.django_db
def test_expiring_twice_releases_the_stock_once():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=5)
    reservation = ReservationFactory(
        inventory=inventory, quantity=3, expires_at=_overdue()
    )

    assert expire_reservation(reservation) is True
    assert expire_reservation(reservation) is False

    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 2


@pytest.mark.django_db
def test_an_overdue_reservation_cannot_be_confirmed():
    reservation = ReservationFactory(expires_at=_overdue())

    with pytest.raises(InvalidTransition, match="expired"):
        confirm_reservation(reservation)

    reservation.refresh_from_db()
    assert reservation.status == Status.PENDING


@pytest.mark.django_db
def test_a_reservation_inside_its_deadline_can_be_confirmed():
    reservation = ReservationFactory(expires_at=_later())

    confirm_reservation(reservation)

    assert reservation.status == Status.CONFIRMED


@pytest.mark.django_db
def test_a_confirmed_reservation_is_never_swept():
    reservation = ReservationFactory(expires_at=_later())
    confirm_reservation(reservation)
    Reservation.objects.filter(pk=reservation.pk).update(expires_at=_overdue())

    assert expire_overdue_reservations() == 0

    reservation.refresh_from_db()
    assert reservation.status == Status.CONFIRMED


@pytest.mark.django_db
def test_the_sweep_expires_only_overdue_pending_reservations():
    inventory = InventoryFactory(total_quantity=20, allocated_quantity=8)
    due_a = ReservationFactory(inventory=inventory, quantity=2, expires_at=_overdue())
    due_b = ReservationFactory(inventory=inventory, quantity=2, expires_at=_overdue())
    not_due = ReservationFactory(inventory=inventory, quantity=2, expires_at=_later())
    confirmed = ReservationFactory(
        inventory=inventory, quantity=2, status=Status.CONFIRMED, expires_at=_overdue()
    )

    assert expire_overdue_reservations() == 2

    inventory.refresh_from_db()
    for reservation in (due_a, due_b, not_due, confirmed):
        reservation.refresh_from_db()
    assert (due_a.status, due_b.status) == (Status.EXPIRED, Status.EXPIRED)
    assert not_due.status == Status.PENDING
    assert confirmed.status == Status.CONFIRMED
    assert inventory.allocated_quantity == 4


@pytest.mark.django_db
def test_the_sweep_honours_its_limit():
    inventory = InventoryFactory(total_quantity=20, allocated_quantity=3)
    for _ in range(3):
        ReservationFactory(inventory=inventory, quantity=1, expires_at=_overdue())

    assert expire_overdue_reservations(limit=2) == 2
    assert expire_overdue_reservations(limit=2) == 1


@pytest.mark.django_db
def test_one_failing_reservation_does_not_block_the_sweep(monkeypatch):
    inventory = InventoryFactory(total_quantity=20, allocated_quantity=2)
    bad = ReservationFactory(inventory=inventory, quantity=1, expires_at=_overdue())
    good = ReservationFactory(inventory=inventory, quantity=1, expires_at=_overdue())
    real_expire = services.expire_reservation

    def flaky(reservation):
        if reservation.pk == bad.pk:
            raise RuntimeError("boom")
        return real_expire(reservation)

    monkeypatch.setattr("reservations.services.expire_reservation", flaky)

    assert expire_overdue_reservations() == 1

    bad.refresh_from_db()
    good.refresh_from_db()
    assert bad.status == Status.PENDING
    assert good.status == Status.EXPIRED


@pytest.mark.django_db
def test_the_expiry_task_expires_a_due_reservation():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=1)
    reservation = ReservationFactory(
        inventory=inventory, quantity=1, expires_at=_overdue()
    )

    result = expire_reservation_task.delay(str(reservation.public_id)).get()

    reservation.refresh_from_db()
    assert result is True
    assert reservation.status == Status.EXPIRED


@pytest.mark.django_db
def test_the_expiry_task_ignores_an_unknown_reservation():
    assert expire_reservation_task.delay(str(uuid.uuid4())).get() is False


def test_the_sweep_is_scheduled_and_its_task_is_registered():
    schedule = settings.CELERY_BEAT_SCHEDULE["expire-overdue-reservations"]

    assert schedule["task"] in app.tasks
    assert schedule["schedule"] == 60.0
