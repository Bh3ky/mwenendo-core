import pytest

from core.limits import MAX_QUANTITY
from inventory.models import Inventory
from inventory.tests.factories import InventoryFactory, ProductFactory


@pytest.mark.django_db
def test_get_inventory_returns_stock_levels(client):
    InventoryFactory(product__sku="DEMO-1", total_quantity=100, allocated_quantity=10)

    response = client.get("/api/products/DEMO-1/inventory")

    assert response.status_code == 200
    assert response.json() == {
        "sku": "DEMO-1",
        "total_quantity": 100,
        "allocated_quantity": 10,
        "available_quantity": 90,
    }


@pytest.mark.django_db
def test_unknown_sku_returns_404(client):
    response = client.get("/api/products/NOPE/inventory")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Not Found",
    }
    assert "application/json" in response["Content-Type"]


@pytest.mark.django_db
def test_product_exists_with_no_inventory_row(client):
    ProductFactory(sku="NO-STOCK")

    response = client.get("/api/products/NO-STOCK/inventory")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert "application/json" in response["Content-Type"]


def test_inventory_endpoint_rejects_post(client):
    response = client.post("/api/products/DEMO-1/inventory")

    assert response.status_code == 405
    assert response["Allow"] == "GET"


@pytest.mark.django_db
def test_get_inventory_uses_one_query(client, django_assert_num_queries):
    InventoryFactory(product__sku="DEMO-1")

    with django_assert_num_queries(1):
        client.get("/api/products/DEMO-1/inventory")


