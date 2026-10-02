import re
import sqlite3
from datetime import datetime
from unittest import mock

import pytest

import scrum_136 as m


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def test_create_application_minimal_defaults_and_trimming(db_path):
    status, body = m.create_application({"company": "  ACME  ", "role": "  Dev  "}, db_path=db_path)
    assert status == 201
    data = body["data"]
    assert isinstance(data["id"], int)
    assert data["company"] == "ACME"
    assert data["role"] == "Dev"
    assert data["status"] == "applied"
    # applied_date defaults to current date; ensure format and a valid date
    assert isinstance(data["applied_date"], str)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["applied_date"])
    assert m.DateUtil.is_valid_date_yyyy_mm_dd(data["applied_date"])
    assert data["notes"] is None


def test_create_application_with_all_fields(db_path):
    payload = {
        "company": "Initech",
        "role": "Engineer",
        "status": "interviewing",
        "applied_date": "2023-12-01",
        "notes": "first round complete",
    }
    status, body = m.create_application(payload, db_path=db_path)
    assert status == 201
    data = body["data"]
    assert data["company"] == "Initech"
    assert data["role"] == "Engineer"
    assert data["status"] == "interviewing"
    assert data["applied_date"] == "2023-12-01"
    assert data["notes"] == "first round complete"


def test_create_application_unknown_fields_error(db_path):
    payload = {"company": "Initech", "role": "Engineer", "foo": "bar", "zzz": 1}
    status, body = m.create_application(payload, db_path=db_path)
    assert status == 400
    assert body["error"] == "Bad Request"
    details = body["details"]
    assert "unknown" in details
    # Should be sorted
    assert details["unknown"] == ["foo", "zzz"]
    # No other validation errors since required fields are provided and valid
    assert set(details.keys()) == {"unknown"}


def test_list_applications_filter_and_order(db_path):
    # Create multiple applications with varying status
    for comp, st in [("A", "applied"), ("B", "offer"), ("C", "interviewing"), ("D", "offer")]:
        status, _ = m.create_application({"company": comp, "role": "Dev", "status": st}, db_path=db_path)
        assert status == 201

    status, body = m.list_applications(db_path=db_path)
    assert status == 200
    items = body["data"]
    assert [i["company"] for i in items] == ["A", "B", "C", "D"]  # ordered by id asc

    status, body = m.list_applications(status="Offer", db_path=db_path)  # mixed case accepted
    assert status == 200
    items = body["data"]
    assert [i["company"] for i in items] == ["B", "D"]
    assert all(i["status"] == "offer" for i in items)


def test_get_update_delete_flow(db_path):
    # Create
    status, body = m.create_application({"company": "Globex", "role": "Analyst"}, db_path=db_path)
    assert status == 201
    app_id = body["data"]["id"]

    # Get
    s, b = m.get_application(app_id, db_path=db_path)
    assert s == 200
    assert b["data"]["id"] == app_id

    # Update with normalized status and notes None
    s, b = m.update_application(app_id, {"status": " OFFER ", "notes": None}, db_path=db_path)
    assert s == 200
    assert b["data"]["status"] == "offer"
    assert b["data"]["notes"] is None

    # Update with empty payload -> non_field error
    s, b = m.update_application(app_id, {}, db_path=db_path)
    assert s == 400
    assert b["details"]["non_field"] == "no updatable fields provided"

    # Update with unknown field -> unknown error only (no non_field)
    s, b = m.update_application(app_id, {"foo": "bar"}, db_path=db_path)
    assert s == 400
    assert "unknown" in b["details"]
    assert "non_field" not in b["details"]

    # Delete
    s, b = m.delete_application(app_id, db_path=db_path)
    assert s == 204
    assert b is None

    # Subsequent get -> 404
    s, b = m.get_application(app_id, db_path=db_path)
    assert s == 404

    # Subsequent delete -> 404
    s, b = m.delete_application(app_id, db_path=db_path)
    assert s == 404


def test_update_application_not_found(db_path):
    s, b = m.update_application(9999, {"status": "offer"}, db_path=db_path)
    assert s == 404
    assert b["error"] == "Not Found"


def test_list_applications_status_validation_errors(db_path):
    s, b = m.list_applications(status=123, db_path=db_path)
    assert s == 400
    assert b["details"]["status"] == "must be a string"

    s, b = m.list_applications(status="unknown", db_path=db_path)
    assert s == 400
    assert "must be one of" in b["details"]["status"]


