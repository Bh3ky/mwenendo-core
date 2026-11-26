import factory

from inventory.models import Inventory, Product, StockMovement


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    sku = factory.Sequence(lambda n: f"SKU-{n}")
    name = factory.Sequence(lambda n: f"Product {n}")


class InventoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Inventory
        # The opening_balance hook below does its own writing.
        skip_postgeneration_save = True

    product = factory.SubFactory(ProductFactory)
    total_quantity = 10
    allocated_quantity = 0

    @factory.post_generation
    def opening_balance(self, create, extracted, **kwargs):
        """Record the starting counters in the ledger, so the inventory reconciles.

        Pass opening_balance=False to build an inventory with no ledger rows.
        """
        if not create or extracted is False:
            return
        if self.total_quantity == 0 and self.allocated_quantity == 0:
            return
        StockMovement.objects.create(
            inventory=self,
            reason=StockMovement.Reason.OPENING_BALANCE,
            total_delta=self.total_quantity,
            allocated_delta=self.allocated_quantity,
        )
