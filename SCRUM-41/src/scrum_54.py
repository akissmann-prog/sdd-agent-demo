"""
scrum_54.py

Feature: Delete products from a SQLite-backed catalog.

This module provides a clean implementation for deleting a product by ID,
following a repository pattern with transactional execution, parameterized SQL,
and explicit error mapping.

Public API:
- delete_product(product_id: int) -> int

Behavior:
- On success: returns 1 (number of deleted rows).
- On missing ID: raises ProductNotFoundError.
- Validates input: product_id must be a positive integer.
- Enforces foreign key constraints via PRAGMA foreign_keys=ON.
- Uses a single transaction per delete.

Configuration:
- The SQLite database path is read from the environment variable CATALOG_DB_PATH.
  Defaults to "catalog.db" if not set.

Schema assumption:
- products(id INTEGER PRIMARY KEY, ...).
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional


# =========================
# errors.py
# =========================

class ProductNotFoundError(Exception):
    """Raised when a delete targets a non-existent product."""

    def __init__(self, product_id: int) -> None:
        self.product_id: int = product_id
        super().__init__(f"Product with id {product_id} not found.")


# =========================
# db.py
# =========================

def get_connection() -> sqlite3.Connection:
    """
    Obtain a SQLite connection with:
    - isolation_level=None (autocommit mode; explicit BEGIN/COMMIT/ROLLBACK)
    - PRAGMA foreign_keys=ON
    - row_factory=None (default)
    """
    db_path: str = os.environ.get("CATALOG_DB_PATH", "catalog.db")
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        # Enforce referential integrity
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        conn.close()
        raise
    return conn


# =========================
# product_repository.py
# =========================

class ProductRepository:
    """Repository for product persistence operations."""

    def delete_by_id(self, conn: sqlite3.Connection, product_id: int) -> int:
        """
        Hard-delete a product by ID.

        Returns:
            int: number of rows deleted (0 or 1).
        """
        sql = "DELETE FROM products WHERE id = ?"
        cur = conn.execute(sql, (product_id,))
        try:
            return cur.rowcount
        finally:
            cur.close()


# =========================
# product_service.py
# =========================

def delete_product(product_id: int) -> int:
    """
    Delete a product by its ID.

    Args:
        product_id (int): The ID of the product to delete. Must be a positive integer.

    Returns:
        int: Number of deleted rows (1 on success).

    Raises:
        ValueError: If product_id is not a positive integer.
        ProductNotFoundError: If no product with the given ID exists.
        sqlite3.IntegrityError: If foreign key constraints prevent the delete.
        sqlite3.OperationalError: For operational DB errors (e.g., database is locked).
    """
    _validate_product_id(product_id)

    conn: Optional[sqlite3.Connection] = None
    repo = ProductRepository()

    try:
        conn = get_connection()
        # Begin explicit transaction since isolation_level=None
        conn.execute("BEGIN")
        deleted = repo.delete_by_id(conn, product_id)

        if deleted == 0:
            conn.rollback()
            raise ProductNotFoundError(product_id)

        conn.commit()
        return deleted
    except (sqlite3.IntegrityError, sqlite3.OperationalError):
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                # Swallow rollback errors to not mask the original DB error.
                pass
        raise
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                # Ensure no exception escapes during cleanup.
                pass


# =========================
# helpers
# =========================

def _validate_product_id(product_id: int) -> None:
    """Ensure product_id is a positive integer and not a boolean."""
    if isinstance(product_id, bool) or not isinstance(product_id, int):
        raise ValueError("product_id must be an integer.")
    if product_id <= 0:
        raise ValueError("product_id must be a positive integer.")


__all__ = [
    "delete_product",
    "ProductNotFoundError",
]