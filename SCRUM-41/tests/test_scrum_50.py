import os
import sqlite3
import pytest

import scrum_50 as mod


def create_cents_schema(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            price_cents INTEGER NOT NULL,
            stock_quantity INTEGER NOT NULL,
            category TEXT NOT NULL,
            CHECK (length(name) <= 50)
        )
        """
    )
    conn.commit()
    conn.close()


def create_real_schema(db_path, with_typeof_check=False):
    conn = sqlite3.connect(db_path)
    typeof_check = "CHECK(typeof(price)='real')" if with_typeof_check else ""
    conn.execute(
        f"""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL {typeof_check},
            stock_quantity INTEGER NOT NULL,
            category TEXT NOT NULL,
            CHECK (length(name) <= 50)
        )
        """
    )
    conn.commit()
    conn.close()


def insert_product_cents(db_path, id, name, description, price_cents, stock_quantity, category):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO products (id, name, description, price_cents, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
        (id, name, description, price_cents, stock_quantity, category),
    )
    conn.commit()
    conn.close()


def insert_product_real(db_path, id, name, description, price, stock_quantity, category):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO products (id, name, description, price, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?)",
        (id, name, description, price, stock_quantity, category),
    )
    conn.commit()
    conn.close()


def get_db_value(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def test_update_product_cents_happy_path_persists_and_rounds(tmp_path, monkeypatch):
    db_path = str(tmp_path / "cents.sqlite")
    monkeypatch.setenv("PRODUCT_DB_PATH", db_path)
    create_cents_schema(db_path)
    insert_product_cents(db_path, 1, "Widget", "Nice", 999, 5, "Tools")

    updated = mod.update_product(
        id=1,
        name="NewName",
        description="New desc",
        price=12.345,  # rounds to 12.35
        stock_quantity=10,
        category="Gadgets",
    )

    assert updated["id"] == 1
    assert updated["name"] == "NewName"
    assert updated["description"] == "New desc"
    assert updated["price"] == 12.35
    assert updated["stock_quantity"] == 10
    assert updated["category"] == "Gadgets"

    # Verify stored cents and other fields in a fresh connection
    price_cents = get_db_value(db_path, "SELECT price_cents FROM products WHERE id = 1")
    assert price_cents == 1235
    name = get_db_value(db_path, "SELECT name FROM products WHERE id = 1")
    assert name == "NewName"


def test_update_product_real_happy_path_persists_and_returns_correct_price(tmp_path, monkeypatch):
    db_path = str(tmp_path / "real.sqlite")
    monkeypatch.setenv("PRODUCT_DB_PATH", db_path)
    # Include typeof(price) check to ensure numeric storage
    create_real_schema(db_path, with_typeof_check=True)
    insert_product_real(db_path, 1, "Widget", "Nice", 9.99, 5, "Tools")

    updated = mod.update_product(
        id=1,
        name="NewName2",
        description="Another desc",
        price="2.5",  # accept strings; should become 2.50
        stock_quantity=7,
        category="Hardware",
    )

    assert updated["id"] == 1
    assert updated["name"] == "NewName2"
    assert updated["description"] == "Another desc"
    assert updated["price"] == 2.50
    assert updated["stock_quantity"] == 7
    assert updated["category"] == "Hardware"

    # Verify stored typeof is real and value is correct
    typeof_price = get_db_value(db_path, "SELECT typeof(price) FROM products WHERE id = 1")
    assert typeof_price == "real"
    stored_price = get_db_value(db_path, "SELECT price FROM products WHERE id = 1")
    assert pytest.approx(stored_price, rel=1e-9) == 2.5


def test_not_found_error_when_id_missing(tmp_path, monkeypatch):
    db_path = str(tmp_path / "nf.sqlite")
    monkeypatch.setenv("PRODUCT_DB_PATH", db_path)
    create_cents_schema(db_path)
    # No insert

    with pytest.raises(mod.NotFoundError):
        mod.update_product(
            id=999,
            name="Name",
            description="Desc",
            price=1.23,
            stock_quantity=1,
            category="Cat",
        )


@pytest.mark.parametrize(
    "bad_id",
    [0, -1, 1.2, True, "abc", ""],
)
def test_invalid_id_validation(bad_id, tmp_path, monkeypatch):
    db_path = str(tmp_path / "inv.sqlite")
    monkeypatch.setenv("PRODUCT_DB_PATH", db_path)
    create_cents_schema(db_path)
    insert_product_cents(db_path, 1, "Widget", "Nice", 999, 5, "Tools")

    with pytest.raises(mod.ValidationError):
        mod.update_product(
            id=bad_id,
            name="Name",
            description="Desc",
            price=1.0,
            stock_quantity=1,
            category="Cat",
        )


def test_float_integer_id_is_accepted(tmp_path, monkeypatch):
    db_path = str(tmp_path / "floatid.sqlite")
    monkeypatch.setenv("PRODUCT_DB_PATH", db_path)
    create_cents_schema(db_path)
    insert_product_cents(db_path, 1, "Widget", "Nice", 100, 2, "Tools")

    updated = mod.update_product(
        id=1.0,
        name="Widget",
        description="Nice",
        price=1.00,
        stock_quantity=2,
        category="Tools",
    )
    assert updated["id"] == 1


@pytest.mark.parametrize(
    "field_kwargs, expected_message_substr",
    [
        (dict(price=-0.01), "price must be greater than or equal to 0"),
        (dict(name="   "), "name must not be empty"),
        (dict(category=""), "category must not be empty"),
        (dict(stock_quantity=-5), "stock_quantity must be a non-negative integer"),
        (dict(price="abc"), "price must be a numeric value"),
        (dict(stock_quantity=1.5), "stock_quantity must be a non-negative integer"),
    ],
)
def test_payload_validation_errors(field_kwargs, expected_message_substr, tmp_path, monkeypatch):
    db_path = str(tmp_path / "val.sqlite")
    monkeypatch.setenv("PRODUCT_DB_PATH", db_path)
    create_cents_schema(db_path)
    insert_product_cents(db_path, 1, "Widget", "Nice", 100, 2, "Tools")

    base_kwargs = dict(
        id=1,
        name="Valid",
        description="Desc",
        price=1.23,
        stock_quantity=3,
        category="Cat",
    )
    base_kwargs.update(field_kwargs)

    with pytest.raises(mod.ValidationError) as ei:
        mod.update_product(**base_kwargs)
    assert expected_message_substr in str(ei.value)


def test_description_normalization_none_and_empty(tmp_path, monkeypatch):
    db_path = str(tmp_path / "desc.sqlite")
    monkeypatch.setenv("PRODUCT_DB_PATH", db_path)
    create_cents_schema(db_path)
    insert_product_cents(db_path, 1, "Widget", "Initial", 100, 2, "Tools")

    # Set to None
    updated1 = mod.update_product(
        id=1,
        name="Widget",
        description=None,
        price=1.00,
        stock_quantity=2,
        category="Tools",
    )
    assert updated1["description"] is None
    desc1 = get_db_value(db_path, "SELECT description FROM products WHERE id = 1")
    assert desc1 is None

    # Set to blank string (should normalize to None)
    updated2 = mod.update_product(
        id=1,
        name="Widget",
        description="   ",
        price=1.00,
        stock_quantity=2,
        category="Tools",
    )
    assert updated2["description"] is None
    desc2 = get_db_value(db_path, "SELECT description FROM products WHERE id = 1")
    assert desc2 is None


def test_update_no_changes_rowcount_zero_commit_and_return(tmp_path, monkeypatch):
    db_path = str(tmp_path / "nochange.sqlite")
    monkeypatch.setenv("PRODUCT_DB_PATH", db_path)
    create_cents_schema(db_path)
    insert_product_cents(db_path, 1, "Widget", "Desc", 1234, 5, "Tools")

    # Calling with same values
    updated = mod.update_product(
        id=1,
        name="Widget",
        description="Desc",
        price=12.34,
        stock_quantity=5,
        category="Tools",
    )
    assert updated["name"] == "Widget"
    assert updated["description"] == "Desc"
    assert updated["price"] == 12.34
    assert updated["stock_quantity"] == 5
    assert updated["category"] == "Tools"

    # Values remain the same in DB
    name = get_db_value(db_path, "SELECT name FROM products WHERE id = 1")
    assert name == "Widget"
    price_cents = get_db_value(db_path, "SELECT price_cents FROM products WHERE id = 1")
    assert price_cents == 1234


def test_integrity_error_on_too_long_name_rolled_back(tmp_path, monkeypatch):
    db_path = str(tmp_path / "integrity.sqlite")
    monkeypatch.setenv("PRODUCT_DB_PATH", db_path)
    # Create schema with strict name length to trigger IntegrityError on update
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL CHECK (length(name) <= 5),
            description TEXT,
            price_cents INTEGER NOT NULL,
            stock_quantity INTEGER NOT NULL,
            category TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
    insert_product_cents(db_path, 1, "Short", "Desc", 100, 2, "Cat")

    with pytest.raises(mod.ValidationError) as ei:
        mod.update_product(
            id=1,
            name="TooLongName",  # violates CHECK(length(name) <= 5)
            description="New",
            price=2.50,
            stock_quantity=3,
            category="Cat",
        )
    assert "Database constraint violated" in str(ei.value)

    # Ensure rollback: name should remain unchanged
    name = get_db_value(db_path, "SELECT name FROM products WHERE id = 1")
    assert name == "Short"
    # And other fields should not have changed either
    desc = get_db_value(db_path, "SELECT description FROM products WHERE id = 1")
    assert desc == "Desc"
    price_cents = get_db_value(db_path, "SELECT price_cents FROM products WHERE id = 1")
    assert price_cents == 100
    stock_qty = get_db_value(db_path, "SELECT stock_quantity FROM products WHERE id = 1")
    assert stock_qty == 2


def test_pricing_from_db_price_malformed_values_return_zero_cents_and_real(monkeypatch):
    # Test for both 'cents' and 'real' storage modes using _row_to_product
    base_row = {
        "id": 1,
        "name": "X",
        "description": None,
        "stock_quantity": 0,
        "category": "C",
    }

    # Cents mode malformed
    monkeypatch.setattr(mod.pricing._local, "storage_mode", "cents", raising=False)
    row_cents = dict(base_row, price_value="notanumber")
    prod_cents = mod.services.products._row_to_product(row_cents)
    assert prod_cents["price"] == 0.0

    # Real mode malformed
    monkeypatch.setattr(mod.pricing._local, "storage_mode", "real", raising=False)
    row_real = dict(base_row, price_value=None)  # None also yields 0.0
    prod_real = mod.services.products._row_to_product(row_real)
    assert prod_real["price"] == 0.0


def test_repository_uses_detected_price_column(tmp_path, monkeypatch):
    # Cents schema
    db_path_cents = str(tmp_path / "det_cents.sqlite")
    monkeypatch.setenv("PRODUCT_DB_PATH", db_path_cents)
    create_cents_schema(db_path_cents)
    insert_product_cents(db_path_cents, 1, "A", None, 250, 1, "Cat")
    conn = mod.db.get_connection()
    row = mod.repositories.products.get_by_id(conn, 1)
    conn.close()
    assert row is not None
    assert row["price_value"] == 250

    # Real schema
    db_path_real = str(tmp_path / "det_real.sqlite")
    monkeypatch.setenv("PRODUCT_DB_PATH", db_path_real)
    create_real_schema(db_path_real)
    insert_product_real(db_path_real, 1, "B", None, 3.75, 2, "Cat")
    conn2 = mod.db.get_connection()
    row2 = mod.repositories.products.get_by_id(conn2, 1)
    conn2.close()
    assert row2 is not None
    assert float(row2["price_value"]) == pytest.approx(3.75)