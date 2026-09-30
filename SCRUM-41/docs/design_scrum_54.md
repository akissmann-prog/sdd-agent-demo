# Design: As a developer, I want to delete products

## Overview
Implement a delete_product(id) function that performs a hard delete of a product row from a SQLite-backed catalog. Use a repository pattern with parameterized SQL, transactional execution, and clear error mapping. On success, return the number of deleted rows (1). If the id does not exist, raise a ProductNotFoundError.

## Components
- db.py
  - get_connection() -> sqlite3.Connection: Opens SQLite connection with PRAGMA foreign_keys=ON; row_factory=None; isolation_level=None (autocommit off).
- errors.py
  - class ProductNotFoundError(Exception): Raised when a delete targets a non-existent product.
- product_repository.py
  - class ProductRepository:
    - delete_by_id(conn, product_id: int) -> int: Executes DELETE FROM products WHERE id = ?; returns cursor.rowcount.
- product_service.py
  - delete_product(product_id: int) -> int: Public API that validates input, manages transaction, calls repository, maps not-found to ProductNotFoundError, and returns deleted count.
- schema assumption
  - products(id INTEGER PRIMARY KEY, ...). Any FKs referencing products should define ON DELETE RESTRICT/CASCADE per domain; enforced by PRAGMA foreign_keys=ON.

## Data Flow
1. Caller invokes delete_product(product_id).
2. Validate product_id is positive int; else raise ValueError.
3. Acquire SQLite connection via get_connection().
4. Begin transaction: conn.execute("BEGIN").
5. Repository executes parameterized DELETE FROM products WHERE id = ? with (product_id,).
6. Inspect cursor.rowcount:
   - If 0: conn.rollback(); raise ProductNotFoundError(product_id).
   - If 1: conn.commit(); return 1.
7. Handle exceptions:
   - sqlite3.IntegrityError (FK violation): conn.rollback(); re-raise or wrap as domain-specific error if needed.
   - sqlite3.OperationalError (locked, etc.): conn.rollback(); re-raise.

## Key Decisions
- Decision: Raise ProductNotFoundError on missing id — Rationale: Explicit error satisfies “not-found error” and cleanly separates control flow from success path.
- Decision: Return deleted row count (int) — Rationale: Unambiguous confirmation; aligns with AC “boolean or count”.
- Decision: Parameterized SQL — Rationale: Prevent SQL injection and ensure correct type binding.
- Decision: Transaction per delete — Rationale: Guarantees atomicity and clear rollback on errors.
- Decision: Enable foreign_keys pragma — Rationale: Enforce referential integrity at delete time.

## Edge Cases & Risks
- Non-integer/negative id: Validate and raise ValueError.
- Concurrency/DB locked: Retry policy could be added; currently bubble up OperationalError.
- FK constraints prevent delete: Raise IntegrityError; document behavior.
- Rowcount reliability: SQLite provides correct rowcount for DELETE; do not SELECT-before-DELETE to avoid race.
- Connection leaks: Use try/finally to close connection.

## Acceptance Criteria (Technical)
- [ ] delete_product(id) deletes the product row and returns 1 when id exists.
- [ ] delete_product(id) raises ProductNotFoundError when id does not exist.
- [ ] Operation executes within a transaction and uses parameterized SQL.
- [ ] Foreign key constraints are enforced (PRAGMA foreign_keys=ON).