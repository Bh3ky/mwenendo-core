import pytest

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
