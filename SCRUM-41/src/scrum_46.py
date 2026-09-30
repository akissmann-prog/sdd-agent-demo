"""
scrum_46.py

Feature: List and retrieve products from a SQLite-backed catalog.

This module exposes two primary API functions:
- list_products(): returns all product records as a list of dicts.
- get_product_by_id(id): returns a single product dict by ID or raises NotFoundError.

Design notes:
- Uses a read-only SQLite connection via URI to prevent accidental writes.
- Connections are opened and closed per call to reflect the latest committed DB state.
- Uses sqlite3.Row for convenient dict(row) mapping.
- Queries are parameterized to avoid SQL injection.
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Callable, Optional, Sequence, TypedDict
from urllib.parse import quote


class NotFoundError(Exception):
    """Raised when a requested product cannot be found."""


class ProductRecord(TypedDict):
    id: int
    name: str
    description: Optional[str]
    price: float
    stock_quantity: int
    category: Optional[str]


def _build_ro_uri(db_path: str) -> str:
    """
    Build a read-only SQLite URI for the provided database path.

    Ensures absolute pathing and proper escaping for URI usage.
    """
    if not db_path or not isinstance(db_path, str):
        raise ValueError("db_path must be a non-empty string")
    abs_path = os.path.abspath(db_path)
    # Escape path for URI; keep path separators as-is.
    escaped = quote(abs_path, safe="/:\\")
    return f"file:{escaped}?mode=ro&cache=shared"


def get_ro_connection(db_path: str) -> sqlite3.Connection:
    """
    Return a read-only SQLite connection with row_factory set to sqlite3.Row and autocommit enabled.
    """
    uri = _build_ro_uri(db_path)
    # isolation_level=None enables autocommit; uri=True enables URI parsing.
    conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


class ProductRepository:
    """
    Repository providing read-only access to product data.
    """

    def __init__(self, db_path: str):
        if not db_path or not isinstance(db_path, str):
            raise ValueError("db_path must be a non-empty string")
        self._db_path = db_path

    def list_products(self) -> list[ProductRecord]:
        """
        Return all products as a list of dicts with keys:
        id, name, description, price, stock_quantity, category.
        """
        sql = (
            "SELECT id, name, description, price, stock_quantity, category "
            "FROM products "
            "ORDER BY id ASC;"
        )
        rows = self._fetch_all(sql, ())
        return [self._row_to_product_dict(row) for row in rows]

    def get_product_by_id(self, product_id: int) -> ProductRecord:
        """
        Return the product with the given id or raise NotFoundError if not found.
        """
        sql = (
            "SELECT id, name, description, price, stock_quantity, category "
            "FROM products "
            "WHERE id = ?;"
        )
        row = self._fetch_one(sql, (product_id,))
        if row is None:
            raise NotFoundError(f"Product with id {product_id} not found")
        return self._row_to_product_dict(row)

    def _fetch_all(self, sql: str, params: Sequence[Any]) -> list[sqlite3.Row]:
        """
        Execute a SELECT returning multiple rows, with a single retry on DatabaseError.
        """
        def _op() -> list[sqlite3.Row]:
            with get_ro_connection(self._db_path) as conn:
                cur = conn.execute(sql, params)
                return cur.fetchall()

        return self._with_retry(_op)

    def _fetch_one(self, sql: str, params: Sequence[Any]) -> Optional[sqlite3.Row]:
        """
        Execute a SELECT returning a single row, with a single retry on DatabaseError.
        """
        def _op() -> Optional[sqlite3.Row]:
            with get_ro_connection(self._db_path) as conn:
                cur = conn.execute(sql, params)
                return cur.fetchone()

        return self._with_retry(_op)

    @staticmethod
    def _with_retry(op: Callable[[], Any]) -> Any:
        """
        Execute the callable, retrying once on sqlite3.DatabaseError after a short delay.
        """
        try:
            return op()
        except sqlite3.DatabaseError:
            # Brief backoff then retry once
            time.sleep(0.05)
            return op()

    @staticmethod
    def _row_to_product_dict(row: sqlite3.Row) -> ProductRecord:
        data = dict(row)
        # Type assertions for ProductRecord
        return ProductRecord(
            id=int(data["id"]),
            name=data["name"],
            description=data.get("description"),
            price=float(data["price"]),
            stock_quantity=int(data["stock_quantity"]),
            category=data.get("category"),
        )


# API layer

# Module-level configurable DB path.
_DB_PATH: str = (
    os.environ.get("PRODUCTS_DB_PATH")
    or os.environ.get("DB_PATH")
    or "products.db"
)


def set_db_path(db_path: str) -> None:
    """
    Configure the SQLite database path used by API functions.
    """
    global _DB_PATH
    if not db_path or not isinstance(db_path, str):
        raise ValueError("db_path must be a non-empty string")
    _DB_PATH = db_path


def _get_repository() -> ProductRepository:
    return ProductRepository(_DB_PATH)


def list_products() -> list[dict]:
    """
    Return all product records as a list of dicts with keys:
    id, name, description, price, stock_quantity, category.
    """
    repo = _get_repository()
    # Return plain dicts (not TypedDict instances) as per acceptance criteria
    products = repo.list_products()
    # Convert TypedDict to plain dict for a more general return type
    return [dict(p) for p in products]


def get_product_by_id(id: int) -> dict:
    """
    Return a single product record by id or raise NotFoundError if not found.

    Validates that id is an integer > 0.
    """
    if not isinstance(id, int) or id <= 0:
        raise ValueError("id must be an integer greater than 0")
    repo = _get_repository()
    product = repo.get_product_by_id(id)
    return dict(product)


__all__ = [
    "NotFoundError",
    "ProductRepository",
    "get_ro_connection",
    "set_db_path",
    "list_products",
    "get_product_by_id",
]