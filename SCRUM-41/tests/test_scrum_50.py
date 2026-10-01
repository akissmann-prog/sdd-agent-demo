import os
import sqlite3
import threading
import pytest

import scrum_50


@pytest.fixture(autouse=True)
def reset_pricing_threadlocal(monkeypatch):
    # Ensure pricing detection does not leak between tests
    monkeypatch.setattr(scrum_50.pricing, "_local", threading.local())


def create_products_table_cents(conn, unique_name=False):
    unique = "UNIQUE" if unique_name else ""
    conn.execute(
        f"""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL {unique},
            description TEXT,
            price_cents INTEGER NOT NULL,
            stock_quantity INTEGER NOT NULL,
            category TEXT NOT NULL
        )
        """
    )
    conn.commit()


def create_products_table_real(conn, unique_name=False):
    unique = "UNIQUE" if unique_name else ""
    conn.execute(
        f"""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL {unique},
            description TEXT,
            price REAL NOT NULL,
            stock_quantity INTEGER NOT NULL,
            category TEXT NOT NULL
        )
        """
    )
    conn.commit()


def test_update_product_cents_storage_happy_path(tmp_path, monkeypatch):
    db_path = tmp_path / "products.db"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = sqlite3.connect(db_path)
    create_products_table_cents(conn)
    conn.execute(
        "INSERT INTO products (id, name, description, price_cents, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Old", "old desc", 1000, 5, "OldCat"),
    )
    conn.commit()
    conn.close()

    updated = scrum_50.update_product(
        id=1,
        name=" New Name ",
        description="  New desc  ",
        price=12.345,
        stock_quantity=7,
        category=" Cat ",
    )

    assert updated["id"] == 1
    assert updated["name"] == "New Name"
    assert updated["description"] == "New desc"
    assert updated["price"] == 12.35
    assert updated["stock_quantity"] == 7
    assert updated["category"] == "Cat"

    # Verify DB persistence and price conversion to cents
    conn2 = sqlite3.connect(db_path)
    row = conn2.execute("SELECT name, description, price_cents, stock_quantity, category FROM products WHERE id = 1").fetchone()
    assert row[0] == "New Name"
    assert row[1] == "New desc"
    assert row[2] == 1235
    assert row[3] == 7
    assert row[4] == "Cat"
    conn2.close()


def test_update_with_identical_values_rowcount_zero_not_notfound(tmp_path, monkeypatch):
    db_path = tmp_path / "products.db"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = sqlite3.connect(db_path)
    create_products_table_cents(conn)
    conn.execute(
        "INSERT INTO products (id, name, description, price_cents, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Same", "desc", 1999, 10, "Cat"),
    )
    conn.commit()
    conn.close()

    # Update with identical values
    updated = scrum_50.update_product(
        id=1,
        name="Same",
        description="desc",
        price=19.99,
        stock_quantity=10,
        category="Cat",
    )
    assert updated["id"] == 1
    assert updated["name"] == "Same"
    assert updated["description"] == "desc"
    assert updated["price"] == 19.99
    assert updated["stock_quantity"] == 10
    assert updated["category"] == "Cat"

    # Ensure row still present and unchanged
    conn2 = sqlite3.connect(db_path)
    row = conn2.execute("SELECT name, description, price_cents, stock_quantity, category FROM products WHERE id = 1").fetchone()
    assert row == ("Same", "desc", 1999, 10, "Cat")
    conn2.close()


def test_update_real_storage_precision_and_rounding_and_text_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "products.db"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = sqlite3.connect(db_path)
    create_products_table_real(conn)
    conn.execute(
        "INSERT INTO products (id, name, description, price, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Old", "desc", 0.0, 1, "Cat"),
    )
    conn.commit()
    conn.close()

    updated = scrum_50.update_product(
        id=1,
        name="Old",
        description="desc",
        price=1.235,  # rounds to 1.24
        stock_quantity=1,
        category="Cat",
    )
    assert updated["price"] == 1.24

    # Ensure SQLite stored the value as TEXT preserving exact 2dp string
    conn2 = sqlite3.connect(db_path)
    row = conn2.execute("SELECT price, typeof(price) FROM products WHERE id = 1").fetchone()
    # Since we passed a string for real mode, SQLite should store TEXT
    assert row[1] == "text"
    assert row[0] == "1.24"

    # Update to 0.1 and ensure we get 0.1 back at API level
    conn2.close()
    updated2 = scrum_50.update_product(
        id=1,
        name="Old",
        description="desc",
        price=0.1,
        stock_quantity=1,
        category="Cat",
    )
    assert updated2["price"] == 0.1


