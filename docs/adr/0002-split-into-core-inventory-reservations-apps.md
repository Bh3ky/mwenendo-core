# ADR-0002: Split the project into `core`, `inventory` and `reservations` apps

- **Status:** Accepted
- **Date:** 2026-11-18
- **Roadmap milestone:** Milestone 1

## Context

The project started with a single Django app, `core`, holding the landing page and the health check. The next milestones add inventory models and constraints (Milestone 2), the reservation API (Milestone 3) and the allocation logic that protects the invariant `allocated_quantity <= total_quantity` (Milestone 4).

If all of that is added to `core`, it becomes a grab-bag: inventory rules, reservation lifecycle and infrastructure endpoints mixed in one package, with no clear place for tests and no boundary to reason about.

A Django app is a Python package with its own models, migrations, views and tests. Moving a model between apps later is possible but needs careful migrations, so the boundaries are cheaper to set before any models exist.

## Options considered

1. **Three apps: `core`, `inventory`, `reservations`**
   - Pros: each app has one job and its own tests and migrations. The boundaries match the roadmap. A one-way dependency can be enforced and explained.
   - Cons: more structure up front, and cross-app calls need to be designed deliberately.

2. **Two apps: `core` and a single `allocation` app holding both domains**
   - Pros: simpler, with no cross-app imports.
   - Cons: mixes concepts with different lifecycles and invariants (what stock exists vs. who has claimed it), so it would grow into a second grab-bag.

3. **One app: keep everything in `core`**
   - Pros: no work now.
   - Cons: the grab-bag problem described above.

## Decision

Use three apps, with these responsibilities:

- **`core`:** infrastructure shared by the project. For now, the landing page and the health-check endpoint. It does not import from `inventory` or `reservations`.
- **`inventory`:** what stock exists. Products, stock quantities and the rules and constraints that keep those quantities valid.
- **`reservations`:** who has claimed stock. The reservation model, its lifecycle (the state machine of Milestone 5) and the operations that create, confirm, cancel and expire reservations.

Dependencies run one way: **`reservations` may import from `inventory`; `inventory` must not import from `reservations`.** `core` stays at the bottom and imports from neither.

Tests live in a `tests/` package inside each app.

## Consequences

- **Good:**
  - Each app can be described in a sentence and tested on its own.
  - A one-way dependency avoids circular imports: if `inventory` and `reservations` imported each other at module level, Python could fail at import time with a partially initialised module, and the apps could not be understood separately.
  - The structure matches how the work will be explained in interviews: stock is a property of inventory, and a reservation is a claim against it.
- **Bad / trade-offs:**
  - Allocation touches both domains in one transaction: a reservation must lock and update an inventory row atomically. The one-way rule means that operation must be orchestrated from `reservations`, calling into `inventory`, and the interface between the two needs deliberate design.
  - Cross-app foreign keys (a reservation points to a product) tie the apps' migrations together, so migration order matters.
  - A model placed in the wrong app is costly to move once data exists.
- **Revisit when:**
  - Allocation logic does not fit cleanly on one side of the dependency. It may then need its own module or app, for example a service layer.
  - Either app grows large enough to have distinct sub-domains.

## Open questions

- Where the locking logic (`select_for_update`) lives: in `inventory` as a function that reservations calls, or in `reservations` directly. To be decided in Milestone 4, with its own ADR.

## References

- [Django: Applications](https://docs.djangoproject.com/en/5.2/ref/applications/)
- [Django: `startapp`](https://docs.djangoproject.com/en/5.2/ref/django-admin/#startapp)
- [Django tutorial: Reusable apps](https://docs.djangoproject.com/en/5.2/intro/reusable-apps/)
