# Design: As a developer, I want to update existing products

## Overview
Implement a service function update_product that validates input, ensures the product exists, performs a parameterized UPDATE in SQLite within a transaction, and returns the updated product by reloading it from the database. Reuse the same validation and persistence conventions (e.g., price storage) as the creation feature.

## Components
- models.Product: Data class or dict shape with fields id, name, description, price, stock_quantity, category.
- db.get_connection(): Provides sqlite3 connection with row_factory=sqlite3.Row and autocommit disabled.
- validators.validate_product_payload(name, description, price, stock_quantity, category): Reused from creation; raises ValidationError on failure.
- pricing.to_db_price(price), pricing.from_db_price(db_value): Convert between API price and stored form (reuse creation strategy: cents integer or REAL).
- repositories.products.get_by_id(conn, id) -> Product|None: SELECT by id.
- repositories.products.update(conn, id, fields) -> int: Executes UPDATE ... WHERE id=?; returns affected row count.
- services.products.update_product(id, name, description, price, stock_quantity, category) -> Product dict: Orchestrates validation, repo calls, and error mapping.
- exceptions.ValidationError, exceptions.NotFoundError: For input and existence errors.

## Data Flow
1. services.update_product receives parameters.
2. Open conn = db.get_connection(); begin transaction.
3. repositories.products.get_by_id(conn, id): if None, raise NotFoundError.
4. validators.validate_product_payload(...). Normalize/trim strings; ensure:
   - name non-empty; category non-empty
   - price is numeric and >= 0
   - stock_quantity is int >= 0
5. Prepare fields:
   - db_price = pricing.to_db_price(price)
   - fields = {name, description, price_column: db_price, stock_quantity, category}
6. count = repositories.products.update(conn, id, fields) using parameterized SQL.
7. If count == 0: raise NotFoundError (defensive).
8. Commit.
9. Reload updated = repositories.products.get_by_id(conn, id); map row to Product with pricing.from_db_price.
10. Return updated as dict/Product.

## Key Decisions
- Decision: Full update semantics — Rationale: Function signature requires all fields; simplifies validation and SQL.
- Decision: Post-update reload instead of RETURNING — Rationale: Ensures compatibility with older SQLite versions.
- Decision: Reuse creation price storage strategy — Rationale: Guarantees consistency (e.g., cents vs REAL).
- Decision: Existence check before validation — Rationale: Fast-fail on invalid id and avoids unnecessary validation work.

## Edge Cases & Risks
- Product not found: raise NotFoundError.
- SQLite constraint violations: surface as ValidationError with friendly message.
- Floating-point issues: avoid by storing price per creation strategy (prefer integer cents via pricing module).
- Concurrency/lost updates: last-write-wins; transaction ensures atomicity.
- Null/empty strings: normalize and validate; description may be None/empty if schema allows.

## Acceptance Criteria (Technical)
- [ ] update_product(id, ...) updates the row in SQLite and commits within a transaction.
- [ ] If id does not exist, update_product raises NotFoundError.
- [ ] Same validations as creation are enforced; invalid inputs raise ValidationError.
- [ ] The returned product reflects persisted values (including price conversion) fetched from DB.
- [ ] SQL uses parameterized queries; no string interpolation.
- [ ] Unit/integration tests cover success path, not-found, and validation failures.