# ADR-0006: Shape of the stock API

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 3

## Context

The API needs to expose the stock services built in Milestone 2 (`add_stock`, `remove_stock`) and let clients read an inventory. Several design choices follow from that: URL structure, how stock changes are expressed, which status code each failure gets, how strictly input is validated, and how many database queries an endpoint may run.

## Options considered

For how stock changes are expressed:

1. **Explicit action endpoints:** `POST /products/{sku}/inventory/add` and `.../remove`, each with `{"quantity": n}`.
   - Pros: each endpoint maps to one service function, and a positive-only quantity is simple to validate.
   - Cons: verbs in URLs are not strictly RESTful.
2. **One adjustments endpoint** with a signed `delta`.
   - Pros: closer to REST, since an adjustment is created.
   - Cons: the sign has to be mapped to add or remove, and `delta: 0` becomes a new invalid case.
3. **`PATCH` the total directly.**
   - Pros: simplest for a client.
   - Cons: reintroduces the lost-update race that `F()` expressions avoid (ADR-0003, ADR-0004).

## Decision

- **Explicit action endpoints** (option 1). We chose it because it allows us to write each action explicitly.
- **Plural resource URLs** keyed by SKU: `/products/{sku}/inventory`.
- **`available_quantity` is computed on read** (`total - allocated`), not stored, so there is no third counter that can drift.
- **An unknown SKU and a product with no inventory row both return the same 404** (`{"detail": "Not Found"}`).
- **Status codes:** 422 for an invalid body (handled by the schema), 409 when a valid request conflicts with current stock (`InsufficientStock`), 404 for a missing resource, including `Inventory.DoesNotExist` raised by the service.
- **Strict request schema:** `quantity: int = Field(gt=0, strict=True)`. Pydantic's default lax mode converted `"3"` to `3` and `True` to `1`, which would let `{"quantity": true}` add one unit. The service layer's own checks remain as a second layer (ADR-0004), for callers that are not HTTP.
- **Exception mapping with `try/except` in each view**, raising `HttpError(..., ...) from exc` so the original exception stays in the chain for debugging. A central `exception_handler` is deferred until the repetition becomes a problem.
- **`InvalidQuantity` is deliberately not caught.** The strict schema rejects bad input first, so if it ever fired the schema and service would disagree, which is a bug and should surface as a 500.
- **Query count:** the read endpoint uses `select_related("product")` and runs one query, pinned by a test. The add endpoint runs four, and the test pins that number (see Consequences).
- **Tests use pytest-django's `client` fixture**, which goes through the real URL configuration, instead of Ninja's `TestClient`, so a mistyped path or an unmounted router fails the test.

## Consequences

- **Good:**
  - Each endpoint is a thin wrapper around one service call, and the stock logic stays in one place.
  - Clients get a consistent mapping: 422 means fix the request, 409 means re-read the state, 404 means no such resource.
  - Returning the same 404 for both missing cases does not reveal which SKUs exist.
  - Tests check persisted state as well as responses, including that a rejected request leaves stock unchanged.
- **Bad / trade-offs:**
  - Verbs in URLs are not strictly RESTful.
  - The add endpoint runs four queries, not three. `refresh_from_db()` at the end of `add_stock` discards the product that `select_related` loaded, so reading `inventory.product.sku` fetches it again. This is the N+1 pattern in miniature and harmless for one row, but it would matter in a loop. We accepted it and pinned it with a test, to optimise only when measurement says it matters (Milestone 7).
  - The 405 response is plain text rather than JSON (see ADR-0005).
  - The `Inventory.DoesNotExist` branch cannot be reached through the HTTP test client without a race, so the API tests simulate it with `monkeypatch` and the service tests cover the real behaviour.
  - `try/except` is repeated per endpoint.
- **Revisit when:**
  - More endpoints share the same mapping, which suggests a central `exception_handler`.
  - Load testing shows the extra query matters.
  - A maximum quantity is decided (the 64-bit column can currently overflow).

## References

- [RFC 9110, section 15.5.10: 409 Conflict](https://www.rfc-editor.org/rfc/rfc9110#name-409-conflict)
- [RFC 9110, section 15.5.21: 422 Unprocessable Content](https://www.rfc-editor.org/rfc/rfc9110#name-422-unprocessable-content)
- [Django Ninja: handling errors](https://django-ninja.dev/guides/errors/)
- [Pydantic: strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/)
- [Django: `select_related`](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-related)
- ADR-0003: Represent stock as counters on an Inventory row
- ADR-0004: Enforce `allocated_quantity <= total_quantity` in the database and in code
