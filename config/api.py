from ninja import NinjaAPI

from inventory.api import router as inventory_router
from reservations.api import router as reservations_router

api = NinjaAPI(title="Mwenendo Core API", version="0.1.0")
api.add_router("", inventory_router)
api.add_router("", reservations_router)
