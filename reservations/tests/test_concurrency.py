import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection, transaction

from inventory.models import Inventory
from inventory.services import InsufficientStock
from inventory.tests.factories import InventoryFactory
from reservations.models import Reservation
from reservations.services import reserve_stock

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


@pytest.mark.django_db(transaction=True)
def test_select_for_update_also_prevents_oversell():
    inventory, results = _race(_row_lock_worker)

    _assert_no_oversell(inventory, results)
