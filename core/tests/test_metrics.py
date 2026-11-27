import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from prometheus_client import REGISTRY

from inventory.services import InsufficientStock, allocate_stock
from inventory.tests.factories import InventoryFactory
from reservations.models import Reservation
from reservations.tests.factories import ReservationFactory

INVENTORY_ROUTE = "api/products/<sku>/inventory"


def _count(method, route, status):
    value = REGISTRY.get_sample_value(
        "http_requests_total", {"method": method, "route": route, "status": status}
    )
    return value or 0


def _gauge(name, labels):
    return REGISTRY.get_sample_value(name, labels)


@pytest.mark.django_db
def test_a_request_is_counted_under_its_route_pattern(client):
    before = _count("GET", INVENTORY_ROUTE, "404")

    client.get("/api/products/NOPE/inventory")

    assert _count("GET", INVENTORY_ROUTE, "404") == before + 1


@pytest.mark.django_db
def test_different_skus_share_one_series(client):
    before = _count("GET", INVENTORY_ROUTE, "404")

    client.get("/api/products/ONE/inventory")
    client.get("/api/products/TWO/inventory")
    client.get("/api/products/THREE/inventory")

    # One series, counted three times. Real paths would have made three.
    assert _count("GET", INVENTORY_ROUTE, "404") == before + 3
    assert _count("GET", "api/products/ONE/inventory", "404") == 0


@pytest.mark.django_db
def test_a_url_that_matches_nothing_is_labelled_unmatched(client):
    before = _count("GET", "unmatched", "404")

    client.get("/some/path/that/does/not/exist")

    assert _count("GET", "unmatched", "404") == before + 1


@pytest.mark.django_db
def test_an_invented_http_method_is_counted_as_other(client):
    before = _count("OTHER", "health/", "200")

    client.generic("BREW", "/health/")

    assert _count("OTHER", "health/", "200") == before + 1


@pytest.mark.django_db
def test_request_durations_are_recorded(client):
    labels = {"method": "GET", "route": "health/"}
    before = (
        REGISTRY.get_sample_value("http_request_duration_seconds_count", labels) or 0
    )

    client.get("/health/")

    after = REGISTRY.get_sample_value("http_request_duration_seconds_count", labels)
    assert after == before + 1


@pytest.mark.django_db
def test_a_scrape_does_not_count_itself(client):
    client.get("/metrics")
    before = _count("GET", "metrics", "200")

    client.get("/metrics")

    assert _count("GET", "metrics", "200") == before == 0


@pytest.mark.django_db
def test_the_metrics_endpoint_serves_the_text_format(client):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    body = response.content.decode()
    assert "# TYPE http_requests_total counter" in body
    assert "# TYPE http_request_duration_seconds histogram" in body
    assert "# TYPE stock_allocation_refused_total counter" in body


@pytest.mark.django_db
def test_refused_allocations_are_counted():
    before = REGISTRY.get_sample_value("stock_allocation_refused_total") or 0
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=9)

    with pytest.raises(InsufficientStock):
        allocate_stock(inventory, 5)

    assert REGISTRY.get_sample_value("stock_allocation_refused_total") == before + 1


@pytest.mark.django_db
def test_reservations_are_counted_by_status_with_zeros_included(client):
    ReservationFactory.create_batch(2)
    ReservationFactory(status=Reservation.Status.CANCELLED)

    body = client.get("/metrics").content.decode()

    assert 'reservations_by_status{status="pending"} 2.0' in body
    assert 'reservations_by_status{status="cancelled"} 1.0' in body
    assert 'reservations_by_status{status="expired"} 0.0' in body


@pytest.mark.django_db
def test_stock_totals_are_summed_across_inventories(client):
    InventoryFactory(total_quantity=10, allocated_quantity=4)
    InventoryFactory(total_quantity=5, allocated_quantity=1)

    body = client.get("/metrics").content.decode()

    assert 'stock_units{kind="total"} 15.0' in body
    assert 'stock_units{kind="allocated"} 5.0' in body


