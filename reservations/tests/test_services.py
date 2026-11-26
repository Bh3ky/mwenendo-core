import pytest
from django.db import DataError
from django.db.models import Sum

from inventory.services import InsufficientStock
from inventory.tests.factories import InventoryFactory
from reservations.models import Reservation
from reservations.services import reserve_stock


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
