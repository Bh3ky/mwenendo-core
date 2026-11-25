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
