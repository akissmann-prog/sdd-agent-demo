import os
import sqlite3
import pytest

import scrum_46


@pytest.fixture
def db_path_with_products(tmp_path):
    db_file = tmp_path / "products.sqlite"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            stock_quantity INTEGER NOT NULL,
            category TEXT
        );
        """
    )
    # Insert out of order to test ORDER BY
    products = [
        (3, "C", None, 2.5, 0, None),
        (1, "A", "desc A", 1.2, 10, "cat1"),
        (2, "B", "desc B", 3.4, 5, "cat2"),
    ]
    conn.executemany(
        "INSERT INTO products (id, name, description, price, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?);",
        products,
    )
    conn.commit()
    conn.close()
    return str(db_file)


def test_list_products_returns_all_ordered_and_plain_dicts(db_path_with_products):
    scrum_46.set_db_path(db_path_with_products)
    products = scrum_46.list_products()
    assert isinstance(products, list)
    assert [p["id"] for p in products] == [1, 2, 3]
    for p in products:
        assert isinstance(p, dict)
        assert set(p.keys()) == {
            "id",
            "name",
            "description",
            "price",
            "stock_quantity",
            "category",
        }
        assert isinstance(p["id"], int)
        assert isinstance(p["price"], float)
        assert isinstance(p["stock_quantity"], int)
    # Validate specific values with approximate comparison for floats
    p1 = products[0]
    assert p1["name"] == "A"
    assert p1["description"] == "desc A"
    assert p1["price"] == pytest.approx(1.2)
    assert p1["stock_quantity"] == 10
    assert p1["category"] == "cat1"
    p3 = products[2]
    assert p3["name"] == "C"
    assert p3["description"] is None
    assert p3["category"] is None


def test_repository_list_products_matches_api(db_path_with_products):
    repo = scrum_46.ProductRepository(db_path_with_products)
    repo_products = repo.list_products()
    api_products = scrum_46.list_products()
    # Convert TypedDict to plain dict for comparison
    repo_products_plain = [dict(p) for p in repo_products]
    assert repo_products_plain == api_products


def test_get_product_by_id_returns_record(db_path_with_products):
    scrum_46.set_db_path(db_path_with_products)
    prod = scrum_46.get_product_by_id(2)
    assert prod["id"] == 2
    assert prod["name"] == "B"
    assert prod["description"] == "desc B"
    assert prod["price"] == pytest.approx(3.4)
    assert prod["stock_quantity"] == 5
    assert prod["category"] == "cat2"


@pytest.mark.parametrize("bad_id", [0, -1, 1.5, "1", None])
def test_get_product_by_id_invalid_id_raises_value_error(db_path_with_products, bad_id):
    scrum_46.set_db_path(db_path_with_products)
    with pytest.raises(ValueError):
        scrum_46.get_product_by_id(bad_id)  # type: ignore[arg-type]


def test_get_product_by_id_bool_is_accepted_as_int(db_path_with_products):
    # bool is a subclass of int; verify current behavior accepts True (1) and returns id=1
    scrum_46.set_db_path(db_path_with_products)
    prod = scrum_46.get_product_by_id(True)  # type: ignore[arg-type]
    assert prod["id"] == 1
    assert prod["name"] == "A"


def test_get_product_by_id_not_found_raises_notfound(db_path_with_products):
    scrum_46.set_db_path(db_path_with_products)
    with pytest.raises(scrum_46.NotFoundError):
        scrum_46.get_product_by_id(999)


def test_get_ro_connection_is_read_only_and_query_only_is_on(db_path_with_products):
    with scrum_46.get_ro_connection(db_path_with_products) as conn:
        # Verify row_factory works (sqlite3.Row) and PRAGMA query_only is set
        row = conn.execute("SELECT 1 AS a").fetchone()
        assert isinstance(row, sqlite3.Row)
        assert row["a"] == 1
        q = conn.execute("PRAGMA query_only;").fetchone()
        assert q[0] == 1

        # Attempting writes should fail due to read-only/query_only
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE t(x INTEGER);")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO products (id, name, description, price, stock_quantity, category) VALUES (?, ?, ?, ?, ?, ?);",
                (10, "X", None, 9.99, 1, None),
            )


def test_get_ro_connection_missing_db_raises(tmp_path):
    missing_db = str(tmp_path / "nope.sqlite")
    with pytest.raises(sqlite3.OperationalError):
        with scrum_46.get_ro_connection(missing_db):
            pass


def test_productrepository_init_validates_db_path():
    with pytest.raises(ValueError):
        scrum_46.ProductRepository("")
    with pytest.raises(ValueError):
        scrum_46.ProductRepository(123)  # type: ignore[arg-type]


def test_set_db_path_validates_input():
    with pytest.raises(ValueError):
        scrum_46.set_db_path("")
    with pytest.raises(ValueError):
        scrum_46.set_db_path(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        scrum_46.set_db_path(123)  # type: ignore[arg-type]


def test_with_retry_retries_once_on_locked_and_succeeds(monkeypatch):
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    # Avoid sleep delay
    monkeypatch.setattr(scrum_46.time, "sleep", lambda _: None)
    result = scrum_46.ProductRepository._with_retry(op)
    assert result == "ok"
    assert calls["n"] == 2


def test_with_retry_does_not_retry_on_non_lock_operationalerror(monkeypatch):
    def op():
        raise sqlite3.OperationalError("near 'SELEC': syntax error")

    def fail_sleep(_):
        raise AssertionError("sleep should not be called for non-lock OperationalError")

    monkeypatch.setattr(scrum_46.time, "sleep", fail_sleep)
    with pytest.raises(sqlite3.OperationalError):
        scrum_46.ProductRepository._with_retry(op)