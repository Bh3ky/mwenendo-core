import pytest
from django.db import IntegrityError, transaction

from inventory.models import Inventory, Product


@pytest.mark.django_db
def test_sku_must_be_unique():
    Product.objects.create(sku="SKU-1", name="First")

    with pytest.raises(IntegrityError) as excinfo:
        # atomic() creates a savepoint, a rollback point inside the transaction
        with transaction.atomic():
            Product.objects.create(sku="SKU-1", name="Second")

    assert "inventory_product_sku_key" in str(excinfo.value)


@pytest.mark.django_db
def test_product_can_have_only_one_inventory_row():
    product = Product.objects.create(sku="SKU-1", name="Widget")
    Inventory.objects.create(product=product)

    with pytest.raises(IntegrityError) as excinfo:
        with transaction.atomic():
            Inventory.objects.create(product=product)

    # assert the right error
    assert "inventory_inventory_product_id_key" in str(excinfo.value)


@pytest.mark.django_db
def test_different_products_can_each_have_inventory():
    first = Product.objects.create(sku="SKU-1", name="First")
    second = Product.objects.create(sku="SKU-2", name="Second")

    Inventory.objects.create(product=first)
    Inventory.objects.create(product=second)

    assert Inventory.objects.count() == 2


@pytest.mark.django_db
def test_allocated_may_equal_total():
    product = Product.objects.create(sku="SKU-1", name="Widget")

    inventory = Inventory.objects.create(
        product=product, total_quantity=5, allocated_quantity=5
    )

    # reload the row from Postgres
    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 5


@pytest.mark.django_db
def test_over_allocation_on_insert_rejected():
    product = Product.objects.create(sku="SKU-1", name="Widget")

    with pytest.raises(IntegrityError) as excinfo:
        with transaction.atomic():
            Inventory.objects.create(
                product=product, total_quantity=5, allocated_quantity=6
            )

    assert "inventory_allocated_lte_total" in str(excinfo.value)


@pytest.mark.django_db
def test_over_allocation_through_update_rejected():
    product = Product.objects.create(sku="SKU-1", name="Widget")
    inventory = Inventory.objects.create(
        product=product, total_quantity=5, allocated_quantity=3
    )

    with pytest.raises(IntegrityError) as excinfo:
        with transaction.atomic():
            Inventory.objects.filter(pk=inventory.pk).update(allocated_quantity=999)

    assert "inventory_allocated_lte_total" in str(excinfo.value)

    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 3


@pytest.mark.django_db
def test_negative_allocated_quantity_rejected_on_insert():
    product = Product.objects.create(sku="SKU-1", name="Widget")

    with pytest.raises(IntegrityError) as excinfo:
        with transaction.atomic():
            Inventory.objects.create(
                product=product, total_quantity=5, allocated_quantity=-1
            )

    assert "inventory_inventory_allocated_quantity_check" in str(excinfo.value)


@pytest.mark.django_db
def test_negative_total_quantity_rejected_on_insert():
    product = Product.objects.create(sku="SKU-1", name="Widget")

    with pytest.raises(IntegrityError) as excinfo:
        with transaction.atomic():
            Inventory.objects.create(
                product=product, total_quantity=-1, allocated_quantity=0
            )

    # a negative total breaks two rules at once (total >= 0
    # and allocated <= total), and Postgres reports only one
    # of them, so we assert the kind of failure, not a
    # specific constraint name.
    assert "violates check constraint" in str(excinfo.value)


@pytest.mark.django_db
def test_negative_allocated_quantity_rejected_on_update():
    product = Product.objects.create(sku="SKU-1", name="Widget")
    inventory = Inventory.objects.create(
        product=product, total_quantity=5, allocated_quantity=3
    )

    with pytest.raises(IntegrityError) as excinfo:
        with transaction.atomic():
            Inventory.objects.filter(pk=inventory.pk).update(allocated_quantity=-1)

    assert "inventory_inventory_allocated_quantity_check" in str(excinfo.value)

    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 3
