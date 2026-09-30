"""
scrum_42.py

Feature: Create products and persist them in a SQLite database.

This module provides a public function `create_product(name, description, price, stock_quantity, category)`
that validates inputs, ensures the SQLite database and products table exist, inserts the product, and returns
a structured result.

Architecture components implemented within this single module:
- db: Database connection and initialization utilities.
- models: Product dataclass.
- validators: Input normalization and validation.
- repository: Data persistence functions for products.
- service: Orchestration logic for product creation.

No external dependencies beyond Python's standard library.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


# ========== db.py ==========

def get_connection(db_path: str = "catalog.db") -> sqlite3.Connection:
    """
    Open a SQLite connection with a timeout and configured row_factory.
    """
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """
    Create the products table if it does not already exist.
    Includes CHECK constraints for defensive validation.
    """
    create_sql = """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL CHECK (trim(name) <> ''),
        description TEXT NOT NULL CHECK (trim(description) <> ''),
        price REAL NOT NULL CHECK (price >= 0),
        stock_quantity INTEGER NOT NULL CHECK (stock_quantity >= 0),
        category TEXT NOT NULL CHECK (trim(category) <> '')
    )
    """
    cur = conn.cursor()
    try:
        cur.execute(create_sql)
        conn.commit()
    finally:
        cur.close()


# ========== models.py ==========

@dataclass(frozen=True)
class Product:
    id: Optional[int]
    name: str
    description: str
    price: float
    stock_quantity: int
    category: str


# ========== validators.py ==========

def _normalize_string(value: Any, field_name: str, errors: List[str]) -> Optional[str]:
    if value is None:
        errors.append(f"{field_name} is required and cannot be empty.")
        return None
    try:
        s = str(value).strip()
    except Exception:
        errors.append(f"{field_name} must be a string.")
        return None
    if s == "":
        errors.append(f"{field_name} is required and cannot be empty.")
        return None
    return s


def _coerce_price(value: Any, errors: List[str]) -> Optional[float]:
    if value is None:
        errors.append("price is required and must be a non-negative number.")
        return None
    if isinstance(value, bool):
        errors.append("price must be a non-negative number.")
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        errors.append("price must be a non-negative number.")
        return None
    if not math.isfinite(f) or f < 0:
        errors.append("price must be a non-negative number.")
        return None
    return f


def _coerce_stock_quantity(value: Any, errors: List[str]) -> Optional[int]:
    if value is None:
        errors.append("stock_quantity is required and must be a non-negative integer.")
        return None
    if isinstance(value, bool):
        errors.append("stock_quantity must be a non-negative integer.")
        return None
    # If explicitly a float, ensure it's an integer value
    if isinstance(value, float) and not value.is_integer():
        errors.append("stock_quantity must be a non-negative integer.")
        return None
    try:
        i = int(value)
    except (TypeError, ValueError):
        errors.append("stock_quantity must be a non-negative integer.")
        return None
    if i < 0:
        errors.append("stock_quantity must be a non-negative integer.")
        return None
    return i


def validate_product_inputs(
    name: Any,
    description: Any,
    price: Any,
    stock_quantity: Any,
    category: Any,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    Validate and normalize product inputs.
    Returns a tuple (normalized, errors).
    - normalized: dict with keys name, description, price, stock_quantity, category when valid; otherwise None.
    - errors: list of error messages (empty when valid).
    """
    errors: List[str] = []

    norm_name = _normalize_string(name, "name", errors)
    norm_description = _normalize_string(description, "description", errors)
    norm_category = _normalize_string(category, "category", errors)
    norm_price = _coerce_price(price, errors)
    norm_stock = _coerce_stock_quantity(stock_quantity, errors)

    if errors:
        return None, errors

    normalized: Dict[str, Any] = {
        "name": norm_name,  # type: ignore[typeddict-item]
        "description": norm_description,  # type: ignore[typeddict-item]
        "price": norm_price,  # type: ignore[typeddict-item]
        "stock_quantity": norm_stock,  # type: ignore[typeddict-item]
        "category": norm_category,  # type: ignore[typeddict-item]
    }
    return normalized, []


# ========== repository/products_repo.py ==========

def insert_product(conn: sqlite3.Connection, product: Product) -> int:
    """
    Insert a new product into the database.
    Returns the generated primary key (lastrowid).
    """
    if product.id is not None:
        raise ValueError("Product.id must be None when inserting a new product.")

    sql = """
    INSERT INTO products (name, description, price, stock_quantity, category)
    VALUES (?, ?, ?, ?, ?)
    """
    params = (product.name, product.description, product.price, product.stock_quantity, product.category)
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        last_id = int(cur.lastrowid)
        conn.commit()
        return last_id
    finally:
        cur.close()


# ========== service/products_service.py ==========

def _map_sqlite_error_code(e: BaseException) -> Optional[int]:
    code: Optional[int] = None
    # Python 3.11+ provides sqlite_errorcode attribute
    if hasattr(e, "sqlite_errorcode"):
        try:
            code = getattr(e, "sqlite_errorcode")  # type: ignore[attr-defined]
        except Exception:
            code = None
    return code


def create_product(
    name: Any,
    description: Any,
    price: Any,
    stock_quantity: Any,
    category: Any,
) -> Dict[str, Any]:
    """
    Orchestrate product creation:
    - Validate inputs
    - Initialize DB/table if needed
    - Insert product
    - Return structured result dict
    """
    normalized, errors = validate_product_inputs(name, description, price, stock_quantity, category)
    if errors:
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "details": errors}}

    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_connection()
        init_db(conn)

        product = Product(
            id=None,
            name=normalized["name"],  # type: ignore[index]
            description=normalized["description"],  # type: ignore[index]
            price=normalized["price"],  # type: ignore[index]
            stock_quantity=normalized["stock_quantity"],  # type: ignore[index]
            category=normalized["category"],  # type: ignore[index]
        )

        new_id = insert_product(conn, product)
        created: Dict[str, Any] = {
            "id": new_id,
            "name": product.name,
            "description": product.description,
            "price": product.price,
            "stock_quantity": product.stock_quantity,
            "category": product.category,
        }
        return {"ok": True, "product": created}

    except sqlite3.Error as e:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                # Ignore rollback errors
                pass

        code = _map_sqlite_error_code(e)
        message = str(e)
        if code == 5 or "locked" in message.lower():
            return {"ok": False, "error": {"code": "DB_LOCKED", "message": message}}
        return {"ok": False, "error": {"code": "DB_ERROR", "message": message}}

    except Exception as e:
        # Non-SQLite unexpected errors; present as DB_ERROR for uniformity
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return {"ok": False, "error": {"code": "DB_ERROR", "message": str(e)}}

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
