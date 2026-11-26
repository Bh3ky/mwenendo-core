# Shared limits for API input. A quantity above this is rejected with a 422
# before it can reach PostgreSQL and overflow a 64-bit column (ADR-0006).
MAX_QUANTITY = 1_000_000
