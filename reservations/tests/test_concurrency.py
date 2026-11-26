import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection

from inventory.models import Inventory
from inventory.services import InsufficientStock
from inventory.tests.factories import InventoryFactory
from reservations.models import Reservation
from reservations.services import reserve_stock

THREADS = 30
STOCK = 10


def _try_to_reserve(inventory_pk: int, barrier: threading.Barrier) -> str:
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


@pytest.mark.django_db(transaction=True)
def test_concurrent_reservations_never_oversell():
    inventory = InventoryFactory(total_quantity=STOCK, allocated_quantity=0)
    barrier = threading.Barrier(THREADS)

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = [
            pool.submit(_try_to_reserve, inventory.pk, barrier) for _ in range(THREADS)
        ]
        results = [future.result() for future in futures]

    inventory.refresh_from_db()
    reservations = Reservation.objects.filter(inventory=inventory)

    assert results.count("reserved") == STOCK
    assert results.count("rejected") == THREADS - STOCK
    assert inventory.allocated_quantity == STOCK
    assert reservations.count() == STOCK
