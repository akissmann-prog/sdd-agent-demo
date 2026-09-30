# Design: As a developer, I want to list and retrieve products

## Overview
Expose two read functions backed by SQLite: list_products() returns all product records; get_product_by_id(id) returns a single product or a not-found error. Use parameterized SQL, read-only connections, and sqlite3.Row to return dict-like records reflecting the current DB state.

## Components
- db.py
  - get_ro_connection(db_path: str) -> sqlite3.Connection: Returns a read-only connection with row_factory=sqlite3.Row and autocommit.
- errors.py
  - NotFoundError(Exception): Raised when a product is not found.
- repository.py
  - ProductRepository(db_path: str)
    - list_products() -> list[dict]: SELECTs all columns and maps rows to dicts.
    - get_product_by_id(product_id: int) -> dict: SELECTs by id, raises NotFoundError if none.
- api.py
  - list_products() -> list[dict]: Thin facade calling repository.
  - get_product_by_id(id: int) -> dict: Validates id, delegates to repository.

Assumed schema (table products): id INTEGER PRIMARY KEY, name TEXT, description TEXT, price REAL, stock_quantity INTEGER, category TEXT.

## Data Flow
1. Caller invokes api.list_products().
2. api.list_products() instantiates ProductRepository with configured DB path.
3. Repository opens a read-only SQLite connection via db.get_ro_connection().
4. Executes: SELECT id, name, description, price, stock_quantity, category FROM products ORDER BY id ASC;
5. Fetches all rows, maps each sqlite3.Row to dict(row), returns list.
6. For get_product_by_id(id):
   - api.get_product_by_id validates id is int > 0.
   - Repository opens RO connection and executes:
     SELECT id, name, description, price, stock_quantity, category FROM products WHERE id = ?;
   - If row exists, return dict(row); else raise NotFoundError.

## Key Decisions
- Decision: Use read-only SQLite URI connections — Rationale: Prevent accidental writes and ensure reads reflect latest committed state.
- Decision: sqlite3.Row row_factory and dict(row) — Rationale: Return plain records matching acceptance fields without extra mapping code.
- Decision: Parameterized queries — Rationale: Prevent SQL injection.
- Decision: Open/close connection per call — Rationale: Ensures visibility of current DB state and simplifies lifecycle.

## Edge Cases & Risks
- Non-integer or <=0 id: Validate and raise ValueError.
- Missing product: Raise NotFoundError.
- Empty table: list_products returns [].
- DB/file not found or schema missing: Surface sqlite3.OperationalError; log and rethrow.
- Large result sets: fetchall may be heavy; acceptable for current scope, consider pagination later.
- Concurrency: Reads see last committed data; handle sqlite3.DatabaseError by retrying once if needed.

## Acceptance Criteria (Technical)
- [ ] list_products() returns list of dicts with keys: id, name, description, price, stock_quantity, category.
- [ ] get_product_by_id(id) returns matching dict or raises NotFoundError if absent.
- [ ] Functions read from the configured SQLite database and reflect current committed state.
- [ ] Queries use parameter binding and connections are properly closed.