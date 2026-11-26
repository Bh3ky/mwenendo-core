import pytest
from django.db import IntegrityError, transaction

from inventory.tests.factories import InventoryFactory
from reservations.models import Reservation
from reservations.tests.factories import ReservationFactory


@pytest.mark.django_db
def test_new_reservation_defaults_to_pending():
    reservation = ReservationFactory()

    assert reservation.status == Reservation.Status.PENDING


@pytest.mark.django_db
def test_each_reservation_gets_its_own_public_id():
    first = ReservationFactory()
    second = ReservationFactory()

    assert first.public_id != second.public_id


@pytest.mark.django_db
def test_zero_quantity_rejected():
    inventory = InventoryFactory()

    with pytest.raises(IntegrityError) as excinfo:
        with transaction.atomic():
            Reservation.objects.create(inventory=inventory, quantity=0, reference="r")

    assert "reservation_quantity_gt_zero" in str(excinfo.value)


@pytest.mark.django_db
def test_two_reservations_cannot_share_an_idempotency_key():
    inventory = InventoryFactory()
    ReservationFactory(inventory=inventory, idempotency_key="key-1")

    with pytest.raises(IntegrityError) as excinfo:
        with transaction.atomic():
            Reservation.objects.create(
                inventory=inventory,
                quantity=1,
                reference="r",
                idempotency_key="key-1",
            )

    assert "reservation_idempotency_key_unique" in str(excinfo.value)


@pytest.mark.django_db
def test_reservations_without_a_key_do_not_collide():
    ReservationFactory()
    ReservationFactory()

    assert Reservation.objects.filter(idempotency_key="").count() == 2
