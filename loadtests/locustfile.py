"""Load scenarios for the reservation API.

Run against a separate benchmark database, never the development one.
See loadtests/README.md for the full procedure.
"""

import os
import random
import uuid

from locust import HttpUser, between, task

# How many products the users spread over. 1 means every user fights for the
# same inventory row (the hot-row case). A larger number spreads the load.
SKU_COUNT = int(os.environ.get("SKU_COUNT", "1"))
SKU_PREFIX = os.environ.get("SKU_PREFIX", "BENCH")


class Shopper(HttpUser):
    wait_time = between(0.05, 0.2)

    def on_start(self):
        self.reservation_ids: list[str] = []

    def _sku(self) -> str:
        return f"{SKU_PREFIX}-{random.randrange(SKU_COUNT)}"

    @task(5)
    def read_inventory(self):
        self.client.get(
            f"/api/products/{self._sku()}/inventory",
            name="GET /products/[sku]/inventory",
        )

    @task(3)
    def reserve(self):
        with self.client.post(
            f"/api/products/{self._sku()}/reservations",
            json={"quantity": 1, "reference": f"user-{uuid.uuid4().hex[:8]}"},
            headers={"Idempotency-Key": uuid.uuid4().hex},
            name="POST /products/[sku]/reservations",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                self.reservation_ids.append(response.json()["id"])
                response.success()
            elif response.status_code == 409:
                # "Not enough stock" is a correct answer once stock runs out.
                response.success()
            else:
                response.failure(f"unexpected status {response.status_code}")

    @task(1)
    def cancel(self):
        if not self.reservation_ids:
            return
        reservation_id = self.reservation_ids.pop()
        self.client.post(
            f"/api/reservations/{reservation_id}/cancel",
            name="POST /reservations/[id]/cancel",
        )
