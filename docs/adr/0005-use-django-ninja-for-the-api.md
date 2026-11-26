# ADR-0005: Use Django Ninja for the HTTP API

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 3

## Context

The project needs an HTTP API on top of the inventory services: read stock, add stock, remove stock, and later create and manage reservations. We need request validation, clear error responses and API documentation, on a Django 5.2 codebase.

## Options considered

1. **Django REST Framework (DRF):** the long-established standard.
   - Pros: very large ecosystem, many ready-made features (authentication classes, throttling, pagination, browsable API) and a large community.
   - Cons: serializer and viewset layers add concepts and boilerplate, and type hints play no part in validation.
2. **Django Ninja:** a framework built on Python type hints and Pydantic.
   - Pros: an endpoint is a plain function with typed parameters, request and response schemas are Pydantic classes, and OpenAPI documentation is generated automatically.
   - Cons: smaller and newer than DRF, with a smaller community and fewer ready-made features.
3. **Plain Django views:** parse JSON and validate by hand.
   - Pros: no dependency.
   - Cons: every endpoint repeats parsing, validation and error formatting, and the project would end up writing its own small framework.

## Decision

Use **Django Ninja** (option 2). It uses the type-hint approach built around Python functions and Pydantic schemas, and it includes automatic OpenAPI docs.

## Consequences

- **Good:**
  - Endpoints read as typed functions, and a bad request body is rejected with a 422 before our code runs.
  - Documentation is generated at `/api/docs`.
  - Pydantic's strict mode lets us reject loosely typed input (`"5"`, `true`) at the boundary.
- **Bad / trade-offs:**
  - Ninja's own responses are not uniform. Its 404 body is JSON, but its 405 is Django's plain-text `HttpResponseNotAllowed` with an HTML content type (`ninja/operation.py`), so clients that expect JSON everywhere would need a custom handler.
  - The 404 body includes the exception text while `DEBUG=True` (`ninja/errors.py`), which is useful in development and must stay off in production.
  - The ecosystem is smaller than DRF's, so some features would be built by hand.
- **Revisit when:**
  - The API needs features Ninja lacks and DRF provides, or a consistent JSON error format for every status code becomes a requirement.

## References

- [Django Ninja documentation](https://django-ninja.dev/)
- [Pydantic: strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/)
- [RFC 9110, section 15.5.6: 405 Method Not Allowed](https://www.rfc-editor.org/rfc/rfc9110#name-405-method-not-allowed)
