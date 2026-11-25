import pytest

from inventory.models import Inventory, Product
from inventory.services import (
    InsufficientStock,
    InvalidQuantity,
    StockError,
    add_stock,
    remove_stock,
)


# shared helper function
def make_inventory(total=10, allocated=0, sku="SKU-1"):
    product = Product.objects.create(sku=sku, name="Widget")
    return Inventory.objects.create(
        product=product, total_quantity=total, allocated_quantity=allocated
    )


@pytest.mark.django_db
def test_add_stock_increases_total_quantity():
    inventory = make_inventory(total=10)

    add_stock(inventory, 5)

    assert Inventory.objects.get(pk=inventory.pk).total_quantity == 15


@pytest.mark.django_db
def test_add_stock_updates_the_object_passed_in():
    inventory = make_inventory(total=10)

    add_stock(inventory, 5)

    assert inventory.total_quantity == 15


@pytest.mark.django_db
@pytest.mark.parametrize("bad_quantity", [0, -5, 2.5, True, "3"])
def test_add_stock_rejects_invalid_quantities(bad_quantity):
    inventory = make_inventory(total=10)

    with pytest.raises(InvalidQuantity):
        add_stock(inventory, bad_quantity)

    assert Inventory.objects.get(pk=inventory.pk).total_quantity == 10


@pytest.mark.django_db
def test_add_stock_handles_two_stale_inventory_objects():
    inventory = make_inventory(total=10)

    a = Inventory.objects.get(pk=inventory.pk)
    b = Inventory.objects.get(pk=inventory.pk)

    add_stock(a, 5)
    add_stock(b, 3)

    updated_inventory = Inventory.objects.get(pk=inventory.pk)

    assert updated_inventory.total_quantity == 18


@pytest.mark.django_db
def test_add_stock_raises_does_not_exist_for_deleted_inventory():
    inventory = make_inventory()

    Inventory.objects.filter(pk=inventory.pk).delete()

    with pytest.raises(Inventory.DoesNotExist, match=r"Inventory \d+ does not exist"):
        add_stock(inventory, 5)


@pytest.mark.django_db
def test_remove_stock_decreases_total():
    inventory = make_inventory(total=10, allocated=0)

    remove_stock(inventory, 4)

    assert Inventory.objects.get(pk=inventory.pk).total_quantity == 6


@pytest.mark.django_db
def test_remove_stock_allows_removal_down_to_allocated_quantity():
    inventory = make_inventory(total=10, allocated=3)

    remove_stock(inventory, 7)

    updated_inventory = Inventory.objects.get(pk=inventory.pk)

    assert updated_inventory.total_quantity == 3


@pytest.mark.django_db
def test_remove_stock_rejects_removal_below_allocated_quantity():
    inventory = make_inventory(total=10, allocated=3)

    with pytest.raises(InsufficientStock) as exc_info:
        remove_stock(inventory, 8)

    updated_inventory = Inventory.objects.get(pk=inventory.pk)

    assert updated_inventory.total_quantity == 10
    assert "only 7 are unallocated" in str(exc_info.value)


@pytest.mark.django_db
def test_remove_stock_uses_current_database_values_for_stale_objects():
    inventory = make_inventory(total=10, allocated=0)

    stale = Inventory.objects.get(pk=inventory.pk)

    # Simulate another operation allocating 3 units.
    Inventory.objects.filter(pk=inventory.pk).update(allocated_quantity=3)

    # The stale object still believes allocated_quantity is 0.
    assert stale.allocated_quantity == 0

    with pytest.raises(InsufficientStock) as exc_info:
        remove_stock(stale, 8)

    updated_inventory = Inventory.objects.get(pk=inventory.pk)

    assert updated_inventory.total_quantity == 10
    assert updated_inventory.allocated_quantity == 3

    assert "only 7 are unallocated" in str(exc_info.value)
    assert "allocated 3" in str(exc_info.value)


@pytest.mark.django_db
@pytest.mark.parametrize("bad_quantity", [0, -5, 2.5, True, "3"])
def test_remove_stock_rejects_invalid_quantities(bad_quantity):
    inventory = make_inventory(total=10, allocated=0)

    with pytest.raises(InvalidQuantity):
        remove_stock(inventory, bad_quantity)

    assert Inventory.objects.get(pk=inventory.pk).total_quantity == 10


@pytest.mark.django_db
def test_remove_stock_raises_does_not_exist_for_deleted_inventory():
    inventory = make_inventory()

    Inventory.objects.filter(pk=inventory.pk).delete()

    with pytest.raises(Inventory.DoesNotExist, match=r"Inventory \d+ does not exist"):
        remove_stock(inventory, 5)


def test_exception_hierarchy():
    assert issubclass(InvalidQuantity, StockError)
    assert issubclass(InvalidQuantity, ValueError)
    assert issubclass(InsufficientStock, StockError)
