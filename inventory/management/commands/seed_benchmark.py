from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory.models import Inventory, Product
from inventory.services import add_stock


class Command(BaseCommand):
    help = (
        "Create products with stock for load testing. Refuses to run unless the "
        "database name contains 'bench', so it can never fill the development "
        "database with benchmark data."
    )

    def add_arguments(self, parser):
        parser.add_argument("--prefix", default="BENCH")
        parser.add_argument("--count", type=int, default=1)
        parser.add_argument("--stock", type=int, default=100_000)

    def handle(self, *args, **options):
        db_name = str(settings.DATABASES["default"]["NAME"])
        if "bench" not in db_name:
            raise CommandError(
                f"Refusing to seed database {db_name!r}: its name must contain "
                "'bench'. Point POSTGRES_DB at a separate benchmark database."
            )

        for index in range(options["count"]):
            sku = f"{options['prefix']}-{index}"
            product, _ = Product.objects.get_or_create(
                sku=sku, defaults={"name": f"Benchmark product {index}"}
            )
            inventory, _ = Inventory.objects.get_or_create(product=product)
            # Through the service, so the ledger gets its row too.
            add_stock(inventory, options["stock"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {options['count']} product(s) in {db_name} "
                f"with {options['stock']} units each."
            )
        )
