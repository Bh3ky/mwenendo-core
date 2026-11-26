from django.db import migrations


def create_opening_balances(apps, schema_editor):
    """Give every existing inventory a ledger row for the stock it already has.

    Before the ledger existed, counters were changed with no record. This
    opening balance makes the ledger add up to the counters from day one.
    """
    Inventory = apps.get_model("inventory", "Inventory")
    StockMovement = apps.get_model("inventory", "StockMovement")

    for inventory in Inventory.objects.exclude(total_quantity=0, allocated_quantity=0):
        StockMovement.objects.create(
            inventory=inventory,
            reason="opening_balance",
            total_delta=inventory.total_quantity,
            allocated_delta=inventory.allocated_quantity,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0004_stockmovement"),
    ]

    operations = [
        # Reversing leaves the rows in place: the ledger is append-only.
        migrations.RunPython(create_opening_balances, migrations.RunPython.noop),
    ]