def test_get_application_not_found(db_path):
    s, b = m.get_application(1, db_path=db_path)
    assert s == 404
    assert b["error"] == "Not Found"


def test_dateutil_validation():
    assert m.DateUtil.is_valid_date_yyyy_mm_dd("2024-02-29")  # leap day valid
    assert not m.DateUtil.is_valid_date_yyyy_mm_dd("2023-02-29")  # non-leap
    assert not m.DateUtil.is_valid_date_yyyy_mm_dd("2023-13-01")  # invalid month
    assert not m.DateUtil.is_valid_date_yyyy_mm_dd("2023/01/01")  # wrong sep
    assert not m.DateUtil.is_valid_date_yyyy_mm_dd(123)  # non-string


def test_schema_allows_invalid_calendar_date_at_db_level_via_repo(db_path):
    # This bypasses validator; demonstrates DB CHECK only validates shape (code review INFO)
    m.SchemaManager.ensure_schema(db_path)
    row = m.ApplicationRepo.create(
        {"company": "ACME", "role": "Dev", "applied_date": "2023-02-30"}, db_path=db_path
    )
    assert row["applied_date"] == "2023-02-30"  # invalid calendar date accepted by DB


def test_repo_update_noop_when_no_fields(db_path):
    # Create a record
    m.SchemaManager.ensure_schema(db_path)
    created = m.ApplicationRepo.create({"company": "ACME", "role": "Dev"}, db_path=db_path)
    app_id = created["id"]
    # Call update with empty dict; repo returns existing row (no-op)
    res = m.ApplicationRepo.update(app_id, {}, db_path=db_path)
    assert res is not None
    assert res["id"] == app_id
    assert res["company"] == "ACME"
    assert res["role"] == "Dev"


def test_repo_delete_returns_bool(db_path):
    m.SchemaManager.ensure_schema(db_path)
    created = m.ApplicationRepo.create({"company": "ACME", "role": "Dev"}, db_path=db_path)
    app_id = created["id"]
    assert m.ApplicationRepo.delete(app_id, db_path=db_path) is True
    assert m.ApplicationRepo.delete(app_id, db_path=db_path) is False


def test_schema_id_autoincrement(db_path):
    m.SchemaManager.ensure_schema(db_path)
    a = m.ApplicationRepo.create({"company": "A", "role": "X"}, db_path=db_path)
    b = m.ApplicationRepo.create({"company": "B", "role": "Y"}, db_path=db_path)
    assert b["id"] == a["id"] + 1


def test_error_leakage_on_create_integrity_error(db_path):
    with mock.patch.object(m.ApplicationRepo, "create", side_effect=sqlite3.IntegrityError("boom")):
        s, b = m.create_application({"company": "A", "role": "X"}, db_path=db_path)
        assert s == 400
        assert "constraint violation: boom" == b["details"]["db"]


def test_error_leakage_on_list_database_error(db_path):
    with mock.patch.object(m.ApplicationRepo, "list_all", side_effect=sqlite3.DatabaseError("db oops")):
        s, b = m.list_applications(db_path=db_path)
        assert s == 500
        assert b["error"] == "Internal Server Error"
        assert b["details"]["db"] == "db oops"


def test_error_leakage_on_get_database_error(db_path):
    with mock.patch.object(m.ApplicationRepo, "get_by_id", side_effect=sqlite3.DatabaseError("oops")):
        s, b = m.get_application(1, db_path=db_path)
        assert s == 500
        assert b["details"]["db"] == "oops"


def test_error_leakage_on_update_integrity_error_and_db_error(db_path):
    # First ensure validator passes by using valid payload
    with mock.patch.object(m.ApplicationRepo, "update", side_effect=sqlite3.IntegrityError("bad check")):
        s, b = m.update_application(1, {"status": "offer"}, db_path=db_path)
        assert s == 400
        assert b["details"]["db"] == "constraint violation: bad check"
    with mock.patch.object(m.ApplicationRepo, "update", side_effect=sqlite3.DatabaseError("update fail")):
        s, b = m.update_application(1, {"status": "offer"}, db_path=db_path)
        assert s == 500
        assert b["details"]["db"] == "update fail"


def test_error_leakage_on_delete_database_error(db_path):
    with mock.patch.object(m.ApplicationRepo, "delete", side_effect=sqlite3.DatabaseError("del err")):
        s, b = m.delete_application(1, db_path=db_path)
        assert s == 500
        assert b["details"]["db"] == "del err"