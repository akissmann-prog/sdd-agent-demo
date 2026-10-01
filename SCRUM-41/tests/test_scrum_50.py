import os
import sqlite3
from decimal import Decimal

import pytest

import scrum_50
from scrum_50 import update_product, ValidationError, NotFoundError


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _create_schema_cents(conn, unique_name=True, include_category=True):
    cols = [
        "id INTEGER PRIMARY KEY",
        "name TEXT NOT NULL" + (" UNIQUE" if unique_name else ""),
        "description TEXT",
        "price_cents INTEGER NOT NULL",
        "stock_quantity INTEGER NOT NULL",
    ]
    if include_category:
        cols.append("category TEXT NOT NULL")
    conn.execute(f"CREATE TABLE products ({', '.join(cols)})")
    conn.commit()


def _create_schema_real(conn, unique_name=True, include_category=True):
    cols = [
        "id INTEGER PRIMARY KEY",
        "name TEXT NOT NULL" + (" UNIQUE" if unique_name else ""),
        "description TEXT",
        "price REAL NOT NULL",
        "stock_quantity INTEGER NOT NULL",
    ]
    if include_category:
        cols.append("category TEXT NOT NULL")
    conn.execute(f"CREATE TABLE products ({', '.join(cols)})")
    conn.commit()


def _insert_cents_product(conn, id, name, description, cents, stock, category=None):
    if category is None:
        conn.execute(
            "INSERT INTO products (id, name, description, price_cents, stock_quantity) VALUES (?, ?, ?, ?, ?)",
            (id, name, description, cents, stock),
        )
    else:
        conn.execute(
            "INSERT INTO products (id, name, description, price_cents, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
            (id, name, description, cents, stock, category),
        )
    conn.commit()


def _insert_real_product(conn, id, name, description, price_val, stock, category=None):
    if category is None:
        conn.execute(
            "INSERT INTO products (id, name, description, price, stock_quantity) VALUES (?, ?, ?, ?, ?)",
            (id, name, description, price_val, stock),
        )
    else:
        conn.execute(
            "INSERT INTO products (id, name, description, price, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
            (id, name, description, price_val, stock, category),
        )
    conn.commit()


def test_update_product_cents_happy_path_rounding_and_persistence(tmp_path, monkeypatch):
    db_path = tmp_path / "db1.sqlite"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = _connect(str(db_path))
    _create_schema_cents(conn)
    _insert_cents_product(conn, 1, "Original", "Old desc", 1234, 10, "Cat")
    conn.close()

    result = update_product(
        1,
        name="New Name",
        description="  New desc  ",
        price=Decimal("1.005"),
        stock_quantity="5",
        category="  Gadgets  ",
    )

    assert result["id"] == 1
    assert result["name"] == "New Name"
    assert result["description"] == "New desc"
    assert result["price"] == pytest.approx(1.01)
    assert result["stock_quantity"] == 5
    assert result["category"] == "Gadgets"

    conn2 = _connect(str(db_path))
    row = conn2.execute("SELECT * FROM products WHERE id = 1").fetchone()
    assert row["name"] == "New Name"
    assert row["description"] == "New desc"
    assert row["price_cents"] == 101
    assert row["stock_quantity"] == 5
    assert row["category"] == "Gadgets"
    conn2.close()


def test_update_product_real_storage_stores_text_due_to_str_and_returns_correct_price(tmp_path, monkeypatch):
    db_path = tmp_path / "db_real.sqlite"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = _connect(str(db_path))
    _create_schema_real(conn)
    _insert_real_product(conn, 1, "Prod", "Desc", 5.5, 2, "CatA")
    conn.close()

    res = update_product(
        1,
        name="Prod2",
        description="New",
        price=Decimal("2.345"),  # should round to 2.35
        stock_quantity=3,
        category="CatB",
    )

    assert res["price"] == pytest.approx(2.35)
    assert res["name"] == "Prod2"
    assert res["description"] == "New"
    assert res["stock_quantity"] == 3
    assert res["category"] == "CatB"

    conn2 = _connect(str(db_path))
    row = conn2.execute("SELECT typeof(price) as t, price FROM products WHERE id = 1").fetchone()
    # Because pricing.to_db_price stores str in real mode, SQLite stores TEXT affinity
    assert row["t"] == "text"
    assert row["price"] == "2.35"
    conn2.close()


def test_update_product_not_found_raises(tmp_path, monkeypatch):
    db_path = tmp_path / "db_nf.sqlite"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = _connect(str(db_path))
    _create_schema_cents(conn)
    conn.close()

    with pytest.raises(NotFoundError):
        update_product(1, "X", None, 1.0, 1, "C")


@pytest.mark.parametrize(
    "bad_id",
    [
        True,
        False,
        -1,
        0,
        1.2,
        "abc",
        None,
    ],
)
def test_update_product_id_validation_errors(bad_id, tmp_path, monkeypatch):
    db_path = tmp_path / "db_id.sqlite"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))
    # No schema needed; should fail at ID validation before connecting
    with pytest.raises(ValidationError):
        update_product(bad_id, "N", None, 1.0, 1, "C")


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("name", "  "),
        ("category", ""),
        ("price", -1),
        ("stock_quantity", -3),
        ("stock_quantity", 1.5),
        ("stock_quantity", True),
    ],
)
def test_update_product_payload_validation_errors(field, bad_value, tmp_path, monkeypatch):
    db_path = tmp_path / "db_val.sqlite"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = _connect(str(db_path))
    _create_schema_cents(conn)
    _insert_cents_product(conn, 1, "Good", "D", 100, 1, "Cat")
    conn.close()

    kwargs = dict(
        id=1,
        name="Good2",
        description="D2",
        price=1.0,
        stock_quantity=2,
        category="Cat2",
    )
    kwargs[field] = bad_value

    with pytest.raises(ValidationError):
        update_product(**kwargs)


