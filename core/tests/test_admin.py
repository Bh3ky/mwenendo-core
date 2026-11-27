import re

import pytest

from inventory.models import Inventory, Product, StockMovement
from inventory.reconciliation import find_discrepancies
from inventory.tests.factories import InventoryFactory, ProductFactory
from reservations.tests.factories import ReservationFactory


@pytest.mark.django_db
def test_a_product_can_be_added_in_the_admin(admin_client):
    response = admin_client.post(
        "/admin/inventory/product/add/", {"sku": "ADMIN-1", "name": "Made in admin"}
    )

    assert response.status_code == 302
    assert Product.objects.get(sku="ADMIN-1").name == "Made in admin"


@pytest.mark.django_db
def test_an_inventory_added_in_the_admin_starts_empty_and_reconciles(admin_client):
    product = ProductFactory(sku="ADMIN-2")

    response = admin_client.post(
        "/admin/inventory/inventory/add/", {"product": product.pk}
    )

    assert response.status_code == 302
    inventory = Inventory.objects.get(product=product)
    assert (inventory.total_quantity, inventory.allocated_quantity) == (0, 0)
    # Nothing was written to the counters, so there is nothing for the ledger to miss.
    assert find_discrepancies() == []


@pytest.mark.django_db
def test_the_inventory_form_does_not_offer_the_counters(admin_client):
    page = admin_client.get("/admin/inventory/inventory/add/").content.decode()

    assert 'name="total_quantity"' not in page
    assert 'name="allocated_quantity"' not in page


@pytest.mark.django_db
def test_counters_and_product_cannot_be_changed_through_the_admin(admin_client):
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=2)
    other_product = ProductFactory()
    original_product = inventory.product

    # Even a hand-made request that names the fields cannot change them.
    response = admin_client.post(
        f"/admin/inventory/inventory/{inventory.pk}/change/",
        {
            "total_quantity": 999,
            "allocated_quantity": 0,
            "product": other_product.pk,
        },
    )

    assert response.status_code == 302
    inventory.refresh_from_db()
    assert (inventory.total_quantity, inventory.allocated_quantity) == (10, 2)
    assert inventory.product == original_product
    assert find_discrepancies() == []


@pytest.mark.django_db
def test_the_inventory_list_shows_the_counters(admin_client):
    InventoryFactory(product__sku="LISTED-1", total_quantity=42, allocated_quantity=7)

    page = admin_client.get("/admin/inventory/inventory/").content.decode()

    assert "LISTED-1" in page
    assert ">42<" in page
    assert ">7<" in page


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    ["reservations/reservation", "inventory/stockmovement"],
)
def test_reservations_and_the_ledger_can_be_looked_at_but_not_changed(
    admin_client, path
):
    ReservationFactory()  # also gives the inventory a ledger row via the factory
    pk = (
        StockMovement.objects.first().pk
        if path.endswith("stockmovement")
        else ReservationFactory().pk
    )

    assert admin_client.get(f"/admin/{path}/").status_code == 200
    assert (
        admin_client.get(f"/admin/{path}/{pk}/change/").status_code == 200
    )  # view only
    assert admin_client.get(f"/admin/{path}/add/").status_code == 403
    assert (
        admin_client.post(f"/admin/{path}/{pk}/change/", {"status": "x"}).status_code
        == 403
    )
    assert admin_client.get(f"/admin/{path}/{pk}/delete/").status_code == 403


@pytest.mark.django_db
def test_every_admin_link_on_the_demo_page_works(client, admin_client):
    page = client.get("/demo/").content.decode()
    links = re.findall(r'href="(/admin/[^"]*)"', page)

    assert links, "the demo page should point at the admin"
    for link in links:
        assert admin_client.get(link).status_code == 200, link
