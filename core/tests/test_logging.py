import json
import logging
from io import StringIO

import pytest

from core.logs import JsonFormatter, request_id_var
from inventory.services import InsufficientStock, allocate_stock
from inventory.tests.factories import InventoryFactory
from reservations.services import (
    cancel_reservation,
    confirm_reservation,
    expire_reservation,
    reserve_stock,
)
from reservations.tests.factories import ReservationFactory


def _record(message="hello", **extra):
    record = logging.LogRecord("test.logger", logging.INFO, "", 0, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_the_formatter_writes_one_json_object_with_the_standard_fields():
    line = JsonFormatter().format(_record("hello"))

    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert "timestamp" in payload
    assert "\n" not in line


def test_extra_fields_become_top_level_keys():
    payload = json.loads(JsonFormatter().format(_record(quantity=3, sku="DEMO-1")))

    assert payload["quantity"] == 3
    assert payload["sku"] == "DEMO-1"


def test_the_formatter_includes_the_current_request_id():
    token = request_id_var.set("abc123")
    try:
        payload = json.loads(JsonFormatter().format(_record()))
    finally:
        request_id_var.reset(token)

    assert payload["request_id"] == "abc123"


def test_the_formatter_omits_the_request_id_outside_a_request():
    payload = json.loads(JsonFormatter().format(_record()))

    assert "request_id" not in payload


def test_values_that_are_not_json_do_not_break_logging():
    payload = json.loads(JsonFormatter().format(_record(thing=object())))

    assert isinstance(payload["thing"], str)


def test_the_formatter_includes_an_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record()
        record.exc_info = sys.exc_info()

    payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in payload["exception"]


@pytest.fixture
def request_log():
    """Collect what the request logger writes, formatted as real output would be."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("mwenendo.request")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield lambda: [json.loads(line) for line in stream.getvalue().splitlines()]
    logger.removeHandler(handler)


@pytest.mark.django_db
def test_each_request_logs_one_line_with_its_details(client, request_log):
    response = client.get("/health/")

    (line,) = request_log()
    assert line["message"] == "request"
    assert line["method"] == "GET"
    assert line["path"] == "/health/"
    assert line["status"] == 200
    assert isinstance(line["duration_ms"], float)
    assert line["request_id"] == response["X-Request-ID"]


@pytest.mark.django_db
def test_the_status_of_an_error_response_is_logged(client, request_log):
    client.get("/api/products/NOPE/inventory")

    (line,) = request_log()
    assert line["status"] == 404


@pytest.mark.django_db
def test_a_valid_request_id_from_the_client_is_kept(client, request_log):
    response = client.get("/health/", headers={"X-Request-ID": "trace-42.a_b"})

    assert response["X-Request-ID"] == "trace-42.a_b"
    assert request_log()[0]["request_id"] == "trace-42.a_b"


@pytest.mark.django_db
@pytest.mark.parametrize("bad_id", ["has space", "x" * 65, "bad;id", "a/b"])
def test_an_unsafe_request_id_is_replaced(client, request_log, bad_id):
    response = client.get("/health/", headers={"X-Request-ID": bad_id})

    assert response["X-Request-ID"] != bad_id
    assert len(response["X-Request-ID"]) == 32  # a generated id


@pytest.mark.django_db
def test_the_request_id_is_cleared_after_the_request(client):
    client.get("/health/")

    assert request_id_var.get() is None


def _events(caplog):
    return {r.getMessage(): r for r in caplog.records if r.name != "mwenendo.request"}


@pytest.mark.django_db
def test_reserving_logs_a_created_event_after_commit(
    caplog, django_capture_on_commit_callbacks
):
    caplog.set_level(logging.INFO)
    inventory = InventoryFactory(total_quantity=10)

    with django_capture_on_commit_callbacks(execute=True):
        reservation = reserve_stock(inventory, 3, "order-1")
        assert "reservation.created" not in _events(caplog)  # not before the commit

    event = _events(caplog)["reservation.created"]
    assert event.reservation_id == str(reservation.public_id)
    assert event.inventory_id == inventory.pk
    assert event.quantity == 3


@pytest.mark.django_db
def test_confirming_logs_an_event(caplog, django_capture_on_commit_callbacks):
    caplog.set_level(logging.INFO)
    reservation = ReservationFactory()

    with django_capture_on_commit_callbacks(execute=True):
        confirm_reservation(reservation)

    assert "reservation.confirmed" in _events(caplog)


@pytest.mark.django_db
def test_cancelling_logs_an_event(caplog, django_capture_on_commit_callbacks):
    caplog.set_level(logging.INFO)
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=1)
    reservation = ReservationFactory(inventory=inventory, quantity=1)

    with django_capture_on_commit_callbacks(execute=True):
        cancel_reservation(reservation)

    assert "reservation.cancelled" in _events(caplog)


@pytest.mark.django_db
def test_expiring_logs_an_event(caplog, django_capture_on_commit_callbacks):
    from datetime import timedelta

    from django.utils import timezone

    caplog.set_level(logging.INFO)
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=1)
    reservation = ReservationFactory(
        inventory=inventory,
        quantity=1,
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    with django_capture_on_commit_callbacks(execute=True):
        assert expire_reservation(reservation) is True

    assert "reservation.expired" in _events(caplog)


@pytest.mark.django_db
def test_a_refused_allocation_logs_a_warning_with_the_numbers(caplog):
    caplog.set_level(logging.INFO)
    inventory = InventoryFactory(total_quantity=10, allocated_quantity=8)

    with pytest.raises(InsufficientStock):
        allocate_stock(inventory, 5)

    event = _events(caplog)["stock.allocation_refused"]
    assert event.levelno == logging.WARNING
    assert (event.requested, event.available) == (5, 2)
