import uuid as _uuid
import sqlite3
import pytest
import scrum_125


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_applications.sqlite")


def test_get_statuses_returns_known_values():
    assert scrum_125.get_statuses() == ("applied", "interviewing", "offer", "rejected")


def test_create_application_defaults_and_persistence(monkeypatch, db_path):
    monkeypatch.setattr(scrum_125, "_today_yyyy_mm_dd", lambda: "2020-01-02")
    payload = {"company": "Acme Corp", "role": "Engineer"}
    app = scrum_125.create_application(payload, db_path=db_path)
    assert app["company"] == "Acme Corp"
    assert app["role"] == "Engineer"
    assert app["status"] == "applied"
    assert app["applied_date"] == "2020-01-02"
    assert app["notes"] == ""

    # persisted and retrievable
    apps = scrum_125.list_applications(db_path=db_path)
    assert len(apps) == 1
    assert apps[0]["id"] == app["id"]

    grouped = scrum_125.group_applications_by_status(db_path=db_path)
    assert set(grouped.keys()) == set(scrum_125.STATUSES)
    assert len(grouped["applied"]) == 1


def test_create_application_validations(db_path):
    # company validations
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"role": "Engineer"}, db_path=db_path)
    assert "company is required" in str(e.value)

    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"company": "", "role": "Engineer"}, db_path=db_path)
    assert "company cannot be empty" in str(e.value)

    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"company": 123, "role": "Engineer"}, db_path=db_path)
    assert "company must be a string" in str(e.value)

    # role validations
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"company": "Acme"}, db_path=db_path)
    assert "role is required" in str(e.value)

    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"company": "Acme", "role": "   "}, db_path=db_path)
    assert "role cannot be empty" in str(e.value)

    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"company": "Acme", "role": 42}, db_path=db_path)
    assert "role must be a string" in str(e.value)

    # status validations
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"company": "Acme", "role": "Engineer", "status": 1}, db_path=db_path)
    assert "status must be a string" in str(e.value)

    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"company": "Acme", "role": "Engineer", "status": "pending"}, db_path=db_path)
    assert "status must be one of" in str(e.value)

    # applied_date validations
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"company": "Acme", "role": "Engineer", "applied_date": 20200101}, db_path=db_path)
    assert "applied_date must be a string in YYYY-MM-DD format" in str(e.value)

    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"company": "Acme", "role": "Engineer", "applied_date": "2024-13-40"}, db_path=db_path)
    assert "applied_date must be in YYYY-MM-DD format" in str(e.value)

    # notes validation
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"company": "Acme", "role": "Engineer", "notes": 0}, db_path=db_path)
    assert "notes must be a string" in str(e.value)


def test_list_ordering(db_path):
    # Insert multiple with assorted dates/companies/roles
    a = scrum_125.create_application(
        {"company": "Beta", "role": "Dev", "status": "applied", "applied_date": "2020-01-02"},
        db_path=db_path,
    )
    b = scrum_125.create_application(
        {"company": "Acme", "role": "Analyst", "status": "interviewing", "applied_date": "2021-05-10"},
        db_path=db_path,
    )
    c = scrum_125.create_application(
        {"company": "Acme", "role": "Developer", "status": "offer", "applied_date": "2021-05-10"},
        db_path=db_path,
    )
    d = scrum_125.create_application(
        {"company": "Zeta", "role": "Manager", "status": "rejected", "applied_date": "2019-12-31"},
        db_path=db_path,
    )
    apps = scrum_125.list_applications(db_path=db_path)
    # Ordered by applied_date DESC, then company ASC, then role ASC
    expected_order = [b["id"], c["id"], a["id"], d["id"]]
    assert [x["id"] for x in apps] == expected_order


def test_get_application_not_found(db_path):
    with pytest.raises(scrum_125.NotFoundError):
        scrum_125.get_application("non-existent-id", db_path=db_path)


def test_update_application_happy_path_and_validations(db_path):
    app = scrum_125.create_application(
        {"company": "Acme", "role": "Engineer", "status": "applied", "applied_date": "2020-1-2"},
        db_path=db_path,
    )
    # Happy path: update several fields, including normalization
    updated = scrum_125.update_application(
        app["id"],
        {"company": " Acme Inc ", "status": "Interviewing", "applied_date": "2020-01-03", "notes": None},
        db_path=db_path,
    )
    assert updated["company"] == "Acme Inc"
    assert updated["status"] == "interviewing"
    assert updated["applied_date"] == "2020-01-03"
    assert updated["notes"] == ""

    # Unknown field
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.update_application(app["id"], {"foo": "bar"}, db_path=db_path)
    assert "Unknown field in update: foo" in str(e.value)

    # Empty patch
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.update_application(app["id"], {}, db_path=db_path)
    assert "No fields to update" in str(e.value)

    # Patch not dict
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.update_application(app["id"], "not-a-dict", db_path=db_path)  # type: ignore
    assert "patch must be an object" in str(e.value)

    # company cannot be empty
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.update_application(app["id"], {"company": "   "}, db_path=db_path)
    assert "company cannot be empty" in str(e.value)

    # status type and value validation
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.update_application(app["id"], {"status": 1}, db_path=db_path)
    assert "status must be a string" in str(e.value)

    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.update_application(app["id"], {"status": "unknown"}, db_path=db_path)
    assert "status must be one of" in str(e.value)

    # applied_date type invalid
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.update_application(app["id"], {"applied_date": 123}, db_path=db_path)
    assert "applied_date must be a string in YYYY-MM-DD format" in str(e.value)

    # applied_date invalid string
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.update_application(app["id"], {"applied_date": "2024-13-40"}, db_path=db_path)
    assert "applied_date must be in YYYY-MM-DD format" in str(e.value)

    # notes type invalid
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.update_application(app["id"], {"notes": 0}, db_path=db_path)
    assert "notes must be a string" in str(e.value)


