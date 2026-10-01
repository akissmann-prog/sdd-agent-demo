"""
scrum_50: Product update service module.

This module implements updating existing product records in a SQLite database,
following a layered architecture:
- models: product representation
- db: connection management
- validators: input validation and normalization
- pricing: conversion between API price and database storage
- repositories.products: database CRUD operations
- services.products: business orchestration
- exceptions: domain-specific errors

Top-level function:
- update_product(id, name, description, price, stock_quantity, category)

Notes:
- Uses parameterized SQL to avoid injection.
- Handles transactions explicitly; commits on success, rolls back on errors.
- Adapts to schemas that store price either as integer cents (price_cents) or REAL (price).
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Dict, Optional, TypedDict
import threading


# =========================
# exceptions
# =========================

class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


class NotFoundError(Exception):
    """Raised when a requested resource is not found."""
    pass


# =========================
# models
# =========================

class Product(TypedDict):
    id: int
    name: str
    description: Optional[str]
    price: float  # External representation in currency units (e.g., dollars)
    stock_quantity: int
    category: str


# =========================
# db
# =========================

_DB_PATH_ENV = "PRODUCT_DB_PATH"
_DEFAULT_DB_PATH = "products.db"


class db:
    """Database utilities."""

    @staticmethod
    def get_connection() -> sqlite3.Connection:
        """
        Create and return a sqlite3 connection with desired configuration:
        - row_factory set to sqlite3.Row
        - autocommit disabled (default isolation level)
        """
        db_path = os.getenv(_DB_PATH_ENV, _DEFAULT_DB_PATH)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Enforce foreign key constraints
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error:
            pass
        # Ensure pricing storage configuration is detected for this connection
        pricing.ensure_price_configuration(conn)
        return conn


# =========================
# validators
# =========================

@dataclass(frozen=True)
class _ValidatedProductPayload:
    name: str
    description: Optional[str]
    price: Decimal
    stock_quantity: int
    category: str


class validators:
    """Input validation and normalization helpers."""

    @staticmethod
    def _to_clean_str(value: Any, field: str, allow_empty: bool = False) -> str:
        if value is None:
            if allow_empty:
                return ""
            raise ValidationError(f"{field} is required")
        s = str(value).strip()
        if not allow_empty and not s:
            raise ValidationError(f"{field} must not be empty")
        return s

    @staticmethod
    def _to_non_negative_int(value: Any, field: str) -> int:
        if isinstance(value, bool):
            raise ValidationError(f"{field} must be a non-negative integer")
        try:
            # Accept str or numeric
            if isinstance(value, (int,)):
                ivalue = int(value)
            elif isinstance(value, float):
                if not value.is_integer():
                    raise ValidationError(f"{field} must be an integer value")
                ivalue = int(value)
            else:
                ivalue = int(str(value).strip())
        except (ValueError, TypeError):
            raise ValidationError(f"{field} must be a non-negative integer")
        if ivalue < 0:
            raise ValidationError(f"{field} must be a non-negative integer")
        return ivalue

    @staticmethod
    def _to_non_negative_decimal(value: Any, field: str) -> Decimal:
        try:
            if isinstance(value, Decimal):
                d = value
            elif isinstance(value, (int,)):
                d = Decimal(value)
            elif isinstance(value, float):
                # Convert via string to preserve decimal digits provided by float repr
                d = Decimal(str(value))
            else:
                d = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError(f"{field} must be a numeric value")
        if d < 0:
            raise ValidationError(f"{field} must be greater than or equal to 0")
        # Normalize to quantized 2 decimal places for currency-like input
        d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return d

    @staticmethod
    def validate_product_payload(
        name: Any,
        description: Any,
        price: Any,
        stock_quantity: Any,
        category: Any,
    ) -> _ValidatedProductPayload:
        """
        Validate and normalize product payload.

        - name: non-empty string (trimmed)
        - category: non-empty string (trimmed)
        - description: optional string; normalized to trimmed string; allow empty
        - price: numeric >= 0; normalized to Decimal with 2 decimal places
        - stock_quantity: int >= 0
        """
        clean_name = validators._to_clean_str(name, "name", allow_empty=False)
        clean_category = validators._to_clean_str(category, "category", allow_empty=False)

        # Description can be None or empty; normalize to trimmed string or None if empty after trim
        if description is None:
            clean_description: Optional[str] = None
        else:
            d = str(description).strip()
            clean_description = d if d != "" else None

        clean_price = validators._to_non_negative_decimal(price, "price")
        clean_stock = validators._to_non_negative_int(stock_quantity, "stock_quantity")

        return _ValidatedProductPayload(
            name=clean_name,
            description=clean_description,
            price=clean_price,
            stock_quantity=clean_stock,
            category=clean_category,
        )


# =========================
# pricing
# =========================

class pricing:
    """
    Pricing conversion utilities.

    Supports two storage strategies detected dynamically from the database schema:
    - "cents": store integer cents in column "price_cents" (INTEGER)
    - "real": store real number in column "price" (REAL)

    The module maintains thread-local configuration after detection to avoid cross-thread interference.
    """
    _local = threading.local()

    @classmethod
    def ensure_price_configuration(cls, conn: sqlite3.Connection) -> None:
        """
        Detect and set the price storage configuration from the schema for the current thread.
        Always re-evaluates for the provided connection to match its schema.
        """
        try:
            cursor = conn.execute("PRAGMA table_info(products)")
            rows = cursor.fetchall()
        except sqlite3.Error:
            # If schema introspection fails, default to cents strategy
            setattr(cls._local, "storage_mode", "cents")
            setattr(cls._local, "price_column", "price_cents")
            return

        cols = {row["name"].lower(): (row["type"] or "").upper() for row in rows}
        if "price_cents" in cols:
            storage_mode = "cents"
            price_column = "price_cents"
        elif "price" in cols:
            sql_type = cols["price"]
            if "INT" in sql_type:
                storage_mode = "cents"
                price_column = "price"
            else:
                # Assume REAL or NUMERIC stores direct currency value
                storage_mode = "real"
                price_column = "price"
        else:
            # Default to cents strategy if price column not present
            storage_mode = "cents"
            price_column = "price_cents"

        setattr(cls._local, "storage_mode", storage_mode)
        setattr(cls._local, "price_column", price_column)

    @classmethod
    def get_price_column(cls) -> str:
        col = getattr(cls._local, "price_column", None)
        if col is None:
            # default fallback
            return "price_cents"
        return col

    @classmethod
    def to_db_price(cls, price: Decimal) -> Any:
        """
        Convert normalized API price (Decimal) to database storage form
        according to detected storage mode.
        """
        mode = getattr(cls._local, "storage_mode", None) or "cents"
        if mode == "cents":
            cents = int((price * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            return cents
        # real storage: store as string to preserve exact 2dp
        return str(price)

    @classmethod
    def from_db_price(cls, db_value: Any) -> float:
        """
        Convert stored database price value to API representation (float).
        """
        mode = getattr(cls._local, "storage_mode", None) or "cents"
        if db_value is None:
            return 0.0
        if mode == "cents":
            try:
                cents = int(db_value)
            except (ValueError, TypeError):
                cents = 0
            d = (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return float(d)
        # real mode
        try:
            d = Decimal(str(db_value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError, TypeError):
            d = Decimal("0.00")
        return float(d)


# =========================
# repositories
# =========================

class repositories:
    class products:
        @staticmethod
        def get_by_id(conn: sqlite3.Connection, id: int) -> Optional[sqlite3.Row]:
            sql = """
                SELECT id, name, description, {price_col} AS price_value, stock_quantity, category
                FROM products
                WHERE id = ?
            """.format(price_col=pricing.get_price_column())
            cur = conn.execute(sql, (id,))
            row = cur.fetchone()
            return row

        @staticmethod
        def update(conn: sqlite3.Connection, id: int, fields: Dict[str, Any]) -> int:
            """
            Update product by id. Returns affected row count.

            fields keys must correspond to columns in the 'products' table.
            """
            if not fields:
                # Nothing to update; return 0 for no-op
                return 0

            # Prepare SQL SET clause
            set_clause_parts = []
            params: list[Any] = []
            for col, val in fields.items():
                set_clause_parts.append(f"{col} = ?")
                params.append(val)
            params.append(id)
            sql = f"UPDATE products SET {', '.join(set_clause_parts)} WHERE id = ?"
            cur = conn.execute(sql, tuple(params))
            return cur.rowcount


# =========================
# services
# =========================

class services:
    class products:
        @staticmethod
        def _row_to_product(row: sqlite3.Row) -> Product:
            return Product(
                id=int(row["id"]),
                name=str(row["name"]),
                description=row["description"] if row["description"] is not None else None,
                price=pricing.from_db_price(row["price_value"]),
                stock_quantity=int(row["stock_quantity"]),
                category=str(row["category"]),
            )

        @staticmethod
        def update_product(
            id: Any,
            name: Any,
            description: Any,
            price: Any,
            stock_quantity: Any,
            category: Any,
        ) -> Product:
            """
            Orchestrates validation, existence check, update, and reload to return updated product.
            """
            # Validate id early
            try:
                if isinstance(id, bool):
                    raise ValidationError("id must be a positive integer")
                if isinstance(id, int):
                    id_int = int(id)
                elif isinstance(id, float):
                    if not id.is_integer():
                        raise ValidationError("id must be a positive integer")
                    id_int = int(id)
                else:
                    id_int = int(str(id).strip())
            except (ValueError, TypeError):
                raise ValidationError("id must be a positive integer")
            if id_int <= 0:
                raise ValidationError("id must be a positive integer")

            conn = db.get_connection()
            try:
                # Existence check
                existing = repositories.products.get_by_id(conn, id_int)
                if existing is None:
                    raise NotFoundError(f"Product with id {id_int} not found")

                # Validate and normalize payload
                val = validators.validate_product_payload(
                    name=name,
                    description=description,
                    price=price,
                    stock_quantity=stock_quantity,
                    category=category,
                )

                # Prepare update fields
                price_col = pricing.get_price_column()
                db_price = pricing.to_db_price(val.price)
                fields: Dict[str, Any] = {
                    "name": val.name,
                    "description": val.description,
                    price_col: db_price,
                    "stock_quantity": val.stock_quantity,
                    "category": val.category,
                }

                # Execute update
                try:
                    repositories.products.update(conn, id_int, fields)
                except sqlite3.IntegrityError as e:
                    conn.rollback()
                    raise ValidationError(f"Database constraint violated: {e}")

                # Commit transaction regardless of rowcount (SQLite may return 0 when values are identical)
                conn.commit()

                # Reload updated record
                updated_row = repositories.products.get_by_id(conn, id_int)
                if updated_row is None:
                    # Treat as not found only if row truly disappeared
                    raise NotFoundError(f"Product with id {id_int} not found after update")

                return services.products._row_to_product(updated_row)

            except (ValidationError, NotFoundError):
                # Propagate domain exceptions as-is
                raise
            except sqlite3.IntegrityError as e:
                conn.rollback()
                raise ValidationError(f"Database constraint violated: {e}")
            except sqlite3.Error as e:
                conn.rollback()
                raise ValidationError(f"Database error: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass


# =========================
# Public API
# =========================

def update_product(
    id: Any,
    name: Any,
    description: Any,
    price: Any,
    stock_quantity: Any,
    category: Any,
) -> Product:
    """
    Update a product and return the updated record.
    Raises:
    - NotFoundError if the product id does not exist.
    - ValidationError for invalid inputs or database constraint violations.
    """
    return services.products.update_product(
        id=id,
        name=name,
        description=description,
        price=price,
        stock_quantity=stock_quantity,
        category=category,
    )