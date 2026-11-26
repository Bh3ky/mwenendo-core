import uuid

import pytest

from core.limits import MAX_QUANTITY
from inventory.models import Inventory
from inventory.tests.factories import InventoryFactory
from reservations.models import Reservation
from reservations.tests.factories import ReservationFactory


def _post(client, sku, body):
    return client.post(
        f"/api/products/{sku}/reservations",
        data=body,
        content_type="application/json",
    )


@pytest.mark.django_db
def test_create_reservation_returns_201_and_allocates_stock(client):
    inventory = InventoryFactory(
        product__sku="DEMO-1", total_quantity=10, allocated_quantity=2
    )

    response = _post(client, "DEMO-1", {"quantity": 3, "reference": "order-1"})

    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == "DEMO-1"
    assert body["quantity"] == 3
    assert body["reference"] == "order-1"
    assert body["status"] == "pending"
    assert uuid.UUID(body["id"])  # a valid UUID
    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 5
    assert Reservation.objects.count() == 1


@pytest.mark.django_db
def test_create_reservation_conflicts_when_stock_is_not_available(client):
    inventory = InventoryFactory(
        product__sku="DEMO-1", total_quantity=10, allocated_quantity=8
    )

    response = _post(client, "DEMO-1", {"quantity": 3, "reference": "order-1"})

    assert response.status_code == 409
    assert "only 2 are unallocated" in response.json()["detail"]
    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 8
    assert Reservation.objects.count() == 0


@pytest.mark.django_db
def test_create_reservation_unknown_sku_returns_404(client):
    response = _post(client, "NOPE", {"quantity": 1, "reference": "order-1"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {"quantity": 0, "reference": "r"},
        {"quantity": -5, "reference": "r"},
        {"quantity": 2.5, "reference": "r"},
        {"quantity": True, "reference": "r"},
        {"quantity": "5", "reference": "r"},
        {"quantity": MAX_QUANTITY + 1, "reference": "r"},
        {"quantity": 1, "reference": ""},
        {"quantity": 1, "reference": "x" * 256},
        {"quantity": 1},
        {"reference": "r"},
    ],
)
def test_create_reservation_rejects_invalid_bodies(client, body):
    inventory = InventoryFactory(product__sku="DEMO-1", total_quantity=10)

    response = _post(client, "DEMO-1", body)

    assert response.status_code == 422
    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 0
    assert Reservation.objects.count() == 0


@pytest.mark.django_db
def test_get_reservation_returns_it(client):
    reservation = ReservationFactory(
        inventory__product__sku="DEMO-1", quantity=4, reference="order-9"
    )

    response = client.get(f"/api/reservations/{reservation.public_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(reservation.public_id)
    assert body["sku"] == "DEMO-1"
    assert body["quantity"] == 4
    assert body["reference"] == "order-9"
    assert body["status"] == "pending"


@pytest.mark.django_db
def test_get_unknown_reservation_returns_404(client):
    response = client.get(f"/api/reservations/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.django_db
def test_get_reservation_with_a_malformed_id_returns_422(client):
    response = client.get("/api/reservations/not-a-uuid")

    assert response.status_code == 422


@pytest.mark.django_db
def test_create_reservation_returns_404_if_the_row_vanishes_mid_request(
    client, monkeypatch
):
    InventoryFactory(product__sku="DEMO-1")

    def row_deleted(inventory, quantity, reference):
        raise Inventory.DoesNotExist

    # Simulate the row being deleted between the lookup and the update,
    # a race the test client cannot trigger on its own.
    monkeypatch.setattr("reservations.api.reserve_stock", row_deleted)

    response = _post(client, "DEMO-1", {"quantity": 1, "reference": "order-1"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def _act(client, public_id, action):
    return client.post(f"/api/reservations/{public_id}/{action}")


@pytest.mark.django_db
def test_confirm_returns_the_confirmed_reservation(client):
    reservation = ReservationFactory(inventory__product__sku="DEMO-1")

    response = _act(client, reservation.public_id, "confirm")

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    assert response.json()["sku"] == "DEMO-1"
    reservation.refresh_from_db()
    assert reservation.status == "confirmed"


@pytest.mark.django_db
def test_cancel_releases_stock_and_returns_the_cancelled_reservation(client):
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=5)
    reservation = ReservationFactory(inventory=inventory, quantity=3)

    response = _act(client, reservation.public_id, "cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 2


@pytest.mark.django_db
def test_cancelling_twice_conflicts_and_releases_stock_only_once(client):
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=5)
    reservation = ReservationFactory(inventory=inventory, quantity=3)

    first = _act(client, reservation.public_id, "cancel")
    second = _act(client, reservation.public_id, "cancel")

    assert first.status_code == 200
    assert second.status_code == 409
    assert "cancelled" in second.json()["detail"]
    inventory.refresh_from_db()
    assert inventory.allocated_quantity == 2


@pytest.mark.django_db
def test_confirming_a_cancelled_reservation_conflicts(client):
    reservation = ReservationFactory(status="cancelled")

    response = _act(client, reservation.public_id, "confirm")

    assert response.status_code == 409


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["confirm", "cancel"])
def test_actions_on_an_unknown_reservation_return_404(client, action):
    response = _act(client, uuid.uuid4(), action)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["confirm", "cancel"])
def test_actions_with_a_malformed_id_return_422(client, action):
    response = client.post(f"/api/reservations/not-a-uuid/{action}")

    assert response.status_code == 422


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["confirm", "cancel"])
def test_actions_return_404_if_the_reservation_vanishes_mid_request(
    client, monkeypatch, action
):
    reservation = ReservationFactory()

    def row_deleted(reservation):
        raise Reservation.DoesNotExist

    monkeypatch.setattr(f"reservations.api.{action}_reservation", row_deleted)

    response = _act(client, reservation.public_id, action)

    assert response.status_code == 404
