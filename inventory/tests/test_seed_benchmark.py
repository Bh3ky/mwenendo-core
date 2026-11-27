from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from inventory.models import Inventory
from inventory.reconciliation import find_discrepancies


@pytest.mark.django_db
def test_seed_benchmark_refuses_a_database_without_bench_in_its_name():
    # The test database is called test_<name>, which has no "bench" in it.
    with pytest.raises(CommandError, match="must contain 'bench'"):
        call_command("seed_benchmark")

    assert Inventory.objects.count() == 0


@pytest.mark.django_db
def test_seed_benchmark_creates_stocked_inventories_that_reconcile(monkeypatch):
    # Patch only the command's view of the settings. Overriding the real
    # DATABASES setting would change the live test connection.
    fake_settings = SimpleNamespace(DATABASES={"default": {"NAME": "mwenendo_bench"}})
    monkeypatch.setattr(
        "inventory.management.commands.seed_benchmark.settings", fake_settings
    )

    call_command("seed_benchmark", count=3, stock=100, stdout=StringIO())

    assert Inventory.objects.count() == 3
    assert set(Inventory.objects.values_list("total_quantity", flat=True)) == {100}
    assert find_discrepancies() == []


@pytest.mark.django_db
def test_seeding_the_same_prefix_twice_is_refused(monkeypatch):
    fake_settings = SimpleNamespace(DATABASES={"default": {"NAME": "mwenendo_bench"}})
    monkeypatch.setattr(
        "inventory.management.commands.seed_benchmark.settings", fake_settings
    )
    call_command("seed_benchmark", prefix="RUN1", count=1, stock=500, stdout=StringIO())

    with pytest.raises(CommandError, match="Use a new prefix"):
        call_command(
            "seed_benchmark", prefix="RUN1", count=1, stock=500, stdout=StringIO()
        )

    assert Inventory.objects.get(product__sku="RUN1-0").total_quantity == 500


@pytest.mark.django_db
def test_top_up_adds_stock_to_existing_products(monkeypatch):
    fake_settings = SimpleNamespace(DATABASES={"default": {"NAME": "mwenendo_bench"}})
    monkeypatch.setattr(
        "inventory.management.commands.seed_benchmark.settings", fake_settings
    )
    call_command("seed_benchmark", prefix="RUN2", count=1, stock=500, stdout=StringIO())

    call_command(
        "seed_benchmark",
        prefix="RUN2",
        count=1,
        stock=500,
        top_up=True,
        stdout=StringIO(),
    )

    assert Inventory.objects.get(product__sku="RUN2-0").total_quantity == 1000
