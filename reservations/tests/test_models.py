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