def test_change_status_convenience(db_path):
    app = scrum_125.create_application({"company": "Acme", "role": "Eng"}, db_path=db_path)
    changed = scrum_125.change_status(app["id"], "offer", db_path=db_path)
    assert changed["status"] == "offer"


def test_delete_application(db_path):
    app = scrum_125.create_application({"company": "Acme", "role": "Eng"}, db_path=db_path)
    # delete success
    assert scrum_125.delete_application(app["id"], db_path=db_path) is None
    # get after delete fails
    with pytest.raises(scrum_125.NotFoundError):
        scrum_125.get_application(app["id"], db_path=db_path)
    # delete non-existent
    with pytest.raises(scrum_125.NotFoundError):
        scrum_125.delete_application(app["id"], db_path=db_path)


def test_validate_create_pure(monkeypatch):
    monkeypatch.setattr(scrum_125, "_today_yyyy_mm_dd", lambda: "2022-02-03")
    sanitized = scrum_125.validate_create(
        {"company": "  Acme  ", "role": " Dev ", "status": "  Applied ", "applied_date": "2022-2-3", "notes": None}
    )
    assert sanitized["company"] == "Acme"
    assert sanitized["role"] == "Dev"
    assert sanitized["status"] == "applied"
    # applied_date provided with single-digit parts should be normalized by datetime.strptime
    assert sanitized["applied_date"] == "2022-02-03"
    assert sanitized["notes"] == ""

    # defaults applied when not provided
    sanitized2 = scrum_125.validate_create({"company": "X", "role": "Y"})
    assert sanitized2["status"] == "applied"
    assert sanitized2["applied_date"] == "2022-02-03"
    assert sanitized2["notes"] == ""


def test_validate_create_errors(monkeypatch):
    monkeypatch.setattr(scrum_125, "_today_yyyy_mm_dd", lambda: "2022-02-03")
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_create({"role": "Dev"})
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_create({"company": "Acme"})
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_create({"company": "Acme", "role": 1})
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_create({"company": "Acme", "role": "Dev", "status": 5})
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_create({"company": "Acme", "role": "Dev", "applied_date": 123})


def test_validate_update_pure():
    # Happy path
    sanitized = scrum_125.validate_update(
        {"company": "  A ", "role": " B ", "status": "Offer", "applied_date": "2020-1-2", "notes": None}
    )
    assert sanitized["company"] == "A"
    assert sanitized["role"] == "B"
    assert sanitized["status"] == "offer"
    assert sanitized["applied_date"] == "2020-01-02"
    assert sanitized["notes"] == ""

    # errors
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_update({})
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_update("not-a-dict")  # type: ignore
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_update({"unknown": "x"})
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_update({"company": "   "})
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_update({"status": 1})
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_update({"applied_date": 1})
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_update({"applied_date": "2020/01/01"})
    with pytest.raises(scrum_125.ValidationError):
        scrum_125.validate_update({"notes": 0})


def test_integrity_error_duplicate_id(monkeypatch, db_path):
    fixed_uuid = _uuid.UUID("12345678-1234-5678-1234-567812345678")
    # Force duplicate UUIDs to trigger UNIQUE constraint
    monkeypatch.setattr(scrum_125.uuid, "uuid4", lambda: fixed_uuid)
    scrum_125.create_application({"company": "A", "role": "R"}, db_path=db_path)
    with pytest.raises(scrum_125.ValidationError) as e:
        scrum_125.create_application({"company": "B", "role": "R2"}, db_path=db_path)
    assert "Integrity error" in str(e.value)
    # Ensure only one row in DB
    apps = scrum_125.list_applications(db_path=db_path)
    assert len(apps) == 1


def test_connect_sets_wal_and_row_factory(db_path):
    conn = scrum_125._connect(db_path)
    try:
        # journal_mode pragma
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
        # row factory
        assert conn.row_factory == sqlite3.Row
    finally:
        conn.close()


def test_schema_indexes_created(db_path):
    conn = scrum_125._connect(db_path)
    try:
        scrum_125._ensure_schema(conn)
        names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
        assert "idx_applications_status" in names
        assert "idx_applications_applied_date" in names
    finally:
        conn.close()


def test_group_applications_by_status_has_all_keys(db_path):
    grouped = scrum_125.group_applications_by_status(db_path=db_path)
    assert tuple(grouped.keys()) == scrum_125.STATUSES
    assert all(isinstance(v, list) for v in grouped.values())
    # Add apps across statuses
    a = scrum_125.create_application({"company": "A", "role": "R", "status": "applied", "applied_date": "2020-01-01"}, db_path=db_path)
    b = scrum_125.create_application({"company": "B", "role": "R", "status": "offer", "applied_date": "2020-01-02"}, db_path=db_path)
    c = scrum_125.create_application({"company": "C", "role": "R", "status": "rejected", "applied_date": "2020-01-03"}, db_path=db_path)
    grouped2 = scrum_125.group_applications_by_status(db_path=db_path)
    assert [x["id"] for x in grouped2["applied"]] == [a["id"]]
    assert [x["id"] for x in grouped2["offer"]] == [b["id"]]
    assert [x["id"] for x in grouped2["rejected"]] == [c["id"]]