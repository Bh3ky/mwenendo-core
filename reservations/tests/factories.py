import factory

from inventory.tests.factories import InventoryFactory
from reservations.models import Reservation


class ReservationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Reservation

    inventory = factory.SubFactory(InventoryFactory)
    quantity = 1
    reference = factory.Sequence(lambda n: f"order-{n}")
