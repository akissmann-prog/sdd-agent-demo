# Design: As a developer, I want to create products

## Overview
Implement a robust create_product function that validates input, ensures SQLite initialization, inserts a product using a parameterized SQL statement within a transaction, and returns a clear result. Validation occurs in code and is reinforced via DB constraints. Errors are exposed in a predictable Result object.

## Components
- db.py
  - get_connection(db_path="catalog.db"): opens sqlite3 connection (row_factory=sqlite3.Row, timeout=5, isolation_level=None), sets PRAGMA foreign_keys=ON, journal_mode=WAL.
  - ensure_schema(conn): CREATE TABLE IF NOT EXISTS products (...).
- validation.py
  - ValidationError(Exception)
  - normalize_and_validate(name, description, price, stock_quantity, category): trims strings; ensures non-empty; converts price to float (non-negative, finite); stock_quantity to int (non-negative).
- products.py
  - create_product(name, description, price, stock_quantity, category, db_path="catalog.db") -> dict: orchestrates validation, DB init, insert, and result.
  - _row_to_product(row): maps sqlite3.Row to dict.

Schema (ensure_schema):
- products(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  price REAL NOT NULL CHECK(price >= 0),
  stock_quantity INTEGER NOT NULL CHECK(stock_quantity >= 0),
  category TEXT NOT NULL,
  created_at TEXT NOT NULL
)

## Data Flow
1. Caller invokes create_product(...).
2. normalize_and_validate trims and validates inputs; returns normalized values or raises ValidationError.
3. get_connection(db_path) opens connection; ensure_schema(conn) creates table if missing.
4. Begin transaction: conn.execute("BEGIN").
5. Execute INSERT with placeholders:
   INSERT INTO products(name, description, price, stock_quantity, category, created_at) VALUES(?,?,?,?,?,?)
6. Retrieve lastrowid; optionally SELECT by id to build full product.
7. Commit; return {"ok": True, "product": {...}} including generated id.
8. On ValidationError: return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": str(e)}}.
9. On sqlite3.Error: rollback and return {"ok": False, "error": {"code": "DB_ERROR", "message": str(e)}}.
10. Close connection in finally.

## Key Decisions
- Decision: Return Result dict (ok/product/error) — Rationale: Satisfies “error is returned” and avoids exception-only contracts.
- Decision: Dual validation (app and DB CHECK) — Rationale: Defense in depth.
- Decision: WAL mode and timeout — Rationale: Better concurrency, reduce lock errors.

## Edge Cases & Risks
- Empty/whitespace-only strings: trim then reject.
- price as string/NaN/inf: coerce, check isfinite; reject invalid.
- stock_quantity non-integer/float: coerce to int if exact, else reject.
- DB locked: timeout configured; still may fail—return DB_ERROR.
- Float precision: store as REAL; acceptance tolerates; consider Decimal later if needed.
- SQL injection: use parameterized queries only.

## Acceptance Criteria (Technical)
- [ ] create_product persists a new product in SQLite and returns {"ok": True, "product": {"id": int, ...}}.
- [ ] All fields validated: non-empty strings; price >= 0 finite; stock_quantity integer >= 0; invalid inputs return {"ok": False, "error": {"code": "VALIDATION_ERROR", ...}}.
- [ ] Database and products table auto-initialize if not present.
- [ ] Uses parameterized SQL and transactions; on DB failure returns {"ok": False, "error": {"code": "DB_ERROR", ...}}.