def test_update_with_empty_description_sets_null(tmp_path, monkeypatch):
    db_path = tmp_path / "db_desc.sqlite"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = _connect(str(db_path))
    _create_schema_cents(conn)
    _insert_cents_product(conn, 1, "P", "Old", 250, 3, "Cat")
    conn.close()

    res = update_product(1, "P", "", 2.5, 3, "Cat")
    assert res["description"] is None

    conn2 = _connect(str(db_path))
    row = conn2.execute("SELECT description FROM products WHERE id = 1").fetchone()
    assert row["description"] is None
    conn2.close()


def test_update_product_duplicate_name_unique_constraint_raises_validation_error_and_rollback(tmp_path, monkeypatch):
    db_path = tmp_path / "db_unique.sqlite"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = _connect(str(db_path))
    _create_schema_cents(conn, unique_name=True)
    _insert_cents_product(conn, 1, "A", "D1", 100, 1, "C1")
    _insert_cents_product(conn, 2, "B", "D2", 200, 2, "C2")
    conn.close()

    with pytest.raises(ValidationError) as ei:
        update_product(1, "B", "D1", 1.0, 1, "C1")
    assert "Database constraint violated" in str(ei.value)

    # Ensure no changes were made to product 1 (rollback)
    conn2 = _connect(str(db_path))
    row1 = conn2.execute("SELECT name, description, price_cents, stock_quantity, category FROM products WHERE id = 1").fetchone()
    assert row1["name"] == "A"
    assert row1["description"] == "D1"
    assert row1["price_cents"] == 100
    assert row1["stock_quantity"] == 1
    assert row1["category"] == "C1"

    row2 = conn2.execute("SELECT name FROM products WHERE id = 2").fetchone()
    assert row2["name"] == "B"
    conn2.close()


def test_generic_db_error_is_wrapped_and_rolled_back(tmp_path, monkeypatch):
    db_path = tmp_path / "db_error.sqlite"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = _connect(str(db_path))
    # Create schema missing 'category' column to cause update failure
    _create_schema_cents(conn, include_category=False)
    _insert_cents_product(conn, 1, "X", "D", 100, 1, None)
    conn.close()

    with pytest.raises(ValidationError) as ei:
        update_product(1, "X2", "D2", 1.5, 2, "CatMissing")
    # Should be wrapped as a generic database error
    assert "Database error:" in str(ei.value)


def test_update_same_values_returns_product(tmp_path, monkeypatch):
    db_path = tmp_path / "db_same.sqlite"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = _connect(str(db_path))
    _create_schema_cents(conn)
    _insert_cents_product(conn, 1, "S", "D", 123, 4, "C")
    conn.close()

    res = update_product(1, "S", "D", Decimal("1.23"), 4, "C")
    assert res["name"] == "S"
    assert res["description"] == "D"
    assert res["price"] == pytest.approx(1.23)
    assert res["stock_quantity"] == 4
    assert res["category"] == "C"

    # Ensure values remain the same in DB
    conn2 = _connect(str(db_path))
    row = conn2.execute("SELECT name, description, price_cents, stock_quantity, category FROM products WHERE id = 1").fetchone()
    assert row["name"] == "S"
    assert row["description"] == "D"
    assert row["price_cents"] == 123
    assert row["stock_quantity"] == 4
    assert row["category"] == "C"
    conn2.close()


def test_pricing_configuration_switch_between_schemas(tmp_path, monkeypatch):
    db_path1 = tmp_path / "db_cents.sqlite"
    db_path2 = tmp_path / "db_real.sqlite"

    # Setup cents DB
    conn1 = _connect(str(db_path1))
    _create_schema_cents(conn1)
    _insert_cents_product(conn1, 1, "CentsProd", "CD", 100, 1, "CatC")
    conn1.close()

    # Setup real DB
    conn2 = _connect(str(db_path2))
    _create_schema_real(conn2)
    _insert_real_product(conn2, 1, "RealProd", "RD", 1.0, 1, "CatR")
    conn2.close()

    # Update cents DB
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path1))
    res1 = update_product(1, "CentsProd", "CD", Decimal("3.33"), 1, "CatC")
    assert res1["price"] == pytest.approx(3.33)

    c1 = _connect(str(db_path1))
    row1 = c1.execute("SELECT price_cents FROM products WHERE id = 1").fetchone()
    assert row1["price_cents"] == 333
    c1.close()

    # Update real DB
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path2))
    res2 = update_product(1, "RealProd", "RD", Decimal("4.44"), 1, "CatR")
    assert res2["price"] == pytest.approx(4.44)

    c2 = _connect(str(db_path2))
    row2 = c2.execute("SELECT typeof(price) AS t, price FROM products WHERE id = 1").fetchone()
    assert row2["t"] == "text"
    assert row2["price"] == "4.44"
    c2.close()

    # Switch back to cents DB and update again
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path1))
    res3 = update_product(1, "CentsProd", "CD", Decimal("1.23"), 1, "CatC")
    assert res3["price"] == pytest.approx(1.23)
    c3 = _connect(str(db_path1))
    row3 = c3.execute("SELECT price_cents FROM products WHERE id = 1").fetchone()
    assert row3["price_cents"] == 123
    c3.close()