@pytest.mark.django_db
def test_request_metrics_are_still_served_when_the_database_is_down(
    client, monkeypatch
):
    class DatabaseDown:
        class objects:  # noqa: N801
            @staticmethod
            def values_list(*args, **kwargs):
                raise RuntimeError("database is down")

    monkeypatch.setattr("config.metrics.Reservation", DatabaseDown)

    response = client.get("/metrics")

    body = response.content.decode()
    assert response.status_code == 200
    assert "http_requests_total" in body
    assert "reservations_by_status" not in body


@pytest.mark.django_db
def test_metrics_are_open_when_no_token_is_set(client, settings):
    settings.METRICS_TOKEN = ""

    assert client.get("/metrics").status_code == 200


@pytest.mark.django_db
def test_a_configured_token_is_required(client, settings):
    settings.METRICS_TOKEN = "s3cret"

    missing = client.get("/metrics")
    wrong = client.get("/metrics", headers={"Authorization": "Bearer nope"})
    right = client.get("/metrics", headers={"Authorization": "Bearer s3cret"})

    assert missing.status_code == 401
    assert missing["WWW-Authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert right.status_code == 200


@pytest.mark.django_db
def test_the_multiprocess_path_serves_metrics(client, monkeypatch, tmp_path):
    # An empty directory is what gunicorn starts with. This checks the code path
    # runs. Adding up real workers can only be shown by running the containers.
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    ReservationFactory()

    response = client.get("/metrics")

    assert response.status_code == 200
    assert 'reservations_by_status{status="pending"} 1.0' in response.content.decode()


@pytest.fixture
def gunicorn_conf():
    path = Path(__file__).resolve().parents[2] / "gunicorn.conf.py"
    spec = importlib.util.spec_from_file_location("gunicorn_conf_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gunicorn_empties_the_metrics_directory_on_start(
    gunicorn_conf, monkeypatch, tmp_path
):
    directory = tmp_path / "multiproc"
    directory.mkdir()
    (directory / "counter_999.db").write_text("left over from an earlier run")
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(directory))

    gunicorn_conf.on_starting(server=None)

    assert directory.is_dir()
    assert list(directory.iterdir()) == []


def test_gunicorn_creates_the_metrics_directory_if_it_is_missing(
    gunicorn_conf, monkeypatch, tmp_path
):
    directory = tmp_path / "does-not-exist-yet"
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(directory))

    gunicorn_conf.on_starting(server=None)

    assert directory.is_dir()


def test_gunicorn_marks_an_exited_worker_dead(gunicorn_conf, monkeypatch, tmp_path):
    dead = []
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setattr(gunicorn_conf.multiprocess, "mark_process_dead", dead.append)

    gunicorn_conf.child_exit(server=None, worker=SimpleNamespace(pid=4321))

    assert dead == [4321]


def test_gunicorn_does_nothing_about_metrics_when_the_directory_is_not_set(
    gunicorn_conf, monkeypatch
):
    dead = []
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    monkeypatch.setattr(gunicorn_conf.multiprocess, "mark_process_dead", dead.append)

    gunicorn_conf.on_starting(server=None)
    gunicorn_conf.child_exit(server=None, worker=SimpleNamespace(pid=1))

    assert dead == []


def test_gunicorn_uses_shared_memory_for_its_heartbeat_only_where_it_exists(
    monkeypatch,
):
    path = Path(__file__).resolve().parents[2] / "gunicorn.conf.py"

    def load(shm_exists):
        monkeypatch.setattr("os.path.isdir", lambda p: shm_exists and p == "/dev/shm")
        spec = importlib.util.spec_from_file_location("gunicorn_conf_shm", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    assert load(shm_exists=True).worker_tmp_dir == "/dev/shm"
    assert load(shm_exists=False).worker_tmp_dir is None  # macOS


@pytest.mark.django_db
def test_registering_the_database_collector_runs_no_queries(
    django_assert_num_queries,
):
    from prometheus_client import CollectorRegistry

    from config.metrics import DatabaseCollector

    # collect() is what queries. Registering must not call it, or every process
    # would hit the database at import time (and during `migrate`).
    with django_assert_num_queries(0):
        # The default REGISTRY, the one we use, is made with auto_describe=True.
        CollectorRegistry(auto_describe=True).register(DatabaseCollector())
