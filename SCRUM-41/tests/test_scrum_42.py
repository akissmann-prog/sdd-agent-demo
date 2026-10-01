import sqlite3
import math
import pytest
from unittest.mock import patch
import scrum_42


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_catalog.db")


@pytest.fixture
def patch_get_connection(monkeypatch, db_path):
    def _get_conn():
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(scrum_42, "get_connection", _get_conn)
    return db_path


def test_create_product_success_persists(patch_get_connection):
    result = scrum_42.create_product("  Name  ", "  Desc  ", "12.50", 3, "  Cat  ")
    assert result["ok"] is True
    product = result["product"]
    assert isinstance(product["id"], int) and product["id"] > 0
    assert product["name"] == "Name"
    assert product["description"] == "Desc"
    assert product["category"] == "Cat"
    assert isinstance(product["price"], float) and product["price"] == pytest.approx(12.5)
    assert isinstance(product["stock_quantity"], int) and product["stock_quantity"] == 3

    # Verify persistence
    with sqlite3.connect(patch_get_connection) as conn:
        cur = conn.execute(
            "SELECT id, name, description, price, stock_quantity, category FROM products"
        )
        rows = cur.fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row[1] == "Name"
        assert row[2] == "Desc"
        assert row[3] == pytest.approx(12.5)
        assert row[4] == 3
        assert row[5] == "Cat"


def test_multiple_inserts_increment_ids_and_persist(patch_get_connection):
    r1 = scrum_42.create_product("A", "D1", 1.0, 1, "C1")
    r2 = scrum_42.create_product("B", "D2", 2.0, 2, "C2")

    assert r1["ok"] is True and r2["ok"] is True
    id1 = r1["product"]["id"]
    id2 = r2["product"]["id"]
    assert isinstance(id1, int) and isinstance(id2, int)
    assert id2 > id1

    with sqlite3.connect(patch_get_connection) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM products")
        assert cur.fetchone()[0] == 2
        names = {row[0] for row in conn.execute("SELECT name FROM products")}
        assert names == {"A", "B"}


def test_insert_product_rejects_non_none_id(db_path):
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        scrum_42.init_db(conn)
        with pytest.raises(ValueError):
            p = scrum_42.Product(id=123, name="X", description="Y", price=1.0, stock_quantity=0, category="Z")
            scrum_42.insert_product(conn, p)
    finally:
        conn.close()


def test_create_product_validation_errors_multiple():
    result = scrum_42.create_product(
        "   ",               # name -> empty after trim
        None,                # description -> required
        -1,                  # price -> negative
        1.2,                 # stock_quantity -> non-integer float
        "   ",               # category -> empty after trim
    )
    assert result["ok"] is False
    err = result["error"]
    assert err["code"] == "VALIDATION_ERROR"
    details = err["details"]
    # Expect 5 errors in order they are validated
    assert details == [
        "name is required and cannot be empty.",
        "description is required and cannot be empty.",
        "category is required and cannot be empty.",
        "price must be a non-negative number.",
        "stock_quantity must be a non-negative integer.",
    ]


def test_stock_integer_float_allowed_via_create_product(patch_get_connection):
    res = scrum_42.create_product("N", "D", 1.99, 5.0, "C")
    assert res["ok"] is True
    assert res["product"]["stock_quantity"] == 5
    with sqlite3.connect(patch_get_connection) as conn:
        val = conn.execute("SELECT stock_quantity FROM products").fetchone()[0]
        assert val == 5


def test_price_rejects_bool_and_nan():
    # Bool
    norm, errors = scrum_42.validate_product_inputs("n", "d", True, 1, "c")
    assert norm is None
    assert errors == ["price must be a non-negative number."]

    # NaN
    norm, errors = scrum_42.validate_product_inputs("n", "d", float("nan"), 1, "c")
    assert norm is None
    assert errors == ["price must be a non-negative number."]


def test_stock_quantity_rejects_bool():
    norm, errors = scrum_42.validate_product_inputs("n", "d", 1.0, True, "c")
    assert norm is None
    assert errors == ["stock_quantity must be a non-negative integer."]


def test_normalize_string_with_bad_str():
    class BadStr:
        def __str__(self):
            raise RuntimeError("cannot stringify")
    norm, errors = scrum_42.validate_product_inputs(BadStr(), "d", 1.0, 1, "c")
    assert norm is None
    assert errors == ["name must be a string."]


def test_create_product_handles_db_locked_by_code(monkeypatch, patch_get_connection):
    class MyOpErr(sqlite3.OperationalError):
        def __init__(self, msg):
            super().__init__(msg)
            self.sqlite_errorcode = 5

    def fake_insert(conn, product):
        raise MyOpErr("some lock condition")

    monkeypatch.setattr(scrum_42, "insert_product", fake_insert)
    res = scrum_42.create_product("N", "D", 1.0, 1, "C")
    assert res["ok"] is False
    assert res["error"]["code"] == "DB_LOCKED"
    assert "lock" in res["error"]["message"].lower()


def test_create_product_handles_db_locked_by_message(monkeypatch):
    def fake_get_connection():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(scrum_42, "get_connection", fake_get_connection)
    res = scrum_42.create_product("N", "D", 1.0, 1, "C")
    assert res["ok"] is False
    assert res["error"]["code"] == "DB_LOCKED"
    assert "locked" in res["error"]["message"].lower()


def test_create_product_db_error_non_locked_operational(monkeypatch, patch_get_connection):
    def fake_insert(conn, product):
        raise sqlite3.OperationalError("other operational error")

    monkeypatch.setattr(scrum_42, "insert_product", fake_insert)
    res = scrum_42.create_product("N", "D", 1.0, 1, "C")
    assert res["ok"] is False
    assert res["error"]["code"] == "DB_ERROR"
    assert "operational" in res["error"]["message"].lower()


def test_create_product_unexpected_exception(monkeypatch, patch_get_connection):
    def fake_insert(conn, product):
        raise RuntimeError("boom")

    monkeypatch.setattr(scrum_42, "insert_product", fake_insert)
    res = scrum_42.create_product("N", "D", 1.0, 1, "C")
    assert res["ok"] is False
    assert res["error"]["code"] == "DB_ERROR"
    assert "boom" in res["error"]["message"]


def test_validate_price_and_stock_edge_cases():
    # price: -0.0 should be allowed and considered 0.0
    norm, errors = scrum_42.validate_product_inputs("n", "d", -0.0, 0, "c")
    assert errors == []
    assert math.copysign(1.0, norm["price"]) == 1.0  # positive zero

    # stock: string integer accepted
    norm, errors = scrum_42.validate_product_inputs("n", "d", 1.0, "3", "c")
    assert errors == []
    assert norm["stock_quantity"] == 3