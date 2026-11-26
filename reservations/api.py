import uuid
from datetime import datetime

from django.shortcuts import get_object_or_404
from ninja import Router, Schema, Status
from ninja.errors import HttpError
from pydantic import Field

from core.limits import MAX_QUANTITY
from inventory.models import Inventory
from inventory.services import InsufficientStock
from reservations.models import Reservation
from reservations.services import reserve_stock

router = Router(tags=["reservations"])


class ReservationIn(Schema):
    quantity: int = Field(gt=0, le=MAX_QUANTITY, strict=True)
    reference: str = Field(min_length=1, max_length=255)


class ReservationOut(Schema):
    id: uuid.UUID
    sku: str
    quantity: int
    status: str
    reference: str
    created_at: datetime


def _to_out(reservation: Reservation, sku: str) -> ReservationOut:
    return ReservationOut(
        id=reservation.public_id,
        sku=sku,
        quantity=reservation.quantity,
        status=reservation.status,
        reference=reservation.reference,
        created_at=reservation.created_at,
    )


@router.post("/products/{sku}/reservations", response={201: ReservationOut})
def create_reservation(request, sku: str, payload: ReservationIn):
    inventory = get_object_or_404(Inventory, product__sku=sku)

    try:
        reservation = reserve_stock(inventory, payload.quantity, payload.reference)
    except InsufficientStock as exc:
        raise HttpError(409, str(exc)) from exc
    except Inventory.DoesNotExist as exc:
        raise HttpError(404, "Not Found") from exc

    # The SKU comes from the URL, so we do not need another query for it.
    return Status(201, _to_out(reservation, sku))


@router.get("/reservations/{public_id}", response=ReservationOut)
def get_reservation(request, public_id: uuid.UUID):
    reservation = get_object_or_404(
        Reservation.objects.select_related("inventory__product"),
        public_id=public_id,
    )
    return _to_out(reservation, reservation.inventory.product.sku)
