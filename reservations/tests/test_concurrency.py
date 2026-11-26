import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.utils import timezone

from inventory.models import Inventory
from inventory.reconciliation import find_discrepancies
from inventory.services import InsufficientStock
from inventory.tests.factories import InventoryFactory
from reservations.models import Reservation
from reservations.services import (
    InvalidTransition,
    cancel_reservation,
    expire_reservation,
    reserve_stock,
)
from reservations.tests.factories import ReservationFactory

THREADS = 30
STOCK = 10

Worker = Callable[[int, threading.Barrier], str]


def _conditional_update_worker(inventory_pk: int, barrier: threading.Barrier) -> str:
    """The real code path: one conditional UPDATE (ADR-0008, option 1)."""
    try:
        inventory = Inventory.objects.get(pk=inventory_pk)
        # Hold every thread here until all have loaded the row, then release
        # them together so the requests really do overlap.
        barrier.wait(timeout=10)
        reserve_stock(inventory, 1, "concurrency-test")
        return "reserved"
    except InsufficientStock:
        return "rejected"
    finally:
        # Each thread opens its own database connection. Close it, or the
        # test database cannot be dropped at the end of the run.
        connection.close()


def _row_lock_worker(inventory_pk: int, barrier: threading.Barrier) -> str:
    """The alternative: lock the row, decide in Python, write (option 2)."""
    try:
        barrier.wait(timeout=10)
        with transaction.atomic():
            # SELECT ... FOR UPDATE: other threads wait here until we commit.
            inventory = Inventory.objects.select_for_update().get(pk=inventory_pk)
            if inventory.total_quantity - inventory.allocated_quantity < 1:
                return "rejected"
            inventory.allocated_quantity += 1
            inventory.save(update_fields=["allocated_quantity"])
            Reservation.objects.create(
                inventory=inventory, quantity=1, reference="concurrency-test"
            )
            return "reserved"
    finally:
        connection.close()


def _race(worker: Worker) -> tuple[Inventory, list[str]]:
    inventory = InventoryFactory(total_quantity=STOCK, allocated_quantity=0)
    barrier = threading.Barrier(THREADS)

    # One worker per thread, so every thread reaches the barrier together.
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = [pool.submit(worker, inventory.pk, barrier) for _ in range(THREADS)]
        results = [future.result() for future in futures]

    inventory.refresh_from_db()
    return inventory, results


def _assert_no_oversell(inventory: Inventory, results: list[str]) -> None:
    reservations = Reservation.objects.filter(inventory=inventory)

    assert results.count("reserved") == STOCK
    assert results.count("rejected") == THREADS - STOCK
    assert inventory.allocated_quantity == STOCK
    assert reservations.count() == STOCK


@pytest.mark.django_db(transaction=True)
def test_concurrent_reservations_never_oversell():
    inventory, results = _race(_conditional_update_worker)

    _assert_no_oversell(inventory, results)
    # The ledger agrees with the counters after the race.
    assert find_discrepancies() == []


@pytest.mark.django_db(transaction=True)
def test_select_for_update_also_prevents_oversell():
    inventory, results = _race(_row_lock_worker)

    _assert_no_oversell(inventory, results)


CANCELLERS = 10


def _cancel_worker(reservation_pk: int, barrier: threading.Barrier) -> str:
    try:
        reservation = Reservation.objects.get(pk=reservation_pk)
        barrier.wait(timeout=10)
        cancel_reservation(reservation)
        return "cancelled"
    except InvalidTransition:
        return "rejected"
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_concurrent_cancels_release_stock_exactly_once():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=3)
    reservation = ReservationFactory(inventory=inventory, quantity=3)
    barrier = threading.Barrier(CANCELLERS)

    with ThreadPoolExecutor(max_workers=CANCELLERS) as pool:
        futures = [
            pool.submit(_cancel_worker, reservation.pk, barrier)
            for _ in range(CANCELLERS)
        ]
        results = [future.result() for future in futures]

    inventory.refresh_from_db()
    reservation.refresh_from_db()

    assert results.count("cancelled") == 1
    assert results.count("rejected") == CANCELLERS - 1
    assert reservation.status == Reservation.Status.CANCELLED
    # Released once: 3 allocated minus 3, not minus 30.
    assert inventory.allocated_quantity == 0
    assert find_discrepancies() == []


def _same_key_worker(inventory_pk: int, barrier: threading.Barrier) -> str:
    try:
        inventory = Inventory.objects.get(pk=inventory_pk)
        barrier.wait(timeout=10)
        reservation = reserve_stock(inventory, 3, "order-1", idempotency_key="key-1")
        return str(reservation.public_id)
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_with_the_same_key_create_one_reservation():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=0)
    barrier = threading.Barrier(CANCELLERS)

    with ThreadPoolExecutor(max_workers=CANCELLERS) as pool:
        futures = [
            pool.submit(_same_key_worker, inventory.pk, barrier)
            for _ in range(CANCELLERS)
        ]
        results = [future.result() for future in futures]

    inventory.refresh_from_db()

    # Every request got the same reservation back, and stock was held once.
    assert len(set(results)) == 1
    assert Reservation.objects.count() == 1
    assert inventory.allocated_quantity == 3
    # A request that lost the race rolled back its ledger row with its stock.
    assert find_discrepancies() == []


def _expire_worker(reservation_pk: int, barrier: threading.Barrier) -> str:
    try:
        reservation = Reservation.objects.get(pk=reservation_pk)
        barrier.wait(timeout=10)
        return "expired" if expire_reservation(reservation) else "skipped"
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_concurrent_expiry_releases_stock_exactly_once():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=3)
    reservation = ReservationFactory(
        inventory=inventory,
        quantity=3,
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    barrier = threading.Barrier(CANCELLERS)

    with ThreadPoolExecutor(max_workers=CANCELLERS) as pool:
        futures = [
            pool.submit(_expire_worker, reservation.pk, barrier)
            for _ in range(CANCELLERS)
        ]
        results = [future.result() for future in futures]

    inventory.refresh_from_db()
    reservation.refresh_from_db()

    assert results.count("expired") == 1
    assert results.count("skipped") == CANCELLERS - 1
    assert reservation.status == Reservation.Status.EXPIRED
    assert inventory.allocated_quantity == 0
    assert find_discrepancies() == []
