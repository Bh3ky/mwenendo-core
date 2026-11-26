import pytest
from django.db import DataError
from django.db.models import Sum

from inventory.services import InsufficientStock, StockError
from inventory.tests.factories import InventoryFactory
from reservations.models import Reservation
from reservations.services import (
    InvalidTransition,
    cancel_reservation,
    confirm_reservation,
    reserve_stock,
)
from reservations.tests.factories import ReservationFactory


@pytest.mark.django_db
def test_reserve_stock_allocates_and_creates_a_pending_reservation():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=2)

    reservation = reserve_stock(inventory, 3, "order-1")

    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 5
    assert reservation.quantity == 3
    assert reservation.reference == "order-1"
    assert reservation.status == Reservation.Status.PENDING


@pytest.mark.django_db
def test_reserve_stock_rejects_more_than_is_unallocated():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=8)

    with pytest.raises(InsufficientStock):
        reserve_stock(inventory, 3, "order-1")

    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 8
    assert Reservation.objects.count() == 0


@pytest.mark.django_db
def test_reserve_stock_rolls_back_the_counter_if_the_insert_fails():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=0)

    # A reference longer than the column allows makes the INSERT fail
    # after the counter has already been updated.
    with pytest.raises(DataError):
        reserve_stock(inventory, 3, "x" * 300)

    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 0
    assert Reservation.objects.count() == 0


@pytest.mark.django_db
def test_allocated_quantity_equals_the_sum_of_reservations():
    inventory = InventoryFactory(total_quantity=100, allocated_quantity=0)

    reserve_stock(inventory, 10, "a")
    reserve_stock(inventory, 25, "b")
    reserve_stock(inventory, 5, "c")

    inventory.refresh_from_db()
    total_reserved = Reservation.objects.filter(inventory=inventory).aggregate(
        total=Sum("quantity")
    )["total"]
    assert inventory.allocated_quantity == total_reserved == 40


Status = Reservation.Status


@pytest.mark.django_db
def test_confirm_moves_pending_to_confirmed_and_keeps_stock_allocated():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=3)
    reservation = ReservationFactory(inventory=inventory, quantity=3)

    confirm_reservation(reservation)

    inventory.refresh_from_db()
    assert reservation.status == Status.CONFIRMED
    assert inventory.allocated_quantity == 3


@pytest.mark.django_db
@pytest.mark.parametrize("start", [Status.PENDING, Status.CONFIRMED])
def test_cancel_releases_the_stock(start):
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=5)
    reservation = ReservationFactory(inventory=inventory, quantity=3, status=start)

    cancel_reservation(reservation)

    inventory.refresh_from_db()
    assert reservation.status == Status.CANCELLED
    assert inventory.allocated_quantity == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "action"),
    [
        (Status.CONFIRMED, confirm_reservation),
        (Status.CANCELLED, confirm_reservation),
        (Status.CANCELLED, cancel_reservation),
    ],
)
def test_illegal_transitions_are_rejected_and_change_nothing(start, action):
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=5)
    reservation = ReservationFactory(inventory=inventory, quantity=3, status=start)

    with pytest.raises(InvalidTransition):
        action(reservation)

    inventory.refresh_from_db()
    reservation.refresh_from_db()
    assert reservation.status == start
    assert inventory.allocated_quantity == 5


@pytest.mark.django_db
def test_cancel_rolls_back_the_status_if_releasing_stock_fails(monkeypatch):
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=5)
    reservation = ReservationFactory(inventory=inventory, quantity=3)

    def release_fails(inventory, quantity):
        raise StockError("boom")

    monkeypatch.setattr("reservations.services.release_stock", release_fails)

    with pytest.raises(StockError):
        cancel_reservation(reservation)

    reservation.refresh_from_db()
    inventory.refresh_from_db()
    assert reservation.status == Status.PENDING
    assert inventory.allocated_quantity == 5


@pytest.mark.django_db
def test_transition_of_a_deleted_reservation_raises_does_not_exist():
    reservation = ReservationFactory()
    Reservation.objects.filter(pk=reservation.pk).delete()

    with pytest.raises(Reservation.DoesNotExist):
        confirm_reservation(reservation)