def test_id_validation_reject_non_integer_float(tmp_path, monkeypatch):
    db_path = tmp_path / "products.db"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = sqlite3.connect(db_path)
    create_products_table_cents(conn)
    conn.execute(
        "INSERT INTO products (id, name, description, price_cents, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "P", "d", 100, 1, "C"),
    )
    conn.commit()
    conn.close()

    with pytest.raises(scrum_50.ValidationError) as ei:
        scrum_50.update_product(
            id=1.5,
            name="P",
            description="d",
            price=1.00,
            stock_quantity=1,
            category="C",
        )
    assert "id must be a positive integer" in str(ei.value)


def test_id_validation_bool_rejected(tmp_path, monkeypatch):
    db_path = tmp_path / "products.db"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = sqlite3.connect(db_path)
    create_products_table_cents(conn)
    conn.execute(
        "INSERT INTO products (id, name, description, price_cents, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "P", "d", 100, 1, "C"),
    )
    conn.commit()
    conn.close()

    with pytest.raises(scrum_50.ValidationError):
        scrum_50.update_product(
            id=True,
            name="P",
            description="d",
            price=1.00,
            stock_quantity=1,
            category="C",
        )


def test_description_empty_normalized_to_null(tmp_path, monkeypatch):
    db_path = tmp_path / "products.db"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = sqlite3.connect(db_path)
    create_products_table_cents(conn)
    conn.execute(
        "INSERT INTO products (id, name, description, price_cents, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Item", "should be cleared", 500, 2, "Cat"),
    )
    conn.commit()
    conn.close()

    updated = scrum_50.update_product(
        id=1,
        name="Item",
        description="   ",  # becomes None
        price=5.00,
        stock_quantity=2,
        category="Cat",
    )
    assert updated["description"] is None

    conn2 = sqlite3.connect(db_path)
    row = conn2.execute("SELECT description FROM products WHERE id = 1").fetchone()
    assert row[0] is None
    conn2.close()


def test_negative_values_validation(tmp_path, monkeypatch):
    db_path = tmp_path / "products.db"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = sqlite3.connect(db_path)
    create_products_table_cents(conn)
    conn.execute(
        "INSERT INTO products (id, name, description, price_cents, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Item", "desc", 100, 1, "Cat"),
    )
    conn.commit()
    conn.close()

    # Negative price
    with pytest.raises(scrum_50.ValidationError) as e1:
        scrum_50.update_product(1, "Item", "desc", -0.01, 1, "Cat")
    assert "price must be greater than or equal to 0" in str(e1.value)

    # Non-integer stock
    with pytest.raises(scrum_50.ValidationError) as e2:
        scrum_50.update_product(1, "Item", "desc", 1.00, 2.5, "Cat")
    assert "stock_quantity must be an integer value" in str(e2.value)

    # Negative stock
    with pytest.raises(scrum_50.ValidationError) as e3:
        scrum_50.update_product(1, "Item", "desc", 1.00, -1, "Cat")
    assert "stock_quantity must be a non-negative integer" in str(e3.value)


def test_not_found_on_missing_id(tmp_path, monkeypatch):
    db_path = tmp_path / "products.db"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = sqlite3.connect(db_path)
    create_products_table_cents(conn)
    # No rows inserted
    conn.close()

    with pytest.raises(scrum_50.NotFoundError):
        scrum_50.update_product(999, "Name", "desc", 1.0, 1, "Cat")


def test_unique_constraint_violation_raises_validation_error(tmp_path, monkeypatch):
    db_path = tmp_path / "products.db"
    monkeypatch.setenv("PRODUCT_DB_PATH", str(db_path))

    conn = sqlite3.connect(db_path)
    create_products_table_cents(conn, unique_name=True)
    conn.execute(
        "INSERT INTO products (id, name, description, price_cents, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Alpha", "d1", 100, 1, "C1"),
    )
    conn.execute(
        "INSERT INTO products (id, name, description, price_cents, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
        (2, "Beta", "d2", 200, 2, "C2"),
    )
    conn.commit()
    conn.close()

    with pytest.raises(scrum_50.ValidationError) as ei:
        scrum_50.update_product(
            id=2,
            name="Alpha",  # violates UNIQUE(name)
            description="d2",
            price=2.00,
            stock_quantity=2,
            category="C2",
        )
    assert "Database constraint violated" in str(ei.value)

    # Ensure no changes applied to row 2
    conn2 = sqlite3.connect(db_path)
    row2 = conn2.execute(
        "SELECT name, description, price_cents, stock_quantity, category FROM products WHERE id = 2"
    ).fetchone()
    assert row2 == ("Beta", "d2", 200, 2, "C2")
    conn2.close()