# Design: As a developer, I want to create products

## Overview
Implement a create_product function that validates inputs, ensures the SQLite database and products table exist, inserts a new product using parameterized SQL, and returns the created record (including generated id). Errors are returned as structured objects for validation and DB failures.

## Components
- module db.py
  - get_connection(db_path='catalog.db'): Opens sqlite3 connection with timeout and row_factory.
  - init_db(conn): Creates products table if not exists.
- module models.py
  - Product(dataclass): id, name, description, price, stock_quantity, category.
- module validators.py
  - validate_product_inputs(name, description, price, stock_quantity, category) -> (normalized, errors)
    - Trims strings; coerces price to float and stock_quantity to int; verifies non-empty and non-negative.
- module repository/products_repo.py
  - insert_product(conn, product: Product without id) -> int: Executes INSERT and returns lastrowid.
- module service/products_service.py
  - create_product(name, description, price, stock_quantity, category) -> dict
    - Orchestrates validation, DB init, insert, returns {"ok": True, "product": {...}} or {"ok": False, "error": {...}}.

## Data Flow
1. create_product receives raw inputs.
2. Call validate_product_inputs:
   - Strip name/description/category; ensure non-empty.
   - Convert price to float; ensure >= 0.
   - Convert stock_quantity to int; ensure >= 0.
   - On any failure, return {"ok": False, "error": {"code": "VALIDATION_ERROR", "details": [list of messages]}}.
3. Acquire conn = get_connection(); call init_db(conn) once per connection.
4. Build INSERT SQL:
   - INSERT INTO products(name, description, price, stock_quantity, category) VALUES (?, ?, ?, ?, ?)
5. Execute with parameters; commit; capture cursor.lastrowid.
6. Return {"ok": True, "product": {"id": lastrowid, "name": ..., "description": ..., "price": ..., "stock_quantity": ..., "category": ...}}.
7. On sqlite3.Error, rollback and return {"ok": False, "error": {"code": "DB_ERROR", "message": str(e)}}; if e.sqlite_errorcode == 5, set code "DB_LOCKED".

## Key Decisions
- Decision: Per-call SQLite connection — Rationale: Simpler, avoids cross-thread issues; SQLite is lightweight.
- Decision: Double validation (app + DB CHECK) — Rationale: Defense-in-depth against bad data.
- Decision: Return structured result dict — Rationale: Clear, non-exception control flow per requirements.

## Edge Cases & Risks
- Price floating-point precision: Using REAL may introduce rounding issues; acceptable for scope, document for future change to integer cents or Decimal.
- Concurrent writes/locked DB: Surface DB_LOCKED error; caller may retry with backoff.
- Whitespace-only strings: Trim before validation to prevent accidental passes.
- Type coercion failures (e.g., "abc" for price): Return validation error.

## Acceptance Criteria (Technical)
- [ ] create_product validates all fields; whitespace-only strings rejected; negative price/stock rejected.
- [ ] On valid input, function creates DB/table if missing, inserts row, commits, and returns product with generated id.
- [ ] On validation failure, function returns {"ok": False, "error": {"code": "VALIDATION_ERROR", "details": [...]}}.
- [ ] On DB error, function returns {"ok": False, "error": {"code": "DB_ERROR" or "DB_LOCKED", "message": ...}}.