@pytest.mark.django_db
def test_add_inventory_increases_total(client):
    inventory = InventoryFactory(
        product__sku="DEMO-1", total_quantity=10, allocated_quantity=2
    )

    response = client.post(
        "/api/products/DEMO-1/inventory/add",
        data={"quantity": 5},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {
        "sku": "DEMO-1",
        "total_quantity": 15,
        "allocated_quantity": 2,
        "available_quantity": 13,
    }
    inventory.refresh_from_db()
    assert inventory.total_quantity == 15


@pytest.mark.django_db
@pytest.mark.parametrize("bad_quantity", [0, -5, 2.5, True, "5"])
def test_add_inventory_rejects_invalid_quantities(client, bad_quantity):
    inventory = InventoryFactory(product__sku="DEMO-1", total_quantity=10)

    response = client.post(
        "/api/products/DEMO-1/inventory/add",
        data={"quantity": bad_quantity},
        content_type="application/json",
    )

    assert response.status_code == 422

    inventory.refresh_from_db()
    assert inventory.total_quantity == 10


@pytest.mark.django_db
def test_add_inventory_rejects_unknown_sku(client):
    response = client.post(
        "/api/products/NOPE/inventory/add",
        data={"quantity": 5},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert "application/json" in response["Content-Type"]


# test: check that the endpoint isn't making hidden extra
# database calls
@pytest.mark.django_db
def test_add_inventory_query_count(client, django_assert_num_queries):
    InventoryFactory(product__sku="DEMO-1")

    with django_assert_num_queries(4):
        client.post(
            "/api/products/DEMO-1/inventory/add",
            data={"quantity": 5},
            content_type="application/json",
        )


@pytest.mark.django_db
def test_remove_inventory_conflicts_when_stock_is_allocated(client):
    inventory = InventoryFactory(
        product__sku="DEMO-1", total_quantity=10, allocated_quantity=3
    )

    response = client.post(
        "/api/products/DEMO-1/inventory/remove",
        data={"quantity": 8},
        content_type="application/json",
    )

    assert response.status_code == 409
    assert "only 7 are unallocated" in response.json()["detail"]
    inventory.refresh_from_db()
    assert inventory.total_quantity == 10


@pytest.mark.django_db
def test_remove_inventory_decreases_total(client):
    inventory = InventoryFactory(
        product__sku="DEMO-1", total_quantity=10, allocated_quantity=3
    )

    response = client.post(
        "/api/products/DEMO-1/inventory/remove",
        data={"quantity": 4},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {
        "sku": "DEMO-1",
        "total_quantity": 6,
        "allocated_quantity": 3,
        "available_quantity": 3,
    }
    inventory.refresh_from_db()
    assert inventory.total_quantity == 6


@pytest.mark.django_db
def test_remove_inventory_allows_removing_exactly_the_unallocated_amount(client):
    inventory = InventoryFactory(
        product__sku="DEMO-1", total_quantity=10, allocated_quantity=3
    )

    response = client.post(
        "/api/products/DEMO-1/inventory/remove",
        data={"quantity": 7},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["available_quantity"] == 0
    inventory.refresh_from_db()
    assert inventory.total_quantity == 3


@pytest.mark.django_db
@pytest.mark.parametrize("bad_quantity", [0, -5, 2.5, True, "5"])
def test_remove_inventory_rejects_invalid_quantities(client, bad_quantity):
    inventory = InventoryFactory(
        product__sku="DEMO-1", total_quantity=10, allocated_quantity=3
    )

    response = client.post(
        "/api/products/DEMO-1/inventory/remove",
        data={"quantity": bad_quantity},
        content_type="application/json",
    )

    assert response.status_code == 422
    inventory.refresh_from_db()
    assert inventory.total_quantity == 10


@pytest.mark.django_db
def test_remove_inventory_unknown_sku_returns_404(client):
    response = client.post(
        "/api/products/NOPE/inventory/remove",
        data={"quantity": 5},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert "application/json" in response["Content-Type"]


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["add", "remove"])
def test_stock_endpoints_return_404_if_row_vanishes_mid_request(
    client, monkeypatch, action
):
    InventoryFactory(product__sku="DEMO-1")

    def row_deleted(inventory, quantity):
        raise Inventory.DoesNotExist

    # Simulate the row being deleted between the lookup and the update,
    # a race the test client cannot trigger on its own.
    monkeypatch.setattr(f"inventory.api.{action}_stock", row_deleted)

    response = client.post(
        f"/api/products/DEMO-1/inventory/{action}",
        data={"quantity": 5},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["add", "remove"])
def test_stock_endpoints_reject_malformed_json(client, action):
    inventory = InventoryFactory(product__sku="DEMO-1", total_quantity=10)

    response = client.post(
        f"/api/products/DEMO-1/inventory/{action}",
        data="{not valid json",
        content_type="application/json",
    )

    assert response.status_code == 400
    inventory.refresh_from_db()
    assert inventory.total_quantity == 10


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["add", "remove"])
def test_stock_endpoints_reject_missing_body(client, action):
    inventory = InventoryFactory(product__sku="DEMO-1", total_quantity=10)

    response = client.post(
        f"/api/products/DEMO-1/inventory/{action}",
        content_type="application/json",
    )

    assert response.status_code == 422
    inventory.refresh_from_db()
    assert inventory.total_quantity == 10


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("action", "expected_total"),
    [("add", 2 * MAX_QUANTITY), ("remove", 0)],
)
def test_stock_endpoints_accept_the_maximum_quantity(client, action, expected_total):
    inventory = InventoryFactory(product__sku="DEMO-1", total_quantity=MAX_QUANTITY)

    response = client.post(
        f"/api/products/DEMO-1/inventory/{action}",
        data={"quantity": MAX_QUANTITY},
        content_type="application/json",
    )

    assert response.status_code == 200
    inventory.refresh_from_db()
    assert inventory.total_quantity == expected_total


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["add", "remove"])
def test_stock_endpoints_reject_quantity_above_the_maximum(client, action):
    inventory = InventoryFactory(product__sku="DEMO-1", total_quantity=10)

    response = client.post(
        f"/api/products/DEMO-1/inventory/{action}",
        data={"quantity": MAX_QUANTITY + 1},
        content_type="application/json",
    )

    assert response.status_code == 422
    inventory.refresh_from_db()
    assert inventory.total_quantity == 10
