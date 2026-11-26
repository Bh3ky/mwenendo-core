from django.core.management.base import BaseCommand, CommandError

from inventory.reconciliation import find_discrepancies


class Command(BaseCommand):
    help = (
        "Check that every inventory's counters equal the sum of its ledger rows. "
        "Exits with an error if any inventory disagrees."
    )

    def handle(self, *args, **options):
        discrepancies = find_discrepancies()

        if not discrepancies:
            self.stdout.write(self.style.SUCCESS("All inventories reconcile."))
            return

        for d in discrepancies:
            self.stdout.write(
                f"{d.sku}: total {d.total_quantity} (ledger {d.ledger_total}), "
                f"allocated {d.allocated_quantity} (ledger {d.ledger_allocated})"
            )

        raise CommandError(f"{len(discrepancies)} inventories do not reconcile.")
