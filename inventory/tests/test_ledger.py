from importlib import import_module
from io import StringIO

import pytest
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from inventory.models import Inventory, StockMovement
from inventory.reconciliation import find_discrepancies
from inventory.services import (
    InsufficientStock,
    add_stock,
    allocate_stock,
    release_stock,
    remove_stock,
)
from inventory.tests.factories import InventoryFactory

Reason = StockMovement.Reason


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("operation", "reason", "total_delta", "allocated_delta"),
    [
        (add_stock, Reason.STOCK_ADDED, 4, 0),
        (remove_stock, Reason.STOCK_REMOVED, -4, 0),
        (allocate_stock, Reason.RESERVED, 0, 4),
        (release_stock, Reason.RELEASED, 0, -4),
    ],
)
def test_each_operation_writes_one_ledger_row(
    operation, reason, total_delta, allocated_delta
):
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=5)
    rows_before = inventory.movements.count()

    operation(inventory, 4)

    assert inventory.movements.count() == rows_before + 1
    movement = inventory.movements.order_by("-id").first()
    assert movement.reason == reason
    assert movement.total_delta == total_delta
    assert movement.allocated_delta == allocated_delta


@pytest.mark.django_db
def test_a_rejected_operation_writes_no_ledger_row():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=8)
    rows_before = inventory.movements.count()

    with pytest.raises(InsufficientStock):
        allocate_stock(inventory, 5)

    assert inventory.movements.count() == rows_before


@pytest.mark.django_db
def test_the_counter_rolls_back_if_the_ledger_write_fails(monkeypatch):
    inventory = InventoryFactory(total_quantity=10)

    def ledger_down(*args, **kwargs):
        raise RuntimeError("ledger down")

    monkeypatch.setattr("inventory.services._record_movement", ledger_down)

    with pytest.raises(RuntimeError):
        add_stock(inventory, 5)

    inventory.refresh_from_db()
    assert inventory.total_quantity == 10


@pytest.mark.django_db
def test_an_empty_movement_is_rejected():
    inventory = InventoryFactory()

    with pytest.raises(IntegrityError) as excinfo:
        with transaction.atomic():
            StockMovement.objects.create(
                inventory=inventory,
                reason=Reason.STOCK_ADDED,
                total_delta=0,
                allocated_delta=0,
            )

    assert "stockmovement_not_empty" in str(excinfo.value)


@pytest.mark.django_db
def test_an_inventory_with_ledger_rows_cannot_be_deleted():
    inventory = InventoryFactory(total_quantity=10)

    with pytest.raises(ProtectedError):
        inventory.delete()


@pytest.mark.django_db
def test_a_sequence_of_operations_still_reconciles():
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=0)

    add_stock(inventory, 20)
    allocate_stock(inventory, 12)
    release_stock(inventory, 5)
    remove_stock(inventory, 3)

    inventory.refresh_from_db()
    assert (inventory.total_quantity, inventory.allocated_quantity) == (27, 7)
    assert find_discrepancies() == []


@pytest.mark.django_db
def test_a_change_made_outside_the_services_is_detected():
    inventory = InventoryFactory(product__sku="DEMO-1", total_quantity=10)

    # Bypasses the services, so no ledger row is written.
    Inventory.objects.filter(pk=inventory.pk).update(total_quantity=50)

    (discrepancy,) = find_discrepancies()
    assert discrepancy.sku == "DEMO-1"
    assert discrepancy.total_quantity == 50
    assert discrepancy.ledger_total == 10


@pytest.mark.django_db
def test_an_inventory_with_no_ledger_rows_is_reported():
    InventoryFactory(product__sku="DEMO-1", total_quantity=10, opening_balance=False)

    (discrepancy,) = find_discrepancies()
    assert discrepancy.ledger_total == 0
    assert discrepancy.total_quantity == 10


@pytest.mark.django_db
def test_reconcile_stock_command_reports_success():
    InventoryFactory(total_quantity=10)
    out = StringIO()

    call_command("reconcile_stock", stdout=out)

    assert "All inventories reconcile." in out.getvalue()


@pytest.mark.django_db
def test_reconcile_stock_command_fails_and_names_the_inventory():
    inventory = InventoryFactory(product__sku="DEMO-1", total_quantity=10)
    Inventory.objects.filter(pk=inventory.pk).update(total_quantity=50)
    out = StringIO()

    with pytest.raises(CommandError, match="1 inventories do not reconcile"):
        call_command("reconcile_stock", stdout=out)

    assert "DEMO-1" in out.getvalue()


@pytest.mark.django_db
def test_the_opening_balance_migration_makes_existing_stock_reconcile():
    migration = import_module("inventory.migrations.0005_opening_balances")
    # Inventories that existed before the ledger: counters but no ledger rows.
    InventoryFactory(total_quantity=10, allocated_quantity=2, opening_balance=False)
    InventoryFactory(total_quantity=0, allocated_quantity=0, opening_balance=False)

    migration.create_opening_balances(apps, None)

    assert StockMovement.objects.count() == 1  # the empty inventory is skipped
    assert find_discrepancies() == []
